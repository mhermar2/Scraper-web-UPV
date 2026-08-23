"""Extractor de "Departamentos" (organizacion/departamentos).

Mismo criterio y mismo diseno que extrae_escuelas.py (ver la cabecera de
ese modulo para el razonamiento completo): el tutor decidio por correo
remitir a la web de cada departamento en vez de homogeneizar su contenido
real, demasiado heterogeneo. Aqui la heterogeneidad es aun mayor que en
escuelas: de los 41 departamentos, unos usan la plantilla WordPress
moderna (con su propio /mapa-del-sitio/) y otros la plantilla Oracle
Portal clasica (sin esa pagina, pero con el mismo arbol de navegacion
disponible en su menu lateral #mnuIzquierda) -- comprobado 2026-08-23
contra la web real, sin ningun patron por codigo de departamento que
permita saber de antemano cual es cual.

Diferencias reales frente a extrae_escuelas.py:
- El catalogo (`DEPARTAMENTOS_URL`) NO agrupa por campus -- es una lista
  plana de <a href="/entidades/<COD>/index-es.html">, sin encabezados
  <h2> intermedios. Se filtra por texto de enlace que empieza por
  "Dpto." (la pagina real incluye ademas, al final, un enlace de
  boilerplate "Doctorados N programas en M ambitos" que no es un
  departamento y hay que descartar).
- No se incluye `campus`: a diferencia de los centros, un departamento
  no esta ligado a un unico campus (imparte docencia en varios) y no hay
  ninguna fuente estructurada fiable para derivarlo -- mismo criterio de
  "no inventar" que ya se aplico en estudios/doctorado y estudios/grado
  para los campos sin fuente verificable.
- No hay ningun departamento con dominio propio documentado (a diferencia
  de ETSII/ETSIE/ETSICCP en escuelas), asi que no existe tabla de
  excepcion equivalente a DOMINIO_PROPIO_CONOCIDO -- el orden de
  prioridad de fuentes se queda en mapa WP > menu clasico > nada.
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
from config import DEPARTAMENTOS_JSON, DEPARTAMENTOS_KB_DIR, DEPARTAMENTOS_URL
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
NIVEL = "departamentos"
TIPO_RECURSO = "informacion"
RESUMEN_URL = DEPARTAMENTOS_URL


# ==========================================================
# 1. Catalogo -- listado plano, filtrado por prefijo "Dpto."
# ==========================================================

def extraer_catalogo(url: str = DEPARTAMENTOS_URL) -> list[dict]:
    soup, es_html = ml.descargar_soup(url, headers=HEADERS)
    if not es_html:
        raise Exception("No se ha podido descargar el listado de departamentos.")

    contenedor = soup.find("main") or soup.find(id="smooth-wrapper")
    if contenedor is None:
        raise Exception("No se ha encontrado el contenedor principal de la pagina.")

    items = []
    for enlace in contenedor.find_all("a", href=True):
        if "/entidades/" not in enlace["href"]:
            continue
        titulo = limpiar_texto(enlace.get_text(" ", strip=True))
        if not titulo.lower().startswith("dpto"):
            continue

        m = ml.normalizar_url(enlace["href"], url)
        codigo_match = re.search(r"/entidades/([A-Za-z0-9_\-]+)", enlace["href"])
        if not codigo_match:
            continue

        items.append({
            "codigo": codigo_match.group(1).upper(),
            "titulo": titulo,
            "url": m,
        })

    items = ml.deduplicar_lista(items, clave="codigo")
    print("Departamentos encontrados:", len(items))
    return items


def guardar_json(items: list[dict], ruta: Path = DEPARTAMENTOS_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"departamentos": items}, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


# ==========================================================
# 2. Mapa del sitio de cada departamento (WP dedicado > menu clasico)
# ==========================================================

def _url_base_departamento(url_pagina: str) -> str:
    if re.search(r"/index[\w-]*\.html?$", url_pagina, re.I):
        return re.sub(r"/index[\w-]*\.html?$", "/", url_pagina, flags=re.I)
    return url_pagina if url_pagina.endswith("/") else url_pagina + "/"


def extraer_mapa_del_sitio(soup_pagina: BeautifulSoup, url_pagina: str):
    """Devuelve (arbol, fuente, contacto) -- ver cabecera del modulo
    para el orden de prioridad de fuentes."""
    base = _url_base_departamento(url_pagina)

    arbol = ml.extraer_arbol_sitemap_wp(base + "mapa-del-sitio/", headers=HEADERS)
    if arbol:
        return arbol, "mapa del sitio publicado por el propio departamento", []

    arbol = ml.extraer_menu_clasico(soup_pagina, url_pagina)
    if arbol:
        return arbol, "menu de navegacion de la ficha clasica del departamento", []

    contacto = _extraer_contacto(soup_pagina, url_pagina)
    return None, None, contacto


def _extraer_contacto(soup_pagina: BeautifulSoup, url_pagina: str) -> list[str]:
    """Ultimo recurso cuando ni el mapa WP ni el menu clasico existen.
    Dos variantes vistas en departamentos reales: (a) la plantilla
    clasica sigue trayendo el contacto en un <iframe> aparte (igual que
    institucion/servicios, ver ml.buscar_iframe_contenido_clasico()), o
    (b) no hay ni menu (#mnuIzquierda) ni iframe -- el contacto esta
    directamente en el propio #contenido de la pagina (variante ya
    documentada "id=contenido sin iframe", vista en DITT/DPV/DSIC/
    DMMCTE: ninguna de esas 4 tiene menu lateral configurado, pero su
    #contenido si trae direccion/telefono/email en texto plano)."""
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
# 3. Markdown por departamento
# ==========================================================

def _yaml_departamento(item: dict) -> str:
    return ml.generar_yaml_metadatos(
        fuente=FUENTE, url=item["url"], categoria=CATEGORIA, nivel=NIVEL,
        tipo_documento="recurso", tipo_recurso=TIPO_RECURSO,
        resumen=RESUMEN_URL, seccion=NIVEL, titulo=item["titulo"],
        campos_extra={"acronimo": item["codigo"]},
    )


def generar_ficha_departamento(item: dict, carpeta: Path) -> bool:
    titulo, url, codigo = item["titulo"], item["url"], item["codigo"]
    print(f"  Extrayendo: {titulo} ({codigo})")

    try:
        respuesta = requests.get(url, headers=HEADERS, timeout=30)
        respuesta.raise_for_status()
    except Exception as error:
        print(f"  ERROR: {error}")
        return False

    soup = BeautifulSoup(respuesta.text, "html.parser")
    arbol, fuente_mapa, contacto = extraer_mapa_del_sitio(soup, respuesta.url)

    bloques = [f"# {titulo}", f"**Web oficial:** {respuesta.url}", "## Mapa del sitio"]
    if arbol:
        bloques.append(f"_Fuente: {fuente_mapa}._")
        bloques.append("\n\n".join(ml.arbol_sitemap_a_markdown(arbol)))
    elif contacto:
        bloques.append("**Contacto:**\n\n" + "\n\n".join(contacto))
    else:
        bloques.append(
            "_No se ha encontrado un mapa del sitio estándar para este departamento; "
            "consulta directamente la web oficial indicada arriba._"
        )

    yaml_metadatos = _yaml_departamento(item)
    markdown = f"{yaml_metadatos}\n" + "\n\n".join(bloques) + "\n"

    ruta = carpeta / f"{codigo.lower()}.md"
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(markdown)
    print(f"  OK: {ruta}")
    return True


def generar_markdowns_departamentos(items: list[dict], carpeta: Path = DEPARTAMENTOS_KB_DIR) -> tuple[int, int, int]:
    carpeta.mkdir(parents=True, exist_ok=True)
    total = correctos = errores = 0
    for item in items:
        total += 1
        if generar_ficha_departamento(item, carpeta):
            correctos += 1
        else:
            errores += 1
        time.sleep(0.3)
    return total, correctos, errores


# ==========================================================
# 4. Markdown resumen (indice de departamentos)
# ==========================================================

def generar_markdown_resumen(items: list[dict]) -> str:
    yaml_metadatos = ml.generar_yaml_metadatos(
        fuente=FUENTE, url=RESUMEN_URL, categoria=CATEGORIA, nivel=NIVEL,
        tipo_documento="resumen", titulo="Departamentos")

    filas = [f"| [{i['codigo']}]({i['url']}) | {i['titulo']} |" for i in items]
    tabla = "| Código | Departamento |\n|---|---|\n" + "\n".join(filas)

    cuerpo = (
        f"La UPV tiene {len(items)} departamentos: las unidades de docencia e investigación "
        "que coordinan las enseñanzas de uno o varios ámbitos del conocimiento y apoyan la "
        "actividad investigadora del profesorado. Cada departamento gestiona su propia web con "
        "información heterogénea; la ficha de cada uno remite a su web oficial y, cuando "
        "existe, a su propio mapa del sitio en vez de duplicar aquí su contenido."
    )
    return f"{yaml_metadatos}\n# Departamentos\n\n{cuerpo}\n\n{tabla}\n"


# ==========================================================
# Ejecucion
# ==========================================================

def main(limite: int | None = None) -> None:
    items = extraer_catalogo()
    guardar_json(items)

    DEPARTAMENTOS_KB_DIR.mkdir(parents=True, exist_ok=True)
    with open(DEPARTAMENTOS_KB_DIR / "departamentos.md", "w", encoding="utf-8") as f:
        f.write(generar_markdown_resumen(items))

    if limite is not None:
        items = items[:limite]
    total, correctos, errores = generar_markdowns_departamentos(items)
    print(f"Departamentos: {total} · generados: {correctos} · errores: {errores}")


if __name__ == "__main__":
    main()
