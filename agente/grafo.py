"""Grafo del agente en LangGraph.

orquestador → evidencia (código) → diagnóstico (LLM) → verificar_anclaje (código)
  ├─ sin anclaje y < 3 intentos → vuelve a diagnóstico con los problemas encontrados
  └─ anclado o 3 intentos → guardar → orquestador (siguiente incidencia)
orquestador sin pendientes → revisión humana (interrupt) → cargar

Las reglas (máximo 3 intentos, no cargar sin revisión humana, anclaje verificado por
código) están en las aristas, así que el modelo no puede saltárselas.
"""
import json
from typing import Any, TypedDict

import pandas as pd
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from . import config, herramientas as h
from .anclaje import verificar_anclaje
from .llm import generar_json

INSTRUCCION = f"""Eres el subagente de diagnóstico de un panel municipal de perros y gatos
extraído de los PDF de vacunación antirrábica de MinSalud (Colombia).
Recibes una incidencia detectada por reglas, la fila del panel y la fila impresa en el PDF.
Decide la causa más probable usando SOLO esa evidencia:
- error_extraccion: el panel no coincide con la fila del PDF, o la fila falta, está repetida o tiene un código que no existe.
- cambio_metodo: las cifras coinciden con el PDF, pero el salto se explica por un cambio de método o de fuente entre años.
- dato_plausible: las cifras coinciden con el PDF y el valor es posible.
- indeterminado: la evidencia no alcanza para decidir.
Responde SOLO con JSON con estas claves exactas:
{{"cod_divipola": "...", "anio": 2017, "valor_citado": "...", "archivo": "...", "pagina": 1,
"cita_textual": "copia exacta de fila_texto del PDF", "causa": "una de {list(config.CAUSAS)}",
"conclusion": "una o dos frases en español"}}
No inventes cifras: todo número de la conclusión debe estar en la evidencia."""


class Estado(TypedDict, total=False):
    pendientes: list[dict]
    actual: dict | None
    evidencia: dict
    diagnostico: dict
    anclaje: dict
    intentos: int
    resultados: list[dict]
    decision_humana: Any


def _limpio(valor):
    if isinstance(valor, float) and pd.isna(valor):
        return None
    return valor.item() if hasattr(valor, "item") else valor


ESTRUCTURALES = {"duplicado": "fila repetida en el panel",
                 "codigo_invalido": "el código no existe en DIVIPOLA"}


def causa_por_codigo(inc: dict, ev: dict) -> str | None:
    """Casos obvios que decide el código, no el modelo. Deja el motivo en ev['motivo_causa']."""
    motivo = ESTRUCTURALES.get(inc.get("regla"))
    if not motivo and inc.get("regla") == "municipio_faltante" and ev.get("encontrado"):
        motivo = "el municipio sí aparece en el PDF pero falta en el panel"
    if not motivo and ev.get("comparacion") and not ev["coincide_pdf"]:
        distintas = [k for k, c in ev["comparacion"].items() if not c["en_pdf"]]
        motivo = "cifras del panel que no están en la fila del PDF: " + ", ".join(distintas)
    ev["motivo_causa"] = motivo
    return "error_extraccion" if motivo else None


def construir(panel: pd.DataFrame | None = None, checkpointer=None):
    panel = h.cargar_panel() if panel is None else panel

    def orquestador(estado: Estado) -> Estado:
        pendientes = list(estado.get("pendientes", []))
        if not pendientes:
            return {"actual": None}
        return {"actual": pendientes.pop(0), "pendientes": pendientes, "intentos": 0}

    def evidencia(estado: Estado) -> Estado:
        inc = estado["actual"]
        fila = h.fila_panel(inc["cod_divipola"], int(inc["anio"]), panel) if inc.get("cod_divipola") else None
        if fila and fila.get("municipio_pdf") and fila.get("fuente"):
            ev = h.evidencia_pdf(fila["fuente"], fila["pagina"], fila["municipio_pdf"])
        elif inc.get("municipio_pdf") and inc.get("archivo"):
            ev = h.evidencia_pdf(inc["archivo"], inc["pagina"], inc["municipio_pdf"])
        elif inc.get("cod_divipola") and str(inc.get("archivo", "")).startswith("minsalud"):
            # Municipio faltante: tomar su nombre de otro año y buscarlo en todo el PDF.
            otros = panel[panel["cod_divipola"] == inc["cod_divipola"]]
            nombre = otros["municipio_pdf"].dropna().iloc[0] if not otros.empty else ""
            ev = h.buscar_en_pdf(inc["archivo"], nombre) if nombre else {"encontrado": False, "numeros": []}
        else:
            ev = {"encontrado": False, "archivo": inc.get("archivo"), "pagina": inc.get("pagina"), "numeros": []}
        ev["fila_panel"] = {k: _limpio(fila.get(k)) for k in h.CAMPOS_PANEL} if fila else None
        ev["comparacion"] = h.comparar_con_pdf(fila, ev) if fila and ev.get("encontrado") else {}
        ev["coincide_pdf"] = bool(ev["comparacion"]) and all(c["en_pdf"] for c in ev["comparacion"].values())
        ev["causa_fija"] = causa_por_codigo(inc, ev)
        return {"evidencia": ev}

    def diagnostico(estado: Estado) -> Estado:
        inc, ev = estado["actual"], estado["evidencia"]
        datos = {"incidencia": {k: _limpio(v) for k, v in inc.items()},
                 "evidencia": {k: ev.get(k) for k in ("encontrado", "archivo", "pagina", "encabezado",
                                                      "fila_texto", "fila_panel", "comparacion", "coincide_pdf")}}
        mensajes = [{"role": "system", "content": INSTRUCCION},
                    {"role": "user", "content": json.dumps(datos, ensure_ascii=False, default=str)}]
        if ev.get("causa_fija"):
            mensajes.append({"role": "user", "content": f"La causa ya la decidió el código: {ev['causa_fija']} "
                             f"({ev['motivo_causa']}). Usa esa causa y explica solo con la evidencia."})
        elif ev.get("coincide_pdf"):
            mensajes.append({"role": "user", "content": "Las cifras del panel coinciden con el PDF, así que NO es "
                             "error_extraccion: elige entre cambio_metodo, dato_plausible o indeterminado."})
        if estado.get("anclaje") and not estado["anclaje"]["anclado"]:
            mensajes.append({"role": "user", "content": "Tu respuesta anterior falló la verificación: "
                             + "; ".join(estado["anclaje"]["problemas"]) + ". Corrígela."})
        diag = generar_json(mensajes, etiqueta=f"diagnostico {inc.get('cod_divipola')}-{inc.get('anio')}")
        if ev.get("causa_fija"):  # el modelo no puede cambiar una causa decidida por código
            diag["causa"] = ev["causa_fija"]
        return {"diagnostico": diag, "intentos": estado.get("intentos", 0) + 1}

    def verificar(estado: Estado) -> Estado:
        return {"anclaje": verificar_anclaje(estado["diagnostico"], estado["actual"], estado["evidencia"])}

    def guardar(estado: Estado) -> Estado:
        inc, diag, anc = estado["actual"], estado["diagnostico"], estado["anclaje"]
        fila = {"id": inc.get("id"), "cod_divipola": inc.get("cod_divipola"), "anio": inc.get("anio"),
                "regla": inc.get("regla"), "causa": diag.get("causa"),
                "decidida_por": "codigo" if estado["evidencia"].get("causa_fija") else "llm",
                "conclusion": diag.get("conclusion"),
                "archivo": diag.get("archivo"), "pagina": diag.get("pagina"),
                "cita_textual": diag.get("cita_textual"), "anclado": anc["anclado"],
                "confianza": anc["confianza"], "problemas": "; ".join(anc["problemas"]),
                "intentos": estado["intentos"]}
        return {"resultados": [*estado.get("resultados", []), fila], "anclaje": None}

    def revision_humana(estado: Estado) -> Estado:
        baja = [r for r in estado.get("resultados", []) if r["confianza"] != "alta"]
        decision = interrupt({"total": len(estado.get("resultados", [])), "para_revisar": baja})
        return {"decision_humana": decision}

    def cargar(estado: Estado) -> Estado:
        decision = (estado.get("decision_humana") or {}).get("decisiones", {})
        resultados = []
        for r in estado.get("resultados", []):
            estado_rev = "aprobado" if r["confianza"] == "alta" else decision.get(str(r["id"]), "pendiente")
            resultados.append({**r, "revision_humana": estado_rev})
        config.RESULTADOS.mkdir(exist_ok=True)
        pd.DataFrame(resultados).to_csv(config.RESULTADOS / "diagnosticos.csv", index=False, encoding="utf-8-sig")
        return {"resultados": resultados}

    g = StateGraph(Estado)
    for nombre, nodo in [("orquestador", orquestador), ("evidencia", evidencia), ("diagnostico", diagnostico),
                         ("verificar_anclaje", verificar), ("guardar", guardar),
                         ("revision_humana", revision_humana), ("cargar", cargar)]:
        g.add_node(nombre, nodo)
    g.add_edge(START, "orquestador")
    g.add_conditional_edges("orquestador", lambda e: "evidencia" if e.get("actual") else "revision_humana",
                            ["evidencia", "revision_humana"])
    g.add_edge("evidencia", "diagnostico")
    g.add_edge("diagnostico", "verificar_anclaje")
    g.add_conditional_edges(
        "verificar_anclaje",
        lambda e: "guardar" if e["anclaje"]["anclado"] or e["intentos"] >= config.MAX_INTENTOS else "diagnostico",
        ["guardar", "diagnostico"])
    g.add_edge("guardar", "orquestador")
    g.add_edge("revision_humana", "cargar")
    g.add_edge("cargar", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())
