"""Rutas y modelo. Por defecto usa Qwen local con Ollama (gratis, sin internet).

Para usar DeepSeek basta con definir LLM_BASE_URL=https://api.deepseek.com, LLM_MODEL=<modelo
vigente> y LLM_API_KEY=<clave>, en variables de entorno o, dentro de Streamlit, en
.streamlit/secrets.toml (en la nube: Settings → Secrets). Las variables de entorno mandan.
"""
import os
import sys
from pathlib import Path


def _valor(nombre: str, defecto: str) -> str:
    """Lee un ajuste: primero la variable de entorno, luego st.secrets (solo si corre Streamlit)."""
    if os.getenv(nombre):
        return os.environ[nombre]
    if "streamlit" in sys.modules:  # no importa Streamlit en la consola ni en la API
        try:
            import streamlit as st
            if nombre in st.secrets:
                return str(st.secrets[nombre])
        except Exception:  # sin secrets.toml Streamlit lanza un error: se usa el valor por defecto
            pass
    return defecto


RAIZ = Path(__file__).resolve().parents[1]
DATA = RAIZ / "data"
PROCESOS = DATA / "secop" / "procesos_funerarios_secop.parquet"
RESULTADOS = RAIZ / "resultados"
LOGS = RAIZ / "logs"

LLM_BASE_URL = _valor("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = _valor("LLM_MODEL", "qwen2.5:7b")
LLM_API_KEY = _valor("LLM_API_KEY", "ollama")  # Ollama ignora la clave
LLM_TIMEOUT = int(_valor("LLM_TIMEOUT", "300"))

MAX_INTENTOS = 3
CAUSAS = ("error_de_registro", "registro_duplicado", "no_funerario", "dato_plausible", "indeterminado")
