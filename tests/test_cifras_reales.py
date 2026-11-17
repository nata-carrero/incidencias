"""Pruebas con las cifras reales del proyecto (datos del parquet, sin llamar a ningún modelo).

Si algún cambio rompe una de estas cifras, algo cambió en los datos o en las reglas de depuración
y hay que revisarlo antes de sustentar. Las cifras salen del informe de integración.
"""
from agente import herramientas as h
from agente.validaciones import detectar
from tablero.datos import base_tablero, concentracion, depurar


def _adjudicaciones(df):
    return df[df["valor_adjudicado_mercado"] > 0]


def test_cifras_reales_depuradas():
    limpia = depurar(base_tablero())
    assert len(limpia) == 2793                      # 3.138 procesos menos 345 quitados
    c = concentracion(limpia)
    assert c["adjudicaciones"] == 1092
    assert c["proveedores"] == 267
    assert round(c["hhi"]) == 523                   # poco concentrado a nivel nacional
    assert round(c["cr4"], 1) == 38.9
    millones = limpia["valor_adjudicado_mercado"].sum() / 1e6
    assert round(millones) == 86745                 # $86.745 millones


def test_cifras_reales_sin_depurar():
    base = base_tablero()
    c = concentracion(base)
    assert c["adjudicaciones"] == 1193
    assert c["proveedores"] == 282
    assert round(c["hhi"]) == 9997                  # parece un monopolio por un solo registro
    assert round(c["cr4"], 2) == 99.99
    assert base["valor_adjudicado_mercado"].sum() > 8e14   # más de 800 billones


def test_cifras_reales_de_las_incidencias():
    inc = detectar(h.cargar_procesos())
    assert len(inc) == 1170
    assert (inc["regla"] == "clasificacion_por_validar").sum() == 373
