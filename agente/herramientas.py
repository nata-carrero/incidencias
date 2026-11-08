"""Herramientas en código (sin LLM): leen el panel, DIVIPOLA y la fila exacta del PDF."""
import re
import unicodedata
from functools import lru_cache

import pymupdf as fitz
import pandas as pd

from . import config

CAMPOS_PANEL = ["pob_dane", "poblacion_perros", "poblacion_gatos", "vacunados_perros",
                "vacunados_perros_gatos", "hab_por_perro", "metodo_estimacion"]


def normalizar(texto) -> str:
    texto = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9 ]", "", texto.upper()).strip()


@lru_cache(maxsize=1)
def cargar_panel() -> pd.DataFrame:
    return pd.read_parquet(config.PANEL)


@lru_cache(maxsize=1)
def cargar_incidencias() -> pd.DataFrame:
    inc = pd.read_csv(config.INCIDENCIAS, dtype={"cod_divipola": str}, encoding="utf-8-sig")
    inc["id"] = range(1, len(inc) + 1)
    return inc


@lru_cache(maxsize=1)
def cargar_divipola() -> set[str]:
    d = pd.read_csv(config.DIVIPOLA, dtype=str)
    return set(d["Código Municipio"].str.zfill(5))


def fila_panel(cod: str, anio: int, panel: pd.DataFrame | None = None) -> dict | None:
    panel = cargar_panel() if panel is None else panel
    f = panel[(panel["cod_divipola"] == cod) & (panel["anio"] == anio)]
    return None if f.empty else f.iloc[0].to_dict()


def _ruta_pdf(archivo: str):
    carpeta = config.PDFS["ins" if archivo.startswith("ins_") else "minsalud"]
    return carpeta / archivo


@lru_cache(maxsize=64)
def _lineas_pagina(archivo: str, pagina: int) -> tuple[str, ...]:
    with fitz.open(_ruta_pdf(archivo)) as doc:
        if not 1 <= pagina <= doc.page_count:
            return ()
        return tuple(l.strip() for l in doc[pagina - 1].get_text().splitlines() if l.strip())


def _es_numero(linea: str) -> bool:
    return bool(re.fullmatch(r"[\d.,%]+", linea))


def _numero(linea: str) -> float:
    s = linea.replace("%", "")
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):  # separador de miles: 177,815 o 177.815
        return float(re.sub(r"[.,]", "", s))
    return float(s.replace(".", "").replace(",", "."))


def evidencia_pdf(archivo: str, pagina: int, municipio_pdf: str) -> dict:
    """Busca el municipio en la página y devuelve su fila de números tal como está impresa."""
    lineas = _lineas_pagina(archivo, int(pagina))
    encabezado = [l for l in lineas[:12] if not _es_numero(l)]
    objetivo = normalizar(municipio_pdf)
    for i, linea in enumerate(lineas):
        if normalizar(linea) == objetivo:
            numeros = []
            for siguiente in lineas[i + 1:i + 9]:
                if not _es_numero(siguiente):
                    break
                numeros.append(siguiente)
            return {"encontrado": True, "archivo": archivo, "pagina": int(pagina),
                    "encabezado": encabezado, "fila_texto": " ".join([linea, *numeros]),
                    "numeros": [_numero(n) for n in numeros]}
    return {"encontrado": False, "archivo": archivo, "pagina": int(pagina),
            "encabezado": encabezado, "fila_texto": "", "numeros": []}


def buscar_en_pdf(archivo: str, municipio_pdf: str) -> dict:
    """Recorre todas las páginas: sirve cuando el municipio falta en el panel."""
    with fitz.open(_ruta_pdf(archivo)) as doc:
        paginas = doc.page_count
    for pagina in range(1, paginas + 1):
        evidencia = evidencia_pdf(archivo, pagina, municipio_pdf)
        if evidencia["encontrado"]:
            return evidencia
    return {"encontrado": False, "archivo": archivo, "pagina": None,
            "encabezado": [], "fila_texto": "", "numeros": []}


def comparar_con_pdf(fila: dict, evidencia: dict) -> dict:
    """Para cada cifra del panel, ¿aparece tal cual en la fila del PDF?"""
    comparacion = {}
    for campo in ("poblacion_perros", "poblacion_gatos", "vacunados_perros_gatos"):
        valor = fila.get(campo)
        if valor is None or pd.isna(valor):
            continue
        comparacion[campo] = {"panel": valor,
                              "en_pdf": any(abs(valor - n) < 0.5 for n in evidencia["numeros"])}
    return comparacion


def pagina_contiene(archivo: str, pagina: int, texto: str) -> bool:
    """Anclaje: la cita textual debe existir en esa página del PDF (ignorando tildes y espacios)."""
    cita = re.sub(r"\s+", "", normalizar(texto))
    if not cita:
        return False
    pagina_txt = re.sub(r"\s+", "", normalizar(" ".join(_lineas_pagina(archivo, int(pagina)))))
    return cita in pagina_txt
