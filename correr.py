"""Corre el agente sobre incidencias reales.

  .venv\\Scripts\\python.exe correr.py --n 5                 # 5 incidencias al azar
  .venv\\Scripts\\python.exe correr.py --n 5 --regla salto_poblacion
  .venv\\Scripts\\python.exe correr.py --n 5 --auto           # sin preguntar en la revisión humana
  .venv\\Scripts\\python.exe correr.py --diagrama             # guarda el grafo en Mermaid
"""
import argparse
import sys
import uuid

import pandas as pd
from langgraph.types import Command

from agente import config, herramientas as h
from agente.grafo import construir

sys.stdout.reconfigure(encoding="utf-8")


def preguntar(para_revisar: list[dict]) -> dict:
    decisiones = {}
    for r in para_revisar:
        print(f"\n[{r['id']}] {r['cod_divipola']}-{r['anio']} {r['regla']} → {r['causa']} ({r['confianza']})")
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
    ap.add_argument("--diagrama", action="store_true")
    a = ap.parse_args()

    grafo = construir()
    if a.diagrama:
        config.RESULTADOS.mkdir(exist_ok=True)
        (config.RESULTADOS / "grafo.mmd").write_text(grafo.get_graph().draw_mermaid(), encoding="utf-8")
        print("Diagrama guardado en resultados/grafo.mmd")
        return

    inc = h.cargar_incidencias()
    if a.regla:
        inc = inc[inc["regla"] == a.regla]
    lote = inc.sample(min(a.n, len(inc)), random_state=a.semilla)
    pendientes = lote.astype(object).where(lote.notna(), None).to_dict("records")

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
    print("\n" + df[["cod_divipola", "anio", "regla", "causa", "confianza", "intentos", "revision_humana"]].to_string(index=False))
    print(f"\nGuardado en {config.RESULTADOS / 'diagnosticos.csv'}  ·  trazas en {config.LOGS / 'trazas.jsonl'}")


if __name__ == "__main__":
    main()
