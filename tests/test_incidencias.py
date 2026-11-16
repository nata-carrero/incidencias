"""Pruebas de la lógica de la pestaña «Incidencias», con un modelo falso (sin llamadas reales)."""
from agente import grafo as G, herramientas as h
from tablero import incidencias as I


def test_tabla_tiene_enlace_y_el_lote_no_pasa_de_5():
    inc = I.tabla_incidencias(h.cargar_procesos())
    assert inc["url_secop"].notna().mean() > 0.9
    assert len(I.elegir_lote(inc, 50)) == I.MAX_LOTE
    assert len(I.elegir_lote(inc, 2)) == 2


def test_decisiones_desde_botones():
    assert I.decisiones_desde({1: "Aprobar", 2: "Rechazar", 3: None}) == {
        "1": "aprobado", "2": "rechazado", "3": "pendiente"}


def test_pausa_y_reanuda_con_las_decisiones(monkeypatch, tmp_path):
    # Un modelo falso que nunca ancla: los dos casos quedan con confianza baja y van a revisión.
    monkeypatch.setattr(G, "generar_json", lambda m, etiqueta: {"causa": "otra"})
    monkeypatch.setattr(G.config, "RESULTADOS", tmp_path)
    inc = I.tabla_incidencias(h.cargar_procesos())
    lote = I.elegir_lote(inc[inc["regla"] == "precio_atipico"], 2)
    avance = []
    corrida = I.iniciar(lote, al_guardar=avance.append)
    assert avance == [1, 2]
    dudosos = corrida["pausa"]["para_revisar"]
    assert len(dudosos) == 2
    decisiones = I.decisiones_desde({dudosos[0]["id"]: "Aprobar", dudosos[1]["id"]: "Rechazar"})
    df = I.reanudar(corrida, decisiones)
    assert list(df["revision_humana"]) == ["aprobado", "rechazado"]
    assert not (tmp_path / "diagnosticos.csv").exists()  # se guarda en una carpeta temporal aparte


def test_pestana_muestra_botones_y_aplica_la_decision():
    """Prueba de la interfaz con AppTest de Streamlit y una corrida falsa en pausa."""
    from streamlit.testing.v1 import AppTest

    def pagina():
        from tablero import incidencias
        incidencias.mostrar()

    class GrafoFalso:
        def invoke(self, comando, hilo):
            decision = comando.resume["decisiones"]["7"]
            return {"resultados": [{"id": 7, "id_proceso": "X", "regla": "precio_atipico", "causa": "dato_plausible",
                                    "decidida_por": "llm", "confianza": "media", "intentos": 1,
                                    "revision_humana": decision}]}

    dudoso = {"id": 7, "id_proceso": "X", "regla": "precio_atipico", "causa": "dato_plausible",
              "confianza": "media", "intentos": 1, "conclusion": "Precio alto pero posible.",
              "cita_textual": "Precio Base: $1", "problemas": "", "url_secop": None}
    at = AppTest.from_function(pagina, default_timeout=60)
    at.session_state["inc_corrida"] = {"grafo": GrafoFalso(), "hilo": {}, "resultados": None,
                                       "pausa": {"total": 1, "para_revisar": [dudoso]}}
    at.run()
    assert not at.exception
    radio = at.radio(key="inc_dec_7")
    assert radio.options == ["Aprobar", "Rechazar"]
    radio.set_value("Rechazar").run()
    at.button[0].click().run()
    assert at.success[0].value == "Diagnóstico y revisión terminados."
    assert at.session_state["inc_corrida"]["resultados"]["revision_humana"].tolist() == ["rechazado"]
