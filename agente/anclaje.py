"""verificar_anclaje(): comprueba con código que el diagnóstico cite evidencia real.

Formato obligatorio del diagnóstico: municipio, año, valor citado, archivo, página,
cita textual del PDF, causa y conclusión.
"""
import json
import re

from . import config
from .herramientas import pagina_contiene


_NUMERO = re.compile(r"\d+(?:[.,]\d+)*")


def _valores(texto) -> set[float]:
    """Todas las lecturas posibles de cada número (177,815 puede ser 177815 o 177.815)."""
    vals = set()
    for n in _NUMERO.findall(str(texto)):
        vals.add(float(re.sub(r"[.,]", "", n)))
        try:
            vals.add(float(n.replace(".", "").replace(",", ".")))
            vals.add(float(n.replace(",", "")))
        except ValueError:
            pass
    return vals


def cifras_inventadas(conclusion: str, incidencia: dict, evidencia: dict) -> list[str]:
    permitidas = set(evidencia.get("numeros") or [])
    for fuente in (evidencia.get("fila_texto"), incidencia.get("valor_citado"), incidencia.get("anio"),
                   evidencia.get("pagina"), json.dumps(evidencia.get("fila_panel") or {})):
        permitidas |= _valores(fuente)
    permitidas |= {100.0, 50.0, 1.7, 11.4, 0.0}  # umbrales de las reglas
    permitidas |= {float(a) for a in range(2010, 2027)}  # años
    sueltas = []
    for n in _NUMERO.findall(conclusion):
        lecturas = _valores(n)
        if not any(abs(l - p) <= 0.5 for l in lecturas for p in permitidas):
            sueltas.append(n)
    return sueltas


def _entero(valor):
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return valor


def verificar_anclaje(diag: dict, incidencia: dict, evidencia: dict) -> dict:
    problemas = []
    if str(diag.get("cod_divipola")) != str(incidencia["cod_divipola"]):
        problemas.append("el código del diagnóstico no es el de la incidencia")
    if _entero(diag.get("anio")) != _entero(incidencia["anio"]):
        problemas.append("el año del diagnóstico no es el de la incidencia")
    if diag.get("causa") not in config.CAUSAS:
        problemas.append(f"causa fuera de {', '.join(config.CAUSAS)}")
    if not diag.get("conclusion"):
        problemas.append("falta la conclusión")

    if evidencia.get("encontrado"):
        if diag.get("archivo") != evidencia["archivo"] or _entero(diag.get("pagina")) != _entero(evidencia["pagina"]):
            problemas.append("archivo o página distintos a los de la evidencia")
        cita = str(diag.get("cita_textual") or "")
        if not pagina_contiene(evidencia["archivo"], evidencia["pagina"], cita):
            problemas.append("la cita textual no está en esa página del PDF")
    elif diag.get("causa") not in ("error_extraccion", "indeterminado"):
        problemas.append("sin fila en el PDF solo caben error_extraccion o indeterminado")

    if evidencia.get("coincide_pdf") and not evidencia.get("causa_fija") and diag.get("causa") == "error_extraccion":
        problemas.append("las cifras del panel coinciden con el PDF; no puede ser error_extraccion")

    inventadas = cifras_inventadas(str(diag.get("conclusion") or ""), incidencia, evidencia)
    if inventadas:
        problemas.append("cifras de la conclusión que no están en la evidencia: " + ", ".join(inventadas))

    if not problemas:
        confianza = "alta"
    elif len(problemas) == 1 and "cita" in problemas[0]:
        confianza = "media"
    else:
        confianza = "baja"
    return {"anclado": not problemas, "confianza": confianza, "problemas": problemas}
