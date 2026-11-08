"""Herramientas en código (sin LLM): leen los procesos funerarios de SECOP II y arman la evidencia."""
import re
import unicodedata
from functools import lru_cache

import pandas as pd

from . import config

ID = "ID del Proceso"
CAMPOS_EVIDENCIA = [
    "Entidad", "Nit Entidad", "Departamento Entidad", "Ciudad Entidad", ID, "Referencia del Proceso",
    "Nombre del Procedimiento", "Descripción del Procedimiento", "Fecha de Publicacion del Proceso",
    "Precio Base", "Modalidad de Contratacion", "Justificación Modalidad de Contratación",
    "Estado del Procedimiento", "Adjudicado", "Valor Total Adjudicacion",
    "Nombre del Proveedor Adjudicado", "Codigo Principal de Categoria", "Tipo de Contrato", "URLProceso",
]
CAMPOS_TEXTO = ["Nombre del Procedimiento", "Descripción del Procedimiento",
                "Justificación Modalidad de Contratación", "Entidad", "Referencia del Proceso"]


def normalizar(texto) -> str:
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", texto.upper())


def pesos(valor) -> float:
    """'$57.333.333' -> 57333333.0; vacío -> NaN."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return float("nan")
    s = re.sub(r"[^\d,]", "", str(valor)).replace(",", ".")
    return float(s) if s else float("nan")


@lru_cache(maxsize=1)
def cargar_procesos() -> pd.DataFrame:
    return preparar(pd.read_parquet(config.PROCESOS))


def preparar(p: pd.DataFrame) -> pd.DataFrame:
    """Agrega columnas numéricas y de fecha sin tocar los textos originales (que son la evidencia)."""
    p = p.copy()
    p["precio_base"] = p["Precio Base"].map(pesos)
    p["valor_adjudicado"] = p["Valor Total Adjudicacion"].map(pesos)
    p["fecha"] = pd.to_datetime(p["Fecha de Publicacion del Proceso"], format="%m/%d/%Y", errors="coerce")
    p["anio"] = p["fecha"].dt.year
    p["referencia_base"] = (p["Referencia del Proceso"].fillna("").str.replace(r"\s*\(.*$", "", regex=True)
                            .map(normalizar))
    return p


def registros(id_proceso: str, procesos: pd.DataFrame) -> list[dict]:
    """Todas las filas de SECOP II con ese ID, con los campos tal como están publicados."""
    filas = procesos[procesos[ID] == id_proceso]
    return [{k: (None if pd.isna(f[k]) else f[k]) for k in CAMPOS_EVIDENCIA} for _, f in filas.iterrows()]


def texto_citable(regs: list[dict]) -> str:
    return " ".join(str(r.get(c) or "") for r in regs for c in CAMPOS_EVIDENCIA)


def cita_existe(cita: str, regs: list[dict]) -> bool:
    """Anclaje: la cita debe salir de un campo del registro (ignorando tildes, signos y espacios).

    Vale «Campo: valor» o el valor completo de un campo; en los textos largos (nombre,
    descripción, justificación…) también vale un fragmento de al menos 8 caracteres.
    """
    c = normalizar(cita)
    if not c:
        return False
    for r in regs:
        for campo in CAMPOS_EVIDENCIA:
            valor = r.get(campo)
            if valor is None:
                continue
            v = normalizar(valor)
            if c in (v, normalizar(f"{campo}: {valor}")):
                return True
            if campo in CAMPOS_TEXTO and len(c) >= 8 and c in v:
                return True
    return False
