"""Extractor de "Admision a Master".

Patron propio, distinto de institucion/servicios/rankings: la pagina de
admision-master esta dividida en <section id="section-01">..
<section id="section-06"> con tarjetas/acordeones/banners/enlaces
propios de esa maquetacion, no motor de "hoja de contenido" generico.
Ademas de la pagina raiz, sigue las URLs que encuentra en el JSON,
descarga cada una y genera un recurso adicional -- con un clasificador
por palabras clave (calendario/matricula/faq/ayudas/admision/programas/
normativa/informacion) y un filtro conservador para descartar contenido
"claramente ajeno" (doctorado, personal investigador, alumni...) que a
veces cuelga de los mismos acordeones.

Pipeline (mismo orden que el notebook original):
  1. extraer_admision_master() -> JSON con el padre + hasta 6 secciones
     (tarjetas, acordeones, banners, enlaces)
  2. guardar_json()
  3. generar_markdowns_secciones() -> 1 .md padre + 1 .md por seccion,
     volcando directamente el JSON (no vuelve a descargar nada)
  4. recopilar_urls_candidatas() -> aplana tarjetas/acordeones/banners/
     enlaces de todas las secciones en una lista de URLs unicas
  5. descargar_y_extraer_paginas() -> visita cada URL de verdad,
     filtra por dominio/tipo de contenido/longitud/temática ajena
  6. generar_markdowns_recursos() -> un .md por pagina util, clasificada
     por tipo, con proteccion anticolision de nombres de archivo

Migrado desde src/extractores/admision/extrae_master.ipynb (antes
Extrae_Admision_Master.ipynb). Notebook limpio, sin celdas
exploratorias ni codigo muerto que descartar -- se unifico
limpiar_nombre/limpiar_nombre_recurso (funcionalmente identicas, con
distinto valor por defecto) en una sola funcion.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bs4 import BeautifulSoup
import requests

from config import ADMISION_MASTER_DIR, ADMISION_MASTER_JSON, ADMISION_MASTER_RECURSOS_DIR, ADMISION_MASTER_URL

HEADERS = {"User-Agent": "Mozilla/5.0"}

CATEGORIA = "admision"
NIVEL = "master"

INTRO_DOCUMENTO = (
    "Información completa sobre el proceso de admisión "
    "a estudios oficiales de máster en la Universitat Politècnica de València."
)

DOMINIOS_UPV = {"www.upv.es", "upv.es", "www.jpa.upv.es", "jpa.upv.es"}

PATRONES_AJENOS = [
    "doctorado", "tesis doctoral", "doctorando",
    "personal docente e investigador", "personal investigador", "pdi", "profesorado",
    "proyecto de investigación", "proyectos de investigación", "grupo de investigación", "grupos de investigación",
    "empresa de base tecnológica", "spin-off", "transferencia tecnológica",
    "antiguos alumnos", "exalumnos",
]

CLASIFICACION = [
    ("calendario", ["plazo", "plazos", "calendario", "calendarios", "fecha", "fechas"]),
    ("matricula", ["precio", "precios", "tasa", "tasas", "matricula", "matrícula"]),
    ("faq", ["faq", "faqs", "preguntas frecuentes"]),
    ("ayudas", ["ayuda", "ayudas", "beca", "becas"]),
    ("admision", ["solicitud", "solicitudes", "preinscripcion", "preinscripción", "admision", "admisión", "acceso"]),
    ("programas", ["master", "máster", "estudios", "oferta", "programa", "programas"]),
    ("normativa", ["normativa", "reglamento", "legislacion", "legislación", "normas"]),
]


def texto_limpio(elemento) -> str:
    return " ".join(elemento.stripped_strings) if elemento is not None else ""


def url_absoluta(url: str, base: str = ADMISION_MASTER_URL) -> str:
    return urljoin(base, url) if url else ""


def primer_enlace(elemento, base: str = ADMISION_MASTER_URL) -> str:
    if elemento is None:
        return ""
    enlace = elemento.find("a", href=True)
    return url_absoluta(enlace["href"], base) if enlace else ""


def obtener_descripcion(contenedor) -> str:
    if contenedor is None:
        return ""
    parrafos = contenedor.find_all("p", recursive=False)
    return " ".join(texto_limpio(p) for p in parrafos).strip()


def limpiar_nombre(nombre: str, por_defecto: str = "") -> str:
    if not nombre:
        return por_defecto
    nombre = nombre.lower()
    for viejo, nuevo in {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"}.items():
        nombre = nombre.replace(viejo, nuevo)
    nombre = re.sub(r"[^a-z0-9]+", "_", nombre).strip("_")
    return nombre or por_defecto


# ==========================================================
# 1. Extraccion del JSON
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


def extraer_enlaces(seccion, base: str) -> list[dict]:
    enlaces = []
    vistos = set()
    for a in seccion.find_all("a", href=True):
        texto = texto_limpio(a)
        url = url_absoluta(a["href"], base)
        if not texto or url in vistos:
            continue
        vistos.add(url)
        enlaces.append({"texto": texto, "url": url})
    return enlaces


def extraer_admision_master(url: str = ADMISION_MASTER_URL) -> dict:
    respuesta = requests.get(url, headers=HEADERS)
    respuesta.raise_for_status()
    soup = BeautifulSoup(respuesta.text, "html.parser")

    titulo_padre = texto_limpio(soup.find("h1"))
    descripcion_padre = texto_limpio(soup.find("h2"))

    secciones_html = []
    for i in range(1, 7):
        seccion = soup.find("section", id=f"section-{i:02d}")
        if seccion is not None:
            secciones_html.append(seccion)

    padre = {"titulo": titulo_padre, "url": url, "descripcion": descripcion_padre, "secciones": []}

    for seccion in secciones_html:
        titulo = texto_limpio(seccion.find(["h2", "h3"]))
        padre["secciones"].append({
            "id": seccion.get("id"),
            "titulo": titulo,
            "descripcion": obtener_descripcion(seccion),
            "tarjetas": extraer_tarjetas(seccion, url),
            "acordeones": extraer_acordeones(seccion, url),
            "banners": extraer_banners(seccion, url),
            "enlaces": extraer_enlaces(seccion, url),
        })

    return {"padres": [padre]}


def guardar_json(datos: dict, ruta: Path = ADMISION_MASTER_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=4)
    print("JSON guardado:", ruta)


# ==========================================================
# 2. Markdown de padre + secciones (vuelca el JSON, sin descargar nada)
# ==========================================================

def _escribir_metadatos(f, tipo_documento: str, seccion: str | None = None) -> None:
    f.write("---\n")
    f.write("fuente: UPV\n")
    f.write(f"categoria: {CATEGORIA}\n")
    f.write(f"nivel: {NIVEL}\n")
    f.write(f"tipo_documento: {tipo_documento}\n")
    if seccion:
        f.write(f"seccion: {seccion}\n")
    f.write("---\n\n")


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


def generar_markdowns_secciones(datos: dict, directorio: Path = ADMISION_MASTER_DIR) -> int:
    directorio.mkdir(parents=True, exist_ok=True)
    contador = 0

    for padre in datos["padres"]:
        nombre_padre = limpiar_nombre(padre["titulo"], "padre")

        with open(directorio / f"{nombre_padre}.md", "w", encoding="utf-8") as f:
            _escribir_metadatos(f, "padre")
            f.write(f"# {padre['titulo']}\n\n")
            f.write(INTRO_DOCUMENTO + "\n\n")
            for seccion in padre["secciones"]:
                f.write(f"## {seccion['titulo']}\n\n")
                if seccion.get("descripcion"):
                    f.write(seccion["descripcion"] + "\n\n")
                _escribir_bloque_seccion(f, seccion, "###", "Más información")
        contador += 1

        for seccion in padre["secciones"]:
            nombre_seccion = limpiar_nombre(seccion["titulo"], "seccion")
            with open(directorio / f"{nombre_seccion}.md", "w", encoding="utf-8") as f:
                _escribir_metadatos(f, "seccion", nombre_seccion)
                f.write(f"# {seccion['titulo']}\n\n")
                f.write(f"Proceso: {padre['titulo']}\n\n")
                if seccion.get("descripcion"):
                    f.write(seccion["descripcion"] + "\n\n")
                _escribir_bloque_seccion(f, seccion, "##", "Enlace oficial")
            contador += 1

    print("Markdown de secciones generado. Archivos:", contador)
    return contador


# ==========================================================
# 3. Recopilar URLs candidatas del JSON
# ==========================================================

def normalizar_url_final(url: str) -> str | None:
    if not url:
        return None
    try:
        p = urlparse(url)
    except Exception:
        return None
    if not p.scheme or not p.netloc:
        return None
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", "", p.query, ""))


def es_url_upv(url: str) -> bool:
    if not url:
        return False
    try:
        return urlparse(url).netloc.lower() in DOMINIOS_UPV
    except Exception:
        return False


def recopilar_urls_candidatas(datos: dict) -> list[dict]:
    urls_candidatas = []
    urls_vistas = set()

    def _agregar(url_bruta, texto, seccion_origen, padre_origen, tipo_origen):
        if not url_bruta:
            return
        url = normalizar_url_final(url_bruta)
        if not url or url in urls_vistas:
            return
        urls_vistas.add(url)
        urls_candidatas.append({"url": url, "texto": texto, "seccion_origen": seccion_origen, "padre_origen": padre_origen, "tipo_origen": tipo_origen})

    for padre in datos["padres"]:
        for seccion in padre.get("secciones", []):
            for tarjeta in seccion.get("tarjetas", []):
                _agregar(tarjeta.get("url", ""), tarjeta.get("titulo", ""), seccion.get("titulo", ""), padre.get("titulo", ""), "tarjeta")
            for acordeon in seccion.get("acordeones", []):
                for enlace in acordeon.get("enlaces", []):
                    _agregar(enlace.get("url", ""), enlace.get("texto", ""), seccion.get("titulo", ""), padre.get("titulo", ""), "acordeon")
            for banner in seccion.get("banners", []):
                _agregar(banner.get("url", ""), banner.get("titulo", ""), seccion.get("titulo", ""), padre.get("titulo", ""), "banner")
            for enlace in seccion.get("enlaces", []):
                _agregar(enlace.get("url", ""), enlace.get("texto", ""), seccion.get("titulo", ""), padre.get("titulo", ""), "enlace")

    return urls_candidatas


# ==========================================================
# 4. Descargar, filtrar y extraer paginas enlazadas
# ==========================================================

def eliminar_basura(soup: BeautifulSoup) -> None:
    for elemento in soup.find_all(["script", "style", "noscript", "header", "footer", "nav", "aside", "form", "iframe"]):
        elemento.decompose()


def encontrar_contenido_principal(soup):
    if soup is None:
        return None
    for selector in ["main", "article", "#content", ".content", ".main-content", ".container"]:
        elemento = soup.select_one(selector)
        if elemento is not None and len(elemento.get_text(" ", strip=True)) >= 100:
            return elemento
    return None


def normalizar_texto_para_comparacion(texto: str) -> str:
    return " ".join(texto.lower().split()) if texto else ""


def contenido_demasiado_corto(contenido: str) -> bool:
    return len(contenido.strip()) < 100


def contenido_claramente_ajeno(titulo: str, contenido: str, url: str) -> bool:
    """Filtro conservador: dos o mas coincidencias de temas ajenos
    (doctorado, personal investigador, alumni...) descartan la pagina;
    una coincidencia aislada no basta."""
    texto = (titulo + " " + contenido + " " + url).lower()
    return sum(1 for patron in PATRONES_AJENOS if patron in texto) >= 2


def descargar_y_validar(url: str) -> tuple[str | None, object, str | None]:
    try:
        respuesta = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        respuesta.raise_for_status()
    except requests.RequestException as e:
        print("Error de descarga:", e)
        return None, None, "error de descarga"

    url_final = normalizar_url_final(respuesta.url)

    if not es_url_upv(url_final):
        return url_final, None, "URL fuera del ámbito útil"

    if "text/html" not in respuesta.headers.get("Content-Type", "").lower():
        return url_final, None, "contenido no HTML"

    soup = BeautifulSoup(respuesta.text, "html.parser")
    eliminar_basura(soup)

    contenido_principal = encontrar_contenido_principal(soup)
    if contenido_principal is None:
        return url_final, None, "no se encontró contenido principal"

    return url_final, contenido_principal, None


def descargar_y_extraer_paginas(urls_candidatas: list[dict]) -> list[dict]:
    paginas_extraidas = []
    urls_finales_procesadas = set()

    for enlace in urls_candidatas:
        url_original = enlace["url"]
        print(url_original)

        if not es_url_upv(url_original):
            print("Descartado (URL fuera del ámbito útil)")
            continue

        url_final, contenido_principal, motivo = descargar_y_validar(url_original)
        if motivo:
            print(f"Descartado ({motivo})")
            continue

        if url_final in urls_finales_procesadas:
            print("Descartado (URL final duplicada)")
            continue
        urls_finales_procesadas.add(url_final)

        h1 = contenido_principal.find("h1")
        titulo = " ".join(h1.stripped_strings) if h1 else " ".join(enlace.get("texto", "").split())

        bloques = []
        for elemento in contenido_principal.find_all(["h1", "h2", "h3", "h4", "p", "li", "table"]):
            texto = " ".join(elemento.stripped_strings)
            if len(texto) < 3:
                continue
            if elemento.name == "h1" and normalizar_texto_para_comparacion(texto) == normalizar_texto_para_comparacion(titulo):
                continue
            bloques.append(texto)

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
            "url_original": url_original, "url_final": url_final, "titulo": titulo,
            "texto_enlace": enlace.get("texto", ""), "seccion_origen": enlace.get("seccion_origen", ""),
            "padre_origen": enlace.get("padre_origen", ""), "tipo_origen": enlace.get("tipo_origen", ""),
            "contenido": contenido,
        })
        print("Página aceptada")

    return paginas_extraidas


# ==========================================================
# 5. Markdown de los recursos (paginas enlazadas)
# ==========================================================

def clasificar_recurso(pagina: dict) -> str:
    texto = (pagina.get("titulo", "") + " " + pagina.get("texto_enlace", "") + " " + pagina.get("url_final", "")).lower()
    for tipo, palabras in CLASIFICACION:
        if any(palabra in texto for palabra in palabras):
            return tipo
    return "informacion"


def _escribir_metadatos_recurso(f, pagina: dict, tipo_recurso: str) -> None:
    f.write("---\n")
    f.write("fuente: UPV\n")
    f.write(f"categoria: {CATEGORIA}\n")
    f.write(f"nivel: {NIVEL}\n")
    f.write("tipo_documento: recurso\n")
    f.write(f"tipo_recurso: {tipo_recurso}\n")
    f.write("seccion_origen: " + limpiar_nombre(pagina.get("seccion_origen", "")) + "\n")
    if pagina.get("padre_origen"):
        f.write("padre_origen: " + limpiar_nombre(pagina["padre_origen"]) + "\n")
    f.write(f"url: {pagina['url_final']}\n")
    f.write("---\n\n")


def generar_markdowns_recursos(paginas_extraidas: list[dict], directorio: Path = ADMISION_MASTER_RECURSOS_DIR) -> int:
    directorio.mkdir(parents=True, exist_ok=True)

    paginas_unicas = []
    urls_vistas = set()
    for pagina in paginas_extraidas:
        url_final = pagina.get("url_final")
        if not url_final or url_final in urls_vistas:
            continue
        urls_vistas.add(url_final)
        paginas_unicas.append(pagina)

    contador = 0
    for pagina in paginas_unicas:
        tipo_recurso = clasificar_recurso(pagina)
        nombre = limpiar_nombre(pagina.get("titulo", ""), "recurso")

        archivo = directorio / f"{nombre}.md"
        if archivo.exists():
            seccion = limpiar_nombre(pagina.get("seccion_origen", ""))
            nombre_base = nombre
            if seccion:
                nombre = f"{nombre_base}_{seccion}"
            archivo = directorio / f"{nombre}.md"

        contador_colision = 2
        while archivo.exists():
            archivo = directorio / f"{nombre}_{contador_colision}.md"
            contador_colision += 1

        with open(archivo, "w", encoding="utf-8") as f:
            _escribir_metadatos_recurso(f, pagina, tipo_recurso)
            f.write(f"# {pagina['titulo']}\n\n")
            f.write(
                "Recurso relacionado con el proceso de admisión a estudios "
                "oficiales de máster de la Universitat Politècnica de València.\n\n"
            )
            if pagina.get("seccion_origen"):
                f.write("Sección de origen: " + pagina["seccion_origen"] + "\n\n")
            f.write(pagina.get("contenido", "") + "\n\n")
            f.write("Fuente oficial: " + pagina["url_final"] + "\n")

        contador += 1

    print("Markdown de recursos generado. Archivos:", contador)
    return contador


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    datos = extraer_admision_master()
    guardar_json(datos)
    generar_markdowns_secciones(datos)

    urls_candidatas = recopilar_urls_candidatas(datos)
    print("URLs candidatas:", len(urls_candidatas))

    paginas_extraidas = descargar_y_extraer_paginas(urls_candidatas)
    generar_markdowns_recursos(paginas_extraidas)


if __name__ == "__main__":
    main()
