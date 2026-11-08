"""Evaluación con 60 fallas sembradas (fase F7 del plan).

Siembra en una copia del panel: 20 duplicados, 15 dígitos cambiados en el código,
10 municipios borrados, 10 coberturas forzadas al 100 % y 5 saltos falsos.
Mide con intervalos de Wilson:
- detección (sensibilidad): fallas sembradas que las reglas encuentran. Umbral ≥ 90 %.
- falsas alarmas: incidencias nuevas que no corresponden a ninguna falla. Umbral ≤ 10 %.
Con --diagnosticar K, además corre el agente (LLM) sobre K fallas detectadas y mide
si diagnostica error_extraccion (la causa correcta: el panel ya no coincide con el PDF)
y si el diagnóstico queda anclado.

  .venv\\Scripts\\python.exe evaluar.py
  .venv\\Scripts\\python.exe evaluar.py --diagnosticar 10
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
PLAN = {"duplicado": 20, "digito_cambiado": 15, "municipio_borrado": 10, "cobertura_forzada": 10, "salto_falso": 5}


def wilson(exitos: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = exitos / n
    centro = (p + z * z / (2 * n)) / (1 + z * z / n)
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centro - margen), min(1.0, centro + margen))


def sembrar(panel: pd.DataFrame, semilla: int):
    rng = random.Random(semilla)
    divipola = h.cargar_divipola()
    base = detectar(panel)
    con_incidencia = set(base["cod_divipola"])
    candidatos = panel[(panel["tipo"] == "municipio") & panel["cod_divipola"].isin(divipola)
                       & ~panel["cod_divipola"].isin(con_incidencia) & (panel["poblacion_perros"] > 0)]
    usados, fallas = set(), []
    p = panel.copy()

    def elegir(filtro=None):
        opciones = candidatos if filtro is None else candidatos[filtro(candidatos)]
        opciones = opciones[~opciones["cod_divipola"].isin(usados)]
        fila = opciones.loc[rng.choice(list(opciones.index))]
        usados.add(fila["cod_divipola"])
        return fila

    for _ in range(PLAN["duplicado"]):
        f = elegir()
        p = pd.concat([p, f.to_frame().T], ignore_index=True)
        fallas.append(("duplicado", f["cod_divipola"], f["anio"], [(f["cod_divipola"], f["anio"])]))
    for _ in range(PLAN["digito_cambiado"]):
        f = elegir()
        cod = f["cod_divipola"]
        nuevo = next(cod[:-1] + d for d in "0123456789" if cod[:-1] + d not in divipola)
        idx = p.index[(p["cod_divipola"] == cod) & (p["anio"] == f["anio"])][0]
        p.at[idx, "cod_divipola"] = nuevo
        fallas.append(("digito_cambiado", cod, f["anio"], [(nuevo, f["anio"]), (cod, f["anio"])]))
    for _ in range(PLAN["municipio_borrado"]):
        f = elegir()
        p = p[~((p["cod_divipola"] == f["cod_divipola"]) & (p["anio"] == f["anio"]))]
        fallas.append(("municipio_borrado", f["cod_divipola"], f["anio"], [(f["cod_divipola"], f["anio"])]))
    for _ in range(PLAN["cobertura_forzada"]):
        f = elegir()
        idx = p.index[(p["cod_divipola"] == f["cod_divipola"]) & (p["anio"] == f["anio"])][0]
        p.at[idx, "vacunados_perros_gatos"] = f["poblacion_perros"] + f["poblacion_gatos"]
        fallas.append(("cobertura_forzada", f["cod_divipola"], f["anio"], [(f["cod_divipola"], f["anio"])]))
    for _ in range(PLAN["salto_falso"]):
        f = elegir(lambda c: c["anio"].isin([2017, 2024]))
        idx = p.index[(p["cod_divipola"] == f["cod_divipola"]) & (p["anio"] == f["anio"])][0]
        p.at[idx, "poblacion_perros"] = f["poblacion_perros"] * 3
        fallas.append(("salto_falso", f["cod_divipola"], f["anio"], [(f["cod_divipola"], f["anio"])]))
    # concat con una fila suelta deja columnas como object; se restauran los tipos del panel.
    return p.reset_index(drop=True).astype(panel.dtypes.to_dict()), base, fallas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--semilla", type=int, default=2026)
    ap.add_argument("--diagnosticar", type=int, default=0)
    a = ap.parse_args()

    panel = h.cargar_panel()
    sembrado, base, fallas = sembrar(panel, a.semilla)
    clave = lambda df: set(zip(df["regla"], df["cod_divipola"], df["anio"].astype(int)))
    detectado = detectar(sembrado)
    nuevas = detectado[~detectado.apply(
        lambda r: (r["regla"], r["cod_divipola"], int(r["anio"])) in clave(base), axis=1)]

    llaves_nuevas = {(c, int(a_)) for c, a_ in zip(nuevas["cod_divipola"], nuevas["anio"])}
    filas = [{"tipo": t, "cod_divipola": c, "anio": int(an),
              "detectada": any((k, int(y)) in llaves_nuevas for k, y in llaves)}
             for t, c, an, llaves in fallas]
    res = pd.DataFrame(filas)
    llaves_fallas = {(k, int(y)) for *_, llaves in fallas for k, y in llaves}
    falsas = sum((c, int(y)) not in llaves_fallas for c, y in zip(nuevas["cod_divipola"], nuevas["anio"]))

    det = int(res["detectada"].sum())
    lo, hi = wilson(det, len(res))
    flo, fhi = wilson(falsas, len(nuevas))
    print(f"Fallas sembradas: {len(res)} · incidencias nuevas: {len(nuevas)}")
    print(f"Detección: {det}/{len(res)} = {det/len(res):.1%} (IC95 % {lo:.1%}–{hi:.1%}) · umbral ≥ 90 %")
    print(f"Falsas alarmas: {falsas}/{len(nuevas)} = {falsas/max(len(nuevas),1):.1%} (IC95 % {flo:.1%}–{fhi:.1%}) · umbral ≤ 10 %")
    print(res.groupby("tipo")["detectada"].agg(["sum", "count"]).to_string())

    config.RESULTADOS.mkdir(exist_ok=True)
    res.to_csv(config.RESULTADOS / "evaluacion_deteccion.csv", index=False, encoding="utf-8-sig")

    if a.diagnosticar:
        from agente.grafo import construir
        grafo = construir(panel=sembrado)
        lote = nuevas[nuevas.apply(lambda r: (r["cod_divipola"], int(r["anio"])) in llaves_fallas, axis=1)]
        lote = lote.sample(min(a.diagnosticar, len(lote)), random_state=a.semilla).reset_index(drop=True)
        lote["id"] = range(1, len(lote) + 1)
        pendientes = lote.astype(object).where(lote.notna(), None).to_dict("records")
        hilo = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 20 * len(pendientes) + 20}
        grafo.invoke({"pendientes": pendientes, "resultados": []}, hilo)
        salida = grafo.invoke(Command(resume={"decisiones": {}}), hilo)
        diag = pd.DataFrame(salida["resultados"])
        ok = int((diag["causa"] == "error_extraccion").sum())
        anc = int(diag["anclado"].sum())
        print(f"\nDiagnóstico correcto (error_extraccion): {ok}/{len(diag)} (IC95 % {wilson(ok, len(diag))[0]:.0%}–{wilson(ok, len(diag))[1]:.0%})")
        print(f"Anclaje verificado: {anc}/{len(diag)} · umbral 100 %")
        print(diag[["cod_divipola", "anio", "regla", "causa", "confianza", "intentos"]].to_string(index=False))
        diag.to_csv(config.RESULTADOS / "evaluacion_diagnostico.csv", index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
