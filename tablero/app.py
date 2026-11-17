"""Tablero del mercado público de servicios funerarios en SECOP II.

  .venv\\Scripts\\python.exe -m streamlit run tablero\\app.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # para importar agente/ y tablero/

import altair as alt
import pandas as pd
import streamlit as st

from tablero import incidencias
from tablero.datos import base_tablero, concentracion, depurar

AZUL = "#2a78d6"  # una sola tonalidad: todos los gráficos comparan magnitudes de una misma medida
GRIS = "#8a8984"
H_ID = "ID del Proceso"
MEDIDAS = {"Valor adjudicado": "valor_adjudicado_mercado", "Precio base (presupuesto)": "precio_base_mercado"}

st.set_page_config(page_title="Mercado público funerario · SECOP II", page_icon="⚱️", layout="wide")


def pesos(valor: float) -> str:
    """Pesos en palabras: $86.745 millones, $814 billones."""
    if pd.isna(valor):
        return "—"
    if valor < 0:  # el signo va antes del $ para que Streamlit dibuje la flecha hacia abajo
        return "-" + pesos(-valor)
    for limite, nombre in ((1e12, "billones"), (1e6, "millones")):
        if abs(valor) >= limite:
            cifra = valor / limite
            texto = f"{cifra:,.0f}" if cifra >= 100 else f"{cifra:,.1f}"
            return "$" + texto.replace(",", "X").replace(".", ",").replace("X", ".") + f" {nombre}"
    return "$" + f"{valor:,.0f}".replace(",", ".")


def entero(n) -> str:
    return f"{n:,.0f}".replace(",", ".")


@st.cache_data(show_spinner="Cargando los procesos de SECOP II…")
def cargar() -> pd.DataFrame:
    return base_tablero()


def escala(maximo: float) -> tuple[float, str]:
    """Unidad del eje en palabras, según el valor más grande que se va a dibujar."""
    if maximo >= 1e12:
        return 1e12, "billones de pesos"
    if maximo >= 1e9:
        return 1e9, "miles de millones de pesos"
    return 1e6, "millones de pesos"


def barras_horizontales(df: pd.DataFrame, etiqueta: str, valor: str, titulo_valor: str):
    divisor, unidad = escala(df[valor].max() if len(df) else 0)
    df = df.assign(texto_valor=df[valor].map(pesos), texto_procesos=df["procesos"].map(entero),
                   en_escala=df[valor] / divisor)
    return (alt.Chart(df).mark_bar(color=AZUL, cornerRadiusEnd=4, height={"band": 0.7})
            .encode(y=alt.Y(f"{etiqueta}:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
                    x=alt.X("en_escala:Q", title=f"{titulo_valor} ({unidad})", axis=alt.Axis(grid=True)),
                    tooltip=[alt.Tooltip(f"{etiqueta}:N", title=etiqueta.capitalize()),
                             alt.Tooltip("texto_valor:N", title=titulo_valor),
                             alt.Tooltip("texto_procesos:N", title="Procesos")])
            .properties(height=max(160, 26 * len(df))))


base_completa = cargar()

# --- Filtros -------------------------------------------------------------------------------
st.title("Mercado público de servicios funerarios")
st.caption("Procesos de contratación de servicios funerarios publicados en SECOP II, 2017–2026 · "
           "3.138 procesos de la base del equipo · pesos corrientes")

with st.sidebar:
    st.header("Filtros")
    anios = st.slider("Años", 2017, 2026, (2017, 2026))
    deptos = st.multiselect("Departamento", sorted(base_completa["departamento"].unique()),
                            placeholder="Todos")
    clasif = st.multiselect("Clasificación del equipo", sorted(base_completa["clasificacion_equipo"].dropna().unique()),
                            placeholder="Todas")
    medida_nombre = st.radio("Medida", list(MEDIDAS), help="El valor adjudicado solo cuenta los procesos adjudicados.")
    depura = st.toggle("Depurar con las reglas del agente", value=True,
                       help="Quita los procesos repetidos con otro ID y los montos imposibles. "
                            "Las filas repetidas del mismo ID siempre se cuentan una vez.")
medida = MEDIDAS[medida_nombre]

filtro = base_completa["anio"].between(*anios)
if anios == (2017, 2026):  # con el rango completo también cuentan los procesos sin fecha
    filtro |= base_completa["anio"].isna()
if deptos:
    filtro &= base_completa["departamento"].isin(deptos)
if clasif:
    filtro &= base_completa["clasificacion_equipo"].isin(clasif)
sin_depurar = base_completa[filtro]
datos = depurar(sin_depurar) if depura else sin_depurar

# --- Indicadores ---------------------------------------------------------------------------
total, total_sin = datos[medida].sum(), sin_depurar[medida].sum()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Procesos", entero(len(datos)),
          f"{entero(len(datos) - len(sin_depurar))} al depurar" if depura else None, delta_color="off")
c2.metric(medida_nombre, pesos(total),
          f"{pesos(total - total_sin)} al depurar" if depura and total != total_sin else None, delta_color="off")
c3.metric("Entidades", entero(datos["Nit Entidad"].nunique()), help="Entidades públicas que contratan")
c4.metric("Proveedores", entero(datos.loc[datos["proveedor_id"] != "", "proveedor_id"].nunique()),
          help="Proveedores adjudicados, por NIT o por nombre")

if not depura and sin_depurar["monto_imposible"].any():
    st.warning(f"Sin depurar, el total incluye {int(sin_depurar['monto_imposible'].sum())} montos imposibles. "
               "Por ejemplo, un valor adjudicado de $813.880.846.788.409 en Rionegro. "
               "Activa «Depurar con las reglas del agente» para quitarlos.")

pestanas = st.tabs(["Evolución", "Dónde se contrata", "Quién contrata", "Concentración", "Qué se depuró",
                   "Incidencias"])

# --- Evolución -----------------------------------------------------------------------------
with pestanas[0]:
    por_anio = (datos.dropna(subset=["anio"]).groupby("anio")
                .agg(valor=(medida, "sum"), procesos=(H_ID, "count")).reset_index())
    por_anio["anio"] = por_anio["anio"].astype(int).astype(str)
    divisor, unidad = escala(por_anio["valor"].max() if len(por_anio) else 0)
    por_anio = por_anio.assign(texto_valor=por_anio["valor"].map(pesos), texto_procesos=por_anio["procesos"].map(entero),
                               en_escala=por_anio["valor"] / divisor)
    izq, der = st.columns(2)
    with izq:
        st.subheader(f"{medida_nombre} por año")
        st.altair_chart(alt.Chart(por_anio).mark_bar(color=AZUL, cornerRadiusEnd=4, width={"band": 0.7})
                        .encode(x=alt.X("anio:N", title=None, axis=alt.Axis(labelAngle=0)),
                                y=alt.Y("en_escala:Q", title=unidad.capitalize()),
                                tooltip=[alt.Tooltip("anio:N", title="Año"), alt.Tooltip("texto_valor:N", title=medida_nombre),
                                         alt.Tooltip("texto_procesos:N", title="Procesos")]),
                        use_container_width=True)
    with der:
        st.subheader("Procesos por año")
        st.altair_chart(alt.Chart(por_anio).mark_bar(color=AZUL, cornerRadiusEnd=4, width={"band": 0.7})
                        .encode(x=alt.X("anio:N", title=None, axis=alt.Axis(labelAngle=0)),
                                y=alt.Y("procesos:Q", title="Procesos"),
                                tooltip=[alt.Tooltip("anio:N", title="Año"), alt.Tooltip("texto_procesos:N", title="Procesos"),
                                         alt.Tooltip("texto_valor:N", title=medida_nombre)]),
                        use_container_width=True)
    st.caption("2026 llega hasta el 6 de octubre, fecha de descarga de SECOP II. "
               f"{entero(datos['anio'].isna().sum())} procesos no tienen fecha de publicación y no aparecen aquí.")

# --- Dónde se contrata ---------------------------------------------------------------------
with pestanas[1]:
    por_depto = (datos.groupby("departamento").agg(valor=(medida, "sum"), procesos=(H_ID, "count"))
                 .reset_index().rename(columns={"departamento": "departamento"}))
    izq, der = st.columns(2)
    with izq:
        st.subheader(f"{medida_nombre} por departamento")
        st.altair_chart(barras_horizontales(por_depto.nlargest(15, "valor"), "departamento", "valor", medida_nombre),
                        use_container_width=True)
    with der:
        st.subheader(f"{medida_nombre} por modalidad")
        por_mod = datos.groupby("modalidad").agg(valor=(medida, "sum"), procesos=(H_ID, "count")).reset_index()
        st.altair_chart(barras_horizontales(por_mod, "modalidad", "valor", medida_nombre), use_container_width=True)
    st.caption("Departamento de la entidad que contrata. Se muestran los 15 departamentos con mayor valor.")

# --- Quién contrata ------------------------------------------------------------------------
with pestanas[2]:
    st.subheader("Entidades que más contratan")
    top = (datos.groupby(["Entidad", "departamento"]).agg(procesos=(H_ID, "count"), valor=(medida, "sum"))
           .reset_index().nlargest(15, "valor"))
    top["participacion"] = top["valor"] / max(total, 1) * 100
    st.dataframe(top.assign(valor=top["valor"].map(pesos)), hide_index=True, use_container_width=True,
                 column_config={"Entidad": "Entidad", "departamento": "Departamento", "procesos": "Procesos",
                                "valor": medida_nombre,
                                "participacion": st.column_config.ProgressColumn(
                                    "Participación", format="%.1f %%", min_value=0, max_value=100)})

# --- Concentración -------------------------------------------------------------------------
with pestanas[3]:
    st.subheader("Concentración de proveedores")
    st.markdown("El **HHI** suma los cuadrados de las participaciones de cada proveedor en el valor adjudicado "
                "(de 0 a 10.000): menos de 1.500 es un mercado poco concentrado, de 1.500 a 2.500 moderado y más "
                "de 2.500 alto. El **CR4** es la participación de los 4 proveedores más grandes.")
    nac = concentracion(datos)
    k1, k2, k3 = st.columns(3)
    k1.metric("HHI nacional", entero(nac["hhi"]) if pd.notna(nac["hhi"]) else "—")
    k2.metric("CR4 nacional", f"{nac['cr4']:.1f} %".replace(".", ",") if pd.notna(nac["cr4"]) else "—")
    k3.metric("Adjudicaciones con proveedor", entero(nac["adjudicaciones"]))
    filas = []
    for depto, grupo in datos.groupby("departamento"):
        c = concentracion(grupo)
        if c["adjudicaciones"] >= 5:
            filas.append({"Departamento": depto, "HHI": round(c["hhi"]), "CR4 (%)": round(c["cr4"], 1),
                          "Proveedores": c["proveedores"], "Adjudicaciones": c["adjudicaciones"]})
    if filas:
        tabla = pd.DataFrame(filas).sort_values("HHI", ascending=False)
        tabla["Nivel"] = pd.cut(tabla["HHI"], [-1, 1500, 2500, 10001], labels=["bajo", "moderado", "alto"])
        st.markdown("**Por departamento** (con al menos 5 adjudicaciones):")
        st.dataframe(tabla, hide_index=True, use_container_width=True)
    st.caption("Cada proveedor se identifica por su NIT cuando SECOP II lo publica y, si no, por su nombre. "
               "Un mismo proveedor escrito de dos formas distintas cuenta como dos, lo que subestima un poco la concentración.")

# --- Qué se depuró -------------------------------------------------------------------------
with pestanas[4]:
    st.subheader("Qué quita la depuración")
    rep, imp = sin_depurar["repetido"].sum(), sin_depurar["monto_imposible"].sum()
    st.markdown(f"- **{entero(sin_depurar['filas_extra'].sum())} filas repetidas del mismo ID**: siempre se cuentan una vez.\n"
                f"- **{entero(rep)} procesos repetidos con otro ID**: casi todos son el mismo proceso publicado en dos "
                "fases (manifestación de interés y presentación de oferta).\n"
                f"- **{entero(imp)} montos imposibles**: precio base o adjudicación que el agente marca como error de "
                "registro (100 veces o más lo que contrata la misma entidad, o adjudicación de 1,5 veces el presupuesto).")
    malos = sin_depurar[sin_depurar["monto_imposible"]][
        ["ID del Proceso", "Entidad", "Precio Base", "Valor Total Adjudicacion", "URLProceso"]]
    if not malos.empty:
        st.dataframe(malos, hide_index=True, use_container_width=True,
                     column_config={"URLProceso": st.column_config.LinkColumn("SECOP", display_text="ver proceso")})
    st.caption("Las reglas y los diagnósticos vienen del agente de incidencias del mismo proyecto.")

# --- Incidencias (agente + revisión humana) ---------------------------------------------------
with pestanas[5]:
    incidencias.mostrar()  # el código está en tablero/incidencias.py

st.divider()
st.caption("Fuente: SECOP II – Procesos de Contratación (datos.gov.co), descarga del 6 de octubre de 2026. "
           "Valores en pesos corrientes, sin deflactar ni adiciones. Proyecto de consultoría USTA.")
