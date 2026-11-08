"""Reglas deterministas (sin LLM) que detectan incidencias en los procesos funerarios de SECOP II.

Cada incidencia queda marcada, sin corregir: es la entrada del agente.
"""
import numpy as np
import pandas as pd

from .herramientas import ID

SIN_COSTO = {"Cancelado", "Borrador"}  # estados donde un precio en 0 no es raro
Z_ATIPICO = 3.5  # sobre log10 del precio, con mediana y MAD por modalidad
EXCESO_ADJUDICACION = 1.05  # adjudicado más de 5 % por encima del precio base


def _inc(regla, fila, valor, detalle, **extra):
    return {"id_proceso": fila[ID], "regla": regla, "valor_citado": valor, "detalle": detalle,
            "entidad": fila["Entidad"], "anio": fila["anio"], **extra}


def detectar(p: pd.DataFrame) -> pd.DataFrame:
    out = []

    for _, f in p[p.duplicated(ID, keep="first")].iterrows():
        out.append(_inc("id_duplicado", f, f[ID], "el mismo ID del proceso aparece en más de una fila"))

    # Mismo proceso publicado con IDs distintos: misma entidad, referencia, año y precio base.
    unicos = p.drop_duplicates(ID)
    con_ref = unicos[unicos["referencia_base"] != ""]
    clave = ["Nit Entidad", "referencia_base", "anio", "precio_base"]
    for _, grupo in con_ref[con_ref.duplicated(clave, keep=False)].groupby(clave):
        ids = list(grupo[ID])
        for _, f in grupo.iloc[1:].iterrows():
            out.append(_inc("posible_repetido", f, f["Referencia del Proceso"],
                            "otro proceso de la misma entidad tiene igual referencia, año y precio base",
                            otros_ids=[i for i in ids if i != f[ID]]))

    for _, f in unicos[(unicos["Adjudicado"] == "Si") & (unicos["valor_adjudicado"] == 0)].iterrows():
        out.append(_inc("adjudicado_sin_valor", f, f["Valor Total Adjudicacion"],
                        "figura como adjudicado pero el valor adjudicado es $0"))

    activos = unicos[~unicos["Estado del Procedimiento"].isin(SIN_COSTO)]
    for _, f in activos[activos["precio_base"] == 0].iterrows():
        out.append(_inc("precio_base_cero", f, f["Precio Base"], "proceso activo con precio base de $0"))

    supera = unicos[(unicos["precio_base"] > 0) & (unicos["valor_adjudicado"] > EXCESO_ADJUDICACION * unicos["precio_base"])]
    for _, f in supera.iterrows():
        out.append(_inc("adjudicacion_supera_base", f, f["Valor Total Adjudicacion"],
                        "el valor adjudicado supera en más de 5 % el precio base",
                        veces_precio_base=round(f["valor_adjudicado"] / f["precio_base"], 1)))

    positivos = unicos[unicos["precio_base"] > 0].copy()
    # Referencia propia de cada entidad: cuánto suele costar lo que esa entidad contrata.
    por_entidad = positivos.groupby("Nit Entidad")["precio_base"]
    positivos["mediana_entidad"] = por_entidad.transform("median")
    positivos["procesos_entidad"] = por_entidad.transform("count")
    positivos["log"] = np.log10(positivos["precio_base"])
    g = positivos.groupby("Modalidad de Contratacion")["log"]
    mediana = g.transform("median")
    mad = g.transform(lambda s: (s - s.median()).abs().median()) * 1.4826
    z = (positivos["log"] - mediana) / mad.replace(0, np.nan)
    for idx in positivos.index[z.abs() > Z_ATIPICO]:
        f = positivos.loc[idx]
        adjudicado = f["valor_adjudicado"] if f["valor_adjudicado"] > 0 else None
        out.append(_inc("precio_atipico", f, f["Precio Base"],
                        "precio base muy lejos de lo usual para su modalidad",
                        mediana_modalidad=round(10 ** mediana[idx]),
                        mediana_entidad=round(f["mediana_entidad"]), procesos_entidad=int(f["procesos_entidad"]),
                        veces_mediana_entidad=round(f["precio_base"] / f["mediana_entidad"], 1),
                        veces_valor_adjudicado=round(f["precio_base"] / adjudicado, 1) if adjudicado else None))

    for _, f in unicos[unicos["Codigo Principal de Categoria"].isin(["UNSPECIFIED", None, "No Definido"])].iterrows():
        out.append(_inc("categoria_no_definida", f, f["Codigo Principal de Categoria"],
                        "el proceso no tiene código UNSPSC definido"))

    for _, f in unicos[unicos["clasificacion_equipo"] == "Mención relacionada / validar objeto"].iterrows():
        out.append(_inc("clasificacion_por_validar", f, f["clasificacion_equipo"],
                        "el término funerario aparece, pero no está claro que sea la compra principal"))

    return pd.DataFrame(out)
