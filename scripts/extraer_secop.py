"""Extrae del archivo completo de SECOP II los procesos funerarios del equipo, sin daños de formato.

Toma los IDs de procesos_exequiales_clasificados.csv (cuyas filas están partidas por saltos
de línea dentro de los textos) y trae esas filas completas desde el CSV oficial de SECOP II.

  .venv\\Scripts\\python.exe scripts\\extraer_secop.py <secop_ii.csv> <procesos_exequiales_clasificados.csv>
"""
import csv
import re
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
COLUMNAS = [
    "Entidad", "Nit Entidad", "Departamento Entidad", "Ciudad Entidad", "OrdenEntidad", "ID del Proceso",
    "Referencia del Proceso", "Nombre del Procedimiento", "Descripción del Procedimiento", "Fase",
    "Fecha de Publicacion del Proceso", "Precio Base", "Modalidad de Contratacion",
    "Justificación Modalidad de Contratación", "Duracion", "Unidad de Duracion",
    "Proveedores Unicos con Respuestas", "Estado del Procedimiento", "Adjudicado", "Fecha Adjudicacion",
    "Valor Total Adjudicacion", "Nombre del Proveedor Adjudicado", "NIT del Proveedor Adjudicado",
    "Codigo Principal de Categoria", "Tipo de Contrato", "URLProceso", "Estado Resumen",
]


def ids_y_clasificacion(ruta_clasificados: Path) -> dict[str, str]:
    """Lee el CSV dañado línea por línea: cada ID va con la clasificación que lo antecede."""
    patron_id = re.compile(r"\bCO1\.(?:REQ|BDOS|PPI)\.\d+\b")
    texto = ruta_clasificados.read_text(encoding="utf-8-sig", errors="replace")
    clasif = {}
    for linea in texto.splitlines():
        m = patron_id.search(linea)
        if m and ";" in linea:
            clasif.setdefault(m.group(0), linea.split(";", 1)[0].strip('"'))
    return clasif


def main(ruta_secop: str, ruta_clasificados: str):
    clasif = ids_y_clasificacion(Path(ruta_clasificados))
    print(f"IDs en la base clasificada: {len(clasif)}")
    trozos = []
    for i, trozo in enumerate(pd.read_csv(ruta_secop, usecols=COLUMNAS, dtype=str, chunksize=500_000,
                                          encoding="utf-8", on_bad_lines="skip", engine="c")):
        sel = trozo[trozo["ID del Proceso"].isin(clasif)]
        if not sel.empty:
            trozos.append(sel)
        print(f"  trozo {i + 1}: {sum(len(t) for t in trozos)} filas encontradas", flush=True)
    base = pd.concat(trozos, ignore_index=True)
    base.insert(0, "clasificacion_equipo", base["ID del Proceso"].map(clasif))
    destino = RAIZ / "data" / "secop" / "procesos_funerarios_secop.parquet"
    destino.parent.mkdir(parents=True, exist_ok=True)
    base.to_parquet(destino, index=False)
    faltan = set(clasif) - set(base["ID del Proceso"])
    print(f"Guardado {destino} · {len(base)} filas · {base['ID del Proceso'].nunique()} procesos · "
          f"IDs sin encontrar en SECOP II: {len(faltan)}")


if __name__ == "__main__":
    csv.field_size_limit(10**8)
    main(*sys.argv[1:3])
