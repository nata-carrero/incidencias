"""Pruebas de los datos del tablero: una fila por proceso, depuración y concentración."""
from tablero.datos import base_tablero, concentracion, depurar


def test_una_fila_por_proceso_y_depuracion_quita_repetidos_e_imposibles():
    base = base_tablero()
    assert len(base) == base["ID del Proceso"].nunique() == 3138
    limpia = depurar(base)
    assert not limpia["repetido"].any() and not limpia["monto_imposible"].any()
    assert "CO1.REQ.1615047" not in set(limpia["ID del Proceso"])  # Rionegro, $813 billones


def test_depurar_quita_casi_todo_el_valor_inflado():
    base = base_tablero()
    assert base["valor_adjudicado_mercado"].sum() > 8e14       # sin depurar: más de 800 billones
    assert depurar(base)["valor_adjudicado_mercado"].sum() < 1e11  # depurado: menos de 100 mil millones


def test_concentracion_hhi_y_cr4():
    import pandas as pd
    dos_iguales = pd.DataFrame({"valor_adjudicado_mercado": [50, 50], "proveedor_id": ["NIT 1", "NIT 2"]})
    c = concentracion(dos_iguales)
    assert round(c["hhi"]) == 5000 and round(c["cr4"]) == 100
