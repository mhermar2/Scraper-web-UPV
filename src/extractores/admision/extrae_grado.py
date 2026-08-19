"""Extractor de "Admision a Grado" -- las 5 vias de acceso (Bachillerato,
Ciclos formativos, Titulados universitarios, Mayores de 25/40/45,
Vengo de otra universidad) en un unico pipeline con un "padre" por via.

Patron propio: secciones section-01..section-06 con tarjetas (.card-bg)
y acordeones (que a su vez pueden contener banners anidados). Sigue
ademas las URLs enlazadas para generar recursos adicionales, con el
mismo filtro conservador de "contenido claramente ajeno" que master.

Pipeline (mismo orden que el notebook original):
  1. extraer_admision_grado() -> JSON con 5 "padres" (uno por via de
     acceso), cada uno con sus secciones
  2. guardar_json()
  3. generar_markdowns_secciones() -> 1 .md padre + 1 .md por seccion,
     por cada una de las 5 vias
  4. recopilar_enlaces() -> aplana tarjetas/acordeones(enlaces+banners)
     de todas las secciones y vias, deduplicando por (padre,seccion,url)
  5. descargar_y_extraer_paginas() -> visita cada URL de verdad
  6. generar_markdowns_recursos() -> un .md por pagina util, clasificada,
     dentro de la carpeta de SU via de acceso correspondiente

Migrado desde src/extractores/admision/extrae_grado.py (antes
Sacar_Admision_Grado.ipynb). Notebook completo y limpio -- unica celda
descartada: la "COMPROBACIÓN DEL JSON" (prints de estadisticas +
pprint.pprint de un padre concreto), pura inspeccion sin efecto en el
resultado.

Nota sobre nombres de carpeta: el notebook original nombraba la carpeta
de cada via de acceso con el slug largo derivado del <title> de su
pagina (ej. "admision_grado_bachillerato_upv_universitat_politecnica_de_valencia"),
igual que el nombre de su .md padre. En este repo esas carpetas ya se
renombraron a los nombres cortos (bachillerato, ciclos_formativos...) al
reorganizar data/processed/ -- ver config.ADMISION_GRADO_FUENTES. El
nombre de archivo del .md padre en si mismo SI se deja con el slug largo
original, sin renombrar.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bs4 import BeautifulSoup
import requests

from config import ADMISION_GRADO_DIR, ADMISION_GRADO_FUENTES, ADMISION_GRADO_JSON

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; UPV-Admision-Bot/1.0)"}
PAUSA = 0.3

CATEGORIA = "admision"
NIVEL = "grado"

INTRO_DOCUMENTO = (
    "Información completa sobre el proceso de admisión "
    "a estudios oficiales de grado en la Universitat Politècnica de València."
)

DOMINIOS_UPV = {"www.upv.es", "upv.es"}

PATRONES_AJENOS = [
    "doctorado", "tesis doctoral", "doctorando",
    "personal docente e investigador", "personal investigador", "pdi", "profesorado",
    "proyecto de investigación", "proyectos de investigación", "grupo de investigación", "grupos de investigación",
    "empresa de base tecnológica", "spin-off", "transferencia tecnológica",
    "antiguos alumnos", "exalumnos",
]

CLASIFICACION = [
    ("calendario", ["plazo", "calendario", "calendarios", "fechas"]),
    ("matricula", ["matricula", "matrícula", "tasas", "precio", "precios"]),
    ("faq", ["faq", "faqs", "preguntas frecuentes"]),
    ("ayudas", ["beca", "becas", "ayuda", "ayudas"]),
    ("admision", ["admision", "admisión", "preinscripcion", "preinscripción", "solicitud", "acceso"]),
    ("estudios", ["grado", "grados", "estudio", "estudios", "titulacion", "titulación", "titulaciones", "oferta academica", "oferta académica"]),
    ("normativa", ["normativa", "reglamento", "legislacion", "legislación"]),
]


def limpiar_texto(txt: str | None) -> str:
    if txt is None:
        return ""
    return re.sub(r"\s+", " ", txt).strip()


def normalizar_url(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme, p.netloc, p.path, "", "", ""))


def get(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        time.sleep(PAUSA)
        return BeautifulSoup(r.text, "html.parser")
    except Exception:
        return None


def texto(tag, selector: str | None = None) -> str:
    if selector is not None:
        tag = tag.select_one(selector)
    if tag is None:
        return ""
    return limpiar_texto(tag.get_text(" ", strip=True))


def url_absoluta(base: str, href: str) -> str:
    if not href:
        return ""
    return normalizar_url(urljoin(base, href))


# ==========================================================
# 1. Extraccion del padre (una via de acceso)
# ==========================================================

def extraer_padre(url: str) -> dict | None:
    print(url)
    soup = get(url)
    if soup is None:
        return None

    titulo = limpiar_texto(soup.title.get_text()) if soup.title else ""

    main = soup.find("main", class_="search-page")
    if main is None:
        return None

    pagina = {"titulo": titulo, "url": normalizar_url(url), "secciones": []}

    for i in range(1, 7):
        sec = main.find(id=f"section-{i:02d}")
        if sec is None:
            continue

        titulo_sec = ""
        descripcion_sec = ""
        info = sec.find("div", class_="col-4")
        if info:
            h = info.find(["h2", "h3"])
            if h:
                titulo_sec = limpiar_texto(h.get_text())
            p = info.find("p", class_="text-sm")
            if p:
                descripcion_sec = limpiar_texto(p.get_text())

        datos_seccion = {"id": f"section-{i:02d}", "titulo": titulo_sec, "descripcion": descripcion_sec, "tarjetas": [], "acordeones": []}

        for card in sec.select(".card-bg"):
            titulo_card = ""
            descripcion_card = ""
            enlace_card = None

            h = card.find(["h3", "h4"])
            if h:
                titulo_card = limpiar_texto(h.get_text())
            p = card.find("p", class_="text-sm")
            if p:
                descripcion_card = limpiar_texto(p.get_text())
            a = card.find("a", href=True)
            if a:
                enlace_card = normalizar_url(urljoin(url, a["href"]))

            datos_seccion["tarjetas"].append({"titulo": titulo_card, "descripcion": descripcion_card, "url": enlace_card})

        for acc in sec.select(".accordion-element-content"):
            titulo_acc = ""
            h = acc.find(["h3", "h4"])
            if h:
                titulo_acc = limpiar_texto(h.get_text())

            texto_acc = limpiar_texto(acc.get_text(" "))

            enlaces = []
            vistos = set()
            for a in acc.find_all("a", href=True):
                href = normalizar_url(urljoin(url, a["href"]))
                if href in vistos:
                    continue
                vistos.add(href)
                enlaces.append({"texto": limpiar_texto(a.get_text(" ")), "url": href})

            banners = []
            for banner in acc.select(".banner"):
                titulo_banner = ""
                descripcion_banner = ""
                enlace_banner = None
                h = banner.find(["h3", "h4"])
                if h:
                    titulo_banner = limpiar_texto(h.get_text())
                p = banner.find("p")
                if p:
                    descripcion_banner = limpiar_texto(p.get_text(" "))
                a = banner.find("a", href=True)
                if a:
                    enlace_banner = normalizar_url(urljoin(url, a["href"]))
                banners.append({"titulo": titulo_banner, "descripcion": descripcion_banner, "url": enlace_banner})

            datos_seccion["acordeones"].append({"titulo": titulo_acc, "texto": texto_acc, "enlaces": enlaces, "banners": banners})

        pagina["secciones"].append(datos_seccion)

    return pagina


def extraer_admision_grado(fuentes: list[tuple[str, str, str]] = ADMISION_GRADO_FUENTES) -> dict:
    padres = []
    for nombre_fuente, url, _carpeta_corta in fuentes:
        print("=" * 70)
        print(nombre_fuente, "-", url)
        pagina = extraer_padre(url)
        if pagina is not None:
            padres.append(pagina)

    return {"fuente": "https://www.upv.es/admision/", "total_padres": len(padres), "padres": padres}


def guardar_json(datos: dict, ruta: Path = ADMISION_GRADO_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


def mapa_padre_a_carpeta(datos: dict, fuentes: list[tuple[str, str, str]] = ADMISION_GRADO_FUENTES) -> dict[str, str]:
    """Construye {titulo_padre: carpeta_corta} cruzando datos['padres']
    (que solo trae la URL normalizada de cada padre) con
    ADMISION_GRADO_FUENTES (que sabe la carpeta corta de cada URL de
    origen) -- ver docstring del modulo sobre por que las carpetas no
    usan el slug largo del <title> como hacia el notebook original."""
    urls_a_carpeta = {normalizar_url(url): carpeta for _nombre, url, carpeta in fuentes}
    mapa = {}
    for padre in datos.get("padres", []):
        carpeta = urls_a_carpeta.get(normalizar_url(padre["url"]))
        mapa[padre["titulo"]] = carpeta or (limpiar_nombre(padre["titulo"]) or "padre")
    return mapa


# ==========================================================
# 2. Markdown de padre + secciones (vuelca el JSON, sin descargar nada)
# ==========================================================

def limpiar_nombre(nombre) -> str:
    nombre = str(nombre).lower().strip()
    for viejo, nuevo in {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"}.items():
        nombre = nombre.replace(viejo, nuevo)
    return re.sub(r"[^a-z0-9]+", "_", nombre).strip("_")


def _escribir_metadatos(f, tipo_documento: str, seccion: str | None = None) -> None:
    f.write("---\n")
    f.write("fuente: UPV\n")
    f.write(f"categoria: {CATEGORIA}\n")
    f.write(f"nivel: {NIVEL}\n")
    f.write(f"tipo_documento: {tipo_documento}\n")
    if seccion:
        f.write(f"seccion: {seccion}\n")
    f.write("---\n\n")


def generar_markdowns_secciones(datos: dict, directorio: Path = ADMISION_GRADO_DIR) -> int:
    directorio.mkdir(parents=True, exist_ok=True)
    mapa_carpetas = mapa_padre_a_carpeta(datos)
    contador = 0

    for padre in datos["padres"]:
        nombre_padre_archivo = limpiar_nombre(padre["titulo"])
        carpeta_padre = directorio / mapa_carpetas[padre["titulo"]]
        carpeta_padre.mkdir(parents=True, exist_ok=True)

        # El notebook original escribia el .md padre en directorio_base
        # (plano, ADMISION/Grado/). En la reorganizacion de data/ ya se
        # movieron esos 5 ficheros dentro de la subcarpeta de su propia
        # categoria -- se escribe ahi para reflejar la estructura actual.
        with open(carpeta_padre / f"{nombre_padre_archivo}.md", "w", encoding="utf-8") as f:
            _escribir_metadatos(f, "padre")
            f.write(f"# {padre['titulo']}\n\n")
            f.write(INTRO_DOCUMENTO + "\n\n")

            for seccion in padre.get("secciones", []):
                f.write(f"## {seccion['titulo']}\n\n")
                if seccion.get("descripcion"):
                    f.write(seccion["descripcion"] + "\n\n")

                for tarjeta in seccion.get("tarjetas", []):
                    if tarjeta.get("titulo"):
                        f.write(f"### {tarjeta['titulo']}\n\n")
                    if tarjeta.get("descripcion"):
                        f.write(tarjeta["descripcion"] + "\n\n")
                    if tarjeta.get("url"):
                        f.write(f"Más información: {tarjeta['url']}\n\n")

                for acordeon in seccion.get("acordeones", []):
                    if acordeon.get("titulo"):
                        f.write(f"### {acordeon['titulo']}\n\n")
                    if acordeon.get("texto"):
                        f.write(acordeon["texto"] + "\n\n")
                    for enlace in acordeon.get("enlaces", []):
                        if enlace.get("texto") and enlace.get("url"):
                            f.write(f"- {enlace['texto']}: {enlace['url']}\n")
                    if acordeon.get("enlaces"):
                        f.write("\n")
                    for banner in acordeon.get("banners", []):
                        if banner.get("titulo"):
                            f.write(f"#### {banner['titulo']}\n\n")
                        if banner.get("descripcion"):
                            f.write(banner["descripcion"] + "\n\n")
                        if banner.get("url"):
                            f.write(f"Más información: {banner['url']}\n\n")
        contador += 1

        for seccion in padre.get("secciones", []):
            nombre_seccion = limpiar_nombre(seccion["titulo"])

            with open(carpeta_padre / f"{nombre_seccion}.md", "w", encoding="utf-8") as f:
                _escribir_metadatos(f, "seccion", nombre_seccion)
                f.write(f"# {seccion['titulo']}\n\n")
                f.write(f"Proceso de admisión: {padre['titulo']}\n\n")
                if seccion.get("descripcion"):
                    f.write(seccion["descripcion"] + "\n\n")

                for tarjeta in seccion.get("tarjetas", []):
                    if tarjeta.get("titulo"):
                        f.write(f"## {tarjeta['titulo']}\n\n")
                    if tarjeta.get("descripcion"):
                        f.write(tarjeta["descripcion"] + "\n\n")
                    if tarjeta.get("url"):
                        f.write(f"Enlace oficial: {tarjeta['url']}\n\n")

                for acordeon in seccion.get("acordeones", []):
                    if acordeon.get("titulo"):
                        f.write(f"## {acordeon['titulo']}\n\n")
                    if acordeon.get("texto"):
                        f.write(acordeon["texto"] + "\n\n")
                    for enlace in acordeon.get("enlaces", []):
                        if enlace.get("texto") and enlace.get("url"):
                            f.write(f"- {enlace['texto']}: {enlace['url']}\n")
                    if acordeon.get("enlaces"):
                        f.write("\n")
                    for banner in acordeon.get("banners", []):
                        if banner.get("titulo"):
                            f.write(f"## {banner['titulo']}\n\n")
                        if banner.get("descripcion"):
                            f.write(banner["descripcion"] + "\n\n")
                        if banner.get("url"):
                            f.write(f"Enlace oficial: {banner['url']}\n\n")
            contador += 1

    print("Markdown de secciones generado. Archivos:", contador)
    return contador


# ==========================================================
# 3. Recopilar enlaces de todas las vias/secciones
# ==========================================================

def recopilar_enlaces(datos: dict) -> list[dict]:
    lista_enlaces = []
    vistos = set()

    for padre in datos["padres"]:
        titulo_padre = padre["titulo"]

        for seccion in padre["secciones"]:
            titulo_seccion = seccion["titulo"]

            for tarjeta in seccion.get("tarjetas", []):
                url = tarjeta.get("url")
                if not url:
                    continue
                url = normalizar_url(url)
                if not url:
                    continue
                clave = (titulo_padre, titulo_seccion, url)
                if clave in vistos:
                    continue
                vistos.add(clave)
                lista_enlaces.append({"url": url, "texto": tarjeta.get("titulo", ""), "seccion_origen": titulo_seccion, "padre_origen": titulo_padre, "tipo_origen": "tarjeta"})

            for acordeon in seccion.get("acordeones", []):
                for enlace in acordeon.get("enlaces", []):
                    url = enlace.get("url")
                    if not url:
                        continue
                    url = normalizar_url(url)
                    if not url:
                        continue
                    clave = (titulo_padre, titulo_seccion, url)
                    if clave in vistos:
                        continue
                    vistos.add(clave)
                    lista_enlaces.append({"url": url, "texto": enlace.get("texto", ""), "seccion_origen": titulo_seccion, "padre_origen": titulo_padre, "tipo_origen": "acordeon"})

                for banner in acordeon.get("banners", []):
                    url = banner.get("url")
                    if not url:
                        continue
                    url = normalizar_url(url)
                    if not url:
                        continue
                    clave = (titulo_padre, titulo_seccion, url)
                    if clave in vistos:
                        continue
                    vistos.add(clave)
                    lista_enlaces.append({"url": url, "texto": banner.get("titulo", ""), "seccion_origen": titulo_seccion, "padre_origen": titulo_padre, "tipo_origen": "banner"})

    print("Enlaces encontrados:", len(lista_enlaces))
    return lista_enlaces


# ==========================================================
# 4. Descargar, filtrar y extraer paginas enlazadas
# ==========================================================

def normalizar_url_final(url: str) -> str | None:
    if not url:
        return None
    p = urlparse(url)
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", "", p.query, ""))


def es_url_grado(url: str) -> bool:
    """Se acepta cualquier recurso del ecosistema principal de la UPV
    (www.upv.es, upv.es, subdominios *.upv.es), sin restringir por rutas
    concretas -- paginas utiles pueden estar en distintas zonas del
    portal."""
    if not url:
        return False
    try:
        dominio = urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return False
    return dominio in DOMINIOS_UPV or dominio.endswith(".upv.es")


def eliminar_basura(soup: BeautifulSoup) -> None:
    for elemento in soup.find_all(["script", "style", "noscript", "header", "footer", "nav", "aside", "form", "iframe"]):
        elemento.decompose()


def encontrar_contenido_principal(soup: BeautifulSoup):
    for selector in ["main", "article", "#content", ".content", ".container", ".main-content"]:
        elemento = soup.select_one(selector)
        if elemento is not None and len(elemento.get_text(" ", strip=True)) >= 100:
            return elemento
    body = soup.find("body")
    if body is not None and len(body.get_text(" ", strip=True)) >= 100:
        return body
    return None


def normalizar_texto_para_comparacion(texto_: str) -> str:
    return " ".join(texto_.lower().split())


def contenido_claramente_ajeno(titulo: str, contenido: str, url: str) -> bool:
    """Filtro deliberadamente conservador: solo descarta con 2+ senales
    simultaneas de contenido ajeno (doctorado, personal investigador,
    alumni...)."""
    texto_ = (titulo + " " + contenido + " " + url).lower()
    return sum(1 for patron in PATRONES_AJENOS if patron in texto_) >= 2


def contenido_demasiado_corto(contenido: str) -> bool:
    return len(contenido.strip()) < 100


def descargar_y_extraer_paginas(enlaces_unicos: list[dict]) -> list[dict]:
    paginas_extraidas = []
    vistos_urls_finales = set()
    sesion = requests.Session()
    sesion.headers.update(HEADERS)

    for enlace in enlaces_unicos:
        url_original = enlace["url"]
        print(url_original)

        if not es_url_grado(url_original):
            print("Descartado (URL fuera del ámbito útil)")
            continue

        try:
            respuesta = sesion.get(url_original, timeout=20, allow_redirects=True)
            respuesta.raise_for_status()
        except Exception as e:
            print("Error de descarga:", e)
            continue

        url_final = normalizar_url_final(respuesta.url)

        if not es_url_grado(url_final):
            print("Descartado (URL final no útil)")
            continue
        if url_final in vistos_urls_finales:
            print("Descartado (URL final duplicada)")
            continue
        vistos_urls_finales.add(url_final)

        if "text/html" not in respuesta.headers.get("Content-Type", "").lower():
            print("Descartado (recurso no HTML)")
            continue

        soup = BeautifulSoup(respuesta.text, "html.parser")
        eliminar_basura(soup)

        contenido_principal = encontrar_contenido_principal(soup)
        if contenido_principal is None:
            print("Descartado (no se encontró contenido principal)")
            continue

        titulo = ""
        h1 = contenido_principal.find("h1")
        if h1:
            titulo = limpiar_texto(h1.get_text(" "))
        if not titulo:
            h1 = soup.find("h1")
            if h1:
                titulo = limpiar_texto(h1.get_text(" "))
        if not titulo:
            titulo = enlace.get("texto", "")
        titulo = limpiar_texto(titulo)

        bloques = []
        for elemento in contenido_principal.find_all(["h1", "h2", "h3", "h4", "p", "li", "table"]):
            texto_ = limpiar_texto(elemento.get_text(" ", strip=True))
            if len(texto_) < 3:
                continue
            if elemento.name == "h1" and normalizar_texto_para_comparacion(texto_) == normalizar_texto_para_comparacion(titulo):
                continue
            bloques.append(texto_)

        bloques_limpios = []
        for bloque in bloques:
            if bloques_limpios and normalizar_texto_para_comparacion(bloque) == normalizar_texto_para_comparacion(bloques_limpios[-1]):
                continue
            bloques_limpios.append(bloque)

        contenido = "\n\n".join(bloques_limpios)

        if contenido_demasiado_corto(contenido):
            print("Descartado (contenido insuficiente)")
            continue
        if contenido_claramente_ajeno(titulo, contenido, url_final):
            print("Descartado (contenido claramente ajeno)")
            continue

        paginas_extraidas.append({
            "url_original": url_original, "url": url_final, "titulo": titulo,
            "texto_enlace": enlace.get("texto", ""), "seccion_origen": enlace.get("seccion_origen", ""),
            "padre_origen": enlace.get("padre_origen", ""), "tipo_origen": enlace.get("tipo_origen", ""),
            "contenido": contenido,
        })
        print("Página aceptada")

    return paginas_extraidas


# ==========================================================
# 5. Markdown de los recursos (paginas enlazadas), por via de acceso
# ==========================================================

def clasificar_recurso(pagina: dict) -> str:
    texto_ = (pagina.get("titulo", "") + " " + pagina.get("url", "") + " " + pagina.get("seccion_origen", "")).lower()
    for tipo, palabras in CLASIFICACION:
        if any(palabra in texto_ for palabra in palabras):
            return tipo
    return "informacion"


def _escribir_metadatos_recurso(f, pagina: dict, tipo_recurso: str) -> None:
    f.write("---\n")
    f.write("fuente: UPV\n")
    f.write(f"categoria: {CATEGORIA}\n")
    f.write(f"nivel: {NIVEL}\n")
    f.write("tipo_documento: recurso\n")
    f.write(f"tipo_recurso: {tipo_recurso}\n")
    f.write("padre: " + limpiar_nombre(pagina.get("padre_origen", "")) + "\n")
    f.write("seccion: " + limpiar_nombre(pagina.get("seccion_origen", "")) + "\n")
    f.write(f"url: {pagina['url']}\n")
    f.write("---\n\n")


def generar_markdowns_recursos(paginas_extraidas: list[dict], datos: dict, directorio_base: Path = ADMISION_GRADO_DIR) -> int:
    mapa_carpetas = mapa_padre_a_carpeta(datos)

    paginas_unicas = []
    urls_vistas = set()
    for pagina in paginas_extraidas:
        url = pagina.get("url", "")
        if not url or url in urls_vistas:
            continue
        urls_vistas.add(url)
        paginas_unicas.append(pagina)

    contador = 0
    for pagina in paginas_unicas:
        padre_origen = pagina.get("padre_origen", "")
        seccion_origen = pagina.get("seccion_origen", "")

        if not padre_origen:
            print("Recurso omitido: no se encontró padre_origen")
            print(pagina.get("url", ""))
            continue

        carpeta_padre = directorio_base / mapa_carpetas.get(padre_origen, limpiar_nombre(padre_origen) or "padre")
        directorio_recursos = carpeta_padre / "recursos"
        directorio_recursos.mkdir(parents=True, exist_ok=True)

        tipo_recurso = clasificar_recurso(pagina)
        nombre = limpiar_nombre(pagina.get("titulo", "")) or "recurso"

        archivo = directorio_recursos / f"{nombre}.md"
        if archivo.exists():
            nombre_seccion = limpiar_nombre(seccion_origen)
            if nombre_seccion:
                archivo = directorio_recursos / f"{nombre}_{nombre_seccion}.md"

        contador_nombre = 2
        nombre_archivo_base = archivo.stem
        while archivo.exists():
            archivo = directorio_recursos / f"{nombre_archivo_base}_{contador_nombre}.md"
            contador_nombre += 1

        with open(archivo, "w", encoding="utf-8") as f:
            _escribir_metadatos_recurso(f, pagina, tipo_recurso)
            titulo = pagina.get("titulo", "Recurso UPV")
            f.write(f"# {titulo}\n\n")
            f.write(
                "Recurso relacionado con el proceso de admisión a estudios "
                "oficiales de grado en la Universitat Politècnica de València.\n\n"
            )
            if padre_origen:
                f.write(f"Proceso de admisión: {padre_origen}\n\n")
            if seccion_origen:
                f.write(f"Sección de origen: {seccion_origen}\n\n")

            contenido = pagina.get("contenido", "")
            if contenido:
                f.write(contenido + "\n\n")

            f.write(f"Fuente oficial: {pagina['url']}\n")

        contador += 1

    print("Markdown de recursos generado. Archivos:", contador)
    return contador


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    datos = extraer_admision_grado()
    guardar_json(datos)
    generar_markdowns_secciones(datos)

    enlaces = recopilar_enlaces(datos)
    paginas_extraidas = descargar_y_extraer_paginas(enlaces)
    generar_markdowns_recursos(paginas_extraidas, datos)


if __name__ == "__main__":
    main()
