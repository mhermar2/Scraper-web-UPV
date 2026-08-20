"""Extractor de Formacion Permanente UPV (estudios/formacion_permanente).

Reescritura completa que sustituye las dos etapas anteriores
(sacar_json_formacion_permanente.py + extrae_formacion_permanente.py,
movidas a legacy) por un unico modulo, siguiendo el patron de
institucion/servicios/rankings: motor de limpieza comun +
metadatos YAML definitivos, en vez de markdownify sobre texto plano con
metadatos extraidos por regex.

cfp.upv.es usa una plantilla Bootstrap muy distinta de la WordPress de
upv.es (mucho widget/tabla), lo que exponia dos limitaciones reales del
motor de limpieza generico al probarlo aqui:
  - Las tablas HTML (precios, horarios, asignaturas...) se perdian en
    silencio: extraer_bloques_contenido() no recorre table/tr/td (no
    estan en TAGS_CANDIDATAS/TAGS_BLOQUE). Se soluciono anadiendo
    reemplazar_tablas_por_listas() a motor_limpieza.py -- convierte cada
    tabla en un <ul><li> equivalente antes del traversal, reutilizable
    por cualquier otra seccion que tenga el mismo problema.
  - El resto de la ficha (fechas, campus, modalidad, responsable) SI
    esta bien cubierto por el traversal generico porque vive en <li>/<p>
    sin bloques anidados -- no hizo falta logica especifica para eso,
    al contrario que la version anterior (regex sobre soup.get_text()
    de toda la pagina, que producia falsos positivos: p.ej. "ECTS: 2026"
    al capturar un curso academico suelto en vez de los creditos).
  - El total de ECTS del programa SI requiere un extra: solo aparece en
    el widget lateral ".service-block-vCFP" (fuera del contenedor de
    contenido principal), se saca aparte y se antepone como una linea.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/ (config.py, common.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # src/extractores/ (motor_limpieza.py)

from bs4 import BeautifulSoup
import requests

from common import limpiar_texto
from config import (
    FORMACION_PERMANENTE_JSON,
    FORMACION_PERMANENTE_KB_DIR,
    FORMACION_PERMANENTE_MD_PADRE,
    FORMACION_PERMANENTE_URL_RAIZ,
)
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

BASE_URL = "https://www.cfp.upv.es"

FUENTES = [
    ("cursos_online", "https://www.cfp.upv.es/formacion-permanente/online/formacion-online.html"),
    ("masters", "https://www.cfp.upv.es/formacion-permanente/masters/masters.html"),
]

ENLACES_BASURA = {"matriculable", "más información", "ver más", "acceder", "inscribirse"}

FUENTE = "UPV"
CATEGORIA = "estudios"
NIVEL = "formacion_permanente"

# Clasificacion de tipo -> tipo_recurso (slug, sin acentos, como el resto
# de valores de tipo_recurso del corpus).
TIPOS_RECURSO = [
    (r"m[aá]ster", "master"),
    (r"diploma de especializaci[oó]n", "diploma_especializacion"),
    (r"diploma de experto", "diploma_experto"),
    (r"diploma de extensi[oó]n", "diploma_extension"),
    (r"curso", "curso"),
]


def clasificar_tipo_recurso(nombre: str, origen: str = "") -> str:
    nombre_normalizado = nombre.lower()
    for patron, tipo in TIPOS_RECURSO:
        if re.search(patron, nombre_normalizado):
            return tipo
    # Muchos titulos de curso son solo el tema ("Excel avanzado"), sin la
    # palabra "curso" -- si no matcheo por titulo, caigo al origen (el
    # listado del que salio la ficha) antes que a un generico sin
    # informacion.
    if origen == "masters":
        return "master"
    if origen == "cursos_online":
        return "curso"
    return "oferta_formativa"


# Amplia el conjunto comun con el ruido propio de la plantilla Bootstrap
# de cfp.upv.es: pestanas de navegacion internas, pitch promocional
# repetido en cada ficha, leyendas de graficos vacios...
TEXTOS_BOILERPLATE_CFP = ml.TEXTOS_BOILERPLATE_BASE | {
    "registrarse", "iniciar sesion", "buscar formacion", "contacto",
    "precios", "observaciones al precio",
    "con la garantia y calidad de la upv", "upv", "condiciones especificas",
    "descargar informacion", "descarga en pdf la informacion de esta actividad",
    "consulta las condiciones especificas de la actividad",
    "quiero recibir informacion sobre esta actividad",
    "rellena el siguiente formulario y el responsable de la actividad se pondra en contacto contigo",
}

# El widget de cuenta atras se renderiza en servidor como ceros ("00
# horas, 00 minutos y 00 segundos.") y el boton de inscripcion viene
# duplicado (icono + texto se leen dos veces): mas robusto detectarlos
# por patron que meterlos en el set de boilerplate de textos exactos.
PATRON_CONTADOR_INSCRIPCION = re.compile(r"^\d{2} horas, \d{2} minutos y \d{2} segundos\.?$")


def es_ruido_ficha_cfp(linea: str) -> bool:
    if PATRON_CONTADOR_INSCRIPCION.match(linea.strip()):
        return True
    match_enlace = re.match(r"^\[([^\]]*)\]\([^)]+\)$", linea.strip())
    texto_plano = match_enlace.group(1) if match_enlace else linea
    normalizado = ml.normalizar_para_comparar(re.sub(r"^#+\s*", "", texto_plano))
    if normalizado.startswith("inscripcion"):
        return True
    if normalizado.startswith("la upv es una de las universidades mejor valorada"):
        return True
    return False


def _yaml_resumen(url: str, titulo: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=url, categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="resumen", titulo=titulo)


def _yaml_recurso(item: dict, url_resumen: str) -> str:
    tipo_recurso = clasificar_tipo_recurso(item["nombre"], origen=item["origen"])
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=item["url"], categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="recurso", tipo_recurso=tipo_recurso,
                                      resumen=url_resumen, seccion=item["origen"], titulo=item["nombre"])


# ==========================================================
# 1. Catalogo (listados de cursos/masteres)
# ==========================================================

def extraer_fichas(origen: str, url: str) -> list[dict]:
    """Enlaces a ficha de curso/master de una pagina de listado."""
    respuesta = requests.get(url, headers=HEADERS, timeout=30)
    respuesta.raise_for_status()
    soup = BeautifulSoup(respuesta.text, "html.parser")

    fichas = []
    for enlace in soup.find_all("a", href=True):
        href = enlace["href"]
        if "/formacion-permanente/curso/" not in href:
            continue

        nombre = limpiar_texto(enlace.get_text(" ", strip=True))
        if not nombre or ml.normalizar_para_comparar(nombre) in ENLACES_BASURA:
            continue

        url_ficha = ml.normalizar_url(href, BASE_URL)
        if not ml.es_url_valida(url_ficha):
            continue

        fichas.append(ml.crear_elemento(titulo=nombre, url=url_ficha, tipo="recurso", url_base=BASE_URL) | {"origen": origen})

    return fichas


def extraer_catalogo(fuentes: list[tuple[str, str]] = FUENTES) -> list[dict]:
    catalogo: dict[str, dict] = {}
    for origen, url in fuentes:
        fichas = extraer_fichas(origen, url)
        print(f"[{origen}] enlaces encontrados: {len(fichas)}")
        for ficha in fichas:
            catalogo.setdefault(ficha["url"], ficha)

    items = [{"nombre": f["titulo"], "url": f["url"], "origen": f["origen"]} for f in catalogo.values()]
    print("Total en catalogo (dedup por URL):", len(items))
    return items


def guardar_json(items: list[dict], ruta: Path = FORMACION_PERMANENTE_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"formaciones": items}, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


# ==========================================================
# 2. Markdown por ficha
# ==========================================================

def extraer_ects_totales(soup: BeautifulSoup) -> str | None:
    """El total de ECTS del programa solo aparece en el widget lateral
    '.service-block-vCFP' (fuera del contenedor de contenido principal,
    ver cabecera del modulo)."""
    widget = soup.find(class_="service-block-vCFP")
    if widget is None:
        return None
    for fila in widget.select(".service-in"):
        etiqueta = ml.extraer_texto_limpio(fila.find("small"))
        valor = ml.extraer_texto_limpio(fila.find("h4"))
        if etiqueta.lower() == "ects" and valor:
            return valor
    return None


PATRON_ID_CURSO = re.compile(r"_(\d+)\.html?$")


def nombre_archivo_curso(item: dict) -> str:
    """cfp.upv.es reutiliza el mismo titulo para ediciones/anos distintos
    de un mismo curso (URLs e IDs distintos, nombre identico) -- usar
    solo el titulo normalizado produce colisiones que se pisan entre si
    en silencio (comprobado: 14 de 304 items). El ID numerico al final
    de la URL es unico por ficha, se ancla siempre para garantizarlo."""
    id_curso = PATRON_ID_CURSO.search(item["url"])
    sufijo = f"_{id_curso.group(1)}" if id_curso else ""
    return ml.normalizar_identificador(item["nombre"]) + sufijo + ".md"


def limpiar_pagina_curso(soup: BeautifulSoup) -> BeautifulSoup:
    soup = ml.limpiar_contenido_html(soup)
    for tag in soup.find_all("form"):
        tag.decompose()
    for tag in soup.select(".funny-boxes, .anuncio-cfp, .tag-box-v6, .service-block-vCFP, .modal, #cfpModal"):
        tag.decompose()
    return soup


def generar_markdown_curso(item: dict, carpeta: Path, url_resumen: str) -> bool:
    titulo = item["nombre"]
    url = item["url"]

    print(f"  Extrayendo: {titulo} ({url})")

    try:
        soup, es_html = ml.descargar_soup(url, headers=HEADERS)
        yaml_metadatos = _yaml_recurso(item, url_resumen)

        if not es_html:
            markdown = (
                f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n"
                "_Este recurso no es una página HTML estándar. "
                "Consulta el contenido directamente en la URL indicada._\n"
            )
            ruta_archivo = carpeta / nombre_archivo_curso(item)
            with open(ruta_archivo, "w", encoding="utf-8") as archivo:
                archivo.write(markdown)
            print(f"  OK (no HTML): {ruta_archivo}")
            return True

        ects = extraer_ects_totales(soup)
        soup = limpiar_pagina_curso(soup)

        contenido = soup.select_one("div.container.content.profile") or soup.body
        if contenido is None:
            print("  AVISO: no se ha encontrado contenido.")
            return False

        ml.reemplazar_tablas_por_listas(soup, contenido)
        lineas_contenido = ml.extraer_bloques_contenido(contenido, url)
        lineas_contenido = ml.limpiar_lineas_finales(lineas_contenido, textos_boilerplate=TEXTOS_BOILERPLATE_CFP)
        lineas_contenido = [l for l in lineas_contenido if not es_ruido_ficha_cfp(l)]

        if not lineas_contenido:
            print("  AVISO: contenido vacío.")
            return False

        cabecera = lineas_contenido[:1]
        resto = lineas_contenido[1:]
        if ects:
            cabecera.append(f"**ECTS totales:** {ects}")

        markdown = f"{yaml_metadatos}\n" + "\n\n".join(cabecera + [f"**URL:** {url}"] + resto) + "\n"

        ruta_archivo = carpeta / nombre_archivo_curso(item)
        with open(ruta_archivo, "w", encoding="utf-8") as archivo:
            archivo.write(markdown)
        print(f"  OK: {ruta_archivo}")
        return True

    except Exception as error:
        print(f"  ERROR: {error}")
        return False


def generar_markdowns_cursos(items: list[dict], carpeta: Path = FORMACION_PERMANENTE_KB_DIR,
                              url_resumen: str = FORMACION_PERMANENTE_URL_RAIZ) -> tuple[int, int, int]:
    carpeta.mkdir(parents=True, exist_ok=True)
    total = correctos = errores = 0
    for item in items:
        total += 1
        if generar_markdown_curso(item, carpeta, url_resumen):
            correctos += 1
        else:
            errores += 1
        time.sleep(0.3)
    return total, correctos, errores


def generar_markdown_padre(url: str = FORMACION_PERMANENTE_URL_RAIZ, ruta: Path = FORMACION_PERMANENTE_MD_PADRE) -> str:
    """Pagina resumen de la seccion. cfp.upv.es/formacion-permanente es un
    home con carruseles muy ruidosos para el motor de limpieza generico;
    en vez de arrastrar ese ruido, se compone un resumen breve a mano con
    enlaces a los dos listados que sí se scrapean (masteres/diplomas y
    cursos online), igual de honesto y mucho mas util para el RAG."""
    yaml_metadatos = _yaml_resumen(url, "Formación permanente")
    markdown = (
        f"{yaml_metadatos}\n# Formación permanente\n\n**URL:** {url}\n\n"
        "Oferta de formación permanente de la UPV (títulos propios): másteres, "
        "diplomas de especialización/experto/extensión universitaria y cursos, "
        "gestionados por el Centro de Formación Permanente (cfp.upv.es).\n\n"
        f"- [Másteres y diplomas]({FUENTES[1][1]})\n"
        f"- [Cursos online]({FUENTES[0][1]})\n"
    )
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as archivo:
        archivo.write(markdown)
    print("OK: Markdown padre generado:", ruta)
    return markdown


# ==========================================================
# Ejecucion
# ==========================================================

def main(limite: int | None = None) -> None:
    generar_markdown_padre()
    items = extraer_catalogo()
    guardar_json(items)
    if limite is not None:
        items = items[:limite]
    total, correctos, errores = generar_markdowns_cursos(items)
    print(f"Formación permanente: {total} · generados: {correctos} · errores: {errores}")


if __name__ == "__main__":
    main()
