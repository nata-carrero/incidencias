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


def es_deepseek() -> bool:
    return "deepseek" in config.LLM_BASE_URL.lower()


def _extra() -> dict:
    """En DeepSeek se apaga el modo de razonamiento para que temperature=0 tenga efecto."""
    return {"extra_body": {"thinking": {"type": "disabled"}}} if es_deepseek() else {}


def probar_conexion() -> dict:
    """Hace UNA llamada mínima al modelo. Devuelve {"ok": bool, "mensaje": str}; nunca muestra la clave."""
    if es_deepseek() and config.LLM_API_KEY in ("", "ollama"):
        return {"ok": False, "mensaje": "Falta la clave LLM_API_KEY de DeepSeek "
                "(variable de entorno o .streamlit/secrets.toml)."}
    try:
        cliente().chat.completions.create(
            model=config.LLM_MODEL, messages=[{"role": "user", "content": "Responde solo: ok"}],
            temperature=0, max_tokens=5, **_extra())
        return {"ok": True, "mensaje": f"El modelo {config.LLM_MODEL} respondió."}
    except Exception as e:  # se traduce el error a un mensaje claro, sin datos sensibles
        nombre = type(e).__name__
        if "Authentication" in nombre or "PermissionDenied" in nombre:
            msg = "La clave fue rechazada (mal copiada o sin saldo)."
        elif "NotFound" in nombre or "BadRequest" in nombre:
            msg = f"El modelo «{config.LLM_MODEL}» no existe o no está disponible: revisa LLM_MODEL."
        elif "Connection" in nombre or "Timeout" in nombre:
            msg = (f"No hay conexión con el modelo en {config.LLM_BASE_URL}. "
                   "Si usas Qwen local, abre Ollama.")
        else:
            msg = f"El modelo no respondió ({nombre})."
        return {"ok": False, "mensaje": msg}


def generar_json(mensajes: list[dict], etiqueta: str) -> dict:
    inicio = time.time()
    resp = cliente().chat.completions.create(
        model=config.LLM_MODEL, messages=mensajes, temperature=0,
        response_format={"type": "json_object"}, **_extra(),
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
