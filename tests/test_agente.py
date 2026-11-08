"""Pruebas sin LLM: herramientas, anclaje, reglas del grafo y evaluación sembrada."""
import uuid

from langgraph.types import Command

from agente import grafo as G, herramientas as h
from agente.anclaje import verificar_anclaje
from evaluar import sembrar, wilson
from agente.validaciones import detectar


def test_fila_pdf_con_separador_de_miles():
    f = h.fila_panel("44847", 2019)
    e = h.evidencia_pdf(f["fuente"], f["pagina"], f["municipio_pdf"])
    assert e["encontrado"]
    assert all(c["en_pdf"] for c in h.comparar_con_pdf(f, e).values())


def test_anclaje_rechaza_cita_inventada():
    f = h.fila_panel("05360", 2017)
    e = h.evidencia_pdf(f["fuente"], f["pagina"], f["municipio_pdf"])
    inc = {"cod_divipola": "05360", "anio": 2017}
    diag = {"cod_divipola": "05360", "anio": 2017, "archivo": e["archivo"], "pagina": e["pagina"],
            "causa": "dato_plausible", "conclusion": "x"}
    assert verificar_anclaje({**diag, "cita_textual": e["fila_texto"]}, inc, e)["confianza"] == "alta"
    assert not verificar_anclaje({**diag, "cita_textual": "ITAGUI 99999"}, inc, e)["anclado"]


def test_anclaje_rechaza_cifras_inventadas_y_extraccion_si_coincide():
    f = h.fila_panel("05360", 2017)
    e = h.evidencia_pdf(f["fuente"], f["pagina"], f["municipio_pdf"])
    e.update(fila_panel={"poblacion_perros": 18740.0}, coincide_pdf=True, causa_fija=None)
    inc = {"cod_divipola": "05360", "anio": 2017, "valor_citado": "+80.2%"}
    diag = {"cod_divipola": "05360", "anio": 2017, "archivo": e["archivo"], "pagina": e["pagina"],
            "cita_textual": e["fila_texto"], "causa": "dato_plausible",
            "conclusion": "En 2017 el PDF reporta 18740 perros, un salto de +80.2%."}
    assert verificar_anclaje(diag, inc, e)["anclado"]
    malo = verificar_anclaje({**diag, "conclusion": "Faltan 844 gatos vacunados."}, inc, e)
    assert any("844" in p for p in malo["problemas"])
    assert not verificar_anclaje({**diag, "causa": "error_extraccion"}, inc, e)["anclado"]


def test_codigo_decide_causa_cuando_el_panel_no_coincide():
    inc = {"regla": "cobertura_100"}
    ev = {"comparacion": {"vacunados_perros_gatos": {"panel": 1.0, "en_pdf": False}}, "coincide_pdf": False}
    assert G.causa_por_codigo(inc, ev) == "error_extraccion"
    assert G.causa_por_codigo({"regla": "duplicado"}, {"comparacion": {}, "coincide_pdf": False}) == "error_extraccion"
    ok = {"comparacion": {"poblacion_perros": {"panel": 1.0, "en_pdf": True}}, "coincide_pdf": True}
    assert G.causa_por_codigo({"regla": "cobertura_100"}, ok) is None


def test_grafo_corta_en_tres_intentos_y_pausa_para_revision(monkeypatch, tmp_path):
    monkeypatch.setattr(G, "generar_json", lambda m, etiqueta: {"causa": "otra"})
    monkeypatch.setattr(G.config, "RESULTADOS", tmp_path)  # no pisar resultados reales
    grafo = G.construir()
    inc = h.cargar_incidencias().head(2)
    hilo = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 80}
    grafo.invoke({"pendientes": inc.astype(object).where(inc.notna(), None).to_dict("records"),
                  "resultados": []}, hilo)
    assert grafo.get_state(hilo).next == ("revision_humana",)
    salida = grafo.invoke(Command(resume={"decisiones": {}}), hilo)
    assert [r["intentos"] for r in salida["resultados"]] == [3, 3]
    assert all(r["revision_humana"] == "pendiente" for r in salida["resultados"])


def test_reglas_reproducen_saltos_de_edward():
    d = detectar(h.cargar_panel())
    inc = h.cargar_incidencias()
    mias = set(zip(d[d.regla == "salto_poblacion"].cod_divipola, d[d.regla == "salto_poblacion"].anio))
    suyas = set(zip(inc[inc.regla == "salto_poblacion"].cod_divipola, inc[inc.regla == "salto_poblacion"].anio))
    assert mias == suyas


def test_siembra_60_fallas_y_wilson():
    _, _, fallas = sembrar(h.cargar_panel(), 2026)
    assert len(fallas) == 60
    lo, hi = wilson(60, 60)
    assert 0.93 < lo < 0.95 and hi > 0.999
