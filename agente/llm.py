"""Cliente del modelo (Qwen local por defecto) con trazas en logs/trazas.jsonl.

Cada llamada queda registrada: instrucción, respuesta, tokens y tiempo. Si están
definidas LANGFUSE_PUBLIC_KEY y LANGFUSE_SECRET_KEY y está instalado `langfuse`,
las trazas también se envían a Langfuse.
"""
import json
import os
import time
from datetime import datetime

from openai import OpenAI

from . import config

_cliente = None


def _langfuse_openai():
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        return None
    try:
        from langfuse.openai import OpenAI as OpenAILangfuse  # envuelve el cliente de OpenAI
        return OpenAILangfuse
    except ImportError:
        return None


def cliente():
    global _cliente
    if _cliente is None:
        clase = _langfuse_openai() or OpenAI
        _cliente = clase(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY,
                         timeout=config.LLM_TIMEOUT, max_retries=0)
    return _cliente


def generar_json(mensajes: list[dict], etiqueta: str) -> dict:
    inicio = time.time()
    resp = cliente().chat.completions.create(
        model=config.LLM_MODEL, messages=mensajes, temperature=0,
        response_format={"type": "json_object"},
    )
    texto = resp.choices[0].message.content or "{}"
    config.LOGS.mkdir(exist_ok=True)
    with open(config.LOGS / "trazas.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "fecha": datetime.now().isoformat(timespec="seconds"), "etiqueta": etiqueta,
            "modelo": config.LLM_MODEL, "segundos": round(time.time() - inicio, 1),
            "tokens_entrada": getattr(resp.usage, "prompt_tokens", None),
            "tokens_salida": getattr(resp.usage, "completion_tokens", None),
            "mensajes": mensajes, "respuesta": texto,
        }, ensure_ascii=False) + "\n")
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return {"error": "JSON inválido", "texto": texto}
