"""Reglas deterministas (sin LLM) que detectan incidencias en el panel.

Reproducen las reglas de Edward que se pueden recalcular desde el panel
(cobertura en 100 %, saltos de ±50 %, habitantes por perro fuera de 1,7–11,4)
y agregan las que necesita la evaluación con fallas sembradas
(duplicados, códigos inválidos y municipios faltantes).
"""
import pandas as pd

from .herramientas import cargar_divipola

RAZON_MIN, RAZON_MAX = 1.7, 11.4
SALTO_MAX = 0.5


def _inc(regla, fila, valor, conclusion):
    return {"cod_divipola": fila["cod_divipola"], "anio": int(fila["anio"]), "regla": regla,
            "valor_citado": valor, "archivo": fila.get("fuente"), "pagina": fila.get("pagina"),
            "municipio_pdf": fila.get("municipio_pdf"), "conclusion": conclusion}


def detectar(panel: pd.DataFrame) -> pd.DataFrame:
    divipola = cargar_divipola()
    p = panel[panel["cod_divipola"].notna()].copy()
    out = []

    for _, f in p[p.duplicated(["cod_divipola", "anio"], keep="first")].iterrows():
        out.append(_inc("duplicado", f, f["cod_divipola"], "fila repetida para el mismo municipio y año"))

    for _, f in p[~p["cod_divipola"].isin(divipola)].iterrows():
        out.append(_inc("codigo_invalido", f, f["cod_divipola"], "el código no existe en DIVIPOLA"))

    # Faltante: el municipio aparece en otros años del reporte, pero no en este.
    presentes = p.groupby("anio")["cod_divipola"].apply(set)
    todos = set().union(*presentes)
    for anio, codigos in presentes.items():
        ref = p[p["anio"] == anio].iloc[0]
        for cod in sorted(todos - codigos):
            if cod in divipola:
                out.append(_inc("municipio_faltante", {**ref, "cod_divipola": cod, "municipio_pdf": None},
                                None, "el municipio no aparece en el reporte de ese año"))

    v = p[p["cod_divipola"].isin(divipola)].drop_duplicates(["cod_divipola", "anio"])
    total = v["poblacion_perros"] + v["poblacion_gatos"]
    cobertura = (v["vacunados_perros_gatos"] / total * 100).where(total > 0)
    for _, f in v[cobertura.round(0) == 100].iterrows():
        out.append(_inc("cobertura_100", f, 100, "cobertura exactamente en 100 %"))

    v = v.sort_values(["cod_divipola", "anio"])
    # Solo años consecutivos (2016→2017, 2023→2024), como en las incidencias de Edward.
    anterior = v.groupby("cod_divipola")["poblacion_perros"].shift()
    consecutivo = v["anio"] - v.groupby("cod_divipola")["anio"].shift() == 1
    cambio = v["poblacion_perros"] / anterior - 1
    for idx in v.index[(cambio.abs() > SALTO_MAX) & (anterior > 0) & consecutivo]:
        f = v.loc[idx]
        out.append(_inc("salto_poblacion", f, f"{cambio[idx]:+.1%}",
                        "población de perros cambió más de ±50 % frente al año anterior"))

    medidos = v[(v["metodo_estimacion"] == "posible_medido") & (v["poblacion_perros"] > 0)]
    razon = medidos["pob_dane"] / medidos["poblacion_perros"]
    for idx in medidos.index[(razon < RAZON_MIN) | (razon > RAZON_MAX)]:
        out.append(_inc("habitantes_por_perro_fuera_de_rango", medidos.loc[idx], round(razon[idx], 2),
                        "fuera de 1,7-11,4 habitantes por perro"))

    return pd.DataFrame(out)
