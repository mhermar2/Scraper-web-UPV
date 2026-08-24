"""Extractor de "PTGAS, PDI y PI" (comunidad_upv/ptgas_pdi_pi).

Segunda sección de la categoría `comunidad_upv`, hueco vacío del sitemap
sin extractor previo. Mismo patrón exacto que `comunidad_upv/estudiante`:
la página real
(`/perfiles/ptgas-pdi-pi/index-es.html`) agrupa sus enlaces bajo 4 `<h2>`
reales sin texto propio salvo una línea de introducción -- "Herramientas
y recursos", "Asuntos propios", "Enlaces de interés", "Organizaciones
sindicales" -- cada uno se convierte en una carpeta, un `.md` por enlace
(mismo estándar que institución/servicios/admisión/estudiante: se sigue
el contenido real de cada página enlazada, no solo un índice).

`dividir_bloques_h2()`/`separar_texto_y_enlaces()` y
`SUBDOMINIOS_FUERA_DE_ALCANCE` ya no son utilidades locales de
`extrae_estudiante.py`: promovidas a `motor_limpieza.py` con este
extractor (segundo sitio real que las necesita, tal y como preveía el
docstring de `extrae_estudiante.py`), sin tocar ese módulo ya comiteado.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/ (config.py, common.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # src/extractores/ (motor_limpieza.py)

from bs4 import BeautifulSoup, Comment
import requests

from config import PTGAS_PDI_PI_CARPETAS, PTGAS_PDI_PI_DIR, PTGAS_PDI_PI_JSON, PTGAS_PDI_PI_URL
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
CATEGORIA = "comunidad_upv"
NIVEL = "ptgas_pdi_pi"
TIPO_RECURSO = "informacion"

TEXTOS_BOILERPLATE_PTGAS = ml.TEXTOS_BOILERPLATE_BASE | ml.TEXTOS_BOILERPLATE_PLANTILLA_CLASICA

UMBRAL_PALABRAS_POCO_CONTENIDO = 60
MAX_ENLACES_HIJOS = 5
MAX_CARACTERES_FRAGMENTO_HIJO = 800

# <h2> reales de /perfiles/ptgas-pdi-pi/index-es.html -> id de seccion/carpeta.
# "Tu espacio profesional en la UPV" (solo miga de pan, sin enlaces
# reales) y "¡Esto te interesa!" (cortado por recortar_en_titulo_plantilla)
# se ignoran a proposito, no estan en este diccionario.
SECCIONES_INDEX = {
    "Herramientas y recursos": "herramientas_recursos",
    "Asuntos propios": "asuntos_propios",
    "Enlaces de interés": "enlaces_interes",
    "Organizaciones sindicales": "organizaciones_sindicales",
}


def limpiar_pagina(soup: BeautifulSoup) -> BeautifulSoup:
    """No se decompone <header> globalmente -- mismo motivo que
    comunidad_upv/estudiante y orientacion: alguna pagina enlazada puede
    envolver su <h1> real en un <header class="entry-header"> de
    articulo."""
    for tag in soup.find_all(["script", "style", "noscript", "svg"]):
        tag.decompose()
    for comentario in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comentario.extract()
    return soup


def _yaml_resumen() -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=PTGAS_PDI_PI_URL, categoria=CATEGORIA,
                                      nivel=NIVEL, tipo_documento="resumen", titulo="PTGAS, PDI y PI")


def _yaml_recurso(recurso: dict, seccion_id: str) -> str:
    return ml.generar_yaml_metadatos(
        fuente=FUENTE, url=recurso.get("url", ""), categoria=CATEGORIA, nivel=NIVEL,
        tipo_documento="recurso", tipo_recurso=TIPO_RECURSO,
        resumen=PTGAS_PDI_PI_URL, seccion=seccion_id, titulo=recurso.get("titulo", ""))


# ==========================================================
# 1. Catalogo (JSON)
# ==========================================================

def extraer_lineas_pagina(url: str) -> list[str]:
    soup, es_html = ml.descargar_soup(url, headers=HEADERS)
    if not es_html:
        raise Exception(f"No se pudo descargar como HTML: {url}")
    soup = limpiar_pagina(soup)
    contenedor = soup.find(id="smooth-wrapper") or soup.find("main")
    if contenedor is None:
        raise Exception(f"No se ha encontrado el contenedor principal en {url}")
    ml.reemplazar_tablas_por_listas(soup, contenedor)
    lineas = ml.extraer_bloques_contenido(contenedor, url)
    return ml.limpiar_lineas_finales(lineas, textos_boilerplate=TEXTOS_BOILERPLATE_PTGAS)


def extraer_catalogo() -> dict:
    lineas_index = extraer_lineas_pagina(PTGAS_PDI_PI_URL)
    bloques_index = ml.dividir_bloques_h2(lineas_index)

    secciones = []
    for bloque in bloques_index:
        seccion_id = SECCIONES_INDEX.get(bloque["titulo"] or "")
        if seccion_id is None:
            continue

        _, enlaces = ml.separar_texto_y_enlaces(bloque["lineas"])
        elementos = [ml.crear_elemento(titulo=t, url=u, tipo="recurso") for t, u in enlaces]
        elementos = ml.deduplicar_lista(elementos, clave="url")

        seccion = ml.crear_seccion(bloque["titulo"], seccion_id)
        seccion["id"] = seccion_id
        seccion["elementos"] = elementos
        secciones.append(seccion)
        print(f"[{bloque['titulo']}] {len(elementos)} enlaces")

    return {"titulo": "PTGAS, PDI y PI", "url": PTGAS_PDI_PI_URL, "secciones": secciones}


def guardar_json(catalogo: dict, ruta: Path = PTGAS_PDI_PI_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(catalogo, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


# ==========================================================
# 2. Markdown de cada recurso enlazado (mismo patron heterogeneo que
#    institucion/servicios/estudiante: moderno / clasico con iframe /
#    PDF / subdominio fuera de alcance / otro)
# ==========================================================

def obtener_enlaces_hijos(contenedor, url_pagina: str, maximo: int = MAX_ENLACES_HIJOS,
                           excluir: set[str] = frozenset()) -> list[tuple[str, str]]:
    enlaces, urls_vistas = [], set(excluir)
    for a in contenedor.find_all("a", href=True):
        href = a["href"]
        if not ml.es_url_valida_para_expandir(href, url_pagina, urls_vistas):
            continue
        absoluta = urljoin(url_pagina, href).split("#")[0]
        if ml.es_subdominio_fuera_de_alcance(absoluta):
            continue
        texto = ml.extraer_texto_limpio(a)
        if not texto:
            continue
        urls_vistas.add(absoluta)
        enlaces.append((texto, absoluta))
        if len(enlaces) >= maximo:
            break
    return enlaces


def resumir_pagina_hija(url: str) -> str | None:
    try:
        soup, es_html = ml.descargar_soup(url, headers=HEADERS)
        if not es_html:
            return None
        soup = limpiar_pagina(soup)
        contenedor = soup.find(id="smooth-wrapper") or soup.find("main") or soup.body
        if contenedor is None:
            return None
        ml.reemplazar_tablas_por_listas(soup, contenedor)
        lineas = ml.limpiar_lineas_finales(ml.extraer_bloques_contenido(contenedor, url),
                                            textos_boilerplate=TEXTOS_BOILERPLATE_PTGAS)
        fragmento = "\n\n".join(lineas)
        if len(fragmento) > MAX_CARACTERES_FRAGMENTO_HIJO:
            fragmento = fragmento[:MAX_CARACTERES_FRAGMENTO_HIJO].rstrip() + "…"
        return fragmento or None
    except Exception:
        return None


def extraer_contenido_iframe_clasico(soup: BeautifulSoup, url_pagina: str) -> tuple[list[str], str | None]:
    iframe_url = ml.buscar_iframe_contenido_clasico(soup, url_pagina)
    if iframe_url is None:
        return [], None
    soup_iframe, es_html = ml.descargar_soup(iframe_url, headers=HEADERS)
    if not es_html:
        return [], iframe_url
    soup_iframe = ml.limpiar_contenido_html(soup_iframe)
    contenido_iframe = soup_iframe.find(id="contenido") or soup_iframe.body
    if contenido_iframe is None:
        return [], iframe_url
    ml.reemplazar_tablas_por_listas(soup_iframe, contenido_iframe)
    lineas = ml.extraer_bloques_contenido(contenido_iframe, iframe_url)
    lineas = ml.limpiar_lineas_finales(lineas, textos_boilerplate=TEXTOS_BOILERPLATE_PTGAS, recortar_h1=False)
    return lineas, iframe_url


def markdown_recurso_no_html(yaml_metadatos: str, titulo: str, url: str, tipo: str, contenido_pdf: bytes | None) -> str:
    if tipo == "pdf":
        paginas = ml.extraer_texto_pdf(contenido_pdf)
        if paginas:
            return f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n" + "\n\n".join(paginas) + "\n"
        return (
            f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n"
            "_PDF sin texto extraíble (probablemente escaneado sin OCR). "
            "Consulta el contenido directamente en la URL indicada._\n"
        )
    return (
        f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n"
        "_Este recurso no es una página HTML ni un PDF estándar "
        "(por ejemplo, un formulario dinámico o un portal externo con inicio de sesión). "
        "Consulta el contenido directamente en la URL indicada._\n"
    )


def generar_markdown_recurso(recurso: dict, carpeta: Path, seccion_id: str, nombres_usados: set[str]) -> bool:
    titulo, url = recurso.get("titulo", ""), recurso.get("url", "")
    if not titulo or not url:
        return False

    print(f"  Extrayendo: {titulo} ({url})")
    try:
        yaml_metadatos = _yaml_recurso(recurso, seccion_id)
        nombre = ml.nombre_archivo_sin_colision(titulo, nombres_usados, desambiguador=seccion_id)

        if ml.es_subdominio_fuera_de_alcance(url):
            markdown = (
                f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n"
                "_Este enlace lleva a un subdominio con aplicación dinámica que requiere "
                "sesión de usuario (intranet, PoliformaT, automatrícula...), sin contenido "
                "real accesible sin iniciar sesión. Consulta el contenido directamente en "
                "la URL indicada._\n"
            )
            with open(carpeta / nombre, "w", encoding="utf-8") as archivo:
                archivo.write(markdown)
            print(f"  OK (fuera de alcance, solo nota): {carpeta / nombre}")
            return True

        respuesta = requests.get(url, headers=HEADERS, timeout=30)
        respuesta.raise_for_status()
        tipo = ml.tipo_contenido(respuesta.headers.get("Content-Type", ""))

        if tipo != "html":
            markdown = markdown_recurso_no_html(yaml_metadatos, titulo, url, tipo, respuesta.content)
            with open(carpeta / nombre, "w", encoding="utf-8") as archivo:
                archivo.write(markdown)
            print(f"  OK ({tipo}): {carpeta / nombre}")
            return True

        soup = BeautifulSoup(respuesta.text, "html.parser")
        soup = limpiar_pagina(soup)
        contenedor_moderno = soup.find(id="smooth-wrapper") or soup.find("main")
        contenido = contenedor_moderno or soup.find(id="contenido") or soup.body
        if contenido is None:
            print("  AVISO: no se ha encontrado contenido.")
            return False

        lineas_iframe, iframe_url = ([], None) if contenedor_moderno is not None else extraer_contenido_iframe_clasico(soup, url)

        ml.reemplazar_tablas_por_listas(soup, contenido)
        lineas_contenido = ml.limpiar_lineas_finales(ml.extraer_bloques_contenido(contenido, url),
                                                       textos_boilerplate=TEXTOS_BOILERPLATE_PTGAS)
        lineas_contenido = lineas_iframe + lineas_contenido
        lineas_contenido = ml.quitar_titulos_redundantes(lineas_contenido, titulo)
        if not lineas_contenido:
            print("  AVISO: contenido vacío.")
            return False

        if ml.contar_palabras(lineas_contenido) < UMBRAL_PALABRAS_POCO_CONTENIDO:
            excluir = {iframe_url} if iframe_url else set()
            enlaces_hijos = obtener_enlaces_hijos(contenido, url, excluir=excluir)
            if enlaces_hijos:
                lineas_contenido.append("## Información relacionada")
                for texto_enlace, url_hija in enlaces_hijos:
                    time.sleep(0.5)
                    fragmento = resumir_pagina_hija(url_hija)
                    lineas_contenido.append(f"### {texto_enlace}")
                    lineas_contenido.append(f"**URL:** {url_hija}")
                    if fragmento:
                        lineas_contenido.append(fragmento)

        markdown = f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n" + "\n\n".join(lineas_contenido) + "\n"
        with open(carpeta / nombre, "w", encoding="utf-8") as archivo:
            archivo.write(markdown)
        print(f"  OK: {carpeta / nombre}")
        return True

    except Exception as error:
        print(f"  ERROR: {error}")
        return False


def generar_markdowns_recursos(catalogo: dict, catalogo_anterior: dict[str, list[dict]] | None = None,
                                carpetas: dict[str, Path] = PTGAS_PDI_PI_CARPETAS) -> tuple[int, int, int]:
    catalogo_anterior = catalogo_anterior or {}
    total = correctos = errores = 0

    for seccion in catalogo["secciones"]:
        seccion_id = seccion["id"]
        carpeta = carpetas[seccion_id]
        carpeta.mkdir(parents=True, exist_ok=True)
        print(f"[{seccion['titulo']}]")

        nombres_usados: set[str] = set()
        elementos_escritos = []
        for recurso in seccion["elementos"]:
            total += 1
            if generar_markdown_recurso(recurso, carpeta, seccion_id, nombres_usados):
                correctos += 1
                elementos_escritos.append(recurso)
            else:
                errores += 1
            time.sleep(0.3)

        ml.limpiar_ficheros_renombrados(catalogo_anterior.get(seccion_id, []), elementos_escritos, carpeta)

    return total, correctos, errores


# ==========================================================
# 3. Markdown resumen (indice)
# ==========================================================

def generar_markdown_resumen(catalogo: dict) -> str:
    cuerpo = (
        "Punto de entrada de la web de la UPV dirigido al personal (PTGAS/PAS, PDI y PI): "
        "herramientas y recursos del día a día, gestiones de asuntos propios, enlaces de "
        "interés a organismos externos y organizaciones sindicales con representación en "
        "la UPV. Cada apartado remite a las páginas reales enlazadas desde la web oficial "
        'de "PTGAS, PDI y PI", agrupadas en las carpetas de abajo.'
    )
    filas = "\n".join(
        f"- **{seccion['titulo']}** — {len(seccion['elementos'])} recursos (carpeta `{seccion['id']}/`)"
        for seccion in catalogo["secciones"]
    )
    return f"{_yaml_resumen()}\n# PTGAS, PDI y PI\n\n{cuerpo}\n\n{filas}\n"


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    catalogo_anterior = ml.cargar_catalogo_anterior(PTGAS_PDI_PI_JSON)
    catalogo = extraer_catalogo()
    guardar_json(catalogo)

    PTGAS_PDI_PI_DIR.mkdir(parents=True, exist_ok=True)
    with open(PTGAS_PDI_PI_DIR / "ptgas_pdi_pi.md", "w", encoding="utf-8") as archivo:
        archivo.write(generar_markdown_resumen(catalogo))

    total, correctos, errores = generar_markdowns_recursos(catalogo, catalogo_anterior=catalogo_anterior)
    print(f"PTGAS, PDI y PI: {total} recursos · generados: {correctos} · errores: {errores}")


if __name__ == "__main__":
    main()
