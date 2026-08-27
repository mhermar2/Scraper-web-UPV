"""Extractor de "Escuelas y facultades" (organizacion/escuelas_facultades).

Se decidio (ver notas de sesion 2026-08-23) NO intentar homogeneizar el
contenido real de cada centro: hay demasiada informacion y es demasiado
heterogenea (18 centros, al menos 3 plantillas/CMS distintos). La
alternativa fue remitir a la web de cada centro y, cuando existe, a su
mapa del sitio -- ese es exactamente el contenido que ya existia a mano
en escuelas.md (datos basicos) y sitemaps_escuelas.md (mapas de sitio de
15 centros, copiados y pegados a mano). Este extractor automatiza esa
misma idea con el mismo estandar que el resto de secciones
(metadatos YAML definitivos, JSON intermedio, generado por codigo en vez
de a mano) y fusiona ambos ficheros en uno solo por centro -- cada ficha
ya incluye su propio mapa del sitio, no hace falta un documento aparte.

Descubrimiento de la estructura real (sesion 2026-08-23, comprobado
contra la web real):

- El catalogo real NO es un JSON estatico (a diferencia de estudios/
  grado y estudios/master): es la propia pagina de listado
  (`ESCUELAS_URL`), HTML estatico normal. Agrupa los centros bajo
  encabezados <h2> "Campus de X" (Valencia/Alcoy/Gandia/Hangzhou) y
  "Centros adscritos", cada uno seguido de los <a href="/entidades/...">
  de sus centros -- se recorre el documento en orden y se usa el ultimo
  <h2> visto como campus del siguiente enlace, cortando en el titulo de
  plantilla "!Esto te interesa!" (boilerplate ya conocido, ver
  motor_limpieza.TITULOS_CORTE_PLANTILLA).
  IMPORTANTE: esta pagina trae 18 centros, no los 15 que tenia el
  escuelas.md anterior -- ademas de los 15 conocidos (12 en Vera + Alcoy
  + Gandia + Hangzhou) aparecen 3 "Centros adscritos" nuevos (Berklee-
  Valencia, Centro Universitario EDEM, Florida Universitaria) que no
  estaban documentados hasta ahora.
- Cada centro puede usar una de tres plantillas, sin patron por URL --
  hay que inspeccionar el HTML de cada uno:
    1. WordPress moderno (la mayoria, 12/18): tiene una pagina propia
       <web>/mapa-del-sitio/ con un arbol <ul class="sitemap"> de hasta
       3 niveles. Se seigue con motor_limpieza.extraer_arbol_sitemap_wp().
    2. Oracle Portal clasico (ETSII, algunos otros): sin esa pagina
       (404), pero su propio menu lateral (#mnuIzquierda) YA es ese
       mismo arbol de categorias, solo que reconstruido con JavaScript en
       vez de <ul>/<li> anidados. Se sigue con
       motor_limpieza.extraer_menu_clasico().
    3. Dominio propio fuera de upv.es (ETSII/ETSIE/ETSICCP): la propia
       ficha de "escuela" bajo upv.es/entidades/<COD>/ es solo un stub de
       contacto/redireccion SIN ningun enlace visible a su dominio real
       (comprobado: ETSII no tiene ningun <a> a etsii.upv.es en su stub)
       -- el dominio real solo se conoce porque ya se habia
       identificado a mano de antemano (escuelas.md). Se mantiene como tabla de
       excepcion conocida (DOMINIO_PROPIO_CONOCIDO) y, si existe, se
       intenta su sitemap.xml (protocolo sitemaps.org estandar,
       resuelto con motor_limpieza.extraer_urls_de_sitemap(), que
       tambien sabe seguir un <sitemapindex> nativo de WordPress como el
       de etsie.upv.es).
    4. Si ninguna de las tres existe (ETSICCP: ASP.NET con navegacion
       via JavaScript, sin sitemap.xml), el stub de upv.es SI trae un
       enlace "Acceso a la Web" hacia el dominio real -- se dejar
       constancia de esa URL sin inventar mas estructura
       (motor_limpieza.buscar_enlace_acceso_web_externa()).
- No se intenta scrapear el contenido real de cada pagina enlazada (ni
  siquiera con el motor de "hoja de contenido" para 1-2 paginas clave):
  seria repetir exactamente la decision ya descartada (ver arriba). La
  ficha de cada centro es un INDICE navegable (datos basicos +
  mapa del sitio), no un resumen de contenido.
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
from config import ESCUELAS_JSON, ESCUELAS_KB_DIR, ESCUELAS_URL
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
CATEGORIA = "organizacion"
NIVEL = "escuelas_facultades"
TIPO_RECURSO = "informacion"
RESUMEN_URL = ESCUELAS_URL

# Centros con dominio propio fuera de upv.es cuyo stub en
# upv.es/entidades/<COD>/ no enlaza a el en ningun sitio (comprobado
# 2026-08-23) -- solo se conocen porque ya se habian identificado a mano
# de antemano en escuelas.md. No hay forma de descubrirlos desde
# el propio HTML de upv.es, asi que se mantienen como excepcion explicita
# en vez de intentar adivinarlos.
DOMINIO_PROPIO_CONOCIDO = {
    "ETSII": "https://www.etsii.upv.es/",
    "ETSIE": "https://www.etsie.upv.es/",
    "ETSICCP": "https://www.iccp.upv.es/",
}


# ==========================================================
# 1. Catalogo -- pagina de listado agrupada por <h2>Campus de X</h2>
# ==========================================================

def extraer_catalogo(url: str = ESCUELAS_URL) -> list[dict]:
    soup, es_html = ml.descargar_soup(url, headers=HEADERS)
    if not es_html:
        raise Exception("No se ha podido descargar el listado de escuelas y facultades.")

    contenedor = soup.find("main") or soup.find(id="smooth-wrapper")
    if contenedor is None:
        raise Exception("No se ha encontrado el contenedor principal de la pagina.")

    items = []
    campus_actual = None
    for tag in contenedor.find_all(["h2", "h3", "a"], recursive=True):
        if tag.name in ("h2", "h3"):
            if tag.name == "h3":
                continue
            texto_normalizado = ml.normalizar_para_comparar(tag.get_text(" ", strip=True))
            if texto_normalizado in ml.TITULOS_CORTE_PLANTILLA:
                break
            if texto_normalizado.startswith("campus de"):
                campus_actual = limpiar_texto(tag.get_text(" ", strip=True))
            elif texto_normalizado == "centros adscritos":
                campus_actual = ""
            continue

        if campus_actual is None:
            continue
        href = tag.get("href", "")
        m = re.search(r"/entidades/([A-Za-z0-9_\-]+)", href)
        if not m:
            continue
        titulo = limpiar_texto(tag.get_text(" ", strip=True))
        if not titulo:
            continue
        items.append({
            "codigo": m.group(1).upper(),
            "titulo": titulo,
            "url": ml.normalizar_url(href, url),
            "campus": campus_actual,
        })

    items = ml.deduplicar_lista(items, clave="codigo")
    print("Centros encontrados:", len(items))
    return items


def guardar_json(items: list[dict], ruta: Path = ESCUELAS_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"centros": items}, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


# ==========================================================
# 2. Mapa del sitio de cada centro (WP dedicado > menu clasico >
#    sitemap.xml de dominio propio conocido > enlace "Acceso a la Web")
# ==========================================================

def _url_base_centro(url_pagina: str) -> str:
    """Carpeta que contiene la ficha del centro (para construir
    <base>mapa-del-sitio/): distinto segun si la URL real es una
    "bonita" (WP moderno, ya termina en /) o la plantilla clasica
    (.../index-es.html)."""
    if re.search(r"/index[\w-]*\.html?$", url_pagina, re.I):
        return re.sub(r"/index[\w-]*\.html?$", "/", url_pagina, flags=re.I)
    return url_pagina if url_pagina.endswith("/") else url_pagina + "/"


def extraer_mapa_del_sitio(soup_pagina: BeautifulSoup, url_pagina: str, codigo: str):
    """Devuelve (arbol, fuente, web_externa, contacto) -- ver cabecera
    del modulo para el orden de prioridad de fuentes."""
    base = _url_base_centro(url_pagina)

    arbol = ml.extraer_arbol_sitemap_wp(base + "mapa-del-sitio/", headers=HEADERS)
    if arbol:
        return arbol, "mapa del sitio publicado por el propio centro", None, []

    arbol = ml.extraer_menu_clasico(soup_pagina, url_pagina)
    if arbol:
        return arbol, "menu de navegacion de la ficha clasica del centro", None, []

    dominio_propio = DOMINIO_PROPIO_CONOCIDO.get(codigo)
    if dominio_propio:
        urls = ml.extraer_urls_de_sitemap(dominio_propio.rstrip("/") + "/sitemap.xml", headers=HEADERS)
        urls = [u for u in urls if "/en/" not in u and "/va/" not in u]
        if urls:
            arbol = ml.agrupar_urls_sitemap_xml_por_seccion(urls)
            return arbol, f"sitemap.xml de {dominio_propio}", None, []

    web_externa = ml.buscar_enlace_acceso_web_externa(soup_pagina, url_pagina)
    contacto = _extraer_contacto(soup_pagina, url_pagina) if web_externa is None else []
    return None, None, web_externa, contacto


def _extraer_contacto(soup_pagina: BeautifulSoup, url_pagina: str) -> list[str]:
    """Ultimo recurso cuando ni el mapa WP ni el menu clasico ni un
    dominio propio conocido dieron nada. Dos variantes: (a) la plantilla
    clasica trae el contacto en un <iframe> aparte (igual que
    institucion/servicios, ver ml.buscar_iframe_contenido_clasico()), o
    (b) no hay ni menu (#mnuIzquierda) ni iframe -- el contacto esta
    directamente en el propio #contenido de la pagina (variante ya
    documentada "id=contenido sin iframe")."""
    iframe_url = ml.buscar_iframe_contenido_clasico(soup_pagina, url_pagina)
    if iframe_url is not None:
        try:
            soup_iframe, es_html = ml.descargar_soup(iframe_url, headers=HEADERS)
        except Exception:
            return []
        if not es_html:
            return []
        soup_iframe = ml.limpiar_contenido_html(soup_iframe)
        contenedor = soup_iframe.find(id="contenido") or soup_iframe.body
        if contenedor is None:
            return []
        ml.reemplazar_tablas_por_listas(soup_iframe, contenedor)
        lineas = ml.extraer_bloques_contenido(contenedor, iframe_url)
        return ml.limpiar_lineas_finales(lineas, recortar_h1=False)

    soup_pagina = ml.limpiar_contenido_html(soup_pagina)
    contenedor = soup_pagina.find(id="contenido")
    if contenedor is None:
        return []
    ml.reemplazar_tablas_por_listas(soup_pagina, contenedor)
    lineas = ml.extraer_bloques_contenido(contenedor, url_pagina)
    return ml.limpiar_lineas_finales(lineas, recortar_h1=False)


# ==========================================================
# 3. Markdown por centro
# ==========================================================

def _yaml_centro(item: dict) -> str:
    campos_extra = {"acronimo": item["codigo"]}
    if item.get("campus"):
        campos_extra["campus"] = item["campus"]
    return ml.generar_yaml_metadatos(
        fuente=FUENTE, url=item["url"], categoria=CATEGORIA, nivel=NIVEL,
        tipo_documento="recurso", tipo_recurso=TIPO_RECURSO,
        resumen=RESUMEN_URL, seccion=NIVEL, titulo=item["titulo"],
        campos_extra=campos_extra,
    )


def generar_ficha_centro(item: dict, carpeta: Path) -> bool:
    titulo, url, codigo = item["titulo"], item["url"], item["codigo"]
    print(f"  Extrayendo: {titulo} ({codigo})")

    try:
        respuesta = requests.get(url, headers=HEADERS, timeout=30)
        respuesta.raise_for_status()
    except Exception as error:
        print(f"  ERROR: {error}")
        return False

    soup = BeautifulSoup(respuesta.text, "html.parser")
    arbol, fuente_mapa, web_externa, contacto = extraer_mapa_del_sitio(soup, respuesta.url, codigo)

    bloques = [f"# {titulo}", f"**Web oficial:** {respuesta.url}"]
    if item.get("campus"):
        bloques.append(f"**Campus:** {item['campus']}")

    bloques.append("## Mapa del sitio")
    if arbol:
        bloques.append(f"_Fuente: {fuente_mapa}._")
        bloques.append("\n\n".join(ml.arbol_sitemap_a_markdown(arbol)))
    else:
        notas = []
        if web_externa:
            notas.append(
                f"Este centro no publica su contenido bajo upv.es: su web real está en "
                f"[{web_externa}]({web_externa})."
            )
        if contacto:
            notas.append("**Contacto:**\n\n" + "\n\n".join(contacto))
        if not notas:
            notas.append(
                "_No se ha encontrado un mapa del sitio estándar para este centro; "
                "consulta directamente la web oficial indicada arriba._"
            )
        bloques.append("\n\n".join(notas))

    yaml_metadatos = _yaml_centro(item)
    markdown = f"{yaml_metadatos}\n" + "\n\n".join(bloques) + "\n"

    ruta = carpeta / f"{codigo.lower()}.md"
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(markdown)
    print(f"  OK: {ruta}")
    return True


def generar_markdowns_centros(items: list[dict], carpeta: Path = ESCUELAS_KB_DIR) -> tuple[int, int, int]:
    carpeta.mkdir(parents=True, exist_ok=True)
    total = correctos = errores = 0
    for item in items:
        total += 1
        if generar_ficha_centro(item, carpeta):
            correctos += 1
        else:
            errores += 1
        time.sleep(0.3)
    return total, correctos, errores


# ==========================================================
# 4. Markdown resumen (indice de centros)
# ==========================================================

def generar_markdown_resumen(items: list[dict]) -> str:
    yaml_metadatos = ml.generar_yaml_metadatos(
        fuente=FUENTE, url=RESUMEN_URL, categoria=CATEGORIA, nivel=NIVEL,
        tipo_documento="resumen", titulo="Escuelas y facultades")

    filas = [
        f"| [{i['codigo']}]({i['url']}) | {i['titulo']} | {i.get('campus') or '—'} |"
        for i in items
    ]
    tabla = "| Código | Centro | Campus |\n|---|---|---|\n" + "\n".join(filas)

    cuerpo = (
        f"La UPV tiene {len(items)} escuelas, facultades y centros adscritos, distribuidos "
        "en cuatro campus (Vera, Alcoy, Gandía y Hangzhou). Cada centro gestiona su propia web "
        "con información heterogénea (organización, titulaciones, trámites, vida académica); "
        "la ficha de cada uno remite a su web oficial y, cuando existe, a su propio mapa del "
        "sitio en vez de duplicar aquí su contenido."
    )
    return f"{yaml_metadatos}\n# Escuelas y facultades\n\n{cuerpo}\n\n{tabla}\n"


# ==========================================================
# Ejecucion
# ==========================================================

def main(limite: int | None = None) -> None:
    items = extraer_catalogo()
    guardar_json(items)

    ESCUELAS_KB_DIR.mkdir(parents=True, exist_ok=True)
    with open(ESCUELAS_KB_DIR / "escuelas.md", "w", encoding="utf-8") as f:
        f.write(generar_markdown_resumen(items))

    if limite is not None:
        items = items[:limite]
    total, correctos, errores = generar_markdowns_centros(items)
    print(f"Escuelas y facultades: {total} · generados: {correctos} · errores: {errores}")


if __name__ == "__main__":
    main()
