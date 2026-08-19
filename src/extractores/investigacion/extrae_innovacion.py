"""Extractor de "UPV Innovacion" (investigacion).

Pagina con maquetacion propia (WordPress + Divi), muy distinta de
institucion/servicios/iniciativas_idi: la extraccion del JSON usa
selectores CSS especificos por seccion (.card-iniciativa,
.card-historia-innovacion, .vtm-servicios-grid__servicio...) en vez del
motor generico de "hoja de contenido" o de una extraccion de texto plano.
El Markdown lleva su propio formato YAML simple (sin lineas en blanco
entre campos), distinto del usado en institucion/servicios -- seccion de
baja calidad segun las notas internas del proyecto, formato de metadatos aun sin normalizar
globalmente.

Pipeline (mismo orden que el notebook original):
  1. extraer_json_innovacion() -> JSON con las 7 secciones semanticas
     (Presentacion, Servicios, Iniciativas, Historias, Temas, Explora,
     Destacados), cada una con su propio selector CSS
  2. guardar_json()
  3. generar_markdown_padre() -> vuelca directamente el JSON (titulos +
     descripciones + enlaces de cada elemento), no vuelve a descargar nada
  4. generar_markdowns_recursos() -> por cada URL unica del JSON, la
     descarga de verdad y extrae su contenido (encabezados/parrafos/
     listas/tablas)

Migrado desde src/extractores/investigacion/extrae_innovacion.ipynb
(antes Extrae_Innovacion.ipynb). Notebook limpio, sin celdas
exploratorias ni codigo muerto que descartar.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bs4 import BeautifulSoup
import requests

from config import INNOVACION_JSON, INNOVACION_MD_PADRE, INNOVACION_RECURSOS_DIR, INNOVACION_URL

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

SECCIONES_BASE = [
    ("Presentación", "presentacion"),
    ("Servicios de Innovación", "servicios"),
    ("Iniciativas", "iniciativas"),
    ("Historias de Innovación", "historias_innovacion"),
    ("Temas", "temas"),
    ("Explora UPV", "explora"),
    ("Destacados", "destacados"),
]


def limpiar_texto(texto: str | None) -> str:
    if texto is None:
        return ""
    return re.sub(r"\s+", " ", str(texto)).strip()


def normalizar_url(url: str, url_base: str | None = None) -> str:
    if not url:
        return ""
    url = url.strip()
    return urljoin(url_base, url) if url_base else url


def deduplicar_lista(elementos: list[dict], clave: str = "url") -> list[dict]:
    resultado, vistos = [], set()
    for elemento in elementos:
        valor = elemento.get(clave, "")
        if valor in vistos:
            continue
        vistos.add(valor)
        resultado.append(elemento)
    return resultado


def _crear_json_base() -> dict:
    return {
        "titulo": "UPV Innovación",
        "url": INNOVACION_URL,
        "tipo": "padre",
        "secciones": [{"id": tipo, "titulo": titulo, "tipo": tipo, "descripcion": "", "elementos": []} for titulo, tipo in SECCIONES_BASE],
    }


def _buscar_seccion_por_tipo(json_data: dict, tipo: str) -> dict | None:
    for seccion in json_data["secciones"]:
        if seccion["tipo"] == tipo:
            return seccion
    return None


def _extraer_texto(elemento) -> str:
    return limpiar_texto(elemento.get_text(" ", strip=True)) if elemento is not None else ""


def _extraer_url(elemento, url_base: str) -> str:
    if elemento is None:
        return ""
    return normalizar_url(elemento.get("href", ""), url_base)


def _extraer_imagen(elemento, url_base: str) -> str:
    if elemento is None:
        return ""
    img = elemento.find("img")
    if img is None:
        return ""
    src = img.get("src") or img.get("data-src") or ""
    return normalizar_url(src, url_base)


def _extraer_enlace_principal(elemento, url_base: str) -> str:
    if elemento is None:
        return ""
    enlace = elemento.find("a", href=True)
    return _extraer_url(enlace, url_base) if enlace is not None else ""


def extraer_json_innovacion(url: str = INNOVACION_URL) -> dict:
    respuesta = requests.get(url, headers=HEADERS, timeout=30)
    respuesta.raise_for_status()
    soup = BeautifulSoup(respuesta.text, "html.parser")

    datos = _crear_json_base()
    datos["url"] = respuesta.url

    main = soup.find("main") or soup.body
    if main is None:
        raise RuntimeError("No se ha podido identificar el contenido principal de la página.")

    titulo_html = soup.find("h1")
    if titulo_html:
        datos["titulo"] = _extraer_texto(titulo_html) or datos["titulo"]

    url_base = respuesta.url

    # Presentación: bloque hero
    seccion = _buscar_seccion_por_tipo(datos, "presentacion")
    bloque = main.find(class_=lambda c: c and any("slider-ppal-home" in x for x in (c if isinstance(c, list) else [c])))
    if bloque:
        seccion["descripcion"] = _extraer_texto(bloque)
        seccion["elementos"] = []

    # Servicios de Innovación
    seccion = _buscar_seccion_por_tipo(datos, "servicios")
    bloques = main.select(".vtm-servicios-grid__servicio") or main.select(".vtm-servicios-grid .et_pb_blurb")
    elementos = []
    for bloque in bloques:
        titulo_elemento = bloque.find(class_=lambda c: c and ("et_pb_module_header" in c if isinstance(c, list) else "et_pb_module_header" in c))
        titulo = _extraer_texto(titulo_elemento) if titulo_elemento else ""
        if titulo:
            elementos.append({"tipo": "servicio", "titulo": titulo, "descripcion": _extraer_texto(bloque), "url": _extraer_enlace_principal(bloque, url_base)})
    seccion["elementos"] = deduplicar_lista(elementos, clave="url")

    # Iniciativas / Historias / Destacados: mismo patron (card + h2-h4 + enlace + imagen)
    for tipo_seccion, selector_css, tipo_elemento in [
        ("iniciativas", ".card-iniciativa", "iniciativa"),
        ("historias_innovacion", ".card-historia-innovacion", "historia"),
        ("destacados", ".slider-destacados-home__item", "destacado"),
    ]:
        seccion = _buscar_seccion_por_tipo(datos, tipo_seccion)
        elementos = []
        for bloque in main.select(selector_css):
            titulo_elemento = bloque.find(["h2", "h3", "h4"])
            titulo = _extraer_texto(titulo_elemento) if titulo_elemento else ""
            enlace = _extraer_enlace_principal(bloque, url_base)
            if titulo or enlace:
                elementos.append({
                    "tipo": tipo_elemento, "titulo": titulo, "descripcion": _extraer_texto(bloque),
                    "url": enlace, "imagen": _extraer_imagen(bloque, url_base),
                })
        seccion["elementos"] = deduplicar_lista(elementos, clave="url")

    # Temas: igual pero sin descripcion
    seccion = _buscar_seccion_por_tipo(datos, "temas")
    elementos = []
    for bloque in main.select(".card-area-mini"):
        titulo_elemento = bloque.find(["h2", "h3", "h4"])
        titulo = _extraer_texto(titulo_elemento) if titulo_elemento else ""
        enlace = _extraer_enlace_principal(bloque, url_base)
        if titulo or enlace:
            elementos.append({"tipo": "tema", "titulo": titulo, "descripcion": "", "url": enlace, "imagen": _extraer_imagen(bloque, url_base)})
    seccion["elementos"] = deduplicar_lista(elementos, clave="url")

    # Explora UPV: un unico bloque call-to-action
    seccion = _buscar_seccion_por_tipo(datos, "explora")
    bloque = main.select_one(".c2action-explora")
    if bloque:
        titulo_elemento = bloque.find(["h2", "h3", "h4"])
        titulo = _extraer_texto(titulo_elemento) if titulo_elemento else ""
        seccion["descripcion"] = _extraer_texto(bloque)
        seccion["elementos"] = [{"tipo": "recurso", "titulo": titulo, "descripcion": _extraer_texto(bloque), "url": _extraer_enlace_principal(bloque, url_base)}]

    for seccion in datos["secciones"]:
        seccion["titulo"] = limpiar_texto(seccion.get("titulo", ""))
        seccion["descripcion"] = limpiar_texto(seccion.get("descripcion", ""))
        seccion.setdefault("elementos", [])

    return datos


def guardar_json(datos: dict, ruta: Path = INNOVACION_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=4)
    print("JSON guardado:", ruta)


# ==========================================================
# Generacion de Markdown
# ==========================================================

def nombre_archivo_markdown(titulo: str, url: str = "") -> str:
    nombre = titulo.strip() or urlparse(url).path.strip("/").split("/")[-1] or "recurso"
    reemplazos = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"}
    nombre = nombre.lower()
    for origen, destino in reemplazos.items():
        nombre = nombre.replace(origen, destino)
    nombre = re.sub(r"[^a-z0-9]+", "_", nombre).strip("_")
    return (nombre or "recurso") + ".md"


def escapar_yaml(texto) -> str:
    return "" if texto is None else str(texto).replace('"', '\\"')


def eliminar_elementos_no_informativos(soup: BeautifulSoup) -> BeautifulSoup:
    for etiqueta in ["script", "style", "noscript", "iframe", "svg", "form"]:
        for elemento in soup.find_all(etiqueta):
            elemento.decompose()
    return soup


def extraer_contenido_pagina(url: str) -> dict | None:
    """Descarga una pagina y extrae su contenido en Markdown basico
    (encabezados/parrafos/listas/tablas). None si no es HTML o falla."""
    try:
        respuesta = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        respuesta.raise_for_status()
    except requests.RequestException as error:
        print(f"    ERROR descargando: {error}")
        return None

    if "text/html" not in respuesta.headers.get("Content-Type", "").lower():
        print("    DESCARTADO: no es HTML")
        return None

    soup = eliminar_elementos_no_informativos(BeautifulSoup(respuesta.text, "html.parser"))

    titulo = limpiar_texto(soup.title.get_text(" ", strip=True)) if soup.title else ""

    contenido_principal = None
    for selector in ["main", "article", "[role='main']", ".entry-content", ".post-content", ".page-content", ".elementor-widget-theme-post-content"]:
        elemento = soup.select_one(selector)
        if elemento:
            contenido_principal = elemento
            break
    contenido_principal = contenido_principal or soup.body
    if contenido_principal is None:
        return None

    for selector in ["header", "footer", "nav", ".menu", ".navbar", ".navigation", ".breadcrumb", ".breadcrumbs", ".cookie", ".cookies"]:
        for elemento in contenido_principal.select(selector):
            elemento.decompose()

    bloques = []
    for elemento in contenido_principal.find_all(["h1", "h2", "h3", "h4", "p", "ul", "ol", "table"]):
        nombre = elemento.name

        if nombre in ("h1", "h2", "h3", "h4"):
            texto = limpiar_texto(elemento.get_text(" ", strip=True))
            if texto:
                bloques.append(("#" * int(nombre[1])) + " " + texto)

        elif nombre == "p":
            texto = limpiar_texto(elemento.get_text(" ", strip=True))
            if texto:
                bloques.append(texto)

        elif nombre in ("ul", "ol"):
            items = [f"- {limpiar_texto(li.get_text(' ', strip=True))}" for li in elemento.find_all("li", recursive=False) if limpiar_texto(li.get_text(" ", strip=True))]
            if items:
                bloques.append("\n".join(items))

        elif nombre == "table":
            filas = []
            for tr in elemento.find_all("tr"):
                celdas = [limpiar_texto(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
                if celdas:
                    filas.append(celdas)
            if filas:
                num_cols = max(len(f) for f in filas)
                encabezado = filas[0] + [""] * (num_cols - len(filas[0]))
                tabla_md = ["| " + " | ".join(encabezado) + " |", "| " + " | ".join(["---"] * num_cols) + " |"]
                for fila in filas[1:]:
                    fila = fila + [""] * (num_cols - len(fila))
                    tabla_md.append("| " + " | ".join(fila) + " |")
                bloques.append("\n".join(tabla_md))

    contenido = "\n\n".join(bloques).strip()
    if not contenido:
        return None

    return {"titulo": titulo, "contenido": contenido, "url_final": respuesta.url}


def generar_markdown_padre(datos: dict, ruta: Path = INNOVACION_MD_PADRE) -> str:
    """Vuelca directamente el JSON (no vuelve a descargar nada)."""
    titulo_padre = datos.get("titulo", "UPV Innovación")
    url_padre = datos.get("url", INNOVACION_URL)

    partes = ["---\n", "tipo: padre\n", "nivel: innovacion\n", f"url: {url_padre}\n", "---\n\n", f"# {titulo_padre}\n\n"]

    for seccion in datos.get("secciones", []):
        titulo_seccion = limpiar_texto(seccion.get("titulo", ""))
        if titulo_seccion:
            partes.append(f"## {titulo_seccion}\n\n")

        descripcion = limpiar_texto(seccion.get("descripcion", ""))
        if descripcion:
            partes.append(descripcion + "\n\n")

        for elemento in seccion.get("elementos", []):
            titulo_elemento = limpiar_texto(elemento.get("titulo", ""))
            descripcion_elemento = limpiar_texto(elemento.get("descripcion", ""))
            url = normalizar_url(elemento.get("url", ""), url_padre)

            if titulo_elemento:
                partes.append(f"### {titulo_elemento}\n\n")
            elif elemento.get("tipo"):
                partes.append(f"### {elemento.get('tipo').capitalize()}\n\n")

            if descripcion_elemento:
                partes.append(descripcion_elemento + "\n\n")
            if url:
                partes.append(f"[{url}]({url})\n\n")

    contenido = "".join(partes)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as archivo:
        archivo.write(contenido)

    print("Markdown principal generado:", ruta)
    return contenido


def generar_markdowns_recursos(datos: dict, carpeta: Path = INNOVACION_RECURSOS_DIR) -> tuple[int, int]:
    carpeta.mkdir(parents=True, exist_ok=True)
    url_padre = datos.get("url", INNOVACION_URL)

    recursos_generados = recursos_descartados = 0
    urls_procesadas = set()

    for seccion in datos.get("secciones", []):
        nombre_seccion = limpiar_texto(seccion.get("titulo", ""))

        for elemento in seccion.get("elementos", []):
            url = normalizar_url(elemento.get("url", ""), url_padre)

            if not url or url in urls_procesadas or not url.startswith(("http://", "https://")):
                continue
            urls_procesadas.add(url)

            print(f"[{recursos_generados + recursos_descartados + 1}] {url}")
            resultado = extraer_contenido_pagina(url)
            if resultado is None:
                recursos_descartados += 1
                continue

            titulo_recurso = limpiar_texto(elemento.get("titulo", "")) or resultado.get("titulo", "")
            if not titulo_recurso:
                titulo_recurso = urlparse(resultado["url_final"]).path.strip("/").split("/")[-1] or "Recurso"

            nombre_archivo = nombre_archivo_markdown(titulo_recurso, resultado["url_final"])
            tipo_recurso = elemento.get("tipo", "recurso")

            with open(carpeta / nombre_archivo, "w", encoding="utf-8") as archivo:
                archivo.write("---\n")
                archivo.write("tipo: recurso\n")
                archivo.write("nivel: innovacion\n")
                archivo.write(f"tipo_recurso: {escapar_yaml(tipo_recurso)}\n")
                archivo.write(f"seccion_origen: {escapar_yaml(nombre_seccion)}\n")
                archivo.write(f"url: {escapar_yaml(resultado['url_final'])}\n")
                archivo.write(f"url_origen: {escapar_yaml(url_padre)}\n")
                archivo.write("---\n\n")
                archivo.write(f"# {titulo_recurso}\n\n")
                archivo.write(resultado["contenido"])
                archivo.write("\n")

            recursos_generados += 1
            print(f"    OK -> {nombre_archivo}")

    return recursos_generados, recursos_descartados


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    datos = extraer_json_innovacion()
    guardar_json(datos)
    generar_markdown_padre(datos)
    generados, descartados = generar_markdowns_recursos(datos)
    print(f"Recursos generados: {generados} · descartados: {descartados}")


if __name__ == "__main__":
    main()
