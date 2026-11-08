"""Rutas y modelo. Por defecto usa Qwen local con Ollama (gratis, sin internet).

Para usar DeepSeek basta con definir en el entorno:
  LLM_BASE_URL=https://api.deepseek.com  LLM_MODEL=deepseek-chat  LLM_API_KEY=<clave>
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DATA = RAIZ / "data"
PROCESOS = DATA / "secop" / "procesos_funerarios_secop.parquet"
RESULTADOS = RAIZ / "resultados"
LOGS = RAIZ / "logs"

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b")
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")  # Ollama ignora la clave
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "300"))

MAX_INTENTOS = 3
CAUSAS = ("error_de_registro", "registro_duplicado", "no_funerario", "dato_plausible", "indeterminado")
