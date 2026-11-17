"""Pruebas del cliente del modelo con un cliente falso: ninguna hace llamadas reales."""
from types import SimpleNamespace

from agente import config, llm


class ClienteFalso:
    """Imita client.chat.completions.create y guarda los argumentos de la última llamada."""

    def __init__(self, error: Exception | None = None):
        self.error, self.ultima = error, None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.ultima = kwargs
        if self.error:
            raise self.error
        mensaje = SimpleNamespace(content='{"causa": "indeterminado"}')
        return SimpleNamespace(choices=[SimpleNamespace(message=mensaje)],
                               usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))


def _usar(monkeypatch, tmp_path, url, clave="clave-de-prueba", error=None):
    falso = ClienteFalso(error)
    monkeypatch.setattr(llm, "_cliente", falso)
    monkeypatch.setattr(config, "LLM_BASE_URL", url)
    monkeypatch.setattr(config, "LLM_API_KEY", clave)
    monkeypatch.setattr(config, "LOGS", tmp_path)  # las trazas de prueba no van a logs/
    return falso


def test_deepseek_apaga_el_razonamiento_y_ollama_no(monkeypatch, tmp_path):
    falso = _usar(monkeypatch, tmp_path, "https://api.deepseek.com")
    assert llm.generar_json([{"role": "user", "content": "x"}], "prueba") == {"causa": "indeterminado"}
    assert falso.ultima["extra_body"] == {"thinking": {"type": "disabled"}}
    assert falso.ultima["temperature"] == 0

    falso = _usar(monkeypatch, tmp_path, "http://localhost:11434/v1", clave="ollama")
    llm.generar_json([{"role": "user", "content": "x"}], "prueba")
    assert "extra_body" not in falso.ultima


def test_probar_conexion_responde_y_avisa_sin_clave(monkeypatch, tmp_path):
    _usar(monkeypatch, tmp_path, "https://api.deepseek.com")
    assert llm.probar_conexion()["ok"]

    falso = _usar(monkeypatch, tmp_path, "https://api.deepseek.com", clave="")
    r = llm.probar_conexion()
    assert not r["ok"] and "LLM_API_KEY" in r["mensaje"] and falso.ultima is None  # ni siquiera llama


def test_probar_conexion_traduce_errores_sin_mostrar_la_clave(monkeypatch, tmp_path):
    class AuthenticationError(Exception):
        pass

    _usar(monkeypatch, tmp_path, "https://api.deepseek.com", clave="sk-secreta",
          error=AuthenticationError("clave sk-secreta inválida"))
    r = llm.probar_conexion()
    assert not r["ok"] and "rechazada" in r["mensaje"] and "sk-secreta" not in r["mensaje"]


def test_config_lee_variables_de_entorno(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "modelo-de-prueba")
    assert config._valor("LLM_MODEL", "otro") == "modelo-de-prueba"
    monkeypatch.delenv("LLM_MODEL")
    assert config._valor("LLM_MODEL", "otro") == "otro"
