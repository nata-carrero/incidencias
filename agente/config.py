"""Rutas y modelo. Por defecto usa Qwen local con Ollama (gratis, sin internet).

Para usar DeepSeek basta con definir en el entorno:
  LLM_BASE_URL=https://api.deepseek.com  LLM_MODEL=deepseek-chat  LLM_API_KEY=<clave>
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DATA = RAIZ / "data"
PANEL = DATA / "processed" / "panel_minsalud_municipal.parquet"
INCIDENCIAS = DATA / "processed" / "incidencias.csv"
DIVIPOLA = DATA / "raw" / "dane" / "dane_divipola.csv"
PDFS = {"minsalud": DATA / "raw" / "minsalud", "ins": DATA / "raw" / "ins"}
RESULTADOS = RAIZ / "resultados"
LOGS = RAIZ / "logs"

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")  # Ollama ignora la clave
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "300"))

MAX_INTENTOS = 3
CAUSAS = ("error_extraccion", "cambio_metodo", "dato_plausible", "indeterminado")
