# Contexto del proyecto

Proyecto de consultoría (USTA): mercado público de servicios funerarios en SECOP II. agente/ = agente de incidencias (reglas en código + LLM + verificación de anclaje + revisión humana) con LangGraph. tablero/ = app Streamlit desplegada en Streamlit Community Cloud desde la rama main. data/secop/procesos_funerarios_secop.parquet = datos; no se modifican.

# Reglas

1. Trabaja solo en la rama integracion. Nunca hagas push a main.
2. No cambies las reglas de agente/validaciones.py ni causa_por_codigo() en agente/grafo.py salvo que te lo pida explícitamente.
3. Nunca escribas claves o tokens en archivos del repo ni los imprimas. Van en variables de entorno o en .streamlit/secrets.toml.
4. Antes de terminar cada tarea ejecuta .venv\Scripts\python.exe -m pytest y dime el resultado.
5. No borres archivos ni datos sin preguntarme antes.
6. Explícame los cambios en español sencillo, con listas cortas.
7. Todo código nuevo lleva comentarios en español y pruebas.
