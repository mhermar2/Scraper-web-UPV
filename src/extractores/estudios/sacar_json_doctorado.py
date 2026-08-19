"""Etapa 1 (JSON) del extractor de Doctorado UPV (estudios, no admision).

Saca el listado de programas de doctorado del indice oficial y lo adapta
al mismo formato que usan los JSON de masteres (acro/tipo/nom/url/...)
para que el extractor de Markdown (extrae_doctorado.py) pueda reutilizar
esa misma logica.

Migrado desde src/extractores/estudios/sacar_json_doctorado.ipynb (antes
Extractores solo JSON/SacarJSON_Doctorado.ipynb). Se descartaron: la
funcion parece_programa() (definida pero nunca usada -- el filtro real es
mas simple, "nombre.startswith('Programa de')"), el bloque comentado con
un primer intento de filtro, las celdas de solo-print para inspeccionar
el resultado, y el guardado especifico en Drive (sustituido por
config.py). Se conservan las DOS salidas del original: el JSON crudo
(doctorados.json) y el adaptado (doctorados_upv.json), que es el que
consume extrae_doctorado.py.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common import get_soup
from config import DOCTORADOS_JSON, DOCTORADOS_UPV_JSON

URL_INDICE = "https://www.upv.es/entidades/edoctorado/todos-los-programas-de-doctorado-ofertados-en-upv/"
BASE = "https://www.upv.es"


def extraer_doctorados(url_indice: str = URL_INDICE) -> list[dict]:
    """Recorre el indice y devuelve los programas en formato 'crudo'."""
    soup = get_soup(url_indice, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    if soup is None:
        return []

    vistos = set()
    doctorados = []

    for a in soup.find_all("a", href=True):
        nombre = a.get_text(" ", strip=True)
        href = a["href"]

        if not nombre.startswith("Programa de"):
            continue

        url = urljoin(BASE, href)
        if url in vistos:
            continue
        vistos.add(url)

        doctorados.append({
            "acro": "",
            "tipo": ["D"],
            "nom": nombre,
            "url": url,
            "centros": [],
            "ramas": [],
            "mostrar_leye": False,
            "id_leye": "VALIDO",
            "mostrar_sello": False,
            "id_sello": None,
            "mostrar_pac": False,
            "pac": None,
            "mostrar_masInfo": False,
            "id_info": None,
        })

    return doctorados


def adaptar_a_formato_masteres(doctorados: list[dict]) -> dict:
    """Adapta el JSON crudo al formato que usan los extractores de masteres."""
    titulaciones_nuevas = []

    for d in doctorados:
        nombre = d["nom"]
        acro = re.sub(r"[^\w\-]", "_", nombre)

        url = d["url"]
        if url.startswith("https://www.upv.es"):
            url = url.replace("https://www.upv.es", "")

        titulaciones_nuevas.append({
            "acro": acro,
            "tipo": ["D"],
            "nom": nombre,
            "url": url,
            "centros": d.get("centros", []),
            "ramas": d.get("ramas", []),
            "mostrar_leye": False,
            "id_leye": "VALIDO",
            "mostrar_sello": False,
            "id_sello": None,
            "mostrar_pac": False,
            "pac": None,
            "mostrar_masInfo": False,
            "id_info": None,
        })

    return {
        "titulaciones": titulaciones_nuevas,
        "ramas": [],
        "campus": [],
        "centros": [],
        "tipos": [{"tipo": "D", "texto": "Doctorado"}],
    }


def main(salida_cruda: Path = DOCTORADOS_JSON, salida_adaptada: Path = DOCTORADOS_UPV_JSON) -> None:
    doctorados = extraer_doctorados()
    print("Doctorados encontrados:", len(doctorados))

    salida_cruda.parent.mkdir(parents=True, exist_ok=True)
    with open(salida_cruda, "w", encoding="utf-8") as f:
        json.dump({"titulaciones": doctorados}, f, ensure_ascii=False, indent=2)

    datos_adaptados = adaptar_a_formato_masteres(doctorados)
    salida_adaptada.parent.mkdir(parents=True, exist_ok=True)
    with open(salida_adaptada, "w", encoding="utf-8") as f:
        json.dump(datos_adaptados, f, ensure_ascii=False, indent=2)

    print(f"Creado {salida_adaptada}: {len(datos_adaptados['titulaciones'])} doctorados")


if __name__ == "__main__":
    main()
