"""Etapa 2 (Markdown) del extractor de Formacion Permanente UPV.

Lee config.FORMACION_PERMANENTE_JSON (generado por
sacar_json_formacion_permanente.py) y escribe un .md por curso/master en
config.FORMACION_PERMANENTE_KB_DIR. Reanudable: guarda el progreso en
config.FORMACION_PERMANENTE_ESTADO.

Migrado desde src/extractores/estudios/extrae_formacion_permanente.ipynb
(antes ExtraeFormacionPermanente_v2.ipynb). Confirmado como la version
correcta -- y no la v1 sin sufijo -- comparando el .md real ya generado
en el repo: solo esta version produce el campo ECTS y la cabecera
"## Informacion adicional" que aparecen en el resultado final.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common import cargar_estado, get, guardar_estado
from config import FORMACION_PERMANENTE_ESTADO, FORMACION_PERMANENTE_JSON, FORMACION_PERMANENTE_KB_DIR

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; UPV-KB-Bot/2.0)"}

CAMPOS_INFO = [
    ("Precio", "precio"),
    ("Horas", "horas"),
    ("ECTS", "ects"),
    ("Modalidad", "modalidad"),
    ("Fechas", "fechas"),
    ("Campus", "campus"),
    ("Responsable", "responsable"),
    ("Promueve", "promotor"),
]

ORDEN_SECCIONES = ["Dirigido a", "Objetivos", "Contenidos", "Evaluación", "Metodología", "Requisitos"]

TITULOS_SECCION = {
    "dirigida a": "Dirigido a",
    "objetivos": "Objetivos",
    "temas": "Contenidos",
    "evaluación": "Evaluación",
    "metodología": "Metodología",
    "requisitos": "Requisitos",
}

BASURA_TEXTOS = [
    "Suscríbete", "Registrarse", "Iniciar sesión",
    "Toggle navigation", "Buscar formación",
    "Descarga en PDF", "Boletín",
]


def buscar_patron(texto: str, patrones: list[str]) -> str | None:
    for p in patrones:
        m = re.search(p, texto, re.I)
        if m:
            return m.group(1).strip()
    return None


def extraer_metadata_mejorada(texto: str) -> dict:
    meta = {}

    meta["precio"] = buscar_patron(texto, [r"Precio\s+(\d+[.,]?\d*\s*€)", r"(\d+[.,]?\d*)\s*€"])
    meta["horas"] = buscar_patron(texto, [r"(\d+)\s*h\b", r"(\d+)\s*horas"])
    meta["ects"] = buscar_patron(texto, [r"(\d+)\s*ECTS"])

    meta["modalidad"] = None
    for m in ["Online", "Presencial", "Semipresencial", "Emisión en directo"]:
        if re.search(r"\b" + re.escape(m) + r"\b", texto, re.I):
            meta["modalidad"] = m
            break

    meta["fechas"] = buscar_patron(texto, [r"Desde:\s*(.+)", r"Hasta:\s*(.+)"])
    meta["campus"] = buscar_patron(texto, [r"Campus\s+de\s+([A-Za-zÁÉÍÓÚáéíóú]+)"])
    meta["responsable"] = buscar_patron(texto, [r"Responsable de la actividad\s*:?\s*\n(.+)"])
    meta["promotor"] = buscar_patron(texto, [r"Promovido por:\s*(.+)", r"Organiza:\s*(.+)"])

    return meta


def html_a_markdown_limpio(html: str) -> str:
    from bs4 import BeautifulSoup
    import markdownify

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "form"]):
        tag.decompose()

    for tag in soup.find_all(["div", "section", "aside"]):
        txt = tag.get_text(" ", strip=True)
        if any(b.lower() in txt.lower() for b in BASURA_TEXTOS):
            tag.decompose()

    main = soup.find("main") or soup.body or soup

    for a in main.find_all("a"):
        a.replace_with(a.get_text(" ", strip=True))

    md = markdownify.markdownify(str(main), heading_style="ATX")
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def extraer_secciones(html: str) -> dict:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    secciones = {}

    for h in soup.find_all(["h2", "h3"]):
        titulo = h.get_text(" ", strip=True).lower()
        key = next((v for k, v in TITULOS_SECCION.items() if k in titulo), None)
        if key is None:
            continue

        bloque = []
        for sib in h.find_next_siblings():
            if sib.name in ["h2", "h3"]:
                break
            txt = sib.get_text(" ", strip=True)
            if txt:
                bloque.append(txt)

        if bloque:
            secciones[key] = " ".join(bloque)

    return secciones


def crear_markdown(item: dict, html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    texto = soup.get_text("\n", strip=True)

    meta = extraer_metadata_mejorada(texto)
    secciones = extraer_secciones(html)

    md = [f"# {item['nombre']}\n", "## Información principal\n"]

    for etiqueta, clave in CAMPOS_INFO:
        if meta.get(clave):
            md.append(f"- **{etiqueta}:** {meta[clave]}")

    md.append(f"\nURL: {item['url']}\n")
    md.append("\n---\n")

    for seccion in ORDEN_SECCIONES:
        if seccion in secciones:
            md.append(f"\n## {seccion}\n")
            md.append(secciones[seccion])

    md.append("\n## Información adicional\n")
    md.append(html_a_markdown_limpio(html))

    return "\n".join(md)


def main(limite: int | None = None, json_url: Path = FORMACION_PERMANENTE_JSON,
         path_kb: Path = FORMACION_PERMANENTE_KB_DIR, estado_path: Path = FORMACION_PERMANENTE_ESTADO) -> None:
    path_kb.mkdir(parents=True, exist_ok=True)

    with open(json_url, encoding="utf-8") as f:
        datos = json.load(f)

    formaciones = datos["formaciones"]
    procesados = cargar_estado(estado_path)

    pendientes = [f for f in formaciones if f["id"] not in procesados]
    if limite is not None:
        pendientes = pendientes[:limite]

    print("Pendientes:", len(pendientes))

    for i, item in enumerate(pendientes, 1):
        print(f"[{i}/{len(pendientes)}] {item['nombre']}")

        html = get(item["url"], headers=HEADERS)
        if not html:
            continue

        md = crear_markdown(item, html)

        nombre = re.sub(r"[^a-z0-9]+", "_", item["id"]) + ".md"
        ruta = path_kb / nombre
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(md)

        procesados.add(item["id"])
        if i % 10 == 0:
            guardar_estado(estado_path, procesados)

    guardar_estado(estado_path, procesados)
    print("KB terminada:", path_kb)


if __name__ == "__main__":
    main()
