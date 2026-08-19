"""Extractor de "Admision a Doctorado".

Mismo patron que extrae_master.py (section-01..section-06 con
tarjetas/acordeones/banners/enlaces), pero con su propio alcance y
reglas para la fase de paginas enlazadas:

- Alcance mucho mas estrecho: solo sigue URLs bajo
  upv.es/entidades/edoctorado/ o upv.es/pls/soalu/ (url_relevante());
  master en cambio aceptaba cualquier URL de upv.es/jpa.upv.es y
  filtraba por tema "claramente ajeno" a posteriori.
- Descarta ademas URLs que requieren autenticacion (poliformat, login,
  shibboleth) y archivos binarios (.pdf/.jpg/.doc/...), algo que master
  no comprobaba explicitamente.
- Selectores de contenido principal distintos (article / main con clase
  que contenga "content" / #content / clase content|contenido|
  page-content, con fallback a main -- no a "no encontrado").
- Clasificador de recursos con categorias parecidas pero keywords
  propias (ej. "programas-de-doctorado" en vez de "master").
- Sin el filtro de "contenido claramente ajeno" que si tiene master.

Pipeline (mismo orden que el notebook original):
  1. extraer_admision_doctorado() -> JSON con el padre + secciones
  2. guardar_json()
  3. generar_markdowns_secciones() -> 1 .md padre + 1 .md por seccion
  4. recopilar_enlaces_unicos() -> aplana tarjetas/acordeones/banners/
     enlaces de todas las secciones, deduplicando por URL
  5. descargar_y_extraer_paginas() -> visita cada URL relevante de
     verdad y extrae su contenido
  6. generar_markdowns_recursos() -> un .md por pagina util, clasificada

Migrado desde src/extractores/admision/extrae_doctorado.ipynb (antes
Extrae_Admision_Doctorado.ipynb). Notebook limpio, sin celdas
exploratorias ni codigo muerto que descartar.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bs4 import BeautifulSoup
import requests

from config import ADMISION_DOCTORADO_DIR, ADMISION_DOCTORADO_JSON, ADMISION_DOCTORADO_RECURSOS_DIR, ADMISION_DOCTORADO_URL

HEADERS = {"User-Agent": "Mozilla/5.0"}

CATEGORIA = "admision"
NIVEL = "doctorado"

INTRO_DOCUMENTO = (
    "Información completa sobre el proceso de admisión "
    "a estudios oficiales de doctorado en la Universitat Politècnica de València."
)

EXTENSIONES_ARCHIVO = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".zip", ".doc", ".docx", ".xls", ".xlsx")
PALABRAS_REQUIEREN_AUTENTICACION = ["poliformat", "login", "shibboleth"]

CLASIFICACION = [
    ("calendario", ["plazo", "calendario", "calendarios", "fechas"]),
    ("matricula", ["precio", "precios", "tasas", "matricula"]),
    ("faq", ["faq", "faqs", "preguntas frecuentes"]),
    ("ayudas", ["ayuda", "ayudas", "beca", "becas"]),
    ("admision", ["solicitud", "preinscripcion", "preinscripción", "admision", "admisión"]),
    ("programas", ["programas-de-doctorado", "programa de doctorado", "oferta"]),
    ("normativa", ["normativa", "reglamento", "legislacion", "legislación"]),
]


def texto_limpio(elemento) -> str:
    return " ".join(elemento.stripped_strings) if elemento is not None else ""


def url_absoluta(url: str, base: str = ADMISION_DOCTORADO_URL) -> str:
    return urljoin(base, url) if url else ""


def primer_enlace(elemento, base: str = ADMISION_DOCTORADO_URL) -> str:
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
    for viejo, nuevo in {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n"}.items():
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


def extraer_admision_doctorado(url: str = ADMISION_DOCTORADO_URL) -> dict:
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
        if not titulo:
            continue
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


def guardar_json(datos: dict, ruta: Path = ADMISION_DOCTORADO_JSON) -> None:
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


def generar_markdowns_secciones(datos: dict, directorio: Path = ADMISION_DOCTORADO_DIR) -> int:
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
# 3. Descubrimiento de enlaces (dedup global por URL)
# ==========================================================

def recopilar_enlaces_unicos(datos: dict) -> list[dict]:
    enlaces: dict[str, dict] = {}

    def registrar(url, texto, seccion):
        if not url or url in enlaces:
            return
        enlaces[url] = {"url": url, "texto": texto, "seccion_origen": seccion}

    for padre in datos["padres"]:
        for seccion in padre["secciones"]:
            nombre_seccion = seccion["titulo"]

            for enlace in seccion.get("enlaces", []):
                registrar(enlace["url"], enlace["texto"], nombre_seccion)
            for tarjeta in seccion.get("tarjetas", []):
                registrar(tarjeta.get("url"), tarjeta.get("titulo"), nombre_seccion)
            for banner in seccion.get("banners", []):
                registrar(banner.get("url"), banner.get("titulo"), nombre_seccion)
            for acordeon in seccion.get("acordeones", []):
                for enlace in acordeon.get("enlaces", []):
                    registrar(enlace["url"], enlace["texto"], nombre_seccion)

    return list(enlaces.values())


# ==========================================================
# 4. Descargar y extraer paginas enlazadas
# ==========================================================

def url_relevante(url: str) -> bool:
    """Alcance del crawler de doctorado: solo entidades/edoctorado y
    las paginas dinamicas Oracle bajo pls/soalu."""
    url = url.lower()
    return "www.upv.es/entidades/edoctorado/" in url or "www.upv.es/pls/soalu/" in url


def descargar_y_extraer_paginas(enlaces: list[dict]) -> list[dict]:
    paginas_extraidas = []

    for enlace in enlaces:
        url = enlace["url"]
        print(url)

        if not url_relevante(url):
            print("Descartado (fuera del ámbito de Doctorado)")
            continue

        try:
            respuesta = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
            respuesta.raise_for_status()
        except Exception:
            print("Error al descargar.")
            continue

        if "upv.es" not in urlparse(respuesta.url).netloc.lower():
            print("Descartado (dominio externo)")
            continue

        if any(palabra in respuesta.url.lower() for palabra in PALABRAS_REQUIEREN_AUTENTICACION):
            print("Descartado (requiere autenticación)")
            continue

        if respuesta.url.lower().split("?")[0].endswith(EXTENSIONES_ARCHIVO):
            print("Descartado (archivo)")
            continue

        soup = BeautifulSoup(respuesta.text, "html.parser")
        for basura in soup.find_all(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
            basura.decompose()

        contenido_principal = (
            soup.find("article")
            or soup.find("main", class_=lambda x: x and "content" in " ".join(x))
            or soup.find(id="content")
            or soup.find(class_=lambda x: x and any(p in " ".join(x).lower() for p in ["content", "contenido", "page-content"]))
        )
        if contenido_principal is None:
            contenido_principal = soup.find("main")
        if contenido_principal is None:
            print("Descartado (no se encontró contenido principal)")
            continue

        titulo = texto_limpio(contenido_principal.find("h1")) or enlace["texto"]

        bloques = []
        vistos = set()
        for elemento in contenido_principal.find_all(["h2", "h3", "h4", "p", "li"]):
            texto = texto_limpio(elemento)
            if len(texto) < 5 or texto in vistos:
                continue
            vistos.add(texto)
            bloques.append(texto)

        contenido = "\n\n".join(bloques)
        if len(contenido) < 50:
            print("Descartado (contenido insuficiente)")
            continue

        paginas_extraidas.append({
            "url": url, "url_final": respuesta.url, "titulo": titulo,
            "seccion_origen": enlace["seccion_origen"], "contenido": contenido,
        })

    return paginas_extraidas


# ==========================================================
# 5. Markdown de los recursos (paginas enlazadas)
# ==========================================================

def clasificar_recurso(pagina: dict) -> str:
    texto = (pagina["titulo"] + " " + pagina["url_final"]).lower()
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
    f.write("seccion_origen: " + limpiar_nombre(pagina["seccion_origen"]) + "\n")
    f.write(f"url: {pagina['url_final']}\n")
    f.write("---\n\n")


def generar_markdowns_recursos(paginas_extraidas: list[dict], directorio: Path = ADMISION_DOCTORADO_RECURSOS_DIR) -> int:
    directorio.mkdir(parents=True, exist_ok=True)

    paginas_unicas = []
    urls_vistas = set()
    for pagina in paginas_extraidas:
        url_final = pagina["url_final"]
        if url_final in urls_vistas:
            continue
        urls_vistas.add(url_final)
        paginas_unicas.append(pagina)

    contador = 0
    for pagina in paginas_unicas:
        tipo_recurso = clasificar_recurso(pagina)
        nombre = limpiar_nombre(pagina["titulo"], "recurso")

        archivo = directorio / f"{nombre}.md"
        if archivo.exists():
            nombre_seccion = limpiar_nombre(pagina["seccion_origen"])
            archivo = directorio / f"{nombre}_{nombre_seccion}.md"

        with open(archivo, "w", encoding="utf-8") as f:
            _escribir_metadatos_recurso(f, pagina, tipo_recurso)
            f.write(f"# {pagina['titulo']}\n\n")
            f.write("Contenido relacionado con el proceso de admisión a doctorado.\n\n")
            f.write(f"Sección de origen: {pagina['seccion_origen']}\n\n")
            f.write(pagina["contenido"] + "\n\n")
            f.write(f"Fuente oficial: {pagina['url_final']}\n")

        contador += 1

    print("Markdown de recursos generado. Archivos:", contador)
    return contador


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    datos = extraer_admision_doctorado()
    guardar_json(datos)
    generar_markdowns_secciones(datos)

    enlaces = recopilar_enlaces_unicos(datos)
    print("Enlaces únicos encontrados:", len(enlaces))

    paginas_extraidas = descargar_y_extraer_paginas(enlaces)
    generar_markdowns_recursos(paginas_extraidas)


if __name__ == "__main__":
    main()
