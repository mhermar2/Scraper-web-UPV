"""Extractor de "Iniciativas de I+D+i" (investigacion).

A diferencia de institucion/servicios, esta pagina no usa el motor de
"hoja de contenido": el contenido se extrae con una estrategia mas
simple (texto plano de main/article/.entry-content...) y no lleva
metadatos YAML -- es una seccion de baja calidad segun las notas internas del proyecto, cola
de trabajo pendiente de rehacer con el motor validado.

Pipeline (mismo orden que el notebook original, quedandonos con la
version FINAL de cada paso -- ver nota de deduplicacion abajo):
  1. extraer_json_padre()  -> JSON con las secciones validas + recursos
  2. guardar_json()
  3. construir_paginas_hijas()  -> aplana json_padre a una lista
  4. extraer_pagina_padre() / extraer_paginas_hijas() -> contenido y
     encabezados de cada pagina
  5. preparar_contenido_markdown() -> paginas "dinamicas" (tipo=="dinamico",
     ej. boletines/convocatorias vía /pls/) se reprocesan con una
     extraccion h1-h4/p/li mas estructurada; el resto conserva su
     contenido tal cual
  6. generar_markdown() -> agrupa paginas por contenido identico
     (varias URLs pueden ser el mismo recurso) y genera un .md por grupo

Migrado desde src/extractores/investigacion/extrae_iniciativas_idi.ipynb
(antes Extrae_I+D.ipynb). El notebook reconstruye la lista de paginas
hijas y su contenido DOS VECES: una primera vez (BLOQUE 9-10) solo para
inspeccionarla por consola, y una segunda vez (BLOQUE 11, con el
comentario explicito "para evitar depender de una variable externa
llamada paginas_hijas") que es la que de verdad alimenta la generacion
de Markdown del BLOQUE 13. Se migra solo esta segunda version. Tambien
se descarta el bloque de "COMPROBACION FINAL" (paginas sin contenido,
contenido corto, duplicados...): calcula `hay_problemas` pero nunca lo
usa para detener nada, es un informe de consola que no afecta al
resultado.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bs4 import BeautifulSoup
import requests

from config import INICIATIVAS_IDI_JSON, INICIATIVAS_IDI_MD_PADRE, INICIATIVAS_IDI_RECURSOS_DIR, INICIATIVAS_IDI_URL

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    )
}

SECCIONES_VALIDAS = {"Convocatorias públicas", "Programas propios", "Enlaces de interés"}

SELECTORES_CONTENIDO = ["main", "article", ".entry-content", "#content", ".content", ".entry"]


def descargar_html(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def limpiar_texto(texto: str) -> str:
    if not texto:
        return ""
    return re.sub(r"\s+", " ", texto).strip()


def normalizar_url(url: str, base_url: str) -> str:
    return urljoin(base_url, url)


def clasificar_recurso(url: str) -> str:
    path = urlparse(url).path
    if "/pls/" in path:
        return "dinamico"
    if "/entidades/" in path:
        return "pagina"
    return "otro"


# ==========================================================
# 1. JSON de la pagina padre
# ==========================================================

def extraer_json_padre(url: str = INICIATIVAS_IDI_URL) -> dict:
    html = descargar_html(url)
    soup = BeautifulSoup(html, "html.parser")

    main = soup.select_one("main.iniciativas-page")
    if main is None:
        raise ValueError("No se ha encontrado 'main.iniciativas-page' en la página.")

    h1 = main.find("h1")
    titulo = limpiar_texto(h1.get_text(" ", strip=True)) if h1 else ""

    resultado = {"url": url, "titulo": titulo, "tipo": "padre", "secciones": []}

    for section in main.find_all("section", recursive=False):
        h3 = section.find("h3")
        if h3 is None:
            continue

        titulo_seccion = limpiar_texto(h3.get_text(" ", strip=True))
        if titulo_seccion not in SECCIONES_VALIDAS:
            continue

        descripcion = ""
        bloque_contenido = section.select_one(".content-block-horizontal--content")
        if bloque_contenido:
            p = bloque_contenido.find("p")
            if p:
                descripcion = limpiar_texto(p.get_text(" ", strip=True))

        recursos = []
        for a in section.find_all("a", href=True):
            titulo_recurso = limpiar_texto(a.get_text(" ", strip=True))
            if not titulo_recurso:
                continue
            url_recurso = normalizar_url(a["href"], url)
            recursos.append({"titulo": titulo_recurso, "url": url_recurso, "tipo": clasificar_recurso(url_recurso)})

        resultado["secciones"].append({"titulo": titulo_seccion, "descripcion": descripcion, "recursos": recursos})

    return resultado


def guardar_json(datos: dict, ruta: Path = INICIATIVAS_IDI_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=4)
    print("JSON guardado:", ruta)


# ==========================================================
# 2. Contenido de la pagina padre y de las paginas hijas
# ==========================================================

def extraer_contenido_principal(html: str) -> str:
    """Texto principal evitando menus/cabeceras/pies, con fallback a body."""
    soup = BeautifulSoup(html, "html.parser")

    for elemento in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        elemento.decompose()

    contenido = None
    for selector in SELECTORES_CONTENIDO:
        elemento = soup.select_one(selector)
        if elemento:
            texto = limpiar_texto(elemento.get_text(" ", strip=True))
            if len(texto) > 200:
                contenido = texto
                break

    if contenido is None:
        body = soup.body
        contenido = limpiar_texto(body.get_text(" ", strip=True)) if body else limpiar_texto(soup.get_text(" ", strip=True))

    return contenido


def extraer_encabezados(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    encabezados = []
    for nivel in ["h1", "h2", "h3"]:
        for elemento in soup.find_all(nivel):
            texto = limpiar_texto(elemento.get_text(" ", strip=True))
            if texto:
                encabezados.append({"nivel": nivel, "texto": texto})
    return encabezados


def extraer_pagina_padre(json_padre: dict, url: str = INICIATIVAS_IDI_URL) -> dict:
    html = descargar_html(url)
    return {
        "url": url,
        "titulo": json_padre.get("titulo", "Iniciativas de I+D+i"),
        "tipo": "padre",
        "contenido": extraer_contenido_principal(html),
        "encabezados": extraer_encabezados(html),
    }


def construir_paginas_hijas(json_padre: dict) -> list[dict]:
    """Aplana json_padre['secciones'] a una lista de paginas hijas."""
    paginas_hijas = []
    for seccion in json_padre.get("secciones", []):
        titulo_seccion = seccion.get("titulo", "")
        for recurso in seccion.get("recursos", []):
            paginas_hijas.append({
                "titulo": recurso.get("titulo", ""),
                "url": recurso.get("url", ""),
                "tipo": recurso.get("tipo", "otro"),
                "padre_origen": json_padre.get("titulo", "Iniciativas de I+D+i"),
                "seccion_origen": titulo_seccion,
            })
    return paginas_hijas


def extraer_paginas_hijas(paginas_hijas: list[dict]) -> list[dict]:
    paginas_extraidas = []
    total = len(paginas_hijas)

    for indice, pagina in enumerate(paginas_hijas, start=1):
        url = pagina.get("url", "")
        if not url:
            print(f"[{indice}/{total}] URL vacía. Omitida.")
            continue

        print(f"[{indice}/{total}] {pagina.get('titulo', '')} ({url})")
        try:
            html = descargar_html(url)
            paginas_extraidas.append({
                "titulo": pagina.get("titulo", ""),
                "url": url,
                "tipo": pagina.get("tipo", "otro"),
                "padre_origen": pagina.get("padre_origen", ""),
                "seccion_origen": pagina.get("seccion_origen", ""),
                "contenido": extraer_contenido_principal(html),
                "encabezados": extraer_encabezados(html),
            })
        except Exception as e:
            print("  ERROR:", e)

    return paginas_extraidas


# ==========================================================
# 3. Contenido Markdown de paginas dinamicas (convocatorias,
#    boletines...): estructura h1-h4/p/li en vez de texto plano
# ==========================================================

def extraer_dinamico_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for elemento in soup(["script", "style", "noscript", "nav", "header", "footer"]):
        elemento.decompose()

    contenedor = None
    for selector in SELECTORES_CONTENIDO:
        elemento = soup.select_one(selector)
        if elemento and len(elemento.get_text(" ", strip=True)) > 200:
            contenedor = elemento
            break

    contenedor = contenedor or soup.body or soup

    bloques = []
    for elemento in contenedor.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        texto = limpiar_texto(elemento.get_text(" ", strip=True))
        if not texto:
            continue

        if elemento.name in ("h1", "h2", "h3", "h4"):
            bloques.append(("#" * int(elemento.name[1])) + " " + texto)
        elif elemento.name == "li":
            bloques.append(f"- {texto}")
        else:
            bloques.append(texto)

    contenido = "\n\n".join(bloques)
    return re.sub(r"\n{3,}", "\n\n", contenido).strip()


def preparar_contenido_markdown(paginas_extraidas: list[dict]) -> list[dict]:
    """Anade el campo contenido_markdown: paginas dinamicas se
    reprocesan con extraer_dinamico_markdown, el resto conserva
    'contenido' tal cual."""
    for pagina in paginas_extraidas:
        if pagina.get("tipo") != "dinamico":
            pagina["contenido_markdown"] = pagina.get("contenido", "")
            continue

        try:
            html = descargar_html(pagina["url"])
            pagina["contenido_markdown"] = extraer_dinamico_markdown(html)
        except Exception as e:
            print("  ERROR:", e)
            pagina["contenido_markdown"] = pagina.get("contenido", "")

    return paginas_extraidas


# ==========================================================
# 4. Generacion de Markdown
# ==========================================================

def nombre_archivo_markdown(titulo: str) -> str:
    nombre = titulo.lower()
    reemplazos = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"}
    for origen, destino in reemplazos.items():
        nombre = nombre.replace(origen, destino)
    nombre = re.sub(r"[^a-z0-9]+", "_", nombre).strip("_")
    return nombre + ".md"


def hash_contenido(contenido: str) -> str:
    return hashlib.sha256(contenido.strip().encode("utf-8")).hexdigest()


def generar_estructura_semantica(contenido: str, encabezados: list[dict]) -> str:
    """Antepone los encabezados como jerarquia Markdown (# ## ###); el
    contenido textual se conserva integro porque la extraccion no
    mantiene la relacion exacta parrafo<->encabezado."""
    encabezados_validos = [
        e for e in encabezados
        if e.get("texto", "").strip() and e.get("nivel") in ("h1", "h2", "h3")
    ]

    if not encabezados_validos:
        return contenido.strip()

    nivel_markdown = {"h1": 1, "h2": 2, "h3": 3}
    estructura = [("#" * nivel_markdown[e["nivel"]]) + " " + e["texto"].strip() for e in encabezados_validos]
    estructura.append("")
    estructura.append(contenido.strip())

    return "\n\n".join(estructura)


def generar_markdown_padre(pagina_padre: dict, ruta: Path = INICIATIVAS_IDI_MD_PADRE) -> None:
    contenido = pagina_padre.get("contenido", "").strip()
    estructura = generar_estructura_semantica(contenido, pagina_padre.get("encabezados", []))

    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as archivo:
        archivo.write(f"# {pagina_padre['titulo']}\n\n")
        archivo.write(f"**Tipo:** {pagina_padre['tipo']}\n\n")
        archivo.write(f"**URL:** {pagina_padre['url']}\n\n")
        archivo.write(estructura)
        archivo.write("\n")

    print("OK: Markdown padre generado:", ruta)


def generar_markdowns_recursos(paginas_extraidas: list[dict], carpeta: Path = INICIATIVAS_IDI_RECURSOS_DIR) -> int:
    """Agrupa paginas por contenido identico (varias URLs pueden ser el
    mismo recurso) y genera un .md por grupo, listando todas sus URLs."""
    carpeta.mkdir(parents=True, exist_ok=True)

    grupos_contenido: dict[str, list[dict]] = {}
    for pagina in paginas_extraidas:
        contenido = pagina.get("contenido_markdown", pagina.get("contenido", "")).strip()
        if not contenido:
            continue
        grupos_contenido.setdefault(hash_contenido(contenido), []).append(pagina)

    recursos_generados = 0
    for grupo in grupos_contenido.values():
        pagina_principal = grupo[0]
        nombre_archivo = nombre_archivo_markdown(pagina_principal["titulo"])
        contenido = pagina_principal.get("contenido_markdown", pagina_principal.get("contenido", "")).strip()
        estructura = generar_estructura_semantica(contenido, pagina_principal.get("encabezados", []))

        with open(carpeta / nombre_archivo, "w", encoding="utf-8") as archivo:
            archivo.write(f"# {pagina_principal['titulo']}\n\n")
            archivo.write(f"**Tipo:** {pagina_principal['tipo']}\n\n")
            archivo.write(f"**Página padre:** {pagina_principal['padre_origen']}\n\n")
            archivo.write(f"**Sección:** {pagina_principal['seccion_origen']}\n\n")
            archivo.write("## URLs asociadas\n\n")
            for pagina in grupo:
                archivo.write(f"- {pagina['url']}\n")
            archivo.write("\n")
            archivo.write(estructura)
            archivo.write("\n")

        recursos_generados += 1
        print(f"[{recursos_generados}/{len(grupos_contenido)}] {nombre_archivo}")

    return recursos_generados


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    json_padre = extraer_json_padre()
    guardar_json(json_padre)

    pagina_padre = extraer_pagina_padre(json_padre)
    paginas_hijas = construir_paginas_hijas(json_padre)
    paginas_extraidas = extraer_paginas_hijas(paginas_hijas)
    paginas_extraidas = preparar_contenido_markdown(paginas_extraidas)

    generar_markdown_padre(pagina_padre)
    recursos_generados = generar_markdowns_recursos(paginas_extraidas)
    print(f"Páginas hijas: {len(paginas_extraidas)} · recursos generados: {recursos_generados}")


if __name__ == "__main__":
    main()
