"""Extractor de "Servicios universitarios" -- seccion de referencia junto
con institucion (motor de limpieza validado, ver las notas internas del proyecto).

A diferencia de institucion, aqui no hay varias secciones tematicas: es
un unico listado (buscador) de entidades. La pagina de listado carga
resultados adicionales via JavaScript ("Cargar mas resultados"), asi que
con requests puro solo se recogen los ~20 servicios presentes en el HTML
inicial de los 74 reales -- se avisa si el recuento es menor de lo
esperado (igual que hacia el notebook original).

Pipeline (mismo orden que el notebook original):
  1. extraer_servicios()  -> JSON con el listado de entidades
  2. guardar_json()
  3. limpiar_json_servicios() -> descarta entradas que no son ficha real
     de servicio (vienen del widget "Esto te interesa" o del pie) y
     dedup por codigo de entidad
  4. generar_markdown_padre_servicios()
  5. generar_markdowns_recursos() -> motor de limpieza comun +
     resolucion de URLs de plantilla antigua + filtros propios de
     "enlaces hijos" utiles

Migrado desde src/extractores/servicios/extrae_servicios.ipynb (antes
Extrae_Servicios.ipynb). Sin celdas exploratorias que descartar. Se
elimino una linea muerta en obtener_enlaces_hijos() ("return enlaces"
tras el return real, con una variable "enlaces" que ni siquiera existia
en ese scope -- resto de un copy/paste, nunca pudo ejecutarse).

Reutiliza motor_limpieza.py (compartido con institucion). El conjunto de
boilerplate de servicios amplia el comun con los terminos de la
plantilla ANTIGUA de fichas de entidad (menu lateral de idioma), que
institucion no debe filtrar (ver commit del refactor de motor_limpieza).
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
from config import SERVICIOS_JSON, SERVICIOS_MD_PADRE, SERVICIOS_DIR, SERVICIOS_URL
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

TOTAL_ESPERADO = 74

FUENTE = "UPV"
CATEGORIA = "servicios"
TIPO_RECURSO = "servicio"
SECCION = "servicios_universitarios"

UMBRAL_PALABRAS_POCO_CONTENIDO = 60
MAX_ENLACES_HIJOS = 5
MAX_CARACTERES_FRAGMENTO_HIJO = 800

# Amplia el conjunto comun con los terminos de la plantilla ANTIGUA de
# fichas de entidad (menu lateral de idioma/accesibilidad, sin contenido
# real) -- institucion no los necesita, ver motor_limpieza.py.
TEXTOS_BOILERPLATE_SERVICIOS = ml.TEXTOS_BOILERPLATE_BASE | {
    "idioma", "idioma · language", "language",
    "valencia", "valencian", "english", "castellano",
    "cercar", "search", "directory", "directori",
    "contacte", "contact",
    "otros", "donde estamos", "¿donde estamos?",
    "webs relacionadas",
}


def _yaml_resumen(url: str, titulo: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=url, categoria=CATEGORIA,
                                      tipo_documento="resumen", titulo=titulo)


def _yaml_recurso(recurso: dict, url_resumen: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=recurso.get("url", ""), categoria=CATEGORIA,
                                      tipo_documento="recurso", tipo_recurso=TIPO_RECURSO,
                                      resumen=url_resumen, seccion=SECCION, titulo=recurso.get("titulo", ""),
                                      descripcion=recurso.get("descripcion", ""))


# ==========================================================
# 1. Extraccion del listado (JSON)
# ==========================================================

def extraer_servicios(url: str = SERVICIOS_URL) -> dict:
    respuesta = requests.get(url, headers=HEADERS, timeout=30)
    respuesta.raise_for_status()
    soup = BeautifulSoup(respuesta.text, "html.parser")

    contenedor_principal = soup.find(id="smooth-wrapper") or soup.find("main") or soup.body
    if contenedor_principal is None:
        raise Exception("No se ha encontrado el contenedor principal de la página.")

    recursos = []
    for enlace in contenedor_principal.find_all("a", href=True):
        href = enlace.get("href", "")
        if "/entidades/" not in href:
            continue

        titulo = limpiar_texto(enlace.get_text(" ", strip=True))
        descripcion = limpiar_texto(enlace.get("title", ""))
        url_recurso = ml.normalizar_url(href, url)

        if not titulo or not ml.es_url_valida(url_recurso):
            continue

        recursos.append(ml.crear_elemento(titulo=titulo, descripcion=descripcion, url=url_recurso, tipo="recurso", url_base=url))

    recursos = ml.deduplicar_lista(recursos, clave="url")

    seccion = ml.crear_seccion("Servicios universitarios", "servicios_universitarios")
    seccion["elementos"] = recursos

    print("Total de recursos encontrados:", len(recursos))
    print("Total esperado:", TOTAL_ESPERADO)
    if len(recursos) < TOTAL_ESPERADO:
        print(
            "AVISO: esta página carga el resto de resultados mediante JavaScript "
            "('Cargar más resultados'). requests/BeautifulSoup no ejecutan ese "
            "JavaScript, así que solo se han recogido los servicios presentes en "
            "el HTML inicial."
        )

    return {"titulo": "Servicios universitarios", "url": url, "tipo": "padre", "secciones": [seccion]}


def guardar_json(datos: dict, ruta: Path = SERVICIOS_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


# ==========================================================
# 2. Limpieza del JSON: descartar entradas que no son ficha
#    real de servicio, dedup por codigo de entidad
# ==========================================================

PATRON_FICHA_SERVICIO = re.compile(r".+\s-\s\([A-Za-z0-9]+\)\s*$")


def es_ficha_real_de_servicio(elemento: dict) -> bool:
    return bool(PATRON_FICHA_SERVICIO.match(elemento.get("titulo", "").strip()))


def codigo_entidad(url: str) -> str:
    m = re.search(r"/entidades/([A-Za-z0-9_\-]+)/?", url)
    return m.group(1).upper() if m else url


def limpiar_json_servicios(datos: dict) -> dict:
    seccion = datos["secciones"][0]
    elementos_originales = seccion["elementos"]

    elementos_validos = [e for e in elementos_originales if es_ficha_real_de_servicio(e)]
    elementos_descartados = [e for e in elementos_originales if not es_ficha_real_de_servicio(e)]

    elementos_limpios = []
    codigos_vistos = set()
    for elemento in elementos_validos:
        codigo = codigo_entidad(elemento["url"])
        if codigo in codigos_vistos:
            continue
        codigos_vistos.add(codigo)
        elementos_limpios.append(elemento)

    seccion["elementos"] = elementos_limpios

    print("Elementos originales en el JSON:", len(elementos_originales))
    print("Descartados (no son ficha real de servicio):", len(elementos_descartados))
    for e in elementos_descartados:
        print(f"  - {e['titulo']}  ->  {e['url']}")
    print("Servicios finales a procesar:", len(elementos_limpios))

    return datos


# ==========================================================
# 3. Generacion de Markdown -- especificos de servicios
# ==========================================================

def es_directorio_generico_de_personas(href: str) -> bool:
    """'sic_per.Busca_Persona' se usa tanto para el Directorio generico
    de toda la UPV (sin parametros de entidad, ruido) como para el
    "Equipo directivo" de una entidad concreta (con P_SG=.../
    P_CARGOS=..., contenido real que no se descarta)."""
    if "sic_per.Busca_Persona" not in href:
        return False
    return "P_SG=" not in href and "P_CARGOS=" not in href


def es_variante_de_la_misma_pagina(href_absoluta: str, url_pagina: str) -> bool:
    """En la plantilla antigua, el propio menu lateral incluye un enlace
    con el nombre de la entidad que apunta a un simple alias de la misma
    pagina (ej. 'indexc.html' junto a 'index-es.html')."""
    if codigo_entidad(href_absoluta) != codigo_entidad(url_pagina):
        return False
    return bool(re.search(r"/index\w*\.html?$", href_absoluta, flags=re.IGNORECASE))


def resolver_url_menu_antiguo(url_absoluta: str) -> str:
    """La plantilla antigua usa enlaces tipo
    '.../menu_urlc.html?//www.upv.es/pls/oalu/...': la URL real va
    incrustada en la query string tras '?//'. requests no ejecuta el
    JavaScript que la resuelve, asi que hay que extraerla a mano."""
    m = re.search(r"menu_url\w*\.html\?(//.+)$", url_absoluta, flags=re.IGNORECASE)
    if not m:
        return url_absoluta
    interno = m.group(1)
    if interno.startswith("//"):
        interno = "https:" + interno
    return interno


def extraer_texto_y_url_de_linea_markdown(linea: str) -> tuple[str | None, str | None]:
    m = re.match(r"^\[([^\]]*)\]\(([^)]+)\)$", linea.strip())
    if not m:
        return None, None
    return m.group(1), m.group(2)


def es_autorreferencia_o_accesibilidad(linea: str, url_pagina: str) -> bool:
    """Descarta lineas que son solo un enlace de accesibilidad (texto de
    1-2 caracteres, ej. "a"/"A") o una autorreferencia a la misma pagina
    con otro nombre."""
    texto, href = extraer_texto_y_url_de_linea_markdown(linea)
    if href is None:
        return False
    if len(texto.strip()) <= 2:
        return True
    return es_variante_de_la_misma_pagina(href, url_pagina)


# Patrones de URL que nunca aportan contenido propio de la entidad:
# selectores de idioma, accesibilidad, buscador generico, plano...
PATRONES_URL_EXCLUIDOS_HIJOS = [
    r"/bin2/tipoacc/",
    r"sic_mag\.MetaBus",
    r"/plano/plano-2d",
    r"/otros/como-llegar",
    r"index-va\.html?$",
    r"index-en\.html?$",
    r"index-i\.html?$",
    r"index-v\.html?$",
    r"/otros/accesibilidad",
    r"/otros/mapa-web",
    r"/otros/contacto",
]

TEXTOS_EXCLUIDOS_HIJOS = {
    "valencia", "valencia language", "valencian", "english",
    "castellano", "cercar", "search", "directory", "directori",
    "contacte", "contact", "idioma", "language", "idioma language",
}

# En la plantilla antigua, estos SI llevan a contenido real de la
# entidad -- se priorizan para no gastar el cupo de enlaces hijos en
# autorreferencias u otro ruido de plantilla.
TEXTOS_PRIORITARIOS_HIJOS = [
    "informacion general", "quienes somos", "presentacion",
    "equipo directivo", "webs relacionadas", "servicios",
    "tramites", "memoria", "funciones", "organigrama",
]


def es_enlace_hijo_util(texto: str, href: str, url_pagina: str) -> bool:
    texto_normalizado = ml.normalizar_para_comparar(texto)

    if len(texto.strip()) <= 2:
        return False
    if texto_normalizado in TEXTOS_BOILERPLATE_SERVICIOS:
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
        lineas = ml.limpiar_lineas_finales(lineas, textos_boilerplate=TEXTOS_BOILERPLATE_SERVICIOS)
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
        lineas_contenido = ml.limpiar_lineas_finales(lineas_contenido, textos_boilerplate=TEXTOS_BOILERPLATE_SERVICIOS)
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

        markdown = f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n{bloque_descripcion}{markdown_contenido}\n"

        ruta_archivo = carpeta / ml.nombre_archivo_markdown(titulo)
        with open(ruta_archivo, "w", encoding="utf-8") as archivo:
            archivo.write(markdown)
        print(f"  OK: {ruta_archivo}")
        return True

    except Exception as error:
        print(f"  ERROR: {error}")
        return False


def generar_markdowns_recursos(datos: dict, carpeta: Path = SERVICIOS_DIR) -> tuple[int, int, int]:
    carpeta.mkdir(parents=True, exist_ok=True)
    seccion = datos["secciones"][0]
    url_resumen = datos.get("url", SERVICIOS_URL)

    total = correctos = errores = 0
    for recurso in seccion["elementos"]:
        total += 1
        if generar_markdown_recurso(recurso, carpeta, url_resumen):
            correctos += 1
        else:
            errores += 1

    return total, correctos, errores


# ==========================================================
# 4. Markdown de la pagina padre (listado)
#
# La pagina indice incrusta el listado de servicios en el mismo
# contenedor que el texto descriptivo: se filtran los enlaces a
# /entidades/... (ya son documentos propios) y el texto del widget de
# filtros de esta pagina en concreto.
# ==========================================================

FILTROS_LISTADO_SERVICIOS = {
    "volver a resultados", "filtrar por", "fundaciones upv",
    "servicios generales", "filtrar", "buscar por palabras",
    "necesitas escribir un minimo de 3 caracteres",
    "cargar mas resultados", "resultados",
}


def es_enlace_a_entidad(linea: str) -> bool:
    return bool(re.search(r"\]\(https?://(www\.)?upv\.es/entidades/", linea))


def es_ruido_listado_servicios(linea: str) -> bool:
    if es_enlace_a_entidad(linea):
        return True

    texto_plano = re.sub(r"^#+\s*", "", linea)
    texto_plano = re.sub(r"^-\s*", "", texto_plano)
    normalizado = ml.normalizar_para_comparar(texto_plano)

    if normalizado in FILTROS_LISTADO_SERVICIOS:
        return True
    if re.match(r"^mostrando resultados de", normalizado):
        return True
    return False


def generar_markdown_padre_servicios(url: str = SERVICIOS_URL, ruta: Path = SERVICIOS_MD_PADRE) -> str:
    soup, es_html = ml.descargar_soup(url, headers=HEADERS)
    soup = ml.limpiar_contenido_html(soup)

    contenedor = soup.find(id="smooth-wrapper") or soup.find("main") or soup.body
    if contenedor is None:
        raise Exception("No se ha encontrado el contenedor principal.")

    lineas = ml.extraer_bloques_contenido(contenedor, url)
    lineas = ml.limpiar_lineas_finales(lineas, textos_boilerplate=TEXTOS_BOILERPLATE_SERVICIOS)
    lineas = [linea for linea in lineas if not es_ruido_listado_servicios(linea)]
    lineas = ml.deduplicar_global(lineas)

    yaml_metadatos = _yaml_resumen(url, "Servicios universitarios")
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
    datos = extraer_servicios()
    guardar_json(datos)
    datos = limpiar_json_servicios(datos)
    guardar_json(datos)
    generar_markdown_padre_servicios()
    total, correctos, errores = generar_markdowns_recursos(datos)
    print(f"Servicios: {total} · generados: {correctos} · errores: {errores}")


if __name__ == "__main__":
    main()
