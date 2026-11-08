"""Corre el agente sobre incidencias reales de los procesos funerarios de SECOP II.

  .venv\\Scripts\\python.exe correr.py --n 5                    # 5 incidencias al azar
  .venv\\Scripts\\python.exe correr.py --n 5 --regla precio_atipico
  .venv\\Scripts\\python.exe correr.py --n 5 --auto              # sin preguntar en la revisión humana
  .venv\\Scripts\\python.exe correr.py --una-por-regla           # una incidencia de cada tipo
  .venv\\Scripts\\python.exe correr.py --solo-detectar           # solo reglas, sin LLM
  .venv\\Scripts\\python.exe correr.py --diagrama                # guarda el grafo en Mermaid
"""
import argparse
import sys
import uuid

import pandas as pd
from langgraph.types import Command

from agente import config, herramientas as h
from agente.grafo import construir
from agente.validaciones import detectar

sys.stdout.reconfigure(encoding="utf-8")


def como_registros(df: pd.DataFrame) -> list[dict]:
    """Filas a dicts sin NaN (los NaN de pandas no se serializan bien en el estado del grafo)."""
    return [{k: (None if not isinstance(v, list) and pd.isna(v) else v) for k, v in fila.items()}
            for fila in df.to_dict("records")]


def preguntar(para_revisar: list[dict]) -> dict:
    decisiones = {}
    for r in para_revisar:
        print(f"\n[{r['id']}] {r['id_proceso']} {r['regla']} → {r['causa']} ({r['confianza']})")
        print(f"   {r['conclusion']}")
        if r["problemas"]:
            print(f"   Problemas: {r['problemas']}")
        resp = input("   ¿Aprobar (a), rechazar (r) u omitir (Enter)? ").strip().lower()
        decisiones[str(r["id"])] = {"a": "aprobado", "r": "rechazado"}.get(resp, "pendiente")
    return decisiones


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--regla")
    ap.add_argument("--semilla", type=int, default=1)
    ap.add_argument("--auto", action="store_true", help="deja la revisión humana como pendiente")
    ap.add_argument("--solo-detectar", action="store_true")
    ap.add_argument("--una-por-regla", action="store_true", help="una incidencia de cada tipo")
    ap.add_argument("--diagrama", action="store_true")
    a = ap.parse_args()
    config.RESULTADOS.mkdir(exist_ok=True)

    if a.diagrama:
        (config.RESULTADOS / "grafo.mmd").write_text(construir().get_graph().draw_mermaid(), encoding="utf-8")
        print("Diagrama guardado en resultados/grafo.mmd")
        return

    inc = detectar(h.cargar_procesos())
    inc.insert(0, "id", range(1, len(inc) + 1))
    inc.to_csv(config.RESULTADOS / "incidencias_secop.csv", index=False, encoding="utf-8-sig")
    print(f"{len(inc)} incidencias detectadas: {inc['regla'].value_counts().to_dict()}")
    if a.solo_detectar:
        return

    if a.regla:
        inc = inc[inc["regla"] == a.regla]
    if a.una_por_regla:
        lote = inc.sample(frac=1, random_state=a.semilla).groupby("regla").head(1)
    else:
        lote = inc.sample(min(a.n, len(inc)), random_state=a.semilla)
    pendientes = como_registros(lote)

    grafo = construir()
    hilo = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 20 * len(pendientes) + 20}
    print(f"Procesando {len(pendientes)} incidencias con {config.LLM_MODEL}...")
    salida = grafo.invoke({"pendientes": pendientes, "resultados": []}, hilo)

    estado = grafo.get_state(hilo)
    if estado.next:  # el grafo quedó en pausa en revision_humana
        datos = estado.tasks[0].interrupts[0].value
        print(f"\nRevisión humana: {len(datos['para_revisar'])} de {datos['total']} con confianza media o baja.")
        decision = {} if a.auto else preguntar(datos["para_revisar"])
        # Nunca reanudar con un dict vacío: LangGraph lo toma como "sin respuesta" y vuelve a pausar.
        salida = grafo.invoke(Command(resume={"decisiones": decision}), hilo)

    df = pd.DataFrame(salida["resultados"])
    print("\n" + df[["id_proceso", "regla", "causa", "decidida_por", "confianza", "intentos",
                     "revision_humana"]].to_string(index=False))
    print(f"\nGuardado en {config.RESULTADOS / 'diagnosticos.csv'}  ·  trazas en {config.LOGS / 'trazas.jsonl'}")


if __name__ == "__main__":
    main()
