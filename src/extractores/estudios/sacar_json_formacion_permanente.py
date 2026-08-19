"""Etapa 1 (JSON) del extractor de Formacion Permanente UPV.

Recorre los listados de cursos/masteres de cfp.upv.es, saca la ficha de
cada uno y escribe el catalogo en config.FORMACION_PERMANENTE_JSON.

Migrado desde src/extractores/estudios/sacar_json_formacion_permanente.ipynb
(antes en Extractores/Extractores solo JSON/SacarJSON_FormacionPermanente.ipynb).
Se descartaron las celdas exploratorias (inspeccion de tags/enlaces por
consola) y el bloque final de busqueda/copia entre carpetas de Drive.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common import get_soup, limpiar_texto
from config import FORMACION_PERMANENTE_JSON

BASE_URL = "https://www.cfp.upv.es"

FUENTES = [
    ("cursos_online", "https://www.cfp.upv.es/formacion-permanente/online/formacion-online.html"),
    ("masters", "https://www.cfp.upv.es/formacion-permanente/masters/masters.html"),
]

ENLACES_BASURA = {"matriculable", "más información", "ver más", "acceder", "inscribirse"}

CAMPUS = ["Vera", "Alcoy", "Gandia"]

CLAVES = ["Promueve", "Organiza", "Responsable", "Director"]


def clasificar_tipo(nombre: str) -> str:
    n = nombre.lower()
    if "máster" in n or "master" in n:
        return "Master"
    if "diploma de especialización" in n:
        return "Diploma de especialización"
    if "diploma de experto" in n:
        return "Diploma de experto"
    if "diploma de extensión" in n:
        return "Diploma de extensión"
    if "curso" in n:
        return "Curso"
    return "Otro"


def extraer_fichas(origen: str, url: str) -> list[dict]:
    """Saca los enlaces a curso/master de una pagina de listado."""
    soup = get_soup(url)
    if not soup:
        return []

    encontrados: dict[str, dict] = {}

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/formacion-permanente/curso/" not in href:
            continue

        url_final = urljoin(BASE_URL, href)
        nombre = limpiar_texto(a.get_text(" ", strip=True))

        if nombre.lower() in ENLACES_BASURA or len(nombre) < 5:
            continue

        encontrados[url_final] = {"nombre": nombre, "url": url_final, "origen": origen}

    return list(encontrados.values())


def extraer_detalle(item: dict) -> dict:
    """Completa una ficha con tipo/ects/horas/precio/campus/responsable."""
    soup = get_soup(item["url"])
    if not soup:
        return item

    texto = soup.get_text("\n", strip=True)

    item["tipo"] = clasificar_tipo(item["nombre"])

    m = re.search(r"(\d+(?:,\d+)?)\s*ECTS", texto, re.I)
    item["ects"] = m.group(1) if m else None

    m = re.search(r"(\d+)\s*horas", texto, re.I)
    item["horas"] = m.group(1) if m else None

    m = re.search(r"(\d+[.,]?\d*)\s*€", texto)
    item["precio"] = f"{m.group(1)} €" if m else None

    item["campus"] = next((c for c in CAMPUS if c.lower() in texto.lower()), None)

    item["promotor"] = None
    item["responsable"] = None
    for linea in texto.split("\n"):
        for clave in CLAVES:
            if not linea.lower().startswith(clave.lower()):
                continue
            valor = linea.split(":", 1)
            if len(valor) != 2:
                continue
            if clave in ("Promueve", "Organiza"):
                item["promotor"] = valor[1].strip()
            else:
                item["responsable"] = valor[1].strip()

    return item


def generar_catalogo(fuentes: list[tuple[str, str]] = FUENTES, limite: int | None = None) -> dict:
    """Pipeline completo: listados -> fichas -> detalle -> catalogo dedup por URL."""
    catalogo: dict[str, dict] = {}

    for origen, url in fuentes:
        print("Procesando:", origen)
        fichas = extraer_fichas(origen, url)
        print("Encontradas:", len(fichas))
        for f in fichas:
            catalogo[f["url"]] = f

    items = list(catalogo.values())
    if limite is not None:
        items = items[:limite]

    print("Total a detallar:", len(items))

    resultado = []
    for i, item in enumerate(items, 1):
        print(f"[{i}/{len(items)}]", item["nombre"])
        item = extraer_detalle(item)
        item["id"] = re.sub(r"[^a-z0-9]+", "_", item["nombre"].lower()).strip("_")
        resultado.append(item)

    return {
        "fuente": "Formación Permanente UPV",
        "total": len(resultado),
        "formaciones": resultado,
    }


def main(limite: int | None = None, salida=FORMACION_PERMANENTE_JSON) -> None:
    datos = generar_catalogo(limite=limite)
    salida.parent.mkdir(parents=True, exist_ok=True)
    with open(salida, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    print("JSON generado:", salida, "- elementos:", datos["total"])


if __name__ == "__main__":
    main()
