"""Extractor de "La UPV en los rankings".

Pagina estatica, sin JS de carga adicional: una sucesion de "tarjetas"
(encabezado que enlaza a una noticia UPV + parrafo descriptivo + enlace
externo a la fuente del ranking -- Shanghai, QS, THE...). Reutiliza el
motor de limpieza comun con institucion/servicios para el Markdown.

Pipeline (mismo orden que el notebook original):
  1. extraer_rankings()  -> JSON con el listado de rankings
  2. guardar_json()
  3. limpiar_json_rankings() -> dedup defensivo por URL (aqui no hace
     falta filtrar "fichas falsas" como en servicios: cada elemento ya
     viene de una tarjeta real con enlace a noticia UPV)
  4. generar_markdown_padre_rankings()
  5. generar_markdowns_recursos() -> motor de limpieza comun + resolucion
     de URLs de plantilla antigua + enlaces hijos utiles (igual que
     servicios)

Migrado desde src/extractores/rankings/extrae_rankings.ipynb (antes
Extrae_Rankings.ipynb). Sin celdas exploratorias que descartar.

Reutiliza motor_limpieza.py. La deteccion de "es la misma pagina"
(es_variante_de_la_misma_pagina) usa aqui comparacion de path de URL, NO
codigo de entidad como en servicios -- las noticias UPV que documentan
cada ranking no son fichas de /entidades/.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/ (config.py, common.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # src/extractores/ (motor_limpieza.py)

from bs4 import BeautifulSoup
import requests

from common import limpiar_texto
from config import RANKINGS_DIR, RANKINGS_JSON, RANKINGS_MD_PADRE, RANKINGS_URL
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

FUENTE = "UPV"
CATEGORIA = "rankings"
TIPO_RECURSO = "ranking"
SECCION = "rankings"

UMBRAL_PALABRAS_POCO_CONTENIDO = 60
MAX_ENLACES_HIJOS = 5
MAX_CARACTERES_FRAGMENTO_HIJO = 800

PATRON_NOTICIA = re.compile(r"/noticias-upv/", re.IGNORECASE)
TAGS_ENCABEZADO = ["h1", "h2", "h3", "h4", "h5", "h6"]

# Amplia el conjunto comun con los terminos de la plantilla antigua (ver
# extrae_servicios.py) mas los especificos de la pagina de rankings.
TEXTOS_BOILERPLATE_RANKINGS = ml.TEXTOS_BOILERPLATE_BASE | {
    "idioma", "idioma · language", "language",
    "valencia", "valencian", "english", "castellano",
    "cercar", "search", "directory", "directori",
    "contacte", "contact",
    "otros", "donde estamos", "¿donde estamos?",
    "webs relacionadas",
    "va", "en", "web (abre en nueva ventana)",
}


def _yaml_resumen(url: str, titulo: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=url, categoria=CATEGORIA,
                                      tipo_documento="resumen", titulo=titulo)


def _yaml_recurso(recurso: dict, url_resumen: str) -> str:
    campos_extra = {"url_externa": recurso["url_externa"]} if recurso.get("url_externa") else None
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=recurso.get("url", ""), categoria=CATEGORIA,
                                      tipo_documento="recurso", tipo_recurso=TIPO_RECURSO,
                                      resumen=url_resumen, seccion=SECCION, titulo=recurso.get("titulo", ""),
                                      descripcion=recurso.get("descripcion", ""), campos_extra=campos_extra)


def es_url_externa(url: str) -> bool:
    try:
        dominio = urlparse(url).netloc.lower()
    except Exception:
        return False
    return bool(dominio) and "upv.es" not in dominio


def es_variante_de_la_misma_pagina(href_absoluta: str, url_pagina: str) -> bool:
    def codigo_pagina(url: str) -> str:
        return urlparse(url).path.rstrip("/").lower()

    if codigo_pagina(href_absoluta) != codigo_pagina(url_pagina):
        return False
    return bool(re.search(r"/index\w*\.html?$", href_absoluta, flags=re.IGNORECASE))


def resolver_url_menu_antiguo(url_absoluta: str) -> str:
    m = re.search(r"menu_url\w*\.html\?(//.+)$", url_absoluta, flags=re.IGNORECASE)
    if not m:
        return url_absoluta
    interno = m.group(1)
    if interno.startswith("//"):
        interno = "https:" + interno
    return interno


# ==========================================================
# 1. Extraccion de rankings (JSON)
# ==========================================================

def extraer_rankings(url: str = RANKINGS_URL) -> dict:
    respuesta = requests.get(url, headers=HEADERS, timeout=30)
    respuesta.raise_for_status()
    soup = BeautifulSoup(respuesta.text, "html.parser")

    contenedor_principal = soup.find(id="smooth-wrapper") or soup.find("main") or soup.body
    if contenedor_principal is None:
        raise Exception("No se ha encontrado el contenedor principal de la página.")

    encabezados_ranking = []
    for encabezado in contenedor_principal.find_all(TAGS_ENCABEZADO):
        enlace = encabezado.find("a", href=True)
        if enlace is None:
            continue
        if not PATRON_NOTICIA.search(enlace.get("href", "")):
            continue
        encabezados_ranking.append((encabezado, enlace))

    recursos = []
    for encabezado, enlace_titulo in encabezados_ranking:
        titulo = limpiar_texto(enlace_titulo.get_text(" ", strip=True)) or limpiar_texto(encabezado.get_text(" ", strip=True))
        url_noticia = ml.normalizar_url(enlace_titulo.get("href", ""), url)

        descripcion = ""
        url_externa = ""

        for hermano in encabezado.find_next_siblings():
            if hermano.name in TAGS_ENCABEZADO:
                break

            if not descripcion:
                texto_bloque = limpiar_texto(hermano.get_text(" ", strip=True))
                if hermano.name in {"p", "div", "span"} and len(texto_bloque) > 15:
                    descripcion = texto_bloque

            if not url_externa:
                for enlace_candidato in hermano.find_all("a", href=True):
                    href_candidato = ml.normalizar_url(enlace_candidato.get("href", ""), url)
                    if es_url_externa(href_candidato):
                        url_externa = href_candidato
                        break

        if not titulo or not ml.es_url_valida(url_noticia):
            continue

        elemento = ml.crear_elemento(titulo=titulo, descripcion=descripcion, url=url_noticia, tipo="ranking", url_base=url)
        if url_externa:
            elemento["url_externa"] = ml.normalizar_url(url_externa, url)
        recursos.append(elemento)

    recursos = ml.deduplicar_lista(recursos, clave="url")

    seccion = ml.crear_seccion("Rankings", "rankings")
    seccion["elementos"] = recursos

    return {"titulo": "La UPV en los rankings", "url": url, "tipo": "padre", "secciones": [seccion]}


def guardar_json(datos: dict, ruta: Path = RANKINGS_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


def limpiar_json_rankings(datos: dict) -> dict:
    """Dedup defensivo por URL (aqui no hace falta filtrar 'fichas
    falsas' como en servicios: cada elemento ya viene de una tarjeta de
    ranking real con enlace a noticia UPV)."""
    seccion = datos["secciones"][0]
    elementos_originales = seccion["elementos"]

    elementos_limpios = []
    urls_vistas = set()
    for elemento in elementos_originales:
        url = elemento.get("url", "")
        if not url or url in urls_vistas:
            continue
        urls_vistas.add(url)
        elementos_limpios.append(elemento)

    seccion["elementos"] = elementos_limpios
    print("Elementos originales en el JSON:", len(elementos_originales))
    print("Rankings finales a procesar:", len(elementos_limpios))
    return datos


# ==========================================================
# 2. Generacion de Markdown -- especificos de rankings
#    (enlaces hijos: misma logica que servicios)
# ==========================================================

TEXTOS_EXCLUIDOS_HIJOS = {
    "valencia", "valencia language", "valencian", "english",
    "castellano", "cercar", "search", "directory", "directori",
    "contacte", "contact", "idioma", "language", "idioma language",
}

TEXTOS_PRIORITARIOS_HIJOS = [
    "informacion general", "quienes somos", "presentacion",
    "equipo directivo", "webs relacionadas", "servicios",
    "tramites", "memoria", "funciones", "organigrama",
]

PATRONES_URL_EXCLUIDOS_HIJOS = [
    r"/bin2/tipoacc/", r"sic_mag\.MetaBus", r"/plano/plano-2d", r"/otros/como-llegar",
    r"index-va\.html?$", r"index-en\.html?$", r"index-i\.html?$", r"index-v\.html?$",
    r"/otros/accesibilidad", r"/otros/mapa-web", r"/otros/contacto",
]


def es_directorio_generico_de_personas(href: str) -> bool:
    if "sic_per.Busca_Persona" not in href:
        return False
    return "P_SG=" not in href and "P_CARGOS=" not in href


def extraer_texto_y_url_de_linea_markdown(linea: str) -> tuple[str | None, str | None]:
    m = re.match(r"^\[([^\]]*)\]\(([^)]+)\)$", linea.strip())
    if not m:
        return None, None
    return m.group(1), m.group(2)


def es_autorreferencia_o_accesibilidad(linea: str, url_pagina: str) -> bool:
    texto, href = extraer_texto_y_url_de_linea_markdown(linea)
    if href is None:
        return False
    if len(texto.strip()) <= 2:
        return True
    return es_variante_de_la_misma_pagina(href, url_pagina)


def es_enlace_hijo_util(texto: str, href: str, url_pagina: str) -> bool:
    texto_normalizado = ml.normalizar_para_comparar(texto)

    if len(texto.strip()) <= 2:
        return False
    if texto_normalizado in TEXTOS_BOILERPLATE_RANKINGS:
        return False
    if texto_normalizado in TEXTOS_EXCLUIDOS_HIJOS:
        return False
    if es_directorio_generico_de_personas(href):
        return False

    absoluta = resolver_url_menu_antiguo(urljoin(url_pagina, href).split("#")[0])
    if es_variante_de_la_misma_pagina(absoluta, url_pagina):
        return False

    for patron in PATRONES_URL_EXCLUIDOS_HIJOS:
        if re.search(patron, href, flags=re.IGNORECASE):
            return False

    return True


def obtener_enlaces_hijos(contenedor, url_pagina: str, maximo: int = MAX_ENLACES_HIJOS) -> list[tuple[str, str]]:
    candidatos = []
    urls_vistas = set()

    for a in contenedor.find_all("a", href=True):
        href = a["href"]
        if not ml.es_url_valida_para_expandir(href, url_pagina, urls_vistas):
            continue

        texto = ml.extraer_texto_limpio(a)
        if not texto:
            continue
        if not es_enlace_hijo_util(texto, href, url_pagina):
            continue

        absoluta = resolver_url_menu_antiguo(urljoin(url_pagina, href).split("#")[0])
        urls_vistas.add(absoluta)
        candidatos.append((texto, absoluta))

    def prioridad(candidato):
        return 0 if ml.normalizar_para_comparar(candidato[0]) in TEXTOS_PRIORITARIOS_HIJOS else 1

    candidatos.sort(key=prioridad)
    return candidatos[:maximo]


def resumir_pagina_hija(url: str) -> str | None:
    try:
        soup, es_html = ml.descargar_soup(url, headers=HEADERS)
        if not es_html:
            return None
        soup = ml.limpiar_contenido_html(soup)
        contenedor = soup.find(id="smooth-wrapper") or soup.find("main") or soup.body
        if contenedor is None:
            return None

        lineas = ml.extraer_bloques_contenido(contenedor, url, resolver_url=resolver_url_menu_antiguo)
        lineas = ml.limpiar_lineas_finales(lineas, textos_boilerplate=TEXTOS_BOILERPLATE_RANKINGS)
        lineas = [l for l in lineas if not es_autorreferencia_o_accesibilidad(l, url)]

        fragmento = "\n\n".join(lineas)
        if len(fragmento) > MAX_CARACTERES_FRAGMENTO_HIJO:
            fragmento = fragmento[:MAX_CARACTERES_FRAGMENTO_HIJO].rstrip() + "…"
        return fragmento or None
    except Exception:
        return None


def generar_markdown_recurso(recurso: dict, carpeta: Path, url_resumen: str) -> bool:
    titulo = recurso.get("titulo", "")
    url = recurso.get("url", "")
    if not titulo or not url:
        return False

    print(f"  Extrayendo: {titulo} ({url})")

    try:
        soup, es_html = ml.descargar_soup(url, headers=HEADERS)
        yaml_metadatos = _yaml_recurso(recurso, url_resumen)

        if not es_html:
            markdown = (
                f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n"
                "_Este recurso no es una página HTML estándar "
                "(por ejemplo, un PDF o un vídeo). "
                "Consulta el contenido directamente en la URL indicada._\n"
            )
            ruta_archivo = carpeta / ml.nombre_archivo_markdown(titulo)
            with open(ruta_archivo, "w", encoding="utf-8") as archivo:
                archivo.write(markdown)
            print(f"  OK (no HTML): {ruta_archivo}")
            return True

        soup = ml.limpiar_contenido_html(soup)
        contenido = soup.find(id="smooth-wrapper") or soup.find("main") or soup.body
        if contenido is None:
            print("  AVISO: no se ha encontrado contenido.")
            return False

        lineas_contenido = ml.extraer_bloques_contenido(contenido, url, resolver_url=resolver_url_menu_antiguo)
        lineas_contenido = ml.limpiar_lineas_finales(lineas_contenido, textos_boilerplate=TEXTOS_BOILERPLATE_RANKINGS)
        lineas_contenido = [l for l in lineas_contenido if not es_autorreferencia_o_accesibilidad(l, url)]

        if not lineas_contenido:
            print("  AVISO: contenido vacío.")
            return False

        if ml.contar_palabras(lineas_contenido) < UMBRAL_PALABRAS_POCO_CONTENIDO:
            enlaces_hijos = obtener_enlaces_hijos(contenido, url)
            if enlaces_hijos:
                lineas_contenido.append("## Información relacionada")
                for texto_enlace, url_hija in enlaces_hijos:
                    time.sleep(0.5)
                    fragmento = resumir_pagina_hija(url_hija)
                    lineas_contenido.append(f"### {texto_enlace}")
                    lineas_contenido.append(f"**URL:** {url_hija}")
                    if fragmento:
                        lineas_contenido.append(fragmento)

        markdown_contenido = "\n\n".join(lineas_contenido)
        descripcion = recurso.get("descripcion", "").strip()
        bloque_descripcion = f"**Descripción breve:** {descripcion}\n\n" if descripcion else ""
        bloque_url_externa = f"**Fuente del ranking:** {recurso['url_externa']}\n\n" if recurso.get("url_externa") else ""

        markdown = f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n{bloque_descripcion}{bloque_url_externa}{markdown_contenido}\n"

        ruta_archivo = carpeta / ml.nombre_archivo_markdown(titulo)
        with open(ruta_archivo, "w", encoding="utf-8") as archivo:
            archivo.write(markdown)
        print(f"  OK: {ruta_archivo}")
        return True

    except Exception as error:
        print(f"  ERROR: {error}")
        return False


def generar_markdowns_recursos(datos: dict, carpeta: Path = RANKINGS_DIR) -> tuple[int, int, int]:
    carpeta.mkdir(parents=True, exist_ok=True)
    seccion = datos["secciones"][0]
    url_resumen = datos.get("url", RANKINGS_URL)

    total = correctos = errores = 0
    for recurso in seccion["elementos"]:
        total += 1
        if generar_markdown_recurso(recurso, carpeta, url_resumen):
            correctos += 1
        else:
            errores += 1

    return total, correctos, errores


# ==========================================================
# 3. Markdown de la pagina padre
# ==========================================================

def es_enlace_a_noticia(linea: str) -> bool:
    return bool(re.search(r"\]\(https?://(www\.)?upv\.es/noticias-upv/", linea))


def generar_markdown_padre_rankings(url: str = RANKINGS_URL, ruta: Path = RANKINGS_MD_PADRE) -> str:
    soup, es_html = ml.descargar_soup(url, headers=HEADERS)
    soup = ml.limpiar_contenido_html(soup)

    contenedor = soup.find(id="smooth-wrapper") or soup.find("main") or soup.body
    if contenedor is None:
        raise Exception("No se ha encontrado el contenedor principal.")

    lineas = ml.extraer_bloques_contenido(contenedor, url)
    lineas = ml.limpiar_lineas_finales(lineas, textos_boilerplate=TEXTOS_BOILERPLATE_RANKINGS)
    lineas = [linea for linea in lineas if not es_enlace_a_noticia(linea)]
    lineas = ml.deduplicar_global(lineas)

    yaml_metadatos = _yaml_resumen(url, "La UPV en los rankings")
    markdown = f"{yaml_metadatos}\n" + "\n\n".join(lineas) + "\n"

    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as archivo:
        archivo.write(markdown)
    print("OK: Markdown padre generado:", ruta)
    return markdown


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    datos = extraer_rankings()
    guardar_json(datos)
    datos = limpiar_json_rankings(datos)
    guardar_json(datos)
    generar_markdown_padre_rankings()
    total, correctos, errores = generar_markdowns_recursos(datos)
    print(f"Rankings: {total} · generados: {correctos} · errores: {errores}")


if __name__ == "__main__":
    main()
