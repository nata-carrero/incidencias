"""Pruebas de la API con TestClient. Ninguna llama al modelo de verdad."""
from fastapi.testclient import TestClient

from agente import grafo as G, llm
from api import main

cliente = TestClient(main.app)


def test_salud():
    assert cliente.get("/salud").json() == {"estado": "ok"}


def test_procesos_filtra_y_pagina():
    r = cliente.get("/procesos", params={"anio": 2024, "limit": 5}).json()
    assert r["total"] > 0 and len(r["datos"]) == 5
    assert all(p["anio"] == 2024 for p in r["datos"])
    todos = cliente.get("/procesos", params={"limit": 1}).json()
    assert todos["total"] == 3138


def test_incidencias_por_regla():
    r = cliente.get("/incidencias", params={"regla": "precio_atipico"}).json()
    assert r["total"] == 19 and all(i["regla"] == "precio_atipico" for i in r["datos"])


def test_concentracion_depurada_y_sin_depurar():
    d = cliente.get("/mercado/concentracion", params={"depurar": "true"}).json()
    assert round(d["hhi"]) == 523 and round(d["cr4"], 1) == 38.9
    s = cliente.get("/mercado/concentracion", params={"depurar": "false"}).json()
    assert s["hhi"] > 9900


def test_diagnosticar_sin_llm_responde_503(monkeypatch):
    monkeypatch.setattr(llm, "probar_conexion", lambda: {"ok": False, "mensaje": "Falta la clave."})
    r = cliente.post("/diagnosticar/CO1.REQ.1615047")
    assert r.status_code == 503 and "Falta la clave" in r.json()["detail"]


def test_diagnosticar_proceso_sin_incidencias_responde_404():
    assert cliente.post("/diagnosticar/NO-EXISTE").status_code == 404


def test_diagnosticar_con_modelo_falso(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "probar_conexion", lambda: {"ok": True, "mensaje": "ok"})
    monkeypatch.setattr(G, "generar_json", lambda m, etiqueta: {
        "causa": "dato_plausible", "conclusion": "Prueba.", "cita_textual": "texto inventado"})
    monkeypatch.setattr(G.config, "RESULTADOS", tmp_path)
    r = cliente.post("/diagnosticar/CO1.REQ.1615047")
    assert r.status_code == 200
    d = r.json()
    assert d["causa"] == "error_de_registro" and d["decidida_por"] == "codigo"  # Rionegro: lo decide el código
