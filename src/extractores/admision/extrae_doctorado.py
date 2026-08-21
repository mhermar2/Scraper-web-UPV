"""Extractor de "Admision a Doctorado".

Reescritura completa (2026-08-21), mismo patron que el nuevo
extrae_master.py: metadatos YAML definitivos para el padre/secciones
(vuelcan directamente el JSON de tarjetas/acordeones/banners, la
maquetacion en <section id="section-01">..<section id="section-06"> no
encaja en el motor de "hoja de contenido") y motor_limpieza.py para el
contenido de cada pagina ENLAZADA (traversal, PDF, plantilla clasica,
limpieza de renombrados) en vez del loop h1-h4/p/li ad-hoc anterior.

Se preserva el alcance mas estrecho que ya tenia esta seccion frente a
admision/master: solo se sigue de verdad el contenido de URLs bajo
upv.es/entidades/edoctorado/ o upv.es/pls/soalu/ (url_relevante()) --
decision deliberada de la version anterior, no alcance nuevo introducido
aqui.
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
from config import ADMISION_DOCTORADO_DIR, ADMISION_DOCTORADO_JSON, ADMISION_DOCTORADO_RECURSOS_DIR, ADMISION_DOCTORADO_URL
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
CATEGORIA = "admision"
NIVEL = "doctorado"
TIPO_RECURSO = "informacion"

INTRO_DOCUMENTO = (
    "Información completa sobre el proceso de admisión "
    "a estudios oficiales de doctorado en la Universitat Politècnica de València."
)

SELECTORES_CONTENIDO = ["main", "article", ".entry-content", "#content", ".content", ".entry", ".mwc_contenido"]


def _yaml_resumen(url: str, titulo: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=url, categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="resumen", titulo=titulo)


def _yaml_seccion(url_resumen: str, titulo: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=url_resumen, categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="seccion", resumen=url_resumen, titulo=titulo)


def _yaml_recurso(elemento: dict, seccion_slug: str, url_resumen: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=elemento["url"], categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="recurso", tipo_recurso=TIPO_RECURSO,
                                      resumen=url_resumen, seccion=seccion_slug, titulo=elemento["titulo"])


def texto_limpio(elemento) -> str:
    return " ".join(elemento.stripped_strings) if elemento is not None else ""


def url_absoluta(url: str, base: str) -> str:
    return ml.normalizar_url(url, base) if url else ""


def primer_enlace(elemento, base: str) -> str:
    if elemento is None:
        return ""
    enlace = elemento.find("a", href=True)
    return url_absoluta(enlace["href"], base) if enlace else ""


def obtener_descripcion(contenedor) -> str:
    if contenedor is None:
        return ""
    parrafos = contenedor.find_all("p", recursive=False)
    return " ".join(texto_limpio(p) for p in parrafos).strip()


# ==========================================================
# 1. Catalogo (padre + secciones con tarjetas/acordeones/banners)
# ==========================================================

def extraer_tarjetas(seccion, base: str) -> list[dict]:
    tarjetas = []
    for caja in seccion.select(".box-number-box"):
        titulo = texto_limpio(caja.find("h3"))
        if not titulo:
            continue
        tarjetas.append({"titulo": titulo, "descripcion": obtener_descripcion(caja), "url": primer_enlace(caja, base)})
    return tarjetas


def extraer_banners(seccion, base: str) -> list[dict]:
    banners = []
    for banner in seccion.select(".banner--content"):
        titulo = texto_limpio(banner.find("h3"))
        banners.append({"titulo": titulo, "descripcion": obtener_descripcion(banner), "url": primer_enlace(banner, base)})
    return banners


def extraer_acordeones(seccion, base: str) -> list[dict]:
    acordeones = []
    for bloque in seccion.select(".accordion-element-content"):
        titulo = texto_limpio(bloque.find("h3"))
        texto = texto_limpio(bloque)
        enlaces = [{"texto": texto_limpio(a), "url": url_absoluta(a["href"], base)} for a in bloque.find_all("a", href=True)]
        acordeones.append({"titulo": titulo, "texto": texto, "enlaces": enlaces})
    return acordeones


def extraer_catalogo(url: str = ADMISION_DOCTORADO_URL) -> dict:
    respuesta = requests.get(url, headers=HEADERS, timeout=30)
    respuesta.raise_for_status()
    soup = BeautifulSoup(respuesta.text, "html.parser")

    titulo_padre = texto_limpio(soup.find("h1"))
    descripcion_padre = texto_limpio(soup.find("h2"))

    secciones = []
    for i in range(1, 7):
        seccion_html = soup.find("section", id=f"section-{i:02d}")
        if seccion_html is None:
            continue
        titulo = texto_limpio(seccion_html.find(["h2", "h3"]))
        if not titulo:
            continue
        secciones.append({
            "id": ml.normalizar_identificador(titulo) or f"seccion_{i:02d}",
            "titulo": titulo,
            "descripcion": obtener_descripcion(seccion_html),
            "tarjetas": extraer_tarjetas(seccion_html, url),
            "acordeones": extraer_acordeones(seccion_html, url),
            "banners": extraer_banners(seccion_html, url),
        })

    recursos = []
    urls_vistas = set()
    for seccion in secciones:
        for tarjeta in seccion["tarjetas"]:
            if tarjeta.get("url") and tarjeta["url"] not in urls_vistas:
                urls_vistas.add(tarjeta["url"])
                recursos.append({"titulo": tarjeta["titulo"], "url": tarjeta["url"], "seccion_id": seccion["id"]})
        for banner in seccion["banners"]:
            if banner.get("url") and banner["url"] not in urls_vistas:
                urls_vistas.add(banner["url"])
                recursos.append({"titulo": banner["titulo"], "url": banner["url"], "seccion_id": seccion["id"]})
        for acordeon in seccion["acordeones"]:
            for enlace in acordeon["enlaces"]:
                if enlace.get("url") and enlace["url"] not in urls_vistas:
                    urls_vistas.add(enlace["url"])
                    recursos.append({"titulo": enlace["texto"], "url": enlace["url"], "seccion_id": seccion["id"]})

    print("Secciones encontradas:", len(secciones), "· recursos enlazados únicos:", len(recursos))
    return {"titulo": titulo_padre, "url": url, "descripcion": descripcion_padre, "secciones": secciones, "recursos": recursos}


def guardar_json(datos: dict, ruta: Path = ADMISION_DOCTORADO_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


def cargar_recursos_anteriores(ruta: Path = ADMISION_DOCTORADO_JSON) -> list[dict]:
    if not ruta.exists():
        return []
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
    except Exception:
        return []
    return [{"titulo": r["titulo"], "url": r["url"]} for r in datos.get("recursos", []) if r.get("titulo") and r.get("url")]


# ==========================================================
# 2. Markdown de padre + secciones (vuelca el JSON, sin descargar nada)
# ==========================================================

def _escribir_bloque_seccion(f, seccion: dict, nivel_titulo: str, prefijo_enlace: str) -> None:
    for t in seccion.get("tarjetas", []):
        f.write(f"{nivel_titulo} {t['titulo']}\n\n")
        if t.get("descripcion"):
            f.write(t["descripcion"] + "\n\n")
        if t.get("url"):
            f.write(f"{prefijo_enlace}: {t['url']}\n\n")

    for acc in seccion.get("acordeones", []):
        if acc.get("titulo"):
            f.write(f"{nivel_titulo} {acc['titulo']}\n\n")
        if acc.get("texto"):
            f.write(acc["texto"] + "\n\n")
        for enlace in acc.get("enlaces", []):
            f.write(f"- {enlace['texto']}: {enlace['url']}\n")
        f.write("\n")

    for b in seccion.get("banners", []):
        if b.get("titulo"):
            f.write(f"{nivel_titulo} {b['titulo']}\n\n")
        if b.get("descripcion"):
            f.write(b["descripcion"] + "\n\n")
        if b.get("url"):
            f.write(f"{prefijo_enlace}: {b['url']}\n\n")


def generar_markdown_padre(datos: dict, ruta_dir: Path = ADMISION_DOCTORADO_DIR) -> Path:
    ruta_dir.mkdir(parents=True, exist_ok=True)
    nombre = ml.nombre_archivo_markdown(datos["titulo"] or "Admisión a doctorado")
    ruta = ruta_dir / nombre

    with open(ruta, "w", encoding="utf-8") as f:
        f.write(_yaml_resumen(datos["url"], datos["titulo"]))
        f.write(f"\n# {datos['titulo']}\n\n")
        f.write(INTRO_DOCUMENTO + "\n\n")
        for seccion in datos["secciones"]:
            f.write(f"## {seccion['titulo']}\n\n")
            if seccion.get("descripcion"):
                f.write(seccion["descripcion"] + "\n\n")
            _escribir_bloque_seccion(f, seccion, "###", "Más información")

    print("OK: Markdown padre generado:", ruta)
    return ruta


def generar_markdowns_secciones(datos: dict, ruta_dir: Path = ADMISION_DOCTORADO_DIR) -> int:
    ruta_dir.mkdir(parents=True, exist_ok=True)
    contador = 0
    for seccion in datos["secciones"]:
        nombre = ml.nombre_archivo_markdown(seccion["titulo"])
        with open(ruta_dir / nombre, "w", encoding="utf-8") as f:
            f.write(_yaml_seccion(datos["url"], seccion["titulo"]))
            f.write(f"\n# {seccion['titulo']}\n\n")
            f.write(f"Proceso: {datos['titulo']}\n\n")
            if seccion.get("descripcion"):
                f.write(seccion["descripcion"] + "\n\n")
            _escribir_bloque_seccion(f, seccion, "##", "Enlace oficial")
        contador += 1
    print("Markdown de secciones generado. Archivos:", contador)
    return contador


# ==========================================================
# 3. Markdown de los recursos enlazados -- motor_limpieza
# ==========================================================

def url_relevante(url: str) -> bool:
    """Alcance de esta seccion (decision ya existente, no nueva): solo
    entidades/edoctorado y las paginas dinamicas Oracle bajo pls/soalu."""
    url = url.lower()
    return "www.upv.es/entidades/edoctorado/" in url or "www.upv.es/pls/soalu/" in url


def encontrar_contenedor(soup: BeautifulSoup):
    contenedor_moderno = soup.find(id="smooth-wrapper") or soup.find("main")
    if contenedor_moderno is not None:
        return contenedor_moderno, True
    for selector in SELECTORES_CONTENIDO:
        elemento = soup.select_one(selector)
        if elemento is not None and len(elemento.get_text(" ", strip=True)) >= 100:
            return elemento, False
    return None, False


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


def generar_markdown_recurso(elemento: dict, seccion_slug: str, carpeta: Path, url_resumen: str) -> bool:
    titulo = elemento.get("titulo", "")
    url = elemento.get("url", "")
    if not titulo or not url:
        return False

    if not url_relevante(url):
        print(f"  Descartado (fuera del ámbito de Doctorado): {url}")
        return False

    print(f"  Extrayendo: {titulo} ({url})")
    try:
        respuesta = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        respuesta.raise_for_status()
    except Exception as error:
        print(f"    ERROR descargando: {error}")
        return False

    tipo = ml.tipo_contenido(respuesta.headers.get("Content-Type", ""))
    yaml_metadatos = _yaml_recurso(elemento, seccion_slug, url_resumen)

    if tipo == "pdf":
        paginas = ml.extraer_texto_pdf(respuesta.content)
        cuerpo = "\n\n".join(paginas) if paginas else "_PDF sin texto extraíble (probablemente escaneado sin OCR)._"
    elif tipo != "html":
        cuerpo = "_Este recurso no es una página HTML ni un PDF estándar. Consulta el contenido directamente en la URL indicada._"
    else:
        soup = BeautifulSoup(respuesta.text, "html.parser")
        soup = ml.limpiar_contenido_html(soup)
        contenedor, es_moderno = encontrar_contenedor(soup)
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

    ruta_archivo = carpeta / ml.nombre_archivo_markdown(titulo)
    with open(ruta_archivo, "w", encoding="utf-8") as archivo:
        archivo.write(markdown)
    print(f"  OK ({tipo}): {ruta_archivo}")
    return True


def generar_markdowns_recursos(datos: dict, carpeta: Path = ADMISION_DOCTORADO_RECURSOS_DIR,
                                catalogo_anterior: list[dict] | None = None) -> tuple[int, int, int]:
    carpeta.mkdir(parents=True, exist_ok=True)
    url_resumen = datos["url"]

    total = correctos = errores = 0
    elementos_escritos = []
    for recurso in datos.get("recursos", []):
        total += 1
        if generar_markdown_recurso(recurso, recurso["seccion_id"], carpeta, url_resumen):
            correctos += 1
            elementos_escritos.append(recurso)
        else:
            errores += 1
        time.sleep(0.3)

    borrados = ml.limpiar_ficheros_renombrados(catalogo_anterior or [], elementos_escritos, carpeta)
    return total, correctos, borrados


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    catalogo_anterior = cargar_recursos_anteriores()

    datos = extraer_catalogo()
    guardar_json(datos)
    generar_markdown_padre(datos)
    generar_markdowns_secciones(datos)

    total, correctos, borrados = generar_markdowns_recursos(datos, catalogo_anterior=catalogo_anterior)
    print(f"Admisión doctorado: recursos {total} · generados: {correctos} · renombrados limpiados: {borrados}")


if __name__ == "__main__":
    main()
