"""Extractor de "Iniciativas de I+D+i" (investigacion).

Reescritura completa (2026-08-21) que sustituye la version anterior --
extraccion de texto plano con extraer_contenido_principal()/get_text(),
sin metadatos YAML ni deteccion de PDF/plantilla clasica -- por el patron
ya validado en institucion/servicios/doctorado: motor de limpieza comun
(motor_limpieza.py) + metadatos YAML definitivos + extraccion de texto de
PDF + soporte de la plantilla clasica de fichas de entidad + limpieza de
ficheros huerfanos por cambio de titulo.

La pagina padre (main.iniciativas-page) tiene un cuarto <section> ("Grados")
ademas de las 3 con contenido real -- se sigue filtrando por titulo en
SECCIONES_VALIDAS, igual que la version anterior.

Los recursos de estas 3 secciones enlazan a paginas muy heterogeneas: la
mayoria de VINV/SRH ya estan en su salida estatica cacheada
(.../info/<id>normalc.html, alguna incluso con la plantilla CLASICA
Oracle Portal -- ver motor_limpieza.buscar_iframe_contenido_clasico()),
pero "Convocatorias publicas" enlaza tambien a buscadores/calendarios
inherentemente dinamicos bajo /pls/ sin equivalente estatico (estos ya se
seguian directamente en la version anterior; no se ha cambiado ese
alcance). Varias URLs distintas pueden llevar exactamente al mismo
contenido (ej. version "calendario" y "buscador" con el mismo resultado
bajo distintos parametros) -- se preserva el deduplicado por hash de
contenido de la version anterior: un unico .md por grupo de contenido
identico, listando todas las URLs asociadas.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/ (config.py, common.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # src/extractores/ (motor_limpieza.py)

from bs4 import BeautifulSoup
import requests

from common import limpiar_texto
from config import INICIATIVAS_IDI_JSON, INICIATIVAS_IDI_MD_PADRE, INICIATIVAS_IDI_RECURSOS_DIR, INICIATIVAS_IDI_URL
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

# Titulo de <h3> de cada <section> -> slug de seccion. Los <section> del
# padre sin <h3> o con un titulo fuera de este diccionario (ej. "Grados")
# se descartan igual que en la version anterior.
SECCIONES_VALIDAS = {
    "Convocatorias públicas": "convocatorias_publicas",
    "Programas propios": "programas_propios",
    "Enlaces de interés": "enlaces_interes",
}

# Esta seccion no usa la plantilla WordPress "#smooth-wrapper" de
# institucion/servicios -- selectores propios, con fallback a la
# plantilla clasica (ver buscar_iframe_contenido_clasico) cuando ninguno
# de estos encaja. ".mwc_contenido" es una TERCERA variante de plantilla
# clasica encontrada en paginas de listados/repositorio de documentos
# (ej. SRH/conypi, convocatorias de contratacion de investigadores):
# ni #smooth-wrapper/main/article/entry-content ni el iframe de
# sic_infoent/oalu que ya cubre ml.buscar_iframe_contenido_clasico() --
# el contenido real vive directamente en la pagina, en un
# div.mwc_contenido separado del menu lateral (id="contmenu"). "#contenido"
# (con ID en espanol, distinto de "#content") es una CUARTA variante,
# encontrada en las paginas de boletines de convocatorias
# (pls/somag/CTT_W04.Boletines): el mismo id="contenido" que usa
# buscar_iframe_contenido_clasico() para el contenido DENTRO del iframe,
# pero aqui aparece directamente en la pagina, sin iframe de por medio.
SELECTORES_CONTENIDO = ["main", "article", ".entry-content", "#content", ".content", ".entry", ".mwc_contenido", "#contenido"]

FUENTE = "UPV"
CATEGORIA = "investigacion"
NIVEL = "iniciativas_idi"
TIPO_RECURSO = "informacion"


def _yaml_resumen(url: str, titulo: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=url, categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="resumen", titulo=titulo)


def _yaml_recurso(elemento: dict, seccion_slug: str, url_resumen: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=elemento["url"], categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="recurso", tipo_recurso=TIPO_RECURSO,
                                      resumen=url_resumen, seccion=seccion_slug, titulo=elemento["titulo"])


# ==========================================================
# 1. Catalogo (padre + 3 secciones con recursos)
# ==========================================================

def extraer_catalogo(url: str = INICIATIVAS_IDI_URL) -> dict:
    respuesta = requests.get(url, headers=HEADERS, timeout=30)
    respuesta.raise_for_status()
    soup = BeautifulSoup(respuesta.text, "html.parser")

    main = soup.select_one("main.iniciativas-page")
    if main is None:
        raise Exception("No se ha encontrado 'main.iniciativas-page' en la página.")

    h1 = main.find("h1")
    titulo_padre = limpiar_texto(h1.get_text(" ", strip=True)) if h1 else "Iniciativas de I+D+i"

    secciones = []
    for section in main.find_all("section", recursive=False):
        h3 = section.find("h3")
        if h3 is None:
            continue
        titulo_seccion = limpiar_texto(h3.get_text(" ", strip=True))
        slug = SECCIONES_VALIDAS.get(titulo_seccion)
        if slug is None:
            continue

        elementos = []
        for a in section.find_all("a", href=True):
            nombre = limpiar_texto(a.get_text(" ", strip=True))
            if not nombre:
                continue
            url_elemento = ml.normalizar_url(a["href"], url)
            if not ml.es_url_valida(url_elemento):
                continue
            elementos.append(ml.crear_elemento(titulo=nombre, url=url_elemento, tipo="recurso", url_base=url))

        seccion = ml.crear_seccion(titulo_seccion, slug)
        seccion["elementos"] = ml.deduplicar_lista(elementos, clave="url")
        secciones.append(seccion)

    total_elementos = sum(len(s["elementos"]) for s in secciones)
    print("Secciones válidas encontradas:", len(secciones), "· elementos totales:", total_elementos)
    return {"titulo": titulo_padre, "url": url, "tipo": "padre", "secciones": secciones}


def guardar_json(datos: dict, ruta: Path = INICIATIVAS_IDI_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


# ==========================================================
# 2. Markdown de la pagina padre
# ==========================================================

def generar_markdown_padre(datos: dict, ruta: Path = INICIATIVAS_IDI_MD_PADRE) -> str:
    url = datos["url"]
    soup, es_html = ml.descargar_soup(url, headers=HEADERS)
    soup = ml.limpiar_contenido_html(soup)

    contenedor = soup.select_one("main.iniciativas-page") or soup.find("main") or soup.body
    if contenedor is None:
        raise Exception("No se ha encontrado el contenedor principal.")

    ml.reemplazar_tablas_por_listas(soup, contenedor)
    lineas = ml.extraer_bloques_contenido(contenedor, url)
    lineas = ml.limpiar_lineas_finales(lineas)

    yaml_metadatos = _yaml_resumen(url, datos.get("titulo", "Iniciativas de I+D+i"))
    markdown = f"{yaml_metadatos}\n" + "\n\n".join(lineas) + "\n"

    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as archivo:
        archivo.write(markdown)
    print("OK: Markdown padre generado:", ruta)
    return markdown


# ==========================================================
# 3. Contenido de cada recurso (HTML/PDF/plantilla clasica)
# ==========================================================

def encontrar_contenedor(soup: BeautifulSoup):
    for selector in SELECTORES_CONTENIDO:
        elemento = soup.select_one(selector)
        if elemento is not None and len(elemento.get_text(" ", strip=True)) >= 100:
            return elemento
    return None


def extraer_contenido_iframe_clasico(soup: BeautifulSoup, url_pagina: str) -> list[str]:
    """Si la pagina usa la plantilla clasica (sin main/article/entry-content
    reconocible), sigue el <iframe> con el contenido real -- ver
    ml.buscar_iframe_contenido_clasico()."""
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


def extraer_contenido_elemento(url: str) -> tuple[str, str] | None:
    """Descarga un recurso y devuelve (tipo, cuerpo_markdown), o None si
    no se ha podido extraer nada util. tipo es 'pdf'/'html'/'otro' (el
    mismo que ml.tipo_contenido())."""
    try:
        respuesta = requests.get(url, headers=HEADERS, timeout=30)
        respuesta.raise_for_status()
    except Exception as error:
        print(f"    ERROR descargando: {error}")
        return None

    tipo = ml.tipo_contenido(respuesta.headers.get("Content-Type", ""))

    if tipo == "pdf":
        paginas = ml.extraer_texto_pdf(respuesta.content)
        return ("pdf", "\n\n".join(paginas)) if paginas else None

    if tipo != "html":
        return None

    soup = BeautifulSoup(respuesta.text, "html.parser")
    soup = ml.limpiar_contenido_html(soup)
    contenedor = encontrar_contenedor(soup)

    if contenedor is None:
        lineas = extraer_contenido_iframe_clasico(soup, url)
    else:
        ml.reemplazar_tablas_por_listas(soup, contenedor)
        lineas = ml.extraer_bloques_contenido(contenedor, url)
        lineas = ml.limpiar_lineas_finales(lineas)

    return ("html", "\n\n".join(lineas)) if lineas else None


# ==========================================================
# 4. Markdown de los recursos -- agrupados por contenido identico
# ==========================================================

def hash_contenido(contenido: str) -> str:
    return hashlib.sha256(contenido.strip().encode("utf-8")).hexdigest()


def recopilar_contenidos(datos: dict) -> dict[str, dict]:
    """Descarga cada elemento de cada seccion y los agrupa por hash de
    contenido (varias URLs pueden llevar al mismo recurso, ver cabecera
    del modulo). Devuelve {hash: {"elemento", "seccion_slug", "tipo",
    "cuerpo", "urls_asociadas"}} -- un unico grupo por contenido distinto,
    quedandose con el primer elemento visto como representante (su
    titulo/url son los que se usan para el nombre de fichero y el YAML)."""
    grupos: dict[str, dict] = {}

    for seccion in datos["secciones"]:
        slug = seccion["id"]
        for elemento in seccion["elementos"]:
            print(f"  Extrayendo: {elemento['titulo']} ({elemento['url']})")
            resultado = extraer_contenido_elemento(elemento["url"])
            time.sleep(0.3)
            if resultado is None:
                print("    AVISO: sin contenido útil.")
                continue
            tipo, cuerpo = resultado
            clave = hash_contenido(cuerpo)

            if clave in grupos:
                grupos[clave]["urls_asociadas"].append(elemento["url"])
                continue

            grupos[clave] = {
                "elemento": elemento,
                "seccion_slug": slug,
                "tipo": tipo,
                "cuerpo": cuerpo,
                "urls_asociadas": [elemento["url"]],
            }

    return grupos


def generar_markdowns_recursos(grupos: dict[str, dict], carpeta: Path = INICIATIVAS_IDI_RECURSOS_DIR,
                                url_resumen: str = INICIATIVAS_IDI_URL,
                                catalogo_anterior: list[dict] | None = None) -> tuple[int, int]:
    carpeta.mkdir(parents=True, exist_ok=True)

    elementos_escritos = []
    for grupo in grupos.values():
        elemento = grupo["elemento"]
        titulo, url = elemento["titulo"], elemento["url"]
        yaml_metadatos = _yaml_recurso(elemento, grupo["seccion_slug"], url_resumen)

        bloque_urls = "## URLs asociadas\n\n" + "\n".join(f"- {u}" for u in grupo["urls_asociadas"]) + "\n\n"
        if grupo["tipo"] == "pdf":
            cuerpo = grupo["cuerpo"] or "_PDF sin texto extraíble (probablemente escaneado sin OCR)._"
        else:
            cuerpo = grupo["cuerpo"]

        markdown = f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n{bloque_urls}{cuerpo}\n"

        ruta_archivo = carpeta / ml.nombre_archivo_markdown(titulo)
        with open(ruta_archivo, "w", encoding="utf-8") as archivo:
            archivo.write(markdown)
        print(f"  OK: {ruta_archivo}")
        elementos_escritos.append(elemento)

    borrados = ml.limpiar_ficheros_renombrados(catalogo_anterior or [], elementos_escritos, carpeta)
    return len(elementos_escritos), borrados


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    catalogo_anterior_por_seccion = ml.cargar_catalogo_anterior(INICIATIVAS_IDI_JSON)
    catalogo_anterior = [e for elementos in catalogo_anterior_por_seccion.values() for e in elementos]

    datos = extraer_catalogo()
    guardar_json(datos)
    generar_markdown_padre(datos)

    grupos = recopilar_contenidos(datos)
    generados, borrados = generar_markdowns_recursos(grupos, catalogo_anterior=catalogo_anterior)
    print(f"Iniciativas I+D+i: recursos generados: {generados} · ficheros renombrados limpiados: {borrados}")


if __name__ == "__main__":
    main()
