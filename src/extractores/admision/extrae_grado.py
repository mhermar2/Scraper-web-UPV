"""Extractor de "Admision a Grado" -- las 5 vias de acceso (Bachillerato,
Ciclos formativos, Titulados universitarios, Mayores de 25/40/45,
Vengo de otra universidad).

Reescritura completa (2026-08-21), mismo patron que los nuevos
extrae_master.py/extrae_doctorado.py: metadatos YAML definitivos y
motor_limpieza.py para el contenido de cada pagina ENLAZADA (traversal,
PDF, plantilla clasica, limpieza de renombrados) en vez del loop
h1-h4/p/li/table ad-hoc anterior. La maquetacion de cada via en
<section id="section-01">..<section id="section-06"> (con tarjetas
".card-bg" y acordeones, distinto de ".box-number-box" que usan
master/doctorado -- comprobado que ambas clases coexisten en el DOM de
las 3 paginas, se respeta la eleccion de selector que ya tenia cada
extractor) se mantiene con extraccion estructurada propia para el padre
y secciones de cada via.

Cada via es un arbol "resumen" independiente (nivel=grado en las 5, pero
url/resumen propios de esa via) -- no hay una pagina combinada que las
englobe a las 5, asi que no se genera ningun indice nuevo que no
existiera ya.

Se preserva el filtro de "contenido claramente ajeno" (2+ senales de
doctorado/personal investigador/alumni... en el mismo recurso) que ya
tenia esta seccion: los acordeones de la web comparten a veces widgets
con otras vias de admision, y sin este filtro se cuela contenido que no
es de grado.
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
from config import ADMISION_GRADO_DIR, ADMISION_GRADO_FUENTES, ADMISION_GRADO_JSON
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
NIVEL = "grado"
TIPO_RECURSO = "informacion"

INTRO_DOCUMENTO = (
    "Información completa sobre el proceso de admisión "
    "a estudios oficiales de grado en la Universitat Politècnica de València."
)

SELECTORES_CONTENIDO = ["main", "article", ".entry-content", "#content", ".content", ".entry", ".mwc_contenido"]

# Filtro conservador: solo descarta un recurso si aparecen 2+ senales de
# contenido claramente ajeno a grado (doctorado, personal investigador,
# alumni...) a la vez -- una coincidencia aislada no basta.
PATRONES_AJENOS = [
    "doctorado", "tesis doctoral", "doctorando",
    "personal docente e investigador", "personal investigador", "pdi", "profesorado",
    "proyecto de investigación", "proyectos de investigación", "grupo de investigación", "grupos de investigación",
    "empresa de base tecnológica", "spin-off", "transferencia tecnológica",
    "antiguos alumnos", "exalumnos",
]


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


# ==========================================================
# 1. Catalogo de cada via (padre + secciones con tarjetas/acordeones/banners)
# ==========================================================

def extraer_tarjetas(seccion, base: str) -> list[dict]:
    tarjetas = []
    for card in seccion.select(".card-bg"):
        titulo = texto_limpio(card.find(["h3", "h4"]))
        descripcion = ""
        p = card.find("p", class_="text-sm")
        if p:
            descripcion = texto_limpio(p)
        tarjetas.append({"titulo": titulo, "descripcion": descripcion, "url": primer_enlace(card, base)})
    return tarjetas


def extraer_banners(seccion, base: str) -> list[dict]:
    banners = []
    for banner in seccion.select(".banner"):
        titulo = texto_limpio(banner.find(["h3", "h4"]))
        descripcion = ""
        p = banner.find("p")
        if p:
            descripcion = texto_limpio(p)
        banners.append({"titulo": titulo, "descripcion": descripcion, "url": primer_enlace(banner, base)})
    return banners


def extraer_acordeones(seccion, base: str) -> list[dict]:
    acordeones = []
    for bloque in seccion.select(".accordion-element-content"):
        titulo = texto_limpio(bloque.find(["h3", "h4"]))
        texto = texto_limpio(bloque)
        enlaces = []
        vistos = set()
        for a in bloque.find_all("a", href=True):
            href = url_absoluta(a["href"], base)
            if not href or href in vistos:
                continue
            vistos.add(href)
            enlaces.append({"texto": texto_limpio(a), "url": href})
        acordeones.append({"titulo": titulo, "texto": texto, "enlaces": enlaces, "banners": extraer_banners(bloque, base)})
    return acordeones


def extraer_padre(nombre_fuente: str, url: str) -> dict | None:
    print("=" * 70)
    print(nombre_fuente, "-", url)
    try:
        respuesta = requests.get(url, headers=HEADERS, timeout=30)
        respuesta.raise_for_status()
    except Exception as error:
        print("  ERROR:", error)
        return None
    soup = BeautifulSoup(respuesta.text, "html.parser")

    main = soup.find("main", class_="search-page")
    if main is None:
        print("  AVISO: no se ha encontrado <main class=\"search-page\">.")
        return None

    titulo_padre = texto_limpio(soup.find("h1")) or nombre_fuente

    secciones = []
    for i in range(1, 7):
        seccion_html = main.find(id=f"section-{i:02d}")
        if seccion_html is None:
            continue

        titulo_seccion, descripcion_seccion = "", ""
        info = seccion_html.find("div", class_="col-4")
        if info:
            h = info.find(["h2", "h3"])
            if h:
                titulo_seccion = texto_limpio(h)
            p = info.find("p", class_="text-sm")
            if p:
                descripcion_seccion = texto_limpio(p)
        if not titulo_seccion:
            continue

        secciones.append({
            "id": ml.normalizar_identificador(titulo_seccion) or f"seccion_{i:02d}",
            "titulo": titulo_seccion,
            "descripcion": descripcion_seccion,
            "tarjetas": extraer_tarjetas(seccion_html, url),
            "acordeones": extraer_acordeones(seccion_html, url),
        })

    recursos = []
    urls_vistas = set()
    for seccion in secciones:
        for tarjeta in seccion["tarjetas"]:
            if tarjeta.get("url") and tarjeta["url"] not in urls_vistas:
                urls_vistas.add(tarjeta["url"])
                recursos.append({"titulo": tarjeta["titulo"], "url": tarjeta["url"], "seccion_id": seccion["id"]})
        for acordeon in seccion["acordeones"]:
            for enlace in acordeon["enlaces"]:
                if enlace.get("url") and enlace["url"] not in urls_vistas:
                    urls_vistas.add(enlace["url"])
                    recursos.append({"titulo": enlace["texto"], "url": enlace["url"], "seccion_id": seccion["id"]})
            for banner in acordeon["banners"]:
                if banner.get("url") and banner["url"] not in urls_vistas:
                    urls_vistas.add(banner["url"])
                    recursos.append({"titulo": banner["titulo"], "url": banner["url"], "seccion_id": seccion["id"]})

    return {"titulo": titulo_padre, "url": url, "secciones": secciones, "recursos": recursos}


def extraer_catalogo(fuentes: list[tuple[str, str, str]] = ADMISION_GRADO_FUENTES) -> dict:
    padres = []
    for nombre_fuente, url, carpeta_corta in fuentes:
        pagina = extraer_padre(nombre_fuente, url)
        if pagina is not None:
            pagina["carpeta"] = carpeta_corta
            padres.append(pagina)
    print("Vías de acceso extraídas:", len(padres), "de", len(fuentes))
    return {"fuente": "https://www.upv.es/admision/", "padres": padres}


def guardar_json(datos: dict, ruta: Path = ADMISION_GRADO_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


def cargar_recursos_anteriores(ruta: Path = ADMISION_GRADO_JSON) -> dict[str, list[dict]]:
    """{carpeta_corta: [{"titulo","url"}, ...]} de la ejecucion
    anterior -- debe llamarse ANTES de guardar_json()."""
    if not ruta.exists():
        return {}
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
    except Exception:
        return {}
    resultado = {}
    for padre in datos.get("padres", []):
        carpeta = padre.get("carpeta", "")
        resultado[carpeta] = [{"titulo": r["titulo"], "url": r["url"]} for r in padre.get("recursos", []) if r.get("titulo") and r.get("url")]
    return resultado


# ==========================================================
# 2. Markdown de padre + secciones de cada via (vuelca el JSON)
# ==========================================================

def _escribir_bloque_seccion(f, seccion: dict, nivel_titulo: str, prefijo_enlace: str) -> None:
    for t in seccion.get("tarjetas", []):
        if t.get("titulo"):
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
        if acc.get("enlaces"):
            f.write("\n")
        for banner in acc.get("banners", []):
            if banner.get("titulo"):
                f.write(f"{nivel_titulo} {banner['titulo']}\n\n")
            if banner.get("descripcion"):
                f.write(banner["descripcion"] + "\n\n")
            if banner.get("url"):
                f.write(f"{prefijo_enlace}: {banner['url']}\n\n")


def generar_markdowns_padre_y_secciones(datos: dict, directorio: Path = ADMISION_GRADO_DIR) -> int:
    directorio.mkdir(parents=True, exist_ok=True)
    contador = 0

    for padre in datos["padres"]:
        carpeta_padre = directorio / padre["carpeta"]
        carpeta_padre.mkdir(parents=True, exist_ok=True)

        nombre_padre = ml.nombre_archivo_markdown(padre["titulo"])
        with open(carpeta_padre / nombre_padre, "w", encoding="utf-8") as f:
            f.write(_yaml_resumen(padre["url"], padre["titulo"]))
            f.write(f"\n# {padre['titulo']}\n\n")
            f.write(INTRO_DOCUMENTO + "\n\n")
            for seccion in padre["secciones"]:
                f.write(f"## {seccion['titulo']}\n\n")
                if seccion.get("descripcion"):
                    f.write(seccion["descripcion"] + "\n\n")
                _escribir_bloque_seccion(f, seccion, "###", "Más información")
        contador += 1

        for seccion in padre["secciones"]:
            nombre_seccion = ml.nombre_archivo_markdown(seccion["titulo"])
            with open(carpeta_padre / nombre_seccion, "w", encoding="utf-8") as f:
                f.write(_yaml_seccion(padre["url"], seccion["titulo"]))
                f.write(f"\n# {seccion['titulo']}\n\n")
                f.write(f"Proceso de admisión: {padre['titulo']}\n\n")
                if seccion.get("descripcion"):
                    f.write(seccion["descripcion"] + "\n\n")
                _escribir_bloque_seccion(f, seccion, "##", "Enlace oficial")
            contador += 1

    print("Markdown de padre/secciones generado. Archivos:", contador)
    return contador


# ==========================================================
# 3. Markdown de los recursos enlazados -- motor_limpieza
# ==========================================================

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


def contenido_claramente_ajeno(titulo: str, cuerpo: str, url: str) -> bool:
    texto = (titulo + " " + cuerpo + " " + url).lower()
    return sum(1 for patron in PATRONES_AJENOS if patron in texto) >= 2


def generar_markdown_recurso(elemento: dict, seccion_slug: str, carpeta: Path, url_resumen: str) -> bool:
    titulo = elemento.get("titulo", "")
    url = elemento.get("url", "")
    if not titulo or not url:
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
        if contenido_claramente_ajeno(titulo, cuerpo, url):
            print("    Descartado (contenido claramente ajeno a grado).")
            return False

    markdown = f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n{cuerpo}\n"

    ruta_archivo = carpeta / ml.nombre_archivo_markdown(titulo)
    with open(ruta_archivo, "w", encoding="utf-8") as archivo:
        archivo.write(markdown)
    print(f"  OK ({tipo}): {ruta_archivo}")
    return True


def generar_markdowns_recursos(datos: dict, directorio_base: Path = ADMISION_GRADO_DIR,
                                catalogo_anterior: dict[str, list[dict]] | None = None) -> tuple[int, int, int]:
    total = correctos = 0
    borrados_totales = 0

    for padre in datos["padres"]:
        carpeta_recursos = directorio_base / padre["carpeta"] / "recursos"
        carpeta_recursos.mkdir(parents=True, exist_ok=True)

        elementos_escritos = []
        for recurso in padre.get("recursos", []):
            total += 1
            if generar_markdown_recurso(recurso, recurso["seccion_id"], carpeta_recursos, padre["url"]):
                correctos += 1
                elementos_escritos.append(recurso)
            time.sleep(0.3)

        anteriores = (catalogo_anterior or {}).get(padre["carpeta"], [])
        borrados_totales += ml.limpiar_ficheros_renombrados(anteriores, elementos_escritos, carpeta_recursos)

    return total, correctos, borrados_totales


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    catalogo_anterior = cargar_recursos_anteriores()

    datos = extraer_catalogo()
    guardar_json(datos)
    generar_markdowns_padre_y_secciones(datos)

    total, correctos, borrados = generar_markdowns_recursos(datos, catalogo_anterior=catalogo_anterior)
    print(f"Admisión grado: recursos {total} · generados: {correctos} · renombrados limpiados: {borrados}")


if __name__ == "__main__":
    main()
