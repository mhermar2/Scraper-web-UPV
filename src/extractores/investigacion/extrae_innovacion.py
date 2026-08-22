"""Extractor de "UPV Innovacion" (investigacion).

Reescritura completa (2026-08-21) que sustituye la version anterior --
YAML propio simplificado, sin deteccion de PDF ni plantilla clasica, y
extraccion de recursos con un loop h1-h4/p/ul/ol/table propio en vez del
motor comun -- por el patron ya validado en institucion/servicios/
doctorado/iniciativas_idi: metadatos YAML definitivos + motor_limpieza.py
para el contenido de cada recurso (traversal por hoja de contenido,
filtrado de boilerplate, PDF, plantilla clasica) + limpieza de ficheros
huerfanos por cambio de titulo.

La pagina padre (WordPress + Divi, maquetacion muy distinta de
institucion/servicios) sigue sin encajar en el motor de "hoja de
contenido": se mantiene la extraccion por selectores CSS propios de cada
seccion (.card-iniciativa, .card-historia-innovacion,
.vtm-servicios-grid__servicio...), pero se corrige la extraccion de
titulo -- comprobado contra la web real, 3 de los 6 tipos de tarjeta
("iniciativas", "temas", "destacados") ya NO llevan su titulo en un
h2/h3/h4 como asumia el extractor anterior, sino en un <div
class="...__titulo"> o solo como aria-label del enlace -- el extractor
anterior generaba esos elementos con "titulo": "" en silencio.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/ (config.py, common.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # src/extractores/ (motor_limpieza.py)

from bs4 import BeautifulSoup
import requests

from common import limpiar_texto
from config import INNOVACION_JSON, INNOVACION_MD_PADRE, INNOVACION_RECURSOS_DIR, INNOVACION_URL
import motor_limpieza as ml

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

# Recursos enlazados desde estas tarjetas pueden ser paginas de
# innovacion.upv.es (WordPress moderno) o de otros dominios UPV con la
# plantilla clasica de fichas de entidad -- mismos selectores que
# iniciativas_idi, con el mismo fallback a la plantilla clasica
# (incluida ".mwc_contenido", confirmada tambien en admision/master, y
# "#contenido" -- id en espanol, distinto de "#content" -- para paginas
# de boletines/listados Oracle Portal sin iframe, ver
# extrae_iniciativas_idi.py).
SELECTORES_CONTENIDO = ["main", "article", ".entry-content", "#content", ".content", ".entry", ".mwc_contenido", "#contenido"]

FUENTE = "UPV"
CATEGORIA = "investigacion"
NIVEL = "innovacion"


def _yaml_resumen(url: str, titulo: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=url, categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="resumen", titulo=titulo)


def _yaml_recurso(elemento: dict, seccion_slug: str, url_resumen: str) -> str:
    tipo_recurso = "servicio" if elemento.get("tipo") == "servicio" else "informacion"
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=elemento["url"], categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="recurso", tipo_recurso=tipo_recurso,
                                      resumen=url_resumen, seccion=seccion_slug, titulo=elemento["titulo"],
                                      descripcion=elemento.get("descripcion", ""))


def _crear_json_base() -> dict:
    return {
        "titulo": "UPV Innovación",
        "url": INNOVACION_URL,
        "tipo": "padre",
        "secciones": [ml.crear_seccion(titulo, tipo) for titulo, tipo in SECCIONES_BASE],
    }


def _buscar_seccion_por_tipo(json_data: dict, tipo: str) -> dict | None:
    # ml.crear_seccion(titulo, tipo) guarda "tipo" tal cual, pero deriva
    # "id" normalizando el TITULO (ej. "servicios_de_innovacion", no
    # "servicios") -- aqui interesa el slug corto y estable de
    # SECCIONES_BASE, asi que se busca por "tipo".
    for seccion in json_data["secciones"]:
        if seccion["tipo"] == tipo:
            return seccion
    return None


def _extraer_texto(elemento) -> str:
    return limpiar_texto(elemento.get_text(" ", strip=True)) if elemento is not None else ""


def _extraer_url(elemento, url_base: str) -> str:
    if elemento is None:
        return ""
    return ml.normalizar_url(elemento.get("href", ""), url_base)


def _extraer_imagen(elemento, url_base: str) -> str:
    if elemento is None:
        return ""
    img = elemento.find("img")
    if img is None:
        return ""
    src = img.get("src") or img.get("data-src") or ""
    return ml.normalizar_url(src, url_base)


def _extraer_enlace_principal(elemento, url_base: str) -> str:
    if elemento is None:
        return ""
    enlace = elemento.find("a", href=True)
    return _extraer_url(enlace, url_base) if enlace is not None else ""


def _extraer_titulo_tarjeta(bloque) -> str:
    """La maquetacion Divi no siempre pone el titulo en un h2/h3/h4:
    'iniciativas'/'temas'/'destacados' lo llevan en un <div
    class="...__titulo"> (a veces sin ningun heading dentro), o solo
    como aria-label del enlace envolvente -- comprobado contra la web
    real, ver cabecera del modulo."""
    encabezado = bloque.find(["h2", "h3", "h4"])
    if encabezado is not None:
        texto = _extraer_texto(encabezado)
        if texto:
            return texto

    contenedor_titulo = bloque.find(
        class_=lambda c: c and any("titulo" in clase for clase in (c if isinstance(c, list) else [c]))
    )
    if contenedor_titulo is not None:
        texto = _extraer_texto(contenedor_titulo)
        if texto:
            return texto

    enlace = bloque.find("a", attrs={"aria-label": True})
    if enlace is not None and enlace.get("aria-label"):
        return limpiar_texto(enlace["aria-label"])

    img = bloque.find("img", alt=True)
    if img is not None and img.get("alt"):
        return limpiar_texto(img["alt"])

    return ""


# ==========================================================
# 1. Catalogo de la pagina padre (selectores CSS propios por seccion)
# ==========================================================

def extraer_catalogo(url: str = INNOVACION_URL) -> dict:
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

    # Servicios de Innovación
    seccion = _buscar_seccion_por_tipo(datos, "servicios")
    bloques = main.select(".vtm-servicios-grid__servicio") or main.select(".vtm-servicios-grid .et_pb_blurb")
    elementos = []
    for bloque in bloques:
        titulo = _extraer_titulo_tarjeta(bloque)
        if titulo:
            elementos.append({"tipo": "servicio", "titulo": titulo, "descripcion": _extraer_texto(bloque), "url": _extraer_enlace_principal(bloque, url_base)})
    seccion["elementos"] = ml.deduplicar_lista(elementos, clave="url")

    # Iniciativas / Historias / Destacados: mismo patron (card + titulo + enlace + imagen)
    for tipo_seccion, selector_css, tipo_elemento in [
        ("iniciativas", ".card-iniciativa", "iniciativa"),
        ("historias_innovacion", ".card-historia-innovacion", "historia"),
        ("destacados", ".slider-destacados-home__item", "destacado"),
    ]:
        seccion = _buscar_seccion_por_tipo(datos, tipo_seccion)
        elementos = []
        for bloque in main.select(selector_css):
            titulo = _extraer_titulo_tarjeta(bloque)
            enlace = _extraer_enlace_principal(bloque, url_base)
            if titulo or enlace:
                elementos.append({
                    "tipo": tipo_elemento, "titulo": titulo, "descripcion": _extraer_texto(bloque),
                    "url": enlace, "imagen": _extraer_imagen(bloque, url_base),
                })
        seccion["elementos"] = ml.deduplicar_lista(elementos, clave="url")

    # Temas: igual pero sin descripcion
    seccion = _buscar_seccion_por_tipo(datos, "temas")
    elementos = []
    for bloque in main.select(".card-area-mini"):
        titulo = _extraer_titulo_tarjeta(bloque)
        enlace = _extraer_enlace_principal(bloque, url_base)
        if titulo or enlace:
            elementos.append({"tipo": "tema", "titulo": titulo, "descripcion": "", "url": enlace, "imagen": _extraer_imagen(bloque, url_base)})
    seccion["elementos"] = ml.deduplicar_lista(elementos, clave="url")

    # Explora UPV: un unico bloque call-to-action
    seccion = _buscar_seccion_por_tipo(datos, "explora")
    bloque = main.select_one(".c2action-explora")
    if bloque:
        titulo = _extraer_titulo_tarjeta(bloque) or "Explora UPV"
        seccion["descripcion"] = _extraer_texto(bloque)
        seccion["elementos"] = [{"tipo": "recurso", "titulo": titulo, "descripcion": _extraer_texto(bloque), "url": _extraer_enlace_principal(bloque, url_base)}]

    for seccion in datos["secciones"]:
        seccion["titulo"] = limpiar_texto(seccion.get("titulo", ""))
        seccion["descripcion"] = limpiar_texto(seccion.get("descripcion", ""))
        seccion.setdefault("elementos", [])

    total_elementos = sum(len(s["elementos"]) for s in datos["secciones"])
    print("Secciones:", len(datos["secciones"]), "· elementos totales:", total_elementos)
    return datos


def guardar_json(datos: dict, ruta: Path = INNOVACION_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


# ==========================================================
# 2. Markdown de la pagina padre -- vuelca directamente el JSON
#    (la maquetacion en tarjetas no es un articulo "hoja de contenido")
# ==========================================================

def generar_markdown_padre(datos: dict, ruta: Path = INNOVACION_MD_PADRE) -> str:
    titulo_padre = datos.get("titulo", "UPV Innovación")
    url_padre = datos.get("url", INNOVACION_URL)

    partes = [_yaml_resumen(url_padre, titulo_padre), f"\n# {titulo_padre}\n\n"]

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
            url = ml.normalizar_url(elemento.get("url", ""), url_padre)

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


# ==========================================================
# 3. Contenido de cada recurso -- motor_limpieza (HTML/PDF/plantilla clasica)
# ==========================================================

def encontrar_contenedor(soup: BeautifulSoup):
    for selector in SELECTORES_CONTENIDO:
        elemento = soup.select_one(selector)
        if elemento is not None and len(elemento.get_text(" ", strip=True)) >= 100:
            return elemento
    return None


def extraer_contenido_iframe_clasico(soup: BeautifulSoup, url_pagina: str) -> list[str]:
    iframe_url = ml.buscar_iframe_contenido_clasico(soup, url_pagina)
    if iframe_url is None:
        return []
    soup_iframe, es_html = ml.descargar_soup(iframe_url, headers=HEADERS)
    if not es_html:
        return []
    soup_iframe = ml.limpiar_contenido_html(soup_iframe)
    contenido_iframe = soup_iframe.find(id="contenido") or soup_iframe.body
    if contenido_iframe is None:
        return []
    ml.reemplazar_tablas_por_listas(soup_iframe, contenido_iframe)
    lineas = ml.extraer_bloques_contenido(contenido_iframe, iframe_url)
    return ml.limpiar_lineas_finales(lineas, recortar_h1=False)


def nombre_archivo_recurso(titulo: str, url: str) -> str:
    """Como ml.nombre_archivo_markdown(), pero con el mismo fallback al
    slug de la URL que tenia la version anterior -- las tarjetas de
    'destacados' pueden enlazar a dominios externos (YouTube...) donde a
    veces no hay titulo de tarjeta ni h1 propio."""
    if titulo.strip():
        return ml.nombre_archivo_markdown(titulo)
    slug = url.rstrip("/").split("/")[-1] or "recurso"
    return ml.nombre_archivo_markdown(slug)


def generar_markdown_recurso(elemento: dict, seccion_slug: str, carpeta: Path, url_resumen: str) -> bool:
    titulo = elemento.get("titulo", "")
    url = elemento.get("url", "")
    if not url:
        return False

    print(f"  Extrayendo: {titulo or url} ({url})")

    try:
        respuesta = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        respuesta.raise_for_status()
    except Exception as error:
        print(f"    ERROR descargando: {error}")
        return False

    tipo = ml.tipo_contenido(respuesta.headers.get("Content-Type", ""))
    if not titulo:
        titulo = url.rstrip("/").split("/")[-1] or "Recurso"
        elemento = {**elemento, "titulo": titulo}

    yaml_metadatos = _yaml_recurso(elemento, seccion_slug, url_resumen)

    if tipo == "pdf":
        paginas = ml.extraer_texto_pdf(respuesta.content)
        cuerpo = "\n\n".join(paginas) if paginas else "_PDF sin texto extraíble (probablemente escaneado sin OCR)._"
    elif tipo != "html":
        cuerpo = "_Este recurso no es una página HTML ni un PDF estándar. Consulta el contenido directamente en la URL indicada._"
    else:
        soup = BeautifulSoup(respuesta.text, "html.parser")
        soup = ml.limpiar_contenido_html(soup)
        contenedor = encontrar_contenedor(soup)
        if contenedor is None:
            lineas = extraer_contenido_iframe_clasico(soup, url)
        else:
            ml.reemplazar_tablas_por_listas(soup, contenedor)
            lineas = ml.extraer_bloques_contenido(contenedor, url)
            lineas = ml.limpiar_lineas_finales(lineas)
        if not lineas:
            print("    AVISO: sin contenido útil.")
            return False
        cuerpo = "\n\n".join(lineas)

    markdown = f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n{cuerpo}\n"

    ruta_archivo = carpeta / nombre_archivo_recurso(titulo, url)
    with open(ruta_archivo, "w", encoding="utf-8") as archivo:
        archivo.write(markdown)
    print(f"  OK ({tipo}): {ruta_archivo}")
    return True


def generar_markdowns_recursos(datos: dict, carpeta: Path = INNOVACION_RECURSOS_DIR,
                                catalogo_anterior: dict[str, list[dict]] | None = None) -> tuple[int, int, int]:
    carpeta.mkdir(parents=True, exist_ok=True)
    url_padre = datos.get("url", INNOVACION_URL)

    elementos_escritos_por_seccion: dict[str, list[dict]] = {}
    generados = descartados = 0
    urls_procesadas = set()

    for seccion in datos.get("secciones", []):
        slug = seccion["id"]
        elementos_escritos_por_seccion[slug] = []

        for elemento in seccion.get("elementos", []):
            url = ml.normalizar_url(elemento.get("url", ""), url_padre)
            if not url or url in urls_procesadas or not ml.es_url_valida(url):
                continue
            urls_procesadas.add(url)

            elemento = {**elemento, "url": url}
            if generar_markdown_recurso(elemento, slug, carpeta, url_padre):
                generados += 1
                elementos_escritos_por_seccion[slug].append(elemento)
            else:
                descartados += 1
            time.sleep(0.3)

    borrados = 0
    for slug, elementos_escritos in elementos_escritos_por_seccion.items():
        elementos_anteriores = (catalogo_anterior or {}).get(slug, [])
        borrados += ml.limpiar_ficheros_renombrados(elementos_anteriores, elementos_escritos, carpeta)

    return generados, descartados, borrados


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    catalogo_anterior = ml.cargar_catalogo_anterior(INNOVACION_JSON)

    datos = extraer_catalogo()
    guardar_json(datos)
    generar_markdown_padre(datos)

    generados, descartados, borrados = generar_markdowns_recursos(datos, catalogo_anterior=catalogo_anterior)
    print(f"Innovación: recursos generados: {generados} · descartados: {descartados} · renombrados limpiados: {borrados}")


if __name__ == "__main__":
    main()
