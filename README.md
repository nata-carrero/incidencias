# Agente de incidencias — panel MinSalud

Agente del proyecto de consultoría (fases F6–F7 del plan). Toma cada incidencia
detectada en el panel municipal de perros y gatos, busca la fila exacta en el PDF
de MinSalud y diagnostica la causa citando municipio, año, valor, archivo y página.

## Cómo funciona

```mermaid
graph TD
  inicio([inicio]) --> orquestador
  orquestador -. quedan incidencias .-> evidencia
  evidencia["evidencia (código): fila del panel + fila del PDF"] --> diagnostico["diagnóstico (LLM)"]
  diagnostico --> verificar["verificar_anclaje (código)"]
  verificar -. no anclado y < 3 intentos .-> diagnostico
  verificar -. anclado o 3 intentos .-> guardar --> orquestador
  orquestador -. sin pendientes .-> revision["revisión humana (pausa)"]
  revision --> cargar --> fin([fin])
```

- **Orquestador:** reparte las incidencias una por una.
- **Subagente de evidencia (código, sin LLM):** lee la fila del panel, encuentra el
  municipio en la página del PDF y compara cifra por cifra.
- **Subagente de diagnóstico (LLM):** elige la causa — `error_extraccion`,
  `cambio_metodo`, `dato_plausible` o `indeterminado` — y responde en JSON.
- **Anclaje (código):** comprueba que código, año, archivo y página coincidan y que la
  cita textual exista en esa página del PDF. Confianza alta, media o baja.
- **Reglas en las aristas:** máximo 3 intentos; nada se carga sin pasar por la revisión
  humana, que solo pide decisión sobre los casos de confianza media o baja.

## Instalación

Requiere Python 3.12 y [Ollama](https://ollama.com) con el modelo Qwen 2.5 7B (gratis, local):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install langgraph openai pandas pyarrow pymupdf openpyxl pytest
ollama pull qwen2.5:7b
```

Para usar DeepSeek en vez de Qwen, define antes de correr:
`$env:LLM_BASE_URL="https://api.deepseek.com"; $env:LLM_MODEL="deepseek-chat"; $env:LLM_API_KEY="<clave>"`.
Para enviar trazas a Langfuse, instala `langfuse` y define `LANGFUSE_PUBLIC_KEY`,
`LANGFUSE_SECRET_KEY` y `LANGFUSE_HOST`. Sin Langfuse, cada llamada queda en `logs/trazas.jsonl`.

## Uso

```powershell
.venv\Scripts\python.exe correr.py --n 5                      # 5 incidencias reales al azar
.venv\Scripts\python.exe correr.py --n 5 --regla cobertura_100
.venv\Scripts\python.exe correr.py --diagrama                 # resultados/grafo.mmd
.venv\Scripts\python.exe evaluar.py                           # 60 fallas sembradas, sin LLM
.venv\Scripts\python.exe evaluar.py --diagnosticar 10         # + diagnóstico del LLM
.venv\Scripts\python.exe -m pytest
```

Salidas: `resultados/diagnosticos.csv`, `resultados/evaluacion_*.csv`, `logs/trazas.jsonl`.

## Datos

`data/` viene del paquete del 1 de noviembre de 2026 (`SHA256SUMS.txt` verifica los archivos):
panel municipal, 1.721 incidencias de Edward y los PDF de MinSalud, INS y DANE.

## Límites conocidos

- Con Qwen en CPU cada diagnóstico tarda de 30 a 70 s; las 1.721 incidencias tardarían
  más de un día. Para la evaluación se usan muestras.
- Las reglas de `validaciones.py` reproducen exactamente las de Edward en saltos (50/50) y
  habitantes por perro (32/32); en cobertura del 100 % coinciden 1.190 de 1.221. Las reglas
  de duplicados, códigos inválidos y faltantes se escribieron para la evaluación, así que la
  detección del 100 % sobre fallas sembradas es optimista.
- El diseño original indica DeepSeek y Langfuse con Docker; aquí se usa Qwen local por costo.
  Hay que declararlo en el documento.
- Uso de IA: el código se escribió con ayuda de Claude Code.
