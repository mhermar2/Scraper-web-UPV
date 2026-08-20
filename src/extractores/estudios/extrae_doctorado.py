"""Extractor de Doctorado UPV (estudios/doctorado).

Reescritura completa que sustituye las dos etapas anteriores
(sacar_json_doctorado.py + extrae_doctorado.py, movidas a legacy) por un
unico modulo, siguiendo el patron de institucion (motor de limpieza
comun + metadatos YAML definitivos) en vez de markdownify con logica de
hero/iframe Oracle.

Esa logica especial (extraer_hero_metadata sobre ".seccion01hero",
seguir_iframe_oracle sobre "pls/oalu") ya no aplica: el microsite
edoctorado.upv.es se rediseno desde que se escribio el notebook
original (comprobado contra la web real, ninguno de esos dos selectores
aparece ya en el HTML) y ahora usa la misma plantilla WordPress
"entry-content"/"<main>" que el resto de microsites de entidad UPV. El
notebook original tambien asumia siempre las mismas dos secciones fijas
("Inicio"/"Admision") con URLs fijas; la pagina actual de cada programa
enlaza a un numero variable de subpaginas (informacion de acceso,
organizacion, actividades formativas, resultados, verificacion...) via
bloques ".wp-block-upv-enlace" -- se siguen los que haya en cada
programa en vez de asumir una lista fija.

`rama` (uno de los campos exclusivos de fichas de titulacion en
estudios/doctorado, ver las notas internas del proyecto) sale de cruzar cada programa con las
paginas de "ambito de investigacion" del menu (Agroalimentacion y
Biotecnologia, Arquitectura, Arte, Ciencias...), que sí listan los
programas por area de forma real. `acronimo`/`campus`/`modalidad`/
`centro` NO se rellenan: a diferencia de admision/master (que sale de un
catalogo JSON con esas facetas), esta pagina no expone esa informacion
de forma estructurada por programa -- un programa participa de varias
estructuras de investigacion y departamentos a la vez (ver "Estructuras
de Investigacion participantes"), asi que forzar un unico `centro` seria
inventar un dato que la fuente no da. Mejor omitir el campo que rellenar
con un valor no verificable.
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
from config import DOCTORADOS_JSON, DOCTORADOS_KB_DIR, DOCTORADOS_MD_PADRE, DOCTORADOS_URL_RAIZ
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

BASE_URL = "https://www.upv.es"

# Menu "Programas de Doctorado" > "Listado por ambitos de investigacion"
# del propio microsite -- unica fuente real de "rama" por programa.
AMBITOS_URL = {
    "Agroalimentación y Biotecnología": "https://www.upv.es/entidades/edoctorado/agroalimentacion-y-biotecnologia/",
    "Arquitectura": "https://www.upv.es/entidades/edoctorado/arquitectura/",
    "Arte": "https://www.upv.es/entidades/edoctorado/arte/",
    "Ciencias": "https://www.upv.es/entidades/edoctorado/ciencias/",
    "Economía y Ciencias Sociales": "https://www.upv.es/entidades/edoctorado/economia-y-ciencias-sociales/",
    "Ingeniería Civil": "https://www.upv.es/entidades/edoctorado/ingenieria-civil/",
    "Ingeniería Industrial": "https://www.upv.es/entidades/edoctorado/ingenieria-industrial/",
    "TIC": "https://www.upv.es/entidades/edoctorado/tic/",
}

FUENTE = "UPV"
CATEGORIA = "estudios"
NIVEL = "doctorado"
TIPO_RECURSO = "informacion"
SECCION = "doctorado"

UMBRAL_PALABRAS_POCO_CONTENIDO = 60


def _yaml_resumen(url: str, titulo: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=url, categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="resumen", titulo=titulo)


def _yaml_recurso(item: dict, url_resumen: str) -> str:
    campos_extra = {"rama": item["rama"]} if item.get("rama") else None
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=item["url"], categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="recurso", tipo_recurso=TIPO_RECURSO,
                                      resumen=url_resumen, seccion=SECCION, titulo=item["nombre"],
                                      campos_extra=campos_extra)


# ==========================================================
# 1. Catalogo (indice + ambitos para la rama)
# ==========================================================

def extraer_catalogo(url_indice: str = DOCTORADOS_URL_RAIZ) -> list[dict]:
    respuesta = requests.get(url_indice, headers=HEADERS, timeout=30)
    respuesta.raise_for_status()
    soup = BeautifulSoup(respuesta.text, "html.parser")

    contenedor = soup.find("main") or soup.body
    recursos = []
    for enlace in contenedor.find_all("a", href=True):
        nombre = limpiar_texto(enlace.get_text(" ", strip=True))
        if not ml.normalizar_para_comparar(nombre).startswith("programa de doctorado"):
            continue
        url = ml.normalizar_url(enlace["href"], BASE_URL)
        if not ml.es_url_valida(url):
            continue
        recursos.append(ml.crear_elemento(titulo=nombre, url=url, tipo="recurso", url_base=BASE_URL))

    recursos = ml.deduplicar_lista(recursos, clave="url")
    print("Programas de doctorado encontrados:", len(recursos))
    return [{"nombre": r["titulo"], "url": r["url"], "rama": ""} for r in recursos]


def asignar_ramas(items: list[dict], ambitos: dict[str, str] = AMBITOS_URL) -> list[dict]:
    """Cruza cada programa con las paginas de ambito de investigacion
    para saber su rama -- unica fuente real de ese dato (ver cabecera)."""
    urls_a_item = {item["url"]: item for item in items}

    for rama, url_ambito in ambitos.items():
        try:
            respuesta = requests.get(url_ambito, headers=HEADERS, timeout=30)
            respuesta.raise_for_status()
        except Exception as error:
            print(f"  AVISO: no se pudo leer ámbito '{rama}': {error}")
            continue

        soup = BeautifulSoup(respuesta.text, "html.parser")
        contenedor = soup.find("main") or soup.body
        for enlace in contenedor.find_all("a", href=True):
            if not ml.normalizar_para_comparar(enlace.get_text(" ", strip=True)).startswith("programa de doctorado"):
                continue
            url = ml.normalizar_url(enlace["href"], BASE_URL)
            item = urls_a_item.get(url)
            if item is not None:
                item["rama"] = rama

    sin_rama = sum(1 for item in items if not item["rama"])
    if sin_rama:
        print(f"AVISO: {sin_rama} programa(s) sin rama asignada (no aparecen en ningún ámbito).")
    return items


def guardar_json(items: list[dict], ruta: Path = DOCTORADOS_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"programas": items}, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


# ==========================================================
# 2. Markdown por programa
# ==========================================================

def limpiar_pagina_programa(soup: BeautifulSoup) -> BeautifulSoup:
    """No se puede reusar ml.limpiar_contenido_html() tal cual: esta
    plantilla WordPress envuelve el <h1> del articulo en un propio
    <header class="entry-header"> (distinto del <header id="masthead">
    del menu del sitio) -- decompose(["header"]) global se lo llevaria
    por delante. Al escoger <main> como contenedor ya quedan fuera el
    menu/pie del sitio, asi que no hace falta ese filtro aqui."""
    for tag in soup.find_all(["script", "style", "noscript", "svg"]):
        tag.decompose()
    for tag in soup.select(".social-sharer"):
        tag.decompose()
    return soup


def extraer_enlaces_subpaginas(contenido) -> list[tuple[str, str]]:
    """Cada programa enlaza a un numero variable de subpaginas propias
    via bloques ".wp-block-upv-enlace" (antes asumido fijo: "Inicio" +
    "Admision", ver cabecera del modulo)."""
    enlaces = []
    for bloque in contenido.select(".wp-block-upv-enlace"):
        a = bloque.find("a", href=True)
        if a is None:
            continue
        texto = limpiar_texto(a.get_text(" ", strip=True))
        url = ml.normalizar_url(a["href"], BASE_URL)
        if texto and ml.es_url_valida(url):
            enlaces.append((texto, url))
    return enlaces


def extraer_contenido_pagina(url: str) -> list[str] | None:
    soup, es_html = ml.descargar_soup(url, headers=HEADERS)
    if not es_html:
        return None
    soup = limpiar_pagina_programa(soup)
    contenido = soup.find("main") or soup.body
    if contenido is None:
        return None

    ml.reemplazar_tablas_por_listas(soup, contenido)
    lineas = ml.extraer_bloques_contenido(contenido, url)
    lineas = ml.limpiar_lineas_finales(lineas)
    return lineas


def generar_markdown_programa(item: dict, carpeta: Path, url_resumen: str) -> bool:
    titulo = item["nombre"]
    url = item["url"]

    print(f"  Extrayendo: {titulo} ({url})")

    try:
        soup, es_html = ml.descargar_soup(url, headers=HEADERS)
        yaml_metadatos = _yaml_recurso(item, url_resumen)

        if not es_html:
            print("  AVISO: no es HTML.")
            return False

        soup = limpiar_pagina_programa(soup)
        contenido = soup.find("main") or soup.body
        if contenido is None:
            print("  AVISO: no se ha encontrado contenido.")
            return False

        subpaginas = extraer_enlaces_subpaginas(contenido)

        ml.reemplazar_tablas_por_listas(soup, contenido)
        lineas_contenido = ml.extraer_bloques_contenido(contenido, url)
        lineas_contenido = ml.limpiar_lineas_finales(lineas_contenido)

        if not lineas_contenido:
            print("  AVISO: contenido vacío.")
            return False

        bloques = [lineas_contenido[0], f"**URL:** {url}"] + lineas_contenido[1:]

        for texto_enlace, url_sub in subpaginas:
            time.sleep(0.3)
            print(f"    -> {texto_enlace}: {url_sub}")
            lineas_sub = extraer_contenido_pagina(url_sub)
            bloques.append(f"## {texto_enlace}")
            if lineas_sub:
                # La subpagina repite su propio <h1> (ya cubierto por el
                # "##" de arriba) -- se descarta para no duplicar titulo.
                bloques.extend(lineas_sub[1:] if lineas_sub[0].startswith("#") else lineas_sub)
            else:
                bloques.append(f"_No se pudo obtener el contenido de esta subpágina. Consulta {url_sub}._")

        markdown = f"{yaml_metadatos}\n" + "\n\n".join(bloques) + "\n"

        ruta_archivo = carpeta / ml.nombre_archivo_markdown(titulo)
        with open(ruta_archivo, "w", encoding="utf-8") as archivo:
            archivo.write(markdown)
        print(f"  OK: {ruta_archivo}")
        return True

    except Exception as error:
        print(f"  ERROR: {error}")
        return False


def generar_markdowns_programas(items: list[dict], carpeta: Path = DOCTORADOS_KB_DIR,
                                 url_resumen: str = DOCTORADOS_URL_RAIZ) -> tuple[int, int, int]:
    carpeta.mkdir(parents=True, exist_ok=True)
    total = correctos = errores = 0
    for item in items:
        total += 1
        if generar_markdown_programa(item, carpeta, url_resumen):
            correctos += 1
        else:
            errores += 1
        time.sleep(0.3)
    return total, correctos, errores


def generar_markdown_padre(url: str = DOCTORADOS_URL_RAIZ, ruta: Path = DOCTORADOS_MD_PADRE) -> str:
    soup, es_html = ml.descargar_soup(url, headers=HEADERS)
    soup = limpiar_pagina_programa(soup)

    contenido = soup.find("main") or soup.body
    if contenido is None:
        raise Exception("No se ha encontrado <main>.")

    lineas = ml.extraer_bloques_contenido(contenido, url)
    lineas = ml.limpiar_lineas_finales(lineas)

    yaml_metadatos = _yaml_resumen(url, "Doctorado")
    markdown = f"{yaml_metadatos}\n" + "\n\n".join(lineas) + "\n"

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
    items = asignar_ramas(items)
    guardar_json(items)
    if limite is not None:
        items = items[:limite]
    total, correctos, errores = generar_markdowns_programas(items)
    print(f"Doctorado: {total} · generados: {correctos} · errores: {errores}")


if __name__ == "__main__":
    main()
