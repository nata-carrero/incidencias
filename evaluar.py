"""Evaluación con 60 fallas sembradas en una copia de los procesos funerarios de SECOP II.

Siembra: 20 IDs duplicados, 10 adjudicados con valor $0, 10 precios base en $0,
10 precios base multiplicados por 1.000, 5 adjudicaciones que triplican el precio base
y 5 procesos copiados con otro ID (repetidos). Mide con intervalos de Wilson:
- detección (sensibilidad): fallas que las reglas encuentran. Umbral ≥ 90 %.
- falsas alarmas: incidencias nuevas que no corresponden a ninguna falla. Umbral ≤ 10 %.
Con --diagnosticar K corre además el agente (LLM) sobre K fallas detectadas y mide si la
causa coincide con la esperada, separando lo que decide el código de lo que decide el modelo.

  .venv\\Scripts\\python.exe evaluar.py
  .venv\\Scripts\\python.exe evaluar.py --diagnosticar 20
"""
import argparse
import math
import random
import sys
import uuid

import pandas as pd
from langgraph.types import Command

from agente import config, herramientas as h
from agente.validaciones import detectar

sys.stdout.reconfigure(encoding="utf-8")
ID = h.ID
PLAN = {"id_duplicado": 20, "adjudicado_sin_valor": 10, "precio_base_cero": 10,
        "precio_x1000": 10, "adjudicacion_x3": 5, "repetido_otro_id": 5}
ESPERADA = {"id_duplicado": "registro_duplicado", "repetido_otro_id": "registro_duplicado",
            "adjudicado_sin_valor": "error_de_registro", "precio_base_cero": "error_de_registro",
            "precio_x1000": "error_de_registro", "adjudicacion_x3": "error_de_registro"}


def wilson(exitos: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = exitos / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centro - margen), min(1.0, centro + margen))


def pesos_texto(valor: float) -> str:
    return "$" + f"{int(valor):,}".replace(",", ".")


def sembrar(procesos: pd.DataFrame, semilla: int):
    rng = random.Random(semilla)
    base = detectar(procesos)
    con_incidencia = set(base["id_proceso"]) | {i for l in base.get("otros_ids", pd.Series(dtype=object)).dropna() for i in l}
    unicos = procesos.drop_duplicates(ID, keep=False)
    candidatos = unicos[~unicos[ID].isin(con_incidencia) & unicos["anio"].notna()
                        & (unicos["referencia_base"] != "") & (unicos["precio_base"] > 0)
                        & ~unicos["Modalidad de Contratacion"].fillna("").str.startswith("Solicitud")]
    usados, fallas, nuevas_filas = set(), [], []
    p = procesos.copy()

    def elegir(filtro=None):
        opciones = candidatos if filtro is None else candidatos[filtro(candidatos)]
        opciones = opciones[~opciones[ID].isin(usados)]
        fila = opciones.loc[rng.choice(list(opciones.index))]
        usados.add(fila[ID])
        return fila

    def fila_de(id_):
        return p.index[p[ID] == id_][0]

    for _ in range(PLAN["id_duplicado"]):
        f = elegir()
        nuevas_filas.append(f)
        fallas.append(("id_duplicado", [f[ID]]))
    for _ in range(PLAN["adjudicado_sin_valor"]):
        f = elegir(lambda c: (c["Adjudicado"] == "Si") & (c["valor_adjudicado"] > 0))
        p.at[fila_de(f[ID]), "Valor Total Adjudicacion"] = "$0"
        fallas.append(("adjudicado_sin_valor", [f[ID]]))
    for _ in range(PLAN["precio_base_cero"]):
        f = elegir(lambda c: c["Estado del Procedimiento"] == "Seleccionado")
        p.at[fila_de(f[ID]), "Precio Base"] = "$0"
        fallas.append(("precio_base_cero", [f[ID]]))
    for _ in range(PLAN["precio_x1000"]):
        f = elegir()
        p.at[fila_de(f[ID]), "Precio Base"] = pesos_texto(f["precio_base"] * 1000)
        fallas.append(("precio_x1000", [f[ID]]))
    for _ in range(PLAN["adjudicacion_x3"]):
        f = elegir(lambda c: (c["Adjudicado"] == "Si") & (c["valor_adjudicado"] > 0))
        p.at[fila_de(f[ID]), "Valor Total Adjudicacion"] = pesos_texto(f["precio_base"] * 3)
        fallas.append(("adjudicacion_x3", [f[ID]]))
    for k in range(PLAN["repetido_otro_id"]):
        f = elegir()
        copia = f.copy()
        copia[ID] = f"CO1.REQ.99{semilla}{k:04d}"
        nuevas_filas.append(copia)
        fallas.append(("repetido_otro_id", [f[ID], copia[ID]]))

    p = pd.concat([p, pd.DataFrame(nuevas_filas)], ignore_index=True)
    columnas_crudas = [c for c in procesos.columns if c not in ("precio_base", "valor_adjudicado", "fecha", "anio", "referencia_base")]
    return h.preparar(p[columnas_crudas]), base, fallas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--semilla", type=int, default=2026)
    ap.add_argument("--diagnosticar", type=int, default=0)
    a = ap.parse_args()

    procesos = h.cargar_procesos()
    sembrado, base, fallas = sembrar(procesos, a.semilla)
    clave_base = set(zip(base["regla"], base["id_proceso"]))
    detectado = detectar(sembrado)
    nuevas = detectado[[(r, i) not in clave_base for r, i in zip(detectado["regla"], detectado["id_proceso"])]]

    ids_nuevos = set(nuevas["id_proceso"])
    res = pd.DataFrame([{"tipo": t, "id_proceso": ids[0], "detectada": any(i in ids_nuevos for i in ids)}
                        for t, ids in fallas])
    ids_fallas = {i for _, ids in fallas for i in ids}
    falsas = int((~nuevas["id_proceso"].isin(ids_fallas)).sum())

    det = int(res["detectada"].sum())
    lo, hi = wilson(det, len(res))
    flo, fhi = wilson(falsas, len(nuevas))
    print(f"Fallas sembradas: {len(res)} · incidencias nuevas: {len(nuevas)}")
    print(f"Detección: {det}/{len(res)} = {det/len(res):.1%} (IC95 % {lo:.1%}–{hi:.1%}) · umbral ≥ 90 %")
    print(f"Falsas alarmas: {falsas}/{len(nuevas)} = {falsas/max(len(nuevas),1):.1%} "
          f"(IC95 % {flo:.1%}–{fhi:.1%}) · umbral ≤ 10 %")
    print(res.groupby("tipo")["detectada"].agg(["sum", "count"]).to_string())
    config.RESULTADOS.mkdir(exist_ok=True)
    res.to_csv(config.RESULTADOS / "evaluacion_deteccion.csv", index=False, encoding="utf-8-sig")

    if a.diagnosticar:
        from agente.grafo import construir
        from correr import como_registros
        tipo_de = {i: t for t, ids in fallas for i in ids}
        lote = nuevas[nuevas["id_proceso"].isin(ids_fallas)].drop_duplicates("id_proceso")
        # Muestra estratificada: al menos una de cada tipo de falla.
        lote = lote.assign(tipo=lote["id_proceso"].map(tipo_de))
        por_tipo = max(1, a.diagnosticar // len(PLAN))
        lote = lote.sample(frac=1, random_state=a.semilla).groupby("tipo").head(por_tipo)
        lote = lote.reset_index(drop=True)
        lote["id"] = range(1, len(lote) + 1)
        grafo = construir(procesos=sembrado)
        hilo = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 20 * len(lote) + 20}
        grafo.invoke({"pendientes": como_registros(lote.drop(columns="tipo")), "resultados": []}, hilo)
        salida = grafo.invoke(Command(resume={"decisiones": {}}), hilo)
        diag = pd.DataFrame(salida["resultados"])
        diag["tipo"] = diag["id_proceso"].map(tipo_de)
        diag["correcta"] = diag["causa"] == diag["tipo"].map(ESPERADA)
        for quien, g in diag.groupby("decidida_por"):
            ok = int(g["correcta"].sum())
            lo, hi = wilson(ok, len(g))
            print(f"\nCausa correcta (decidida por {quien}): {ok}/{len(g)} (IC95 % {lo:.0%}–{hi:.0%})")
        print(f"Anclaje verificado: {int(diag['anclado'].sum())}/{len(diag)} · umbral 100 %")
        print(diag[["tipo", "regla", "causa", "decidida_por", "correcta", "confianza", "intentos"]].to_string(index=False))
        diag.to_csv(config.RESULTADOS / "evaluacion_diagnostico.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
