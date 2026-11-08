"""Pruebas sin LLM: herramientas, reglas, anclaje, grafo y evaluación sembrada sobre SECOP II."""
import uuid

from langgraph.types import Command

from agente import grafo as G, herramientas as h
from agente.anclaje import verificar_anclaje
from agente.validaciones import detectar
from correr import como_registros
from evaluar import sembrar, wilson


def test_pesos_lee_formato_secop():
    assert h.pesos("$57.333.333") == 57333333
    assert h.pesos("$0") == 0
    assert h.pesos(None) != h.pesos(None)  # NaN


def test_reglas_detectan_el_valor_imposible_de_rionegro():
    d = detectar(h.cargar_procesos())
    fila = d[(d["id_proceso"] == "CO1.REQ.1615047") & (d["regla"] == "adjudicacion_supera_base")]
    assert len(fila) == 1


def test_anclaje_exige_cita_real_y_cifras_del_registro():
    p = h.cargar_procesos()
    id_ = p.iloc[0][h.ID]
    ev = {"registros": h.registros(id_, p), "otros": []}
    nombre = ev["registros"][0]["Nombre del Procedimiento"]
    precio = ev["registros"][0]["Precio Base"]
    diag = {"id_proceso": id_, "causa": "dato_plausible", "cita_textual": nombre[:60],
            "conclusion": f"El precio base publicado es {precio}."}
    inc = {"id_proceso": id_, "regla": "precio_atipico"}
    assert verificar_anclaje(diag, inc, ev)["anclado"]
    assert not verificar_anclaje({**diag, "cita_textual": "texto que no está en SECOP"}, inc, ev)["anclado"]
    assert verificar_anclaje({**diag, "cita_textual": f"Precio Base: {precio}"}, inc, ev)["anclado"]
    # Un pedazo de una cifra no cuenta como cita: "$57" no ancla "$57.333.333".
    assert not verificar_anclaje({**diag, "cita_textual": f"Precio Base: {precio[:4]}"}, inc, ev)["anclado"]
    malo = verificar_anclaje({**diag, "conclusion": "Costó $123.456.789.999."}, inc, ev)
    assert any("123.456.789.999" in x for x in malo["problemas"])


def test_codigo_decide_casos_obvios():
    ev = {"registros": [{"Modalidad de Contratacion": "Mínima cuantía"}]}
    assert G.causa_por_codigo({"regla": "id_duplicado"}, ev)[0] == "registro_duplicado"
    assert G.causa_por_codigo({"regla": "precio_base_cero"}, ev)[0] == "error_de_registro"
    sol = {"registros": [{"Modalidad de Contratacion": "Solicitud de información a los Proveedores"}]}
    assert G.causa_por_codigo({"regla": "precio_base_cero"}, sol)[0] is None
    assert G.causa_por_codigo({"regla": "precio_atipico"}, ev)[0] is None


def test_codigo_decide_montos_imposibles_pero_no_contratos_grandes_reales():
    d = detectar(h.cargar_procesos()).set_index("id_proceso")
    ev = {"registros": [{}]}
    causa = lambda id_, regla: G.causa_por_codigo({**d[d["regla"] == regla].loc[id_].to_dict(), "regla": regla}, ev)[0]
    assert causa("CO1.REQ.387286", "precio_atipico") == "error_de_registro"         # $4,8 billones
    assert causa("CO1.REQ.1615047", "adjudicacion_supera_base") == "error_de_registro"  # Rionegro
    assert causa("CO1.REQ.2548914", "precio_atipico") is None                         # Colpensiones: lo juzga el modelo


def test_grafo_corta_en_tres_intentos_y_pausa_para_revision(monkeypatch, tmp_path):
    monkeypatch.setattr(G, "generar_json", lambda m, etiqueta: {"causa": "otra"})
    monkeypatch.setattr(G.config, "RESULTADOS", tmp_path)  # no pisar resultados reales
    inc = detectar(h.cargar_procesos()).head(2)
    inc.insert(0, "id", [1, 2])
    grafo = G.construir()
    hilo = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 80}
    grafo.invoke({"pendientes": como_registros(inc), "resultados": []}, hilo)
    assert grafo.get_state(hilo).next == ("revision_humana",)
    salida = grafo.invoke(Command(resume={"decisiones": {}}), hilo)
    assert [r["intentos"] for r in salida["resultados"]] == [3, 3]
    assert all(r["revision_humana"] == "pendiente" for r in salida["resultados"])


def test_siembra_60_fallas_y_wilson():
    _, _, fallas = sembrar(h.cargar_procesos(), 2026)
    assert len(fallas) == 60
    lo, hi = wilson(60, 60)
    assert 0.93 < lo < 0.95 and hi > 0.999
