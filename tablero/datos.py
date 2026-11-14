"""Datos del tablero: una fila por proceso, con marcas de depuración tomadas de las reglas del agente.

Depurar = quitar del cálculo lo que las reglas del agente señalan como inflado:
- filas repetidas del mismo ID (se conserva una);
- procesos repetidos con otro ID (posible_repetido: se conserva el primero del grupo);
- montos imposibles (los que el código del agente decide como error_de_registro).
"""
import pandas as pd

from agente import herramientas as h
from agente.grafo import causa_por_codigo
from agente.validaciones import detectar

REGLAS_MONTO = ["precio_atipico", "adjudicacion_supera_base", "adjudicado_sin_valor"]
SIN_PROVEEDOR = {"No Definido", "No Adjudicado", ""}


def base_tablero(procesos: pd.DataFrame | None = None) -> pd.DataFrame:
    p = h.cargar_procesos() if procesos is None else procesos
    inc = detectar(p)
    unicos = p.drop_duplicates(h.ID).copy()

    repetidos = set(inc.loc[inc["regla"] == "posible_repetido", "id_proceso"])
    imposibles = set()
    for _, r in inc[inc["regla"].isin(REGLAS_MONTO)].iterrows():
        causa, _ = causa_por_codigo(r.dropna().to_dict(), {"registros": [{}]})
        if causa == "error_de_registro" and r["regla"] != "adjudicado_sin_valor":
            imposibles.add(r["id_proceso"])

    unicos["repetido"] = unicos[h.ID].isin(repetidos)
    unicos["monto_imposible"] = unicos[h.ID].isin(imposibles)
    unicos["filas_extra"] = unicos[h.ID].map(p[h.ID].value_counts()) - 1
    unicos["adjudicado"] = unicos["Adjudicado"].eq("Si")
    unicos["valor_adjudicado_mercado"] = unicos["valor_adjudicado"].where(unicos["adjudicado"], 0).fillna(0)
    unicos["precio_base_mercado"] = unicos["precio_base"].fillna(0)
    unicos["departamento"] = unicos["Departamento Entidad"].fillna("Sin dato")
    unicos["modalidad"] = unicos["Modalidad de Contratacion"].fillna("Sin dato")
    # Proveedor: el NIT cuando SECOP lo publica (solo ~30 % de las adjudicaciones);
    # si no, el nombre normalizado, que casi siempre está.
    nit = unicos["NIT del Proveedor Adjudicado"].fillna("")
    nombre = unicos["Nombre del Proveedor Adjudicado"].fillna("")
    unicos["proveedor_id"] = ("NIT " + nit).where(~nit.isin(SIN_PROVEEDOR), "")
    sin_nit = unicos["proveedor_id"].eq("") & ~nombre.isin(SIN_PROVEEDOR)
    unicos.loc[sin_nit, "proveedor_id"] = "NOMBRE " + nombre[sin_nit].map(h.normalizar)
    return unicos


def depurar(base: pd.DataFrame) -> pd.DataFrame:
    """Quita repetidos y montos imposibles (las filas repetidas del mismo ID ya se quitaron)."""
    return base[~base["repetido"] & ~base["monto_imposible"]]


def concentracion(base: pd.DataFrame, columna_valor: str = "valor_adjudicado_mercado") -> dict:
    """HHI (0–10.000) y CR4 (%) sobre el valor adjudicado por proveedor."""
    adj = base[(base[columna_valor] > 0) & (base["proveedor_id"] != "")]
    por_prov = adj.groupby("proveedor_id")[columna_valor].sum()
    if por_prov.empty:
        return {"hhi": float("nan"), "cr4": float("nan"), "proveedores": 0, "adjudicaciones": 0}
    cuota = por_prov / por_prov.sum() * 100
    return {"hhi": float((cuota ** 2).sum()), "cr4": float(cuota.nlargest(4).sum()),
            "proveedores": int(len(por_prov)), "adjudicaciones": int(len(adj))}
