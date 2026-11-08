"""Corre el agente sobre una sola incidencia y muestra la traza completa (para el informe)."""
import json
import sys
import uuid

from langgraph.types import Command

from agente import config, herramientas as h
from agente.grafo import construir
from agente.validaciones import detectar
from correr import como_registros

sys.stdout.reconfigure(encoding="utf-8")
id_proceso, regla = sys.argv[1], sys.argv[2]
inc = detectar(h.cargar_procesos())
inc.insert(0, "id", range(1, len(inc) + 1))
fila = inc[(inc["id_proceso"] == id_proceso) & (inc["regla"] == regla)]
grafo = construir()
hilo = {"configurable": {"thread_id": str(uuid.uuid4())}, "recursion_limit": 60}
for paso in grafo.stream({"pendientes": como_registros(fila), "resultados": []}, hilo, stream_mode="updates"):
    print(json.dumps(paso, ensure_ascii=False, default=str)[:1500])
salida = grafo.invoke(Command(resume={"decisiones": {}}), hilo)
print(json.dumps(salida["resultados"], ensure_ascii=False, indent=1))
