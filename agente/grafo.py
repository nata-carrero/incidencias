"""Grafo del agente en LangGraph.

orquestador → evidencia (código) → diagnóstico (LLM) → verificar_anclaje (código)
  ├─ sin anclaje y < 3 intentos → vuelve a diagnóstico con los problemas encontrados
  └─ anclado o 3 intentos → guardar → orquestador (siguiente incidencia)
orquestador sin pendientes → revisión humana (interrupt) → cargar

Las reglas (máximo 3 intentos, causas obvias decididas por código, anclaje verificado,
nada se carga sin revisión humana) están en el grafo, así que el modelo no puede saltárselas.
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

INSTRUCCION = f"""Eres el subagente de diagnóstico de procesos de contratación pública de servicios
funerarios publicados en SECOP II (Colombia). Recibes una incidencia detectada por reglas y el
registro tal como está publicado en SECOP. Decide la causa más probable usando SOLO esa evidencia:
- error_de_registro: un valor, fecha o campo del registro está mal diligenciado (p. ej. una cifra imposible).
- registro_duplicado: el mismo proceso aparece registrado más de una vez sin justificación.
- no_funerario: el objeto del contrato no es la compra de servicios o bienes funerarios.
- dato_plausible: el dato es correcto o tiene explicación en el propio registro (p. ej. un proceso
  publicado en dos fases, un cambio de estado o una adjudicación por lotes).
- indeterminado: la evidencia no alcanza para decidir.
Responde SOLO con JSON con estas claves exactas:
{{"id_proceso": "...", "causa": "una de {list(config.CAUSAS)}",
"cita_textual": "«Campo: valor» exacto del registro (p. ej. Precio Base: $0) o un fragmento literal del Nombre o la Descripción; nunca el texto de la alerta",
"conclusion": "una o dos frases en español; toda cifra debe copiarse tal cual del registro"}}"""

CAUSA_FIJA = {
    "id_duplicado": ("registro_duplicado", "el mismo ID aparece en varias filas"),
    "adjudicado_sin_valor": ("error_de_registro", "adjudicado con valor $0"),
    "categoria_no_definida": ("error_de_registro", "falta el código UNSPSC"),
}
# Cuando decide el código, la cita también la pone el código: el campo que prueba la causa.
CAMPO_CITA = {"id_duplicado": h.ID, "adjudicado_sin_valor": "Valor Total Adjudicacion",
              "categoria_no_definida": "Codigo Principal de Categoria", "precio_base_cero": "Precio Base"}


def causa_por_codigo(inc: dict, ev: dict) -> tuple[str, str] | tuple[None, None]:
    """Casos obvios que decide el código, no el modelo."""
    if inc["regla"] in CAUSA_FIJA:
        return CAUSA_FIJA[inc["regla"]]
    modalidad = (ev["registros"][0].get("Modalidad de Contratacion") or "") if ev["registros"] else ""
    if inc["regla"] == "precio_base_cero" and not modalidad.startswith("Solicitud de información"):
        return ("error_de_registro", "proceso activo con precio base $0")
    return (None, None)


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


def construir(procesos: pd.DataFrame | None = None, checkpointer=None):
    procesos = h.cargar_procesos() if procesos is None else procesos

    def orquestador(estado: Estado) -> Estado:
        pendientes = list(estado.get("pendientes", []))
        if not pendientes:
            return {"actual": None}
        return {"actual": pendientes.pop(0), "pendientes": pendientes, "intentos": 0}

    def evidencia(estado: Estado) -> Estado:
        inc = estado["actual"]
        ev = {"registros": h.registros(inc["id_proceso"], procesos),
              "otros": [r for i in (inc.get("otros_ids") or [])[:3] for r in h.registros(i, procesos)]}
        ev["causa_fija"], ev["motivo_causa"] = causa_por_codigo(inc, ev)
        return {"evidencia": ev}

    def diagnostico(estado: Estado) -> Estado:
        inc, ev = estado["actual"], estado["evidencia"]
        # "regla" se pasa como "tipo_de_alerta" para que el modelo no la confunda con la causa.
        alerta = {("tipo_de_alerta" if k == "regla" else k): _limpio(v) for k, v in inc.items() if k != "id"}
        datos = {"alerta": alerta, "registro_secop": ev["registros"], "otros_procesos_parecidos": ev["otros"]}
        mensajes = [{"role": "system", "content": INSTRUCCION},
                    {"role": "user", "content": json.dumps(datos, ensure_ascii=False, default=str)}]
        if ev["causa_fija"]:
            mensajes.append({"role": "user", "content": f"La causa ya la decidió el código: {ev['causa_fija']} "
                             f"({ev['motivo_causa']}). Usa esa causa y explícala solo con la evidencia."})
        if estado.get("anclaje") and not estado["anclaje"]["anclado"]:
            mensajes.append({"role": "user", "content": "Tu respuesta anterior falló la verificación: "
                             + "; ".join(estado["anclaje"]["problemas"]) + ". Corrígela."})
        diag = generar_json(mensajes, etiqueta=f"diagnostico {inc['id_proceso']} {inc['regla']}")
        if ev["causa_fija"]:  # el modelo no puede cambiar una causa decidida por código
            diag["causa"] = ev["causa_fija"]
            campo = CAMPO_CITA.get(inc["regla"])
            if campo and ev["registros"]:
                diag["cita_textual"] = f"{campo}: {ev['registros'][0].get(campo)}"
        return {"diagnostico": diag, "intentos": estado.get("intentos", 0) + 1}

    def verificar(estado: Estado) -> Estado:
        return {"anclaje": verificar_anclaje(estado["diagnostico"], estado["actual"], estado["evidencia"])}

    def guardar(estado: Estado) -> Estado:
        inc, diag, anc = estado["actual"], estado["diagnostico"], estado["anclaje"]
        url = estado["evidencia"]["registros"][0].get("URLProceso") if estado["evidencia"]["registros"] else None
        fila = {"id": inc.get("id"), "id_proceso": inc["id_proceso"], "entidad": inc.get("entidad"),
                "regla": inc["regla"], "valor_citado": inc.get("valor_citado"), "causa": diag.get("causa"),
                "decidida_por": "codigo" if estado["evidencia"]["causa_fija"] else "llm",
                "conclusion": diag.get("conclusion"), "cita_textual": diag.get("cita_textual"),
                "url_secop": url, "anclado": anc["anclado"], "confianza": anc["confianza"],
                "problemas": "; ".join(anc["problemas"]), "intentos": estado["intentos"]}
        return {"resultados": [*estado.get("resultados", []), fila], "anclaje": None}

    def revision_humana(estado: Estado) -> Estado:
        dudosos = [r for r in estado.get("resultados", []) if r["confianza"] != "alta"]
        decision = interrupt({"total": len(estado.get("resultados", [])), "para_revisar": dudosos})
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
