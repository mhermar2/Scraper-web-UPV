"""Etapa 2 (Markdown) del extractor de Doctorado UPV (estudios, no admision).

Adaptacion del extractor de masteres UPV: lee
config.DOCTORADOS_UPV_JSON y genera un _indice.md (tabla) y un .md por
programa en config.DOCTORADOS_KB_DIR. Reanudable via
config.DOCTORADOS_ESTADO.

Migrado desde src/extractores/estudios/extrae_doctorado.ipynb (antes
Extrae_Doctorados.ipynb). Sin celdas exploratorias que descartar; solo
Colab (drive.mount, rutas /content/drive) sustituido por config.py.
cargar_estado/guardar_estado ahora vienen de common.py. La funcion get()
que usaba el notebook original no estaba definida en las celdas
guardadas (quedo huerfana de una celda de una sesion anterior de Colab
que no se guardo) -- aqui se usa common.get_response(), que es el patron
equivalente (misma pausa/manejo de errores) usado en el resto de
extractores, y que por su uso (.text, .json()) es evidentemente lo que
esa funcion perdida hacia.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bs4 import BeautifulSoup
import markdownify

from common import cargar_estado, get_response, guardar_estado
from config import DOCTORADOS_ESTADO, DOCTORADOS_INDICE_MD, DOCTORADOS_KB_DIR, DOCTORADOS_UPV_JSON

BASE_URL = "https://www.upv.es"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; UPV-KB-Bot/2.0)"}

# Secciones del programa de doctorado
SECCIONES = {
    "Inicio": "",
    "Admisión": "admision/",
}

HEADINGS_RUIDO = {
    "Conoce el máster a fondo", "Galería de imágenes",
    "Actualidad del máster", "Mantente al día",
    "Normativa general", "Otros enlaces de interés",
    "Conoce el master a fondo",
}

TEXTO_PROMO = re.compile(r"Desde 1991 hemos gestionado|Hemos creado 5500|hemos tramitado \d", re.I)


def _get(url: str):
    return get_response(url, headers=HEADERS)


def generar_indice(json_url: Path = DOCTORADOS_UPV_JSON, salida: Path = DOCTORADOS_INDICE_MD) -> None:
    """Genera _indice.md (tabla) a partir del JSON de doctorados."""
    with open(json_url, encoding="utf-8") as f:
        datos = json.load(f)

    tipos_idx = {t["tipo"]: t["texto"] for t in datos.get("tipos", [])}

    lineas = [
        "# Índice de Doctorados UPV",
        "",
        "| Acrónimo | Título | Tipo |",
        "|----------|--------|------|",
    ]

    for d in sorted(datos["titulaciones"], key=lambda x: x["nom"]):
        acro = d["acro"]
        nom = d["nom"]
        tipos = ", ".join(tipos_idx.get(t, t) for t in d.get("tipo", []))
        url = f"https://www.upv.es{d['url']}"
        lineas.append(f"| [{acro}]({url}) | {nom} | {tipos} |")

    salida.parent.mkdir(parents=True, exist_ok=True)
    with open(salida, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas))

    print(f"Índice generado: {len(datos['titulaciones'])} doctorados -> {salida}")


def _limpiar_ruido_inicio(main) -> None:
    """Elimina in-place secciones ruidosas del arbol BeautifulSoup de Inicio."""
    for heading in main.find_all(["h1", "h2", "h3", "h4"]):
        texto_h = heading.get_text(strip=True)
        if any(r.lower() in texto_h.lower() for r in HEADINGS_RUIDO):
            padre = heading.find_parent(
                lambda t: t.name in ("section", "div", "aside", "article") and t != main
            )
            if padre:
                padre.decompose()
            else:
                for sib in list(heading.find_next_siblings()):
                    sib.decompose()
                heading.decompose()

    for a in main.find_all("a", string=re.compile(r"Lee más", re.I)):
        contenedor = a.find_parent(["li", "article", "div"])
        if contenedor:
            contenedor.decompose()

    for nodo in main.find_all(string=TEXTO_PROMO):
        bloque = nodo.find_parent(["div", "section", "p", "h3"])
        if bloque:
            bloque.decompose()

    for sel in [".wp-block-gallery", "figure.wp-block-image", '[class*="galeria"]']:
        for tag in main.select(sel):
            tag.decompose()


def extraer_hero_metadata(soup: BeautifulSoup) -> str:
    """Extrae el banner hero de cabecera: acronimo, idioma, modalidad, campus, creditos..."""
    hero = soup.find(class_="seccion01hero")
    if not hero:
        return ""

    lineas = ["### Datos del programa\n"]

    for col in hero.find_all(class_="columna_arriba"):
        t = col.get_text(" ", strip=True)
        if t:
            lineas.append(f"- {t}")

    lineas.append("")

    for col in hero.find_all(class_="columna_abajo"):
        h = col.find(["h3", "h4"])
        p = col.find("p")
        if h and p:
            clave = h.get_text(strip=True)
            valor = p.get_text(strip=True)
            if clave and valor:
                lineas.append(f"**{clave}**: {valor}")

    return "\n".join(lineas) if len(lineas) > 2 else ""


def seguir_iframe_oracle(soup: BeautifulSoup) -> str:
    """Sigue iframes Oracle/UPV (pls/oalu/...) con el listado real de asignaturas."""
    iframe = (soup.find(class_="upv_query") or soup).find(
        "iframe", src=re.compile(r"pls/oalu|oalu/sic_", re.I)
    )
    if not iframe or not iframe.get("src"):
        return ""

    src = iframe["src"]
    if src.startswith("//"):
        src = "https:" + src
    elif src.startswith("/"):
        src = BASE_URL + src

    print(f"      -> iframe Oracle: {src[:90]}...")
    resp = _get(src)
    if not resp:
        return ""

    isoup = BeautifulSoup(resp.text, "html.parser")
    for tag in isoup(["script", "style", "noscript", "link", "meta"]):
        tag.decompose()

    body = isoup.find("body") or isoup
    md = markdownify.markdownify(str(body), heading_style="ATX", strip=["a", "img"])
    return re.sub(r"\n{3,}", "\n\n", md).strip()


def limpiar_html_pagina(soup: BeautifulSoup, es_inicio: bool = False) -> str:
    """Limpia la pagina WordPress y devuelve el contenido util en Markdown."""
    for tag in soup(["script", "style", "noscript", "link", "meta", "header", "footer", "nav"]):
        tag.decompose()

    for sel in [
        ".master-global-header", ".master-global-header-secondary",
        "#masthead-container", "#masthead", "#colophon", "#site-navigation",
        ".global-menu", ".bg-overlay", ".breadcrumb", ".social-sharer",
        ".cookies-banner", ".menu-lateral", ".accessible-megamenu",
        ".boton_policonsulta", ".footer-area", ".footer-bottom-bar",
    ]:
        for tag in soup.select(sel):
            tag.decompose()

    for tag in soup.find_all(["div", "section", "aside", "article"]):
        try:
            clases = " ".join(tag.get("class", []))
            id_tag = tag.get("id", "")
            if "conoce-la-universitat" in clases + id_tag or "bloque-conoce" in clases + id_tag:
                tag.decompose()
        except Exception:
            pass

    main = (
        soup.find("main")
        or soup.find(id="primary")
        or soup.find(id="cuerpo")
        or soup.find(class_=re.compile(r"entry-content|page-content"))
        or soup.body
    )
    if not main:
        return ""

    if es_inicio:
        _limpiar_ruido_inicio(main)

    md = markdownify.markdownify(str(main), heading_style="ATX", strip=["a", "img"])
    return re.sub(r"\n{3,}", "\n\n", md).strip()


def extraer_seccion(url: str, nombre: str, es_inicio: bool = False) -> str:
    """Descarga una seccion del programa y devuelve su contenido en Markdown."""
    resp = _get(url)
    if resp is None:
        return f'> ⚠️ No se pudo obtener "{nombre}" ({url})\n'

    soup = BeautifulSoup(resp.text, "html.parser")
    partes = []

    if es_inicio:
        hero = extraer_hero_metadata(soup)
        if hero:
            partes.append(hero)

    iframe_md = seguir_iframe_oracle(soup)
    if iframe_md:
        partes.append(iframe_md)

    if es_inicio or nombre == "Admisión" or not iframe_md:
        html_md = limpiar_html_pagina(soup, es_inicio=es_inicio)
        if html_md:
            partes.append(html_md)

    if not partes:
        return f'> ℹ️ Sección "{nombre}" sin contenido extraíble.\n'

    return "\n\n".join(partes)


def construir_metadata(m: dict, ramas_idx: dict, campus_idx: dict, centros_idx: dict, tipos_idx: dict) -> str:
    """Cabecera YAML-like con los metadatos del JSON para facilitar el filtrado en RAG."""
    ramas = ", ".join(ramas_idx.get(r, str(r)) for r in m.get("ramas", []))
    campus = campus_idx.get(m.get("id_campus", ""), m.get("id_campus", ""))
    centros = ", ".join(centros_idx.get(c, c) for c in m.get("centros", []))
    tipos = ", ".join(tipos_idx.get(t, t) for t in m.get("tipo", []))
    modal = {"1": "Presencial", "2": "Semipresencial", "3": "En línea"}.get(str(m.get("id_modalidad", "")), "")
    return "\n".join([
        "---",
        f'título: "{m["nom"]}"',
        f"acrónimo: {m['acro']}",
        f"tipo: {tipos}",
        f"campus: {campus}",
        f"modalidad: {modal}",
        f"centros: {centros}",
        f"ramas: {ramas}",
        f"url: {BASE_URL}{m['url']}",
        "---", "",
    ])


def procesar_doctorados(json_url: Path = DOCTORADOS_UPV_JSON, path_kb: Path = DOCTORADOS_KB_DIR,
                         estado_path: Path = DOCTORADOS_ESTADO, limite: int | None = None) -> None:
    print("Descargando catálogo de doctorados...")

    with open(json_url, "r", encoding="utf-8") as f:
        datos = json.load(f)

    doctorados = datos["titulaciones"]

    ramas_idx = {r["id_rama"]: r["nom"] for r in datos.get("ramas", [])}
    campus_idx = {c["id_campus"]: c["nom"] for c in datos.get("campus", [])}
    centros_idx = {c["acro"]: c["nom"] for c in datos.get("centros", [])}
    tipos_idx = {t["tipo"]: t["texto"] for t in datos.get("tipos", [])}

    print(f"{len(doctorados)} títulos en el catálogo.")

    path_kb.mkdir(parents=True, exist_ok=True)
    procesados = cargar_estado(estado_path)
    pendientes = [d for d in doctorados if d["acro"] not in procesados]
    if limite is not None:
        pendientes = pendientes[:limite]

    print(f"{len(procesados)} ya procesados, {len(pendientes)} pendientes.")

    for i, doctorado in enumerate(pendientes, 1):
        acro = doctorado["acro"]
        nom = doctorado["nom"]
        url_base = urljoin(BASE_URL, doctorado["url"])

        print(f"\n[{i}/{len(pendientes)}] -- {acro}: {nom}")

        partes = [
            construir_metadata(doctorado, ramas_idx, campus_idx, centros_idx, tipos_idx),
            f"# {nom}\n",
        ]

        for nombre_sec, sufijo in SECCIONES.items():
            url_sec = url_base if sufijo == "" else urljoin(url_base, sufijo)
            es_inicio = nombre_sec == "Inicio"

            print(f"    -> {nombre_sec}: {url_sec}")

            contenido = extraer_seccion(url_sec, nombre_sec, es_inicio=es_inicio)
            partes.append(f"\n## {nombre_sec}\n\n{contenido}\n")

        documento = "\n".join(partes)

        nombre_archivo = re.sub(r"[^\w\-]", "_", acro) + ".md"
        ruta = path_kb / nombre_archivo
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(documento)

        procesados.add(acro)
        if i % 5 == 0:
            guardar_estado(estado_path, procesados)
            print(f"    Checkpoint ({len(procesados)} procesados)")

    guardar_estado(estado_path, procesados)

    total = len([f for f in path_kb.iterdir() if f.suffix == ".md"])
    print(f"\nCompletado. Archivos .md: {total}")
    print(f"   Ruta: {path_kb}")


def main(limite: int | None = None) -> None:
    generar_indice()
    procesar_doctorados(limite=limite)


if __name__ == "__main__":
    main()
