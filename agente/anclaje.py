"""verificar_anclaje(): comprueba con código que el diagnóstico cite evidencia real de SECOP.

Formato obligatorio: id del proceso, causa, cita textual copiada del registro y conclusión.
"""
import json
import re

from . import config
from .herramientas import cita_existe, texto_citable

_NUMERO = re.compile(r"\d+(?:[.,]\d+)*")


def _valores(texto) -> set[float]:
    """Lecturas posibles de cada número: '57.333.333' -> 57333333; '1,5' -> 1.5."""
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
    permitidas = _valores(texto_citable(evidencia["registros"] + evidencia.get("otros", [])))
    permitidas |= _valores(json.dumps(incidencia, default=str)) | {0.0, 5.0, 100.0}
    return [n for n in _NUMERO.findall(conclusion)
            if not any(abs(l - p) <= 0.5 for l in _valores(n) for p in permitidas)]


def verificar_anclaje(diag: dict, incidencia: dict, evidencia: dict) -> dict:
    problemas = []
    if str(diag.get("id_proceso")) != str(incidencia["id_proceso"]):
        problemas.append("el ID del diagnóstico no es el de la incidencia")
    if diag.get("causa") not in config.CAUSAS:
        problemas.append(f"causa fuera de {', '.join(config.CAUSAS)}")
    if not diag.get("conclusion"):
        problemas.append("falta la conclusión")
    if not cita_existe(str(diag.get("cita_textual") or ""), evidencia["registros"] + evidencia.get("otros", [])):
        problemas.append("la cita textual no está en el registro de SECOP")
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
