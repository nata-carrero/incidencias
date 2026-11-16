"""Pestaña «Incidencias»: el agente diagnostica y una persona aprueba o rechaza con botones.

La lógica (elegir el lote, correr el grafo, reanudarlo con las decisiones) está en funciones
sin Streamlit para poder probarla; `mostrar()` solo dibuja la pestaña.
"""
import tempfile
import uuid

import pandas as pd
from langgraph.types import Command

from agente import config, herramientas as h
from agente.grafo import construir
from agente.validaciones import detectar

MAX_LOTE = 5  # cada incidencia hace llamadas al modelo (pagas si es DeepSeek)
OPCIONES = {"Aprobar": "aprobado", "Rechazar": "rechazado"}
COLUMNAS_RESULTADO = ["id_proceso", "regla", "causa", "decidida_por", "confianza", "intentos",
                      "revision_humana", "conclusion", "cita_textual", "url_secop"]


# --- Lógica (sin Streamlit) ----------------------------------------------------------------------

def tabla_incidencias(procesos: pd.DataFrame) -> pd.DataFrame:
    """Incidencias detectadas por las reglas, numeradas y con el enlace a SECOP del proceso."""
    inc = detectar(procesos)
    inc.insert(0, "id", range(1, len(inc) + 1))
    urls = procesos.drop_duplicates(h.ID).set_index(h.ID)["URLProceso"]
    inc["url_secop"] = inc["id_proceso"].map(urls)
    return inc


def como_registros(df: pd.DataFrame) -> list[dict]:
    """Filas a dicts sin NaN (los NaN no se guardan bien en el estado del grafo)."""
    return [{k: (None if not isinstance(v, list) and pd.isna(v) else v) for k, v in fila.items()}
            for fila in df.to_dict("records")]


def elegir_lote(inc: pd.DataFrame, n: int, semilla: int = 1) -> list[dict]:
    """Toma al azar hasta MAX_LOTE incidencias para diagnosticar (sin la columna de enlace)."""
    n = max(1, min(int(n), MAX_LOTE, len(inc)))
    return como_registros(inc.sample(n, random_state=semilla).drop(columns=["url_secop"], errors="ignore"))


def iniciar(lote: list[dict], procesos: pd.DataFrame | None = None, al_guardar=None) -> dict:
    """Corre el grafo hasta la pausa de revisión humana.

    Devuelve una «corrida»: el grafo, su hilo y, si quedó en pausa, los casos para revisar.
    al_guardar(n) se llama cada vez que termina una incidencia (para mostrar el progreso).
    """
    carpeta = tempfile.mkdtemp(prefix="diagnosticos_")  # no pisa resultados/diagnosticos.csv
    grafo = construir(procesos, carpeta_resultados=carpeta)
    hilo = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 20 * len(lote) + 20}
    hechas = 0
    for paso in grafo.stream({"pendientes": lote, "resultados": []}, hilo, stream_mode="updates"):
        if "guardar" in paso:
            hechas += 1
            if al_guardar:
                al_guardar(hechas)
    estado = grafo.get_state(hilo)
    pausa = estado.tasks[0].interrupts[0].value if estado.next else None
    return {"grafo": grafo, "hilo": hilo, "pausa": pausa, "resultados": None}


def decisiones_desde(elegidas: dict) -> dict:
    """{id: "Aprobar" | "Rechazar" | None} → {"id": "aprobado" | "rechazado" | "pendiente"}."""
    return {str(k): OPCIONES.get(v, "pendiente") for k, v in elegidas.items()}


def reanudar(corrida: dict, decisiones: dict) -> pd.DataFrame:
    """Reanuda el grafo con las decisiones humanas, igual que correr.py, y devuelve los resultados."""
    salida = corrida["grafo"].invoke(Command(resume={"decisiones": decisiones}), corrida["hilo"])
    return pd.DataFrame(salida["resultados"])


# --- Pestaña (Streamlit) -------------------------------------------------------------------------

def mostrar():
    import streamlit as st
    from agente.llm import probar_conexion

    procesos = h.cargar_procesos()
    inc = _incidencias_cacheadas(st)()

    st.subheader("Incidencias detectadas por las reglas")
    st.caption("Las reglas son código, sin modelo de lenguaje, y revisan los 3.138 procesos. "
               "Después, el agente diagnostica la causa de algunas y una persona revisa los casos dudosos.")
    reglas = ["Todas"] + sorted(inc["regla"].unique())
    regla = st.selectbox("Tipo de alerta", reglas, key="inc_regla")
    vista = inc if regla == "Todas" else inc[inc["regla"] == regla]
    st.dataframe(vista[["id_proceso", "regla", "entidad", "anio", "valor_citado", "detalle", "url_secop"]],
                 hide_index=True, use_container_width=True, height=300,
                 column_config={"anio": st.column_config.NumberColumn("año", format="%d"),
                                "url_secop": st.column_config.LinkColumn("SECOP", display_text="ver proceso")})
    st.caption(f"{len(vista):,} incidencias".replace(",", "."))

    st.subheader("Diagnóstico con el agente")
    st.caption(f"Modelo: {config.LLM_MODEL} en {config.LLM_BASE_URL}")
    corrida = st.session_state.get("inc_corrida")

    if corrida is None:
        n = st.number_input("¿Cuántas incidencias diagnosticar?", 1, MAX_LOTE, 2, key="inc_n")
        if st.button("Diagnosticar", type="primary"):
            conexion = probar_conexion()
            if not conexion["ok"]:
                st.warning("El agente no está disponible: " + conexion["mensaje"] +
                           " Las reglas y la tabla de arriba funcionan igual.")
                return
            lote = elegir_lote(vista, n, semilla=uuid.uuid4().int % 10_000)
            try:
                with st.status(f"Diagnosticando {len(lote)} incidencias…", expanded=True) as estado:
                    corrida = iniciar(lote, procesos,
                                      al_guardar=lambda k: st.write(f"Incidencia {k} de {len(lote)} lista."))
                    estado.update(label="Diagnóstico terminado", state="complete")
            except Exception as e:  # p. ej., el modelo se cae a mitad de camino
                st.error(f"El diagnóstico se detuvo: {type(e).__name__}. Intenta de nuevo con menos incidencias.")
                return
            st.session_state["inc_corrida"] = corrida
            st.rerun()
        return

    if corrida["resultados"] is None:
        pausa = corrida["pausa"] or {"total": 0, "para_revisar": []}
        dudosos = pausa["para_revisar"]
        st.info(f"Revisión humana: {len(dudosos)} de {pausa['total']} diagnósticos tienen confianza media o baja. "
                "Los de confianza alta se aprueban solos.")
        elegidas = {}
        for r in dudosos:
            with st.container(border=True):
                st.markdown(f"**{r['id_proceso']}** · {r['regla']} → **{r['causa']}** "
                            f"(confianza {r['confianza']}, {r['intentos']} intentos)")
                st.write(r["conclusion"] or "Sin conclusión.")
                st.markdown(f"Cita: «{r['cita_textual']}»")
                if r["problemas"]:
                    st.caption("Problemas del anclaje: " + r["problemas"])
                if r.get("url_secop"):
                    st.markdown(f"[Ver el proceso en SECOP]({r['url_secop']})")
                elegidas[r["id"]] = st.radio("Decisión", list(OPCIONES), index=None, horizontal=True,
                                             key=f"inc_dec_{r['id']}")
        if st.button("Confirmar revisión" if dudosos else "Ver resultados", type="primary"):
            corrida["resultados"] = reanudar(corrida, decisiones_desde(elegidas))
            st.rerun()
        return

    df = corrida["resultados"]
    st.success("Diagnóstico y revisión terminados.")
    st.dataframe(df[[c for c in COLUMNAS_RESULTADO if c in df.columns]], hide_index=True,
                 use_container_width=True,
                 column_config={"url_secop": st.column_config.LinkColumn("SECOP", display_text="ver proceso")})
    st.download_button("Descargar resultados (CSV)", df.to_csv(index=False).encode("utf-8-sig"),
                       file_name="diagnosticos.csv", mime="text/csv")
    st.caption("En la app en línea los archivos se borran al reiniciar: descarga el CSV para conservarlo.")
    if st.button("Nuevo diagnóstico"):
        del st.session_state["inc_corrida"]
        st.rerun()


def _incidencias_cacheadas(st):
    @st.cache_data(show_spinner="Revisando los procesos con las reglas…")
    def _cargar():
        return tabla_incidencias(h.cargar_procesos())
    return _cargar
