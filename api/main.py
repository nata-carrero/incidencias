"""API del mercado público funerario (SECOP II) con FastAPI.

Expone por HTTP los mismos datos del tablero y el agente de incidencias, sin duplicar lógica:
usa tablero/datos.py, agente/validaciones.py (vía tablero/incidencias.py) y el grafo del agente.

  .venv\\Scripts\\python.exe -m uvicorn api.main:app --reload
  → documentación automática en http://127.0.0.1:8000/docs
"""
from functools import lru_cache

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from agente import herramientas as h, llm
from tablero import incidencias as I
from tablero.datos import base_tablero, concentracion, depurar

app = FastAPI(title="Mercado público funerario · SECOP II",
              description="Procesos, incidencias, concentración y diagnóstico del agente. Proyecto de consultoría USTA.")


# --- Modelos de respuesta ------------------------------------------------------------------------

class Salud(BaseModel):
    estado: str


class Proceso(BaseModel):
    id_proceso: str
    entidad: str | None
    departamento: str
    anio: int | None
    modalidad: str
    precio_base: float | None
    valor_adjudicado: float | None
    url_secop: str | None


class Incidencia(BaseModel):
    id: int
    id_proceso: str
    regla: str
    entidad: str | None
    anio: int | None
    valor_citado: str | None
    detalle: str | None
    url_secop: str | None


class Pagina(BaseModel):
    total: int
    limit: int
    offset: int


class PaginaProcesos(Pagina):
    datos: list[Proceso]


class PaginaIncidencias(Pagina):
    datos: list[Incidencia]


class Concentracion(BaseModel):
    depurado: bool
    hhi: float
    cr4: float
    proveedores: int
    adjudicaciones: int


class Diagnostico(BaseModel):
    id_proceso: str
    regla: str
    causa: str | None
    decidida_por: str
    conclusion: str | None
    cita_textual: str | None
    anclado: bool
    confianza: str
    intentos: int
    revision_humana: str
    url_secop: str | None


# --- Datos en memoria (se calculan una vez) -------------------------------------------------------

@lru_cache
def _base() -> pd.DataFrame:
    return base_tablero()


@lru_cache
def _incidencias() -> pd.DataFrame:
    return I.tabla_incidencias(h.cargar_procesos())


def _limpiar(fila: dict) -> dict:
    """NaN de pandas → None, y años como enteros."""
    limpio = {k: (None if not isinstance(v, (list, dict)) and pd.isna(v) else v) for k, v in fila.items()}
    if limpio.get("anio") is not None:
        limpio["anio"] = int(limpio["anio"])
    return limpio


def _paginar(df: pd.DataFrame, limit: int, offset: int) -> tuple[int, list[dict]]:
    return len(df), [_limpiar(f) for f in df.iloc[offset:offset + limit].to_dict("records")]


# --- Endpoints -------------------------------------------------------------------------------------

@app.get("/salud", response_model=Salud)
def salud():
    return {"estado": "ok"}


@app.get("/procesos", response_model=PaginaProcesos)
def procesos(anio: int | None = None, departamento: str | None = None,
             limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    b = _base()
    if anio is not None:
        b = b[b["anio"] == anio]
    if departamento:
        b = b[b["departamento"].str.casefold() == departamento.casefold()]
    vista = pd.DataFrame({
        "id_proceso": b[h.ID], "entidad": b["Entidad"], "departamento": b["departamento"], "anio": b["anio"],
        "modalidad": b["modalidad"], "precio_base": b["precio_base"], "valor_adjudicado": b["valor_adjudicado"],
        "url_secop": b["URLProceso"]})
    total, datos = _paginar(vista, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "datos": datos}


@app.get("/incidencias", response_model=PaginaIncidencias)
def incidencias(regla: str | None = None,
                limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    inc = _incidencias()
    if regla:
        inc = inc[inc["regla"] == regla]
    columnas = ["id", "id_proceso", "regla", "entidad", "anio", "valor_citado", "detalle", "url_secop"]
    vista = inc[columnas].astype({"valor_citado": "string"})
    total, datos = _paginar(vista, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "datos": datos}


@app.get("/mercado/concentracion", response_model=Concentracion)
def mercado_concentracion(depurar_datos: bool = Query(True, alias="depurar")):
    b = depurar(_base()) if depurar_datos else _base()
    return {"depurado": depurar_datos, **concentracion(b)}


@app.post("/diagnosticar/{id_proceso}", response_model=Diagnostico)
def diagnosticar(id_proceso: str):
    """Corre el agente con UNA incidencia del proceso. La revisión humana queda «pendiente» si hace falta."""
    inc = _incidencias()
    del_proceso = inc[inc["id_proceso"] == id_proceso]
    if del_proceso.empty:
        raise HTTPException(404, f"El proceso {id_proceso} no tiene incidencias detectadas.")
    conexion = llm.probar_conexion()
    if not conexion["ok"]:
        raise HTTPException(503, "El agente no está disponible: " + conexion["mensaje"])
    lote = I.como_registros(del_proceso.head(1).drop(columns=["url_secop"]))
    corrida = I.iniciar(lote)
    resultados = I.reanudar(corrida, {}) if corrida["pausa"] else None
    if resultados is None:  # sin pausa no debería pasar: el grafo siempre pasa por la revisión
        raise HTTPException(500, "El agente terminó sin resultados.")
    return _limpiar(resultados.iloc[0].to_dict())
