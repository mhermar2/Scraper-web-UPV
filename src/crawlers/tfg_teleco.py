"""Crawler generico inicial de UPV (punto de partida para el crawler
generico del plan a medio plazo del proyecto).

A diferencia de los extractores por seccion, este no se limita a una URL
raiz conocida: parte de una semilla de páginas y sigue enlaces
libremente por todo upv.es, aplicando una lista negra de dominios/rutas
(riunet, intranet, poliformat, idiomas no castellanos, ficheros
multimedia...), deduplicando por contenido (hash) ademas de por URL, y
clasificando cada pagina guardada en un "silo" tematico basico
(Legislacion/Academico/Entidades/Noticias/General) segun patrones en la
URL. Es reanudable via checkpoint en pickle.

Migrado desde src/crawlers/tfg_teleco.ipynb. El notebook tenia 4 celdas
de exploracion previa que se descartan (no producen el resultado final,
solo iteraciones de diagnostico):
  - "Programa previo para ver la cantidad de paginas a rastrear": escaner
    superficial (solo HEAD + conteo) de una entidad de prueba (ASIC)
  - "Extractor de estructura": mapeo de las primeras 1000 URLs a un CSV
    de inventario, para hacerse una idea del tamaño del sitio
  - Una celda vacia (aborted, sin contenido)
  - Un primer intento de montar Drive y crear la carpeta de salida
    (aborted, sin logica de crawling)
El crawler real es la ultima celda (tambien con status "aborted" en el
notebook original, pero por interrupcion de un crawl largo en Colab, no
porque el codigo estuviera incompleto -- es la unica celda con logica de
guardado real y con checkpoint/reanudacion). Se sustituye PyPDF2 por
pypdf (mismo API, ver requirements.txt) y se quita el intento de
"!pip install" en caliente.
"""

from __future__ import annotations

import hashlib
import os
import pickle
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import markdownify
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

from config import CRAWLER_ESTADO, CRAWLER_OUTPUT_DIR

HEADERS = {"User-Agent": "Mozilla/5.0"}

DOMINIOS_PROHIBIDOS = [
    "riunet.upv.es", "intranet.upv.es", "polilupa.upv.es", "correo.upv.es",
    "search.upv.es", "sede.upv.es", "alumni.upv.es", "wiki.upv.es", "apps.upv.es",
]

URLS_PROHIBIDAS = [
    "p_idioma=v", "p_idioma=i", "/va/", "/en/", "index-va", "index-en",
    "/ficha-personal/", "/bitstream/", "handle/10251",
    "podcast.upv.es", "media.upv.es", "tv.upv.es", ".mp4", ".mp3", ".zip",
    "wp-login.php", "sharer.php", "/feed",
]

SEMILLA = [
    ("https://www.upv.es/index.html", 0),
    ("https://www.upv.es/organizacion/la-institucion/index.html", 0),
    ("https://www.upv.es/estudios/grado/index.html", 0),
    ("https://www.upv.es/estudios/master/index.html", 0),
    ("https://www.upv.es/pls/oalu/est_noticias.buscadornoticias", 0),
    ("https://www.upv.es/entidades/SG/infoweb/sg/info/513084normalc.html", 0),
]


def es_valida(url: str) -> bool:
    """Solo dominio UPV y fuera de la lista negra de dominios/rutas."""
    u = urlparse(url)
    dom = u.netloc.lower()
    if not (dom == "upv.es" or dom.endswith(".upv.es")):
        return False
    if any(d in dom for d in DOMINIOS_PROHIBIDOS):
        return False
    if any(p in url.lower() for p in URLS_PROHIBIDAS):
        return False
    return True


def normalizar_url(url: str) -> str:
    """Elimina fragmentos y parametros de ruido para evitar duplicados."""
    url = url.split("#")[0]
    url = re.sub(r"index(-es|c|v|en)?\.html", "index.html", url)
    u = urlparse(url)
    params_ruido = {"tl", "p_sesion", "p_vista", "lang", "jsessionid", "p_idioma", "ie", "q"}
    query = parse_qs(u.query.lower())
    query_limpia = {k: v for k, v in query.items() if k not in params_ruido}
    nueva_query = urlencode(query_limpia, doseq=True)
    return urlunparse((u.scheme, u.netloc.lower(), u.path.lower(), u.params, nueva_query, "")).rstrip("/")


def pdf_to_text(content: bytes) -> str:
    try:
        import io
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(p.extract_text() for p in reader.pages if p.extract_text())
    except Exception:
        return ""


def extraer_guia_docente_profunda(url_asig: str) -> str:
    """Navega por las pestañas de la asignatura para extraer el 100% de la info."""
    try:
        res = requests.get(url_asig, timeout=10, headers=HEADERS)
        soup = BeautifulSoup(res.text, "html.parser")
        datos_full = [f"# GUÍA DOCENTE COMPLETA: {url_asig}\n"]

        pestanas = soup.find_all("a", string=re.compile(r"Unidades|Evaluación|Resultados|Descripción|Bibliografía", re.I))
        for p in pestanas:
            u_p = urljoin(url_asig, p["href"])
            try:
                r_p = requests.get(u_p, timeout=5)
                s_p = BeautifulSoup(r_p.text, "html.parser")
                cuerpo = s_p.find(id="cuerpo") or s_p.find("main") or s_p.body
                datos_full.append(f"## SECCIÓN: {p.get_text(strip=True)}\n" + markdownify.markdownify(str(cuerpo)))
            except Exception:
                continue
        return "\n\n".join(datos_full)
    except Exception:
        return ""


def obtener_silo(url: str) -> str:
    u = url.lower()
    if any(x in u for x in ["boupv", "normativa", "estatutos", "presupuesto", "reglamento"]):
        return "01_Legislacion"
    if "/titulaciones/" in u or "/estudios/" in u:
        return "02_Academico"
    if "/entidades/" in u or "/contenidos/" in u:
        return "03_Entidades"
    if "noticia" in u or "ndp-app" in u:
        return "04_Noticias"
    return "05_General"


def cargar_progreso(archivo_estado: Path, semilla: list[tuple[str, int]]) -> tuple[list, set, set]:
    if archivo_estado.exists():
        print("Reanudando sesión y depurando cola...")
        with open(archivo_estado, "rb") as f:
            datos = pickle.load(f)
        visitadas = datos.get("visitadas", set())
        hashes_contenido = datos.get("hashes_contenido", set())
        cola_previa = datos.get("cola", [])

        cola = []
        vistas_en_cola = set()
        for uc, pr in cola_previa:
            un = normalizar_url(uc)
            if es_valida(un) and un not in visitadas and un not in vistas_en_cola:
                cola.append((un, pr))
                vistas_en_cola.add(un)
        print(f"Cola optimizada: de {len(cola_previa)} a {len(cola)} URLs.")
        return cola, visitadas, hashes_contenido

    print("Iniciando extracción desde cero...")
    return list(semilla), set(), set()


def guardar_progreso(archivo_estado: Path, cola: list, visitadas: set, hashes_contenido: set) -> None:
    archivo_estado.parent.mkdir(parents=True, exist_ok=True)
    with open(archivo_estado, "wb") as f:
        pickle.dump({"visitadas": visitadas, "cola": cola, "hashes_contenido": hashes_contenido}, f)


def rastrear(max_paginas: int = 50000, path_base: Path = CRAWLER_OUTPUT_DIR, archivo_estado: Path = CRAWLER_ESTADO,
             semilla: list[tuple[str, int]] = SEMILLA) -> int:
    """Bucle principal de crawling. Devuelve el numero de paginas visitadas."""
    path_base.mkdir(parents=True, exist_ok=True)
    cola, visitadas, hashes_contenido = cargar_progreso(archivo_estado, semilla)

    print("Ejecutando rastreador sin simplificaciones...")

    try:
        while cola and len(visitadas) < max_paginas:
            url_cruda, prof = cola.pop(0)
            url_norm = normalizar_url(url_cruda)

            if url_norm in visitadas or not es_valida(url_norm):
                continue

            try:
                print(f"[{len(visitadas)}] Analizando: {url_norm}")
                res = requests.get(url_norm, timeout=12, headers=HEADERS)
                visitadas.add(url_norm)

                if url_norm.lower().endswith(".pdf"):
                    content = pdf_to_text(res.content)
                elif "detAsignatura" in url_norm:
                    content = extraer_guia_docente_profunda(url_norm)
                else:
                    if "text/html" not in res.headers.get("Content-Type", "").lower():
                        continue
                    soup = BeautifulSoup(res.text, "html.parser")

                    iframe = soup.find("iframe", id="marco")
                    if iframe and iframe.get("src"):
                        try:
                            res_if = requests.get(urljoin(url_norm, iframe["src"]), timeout=10)
                            soup_if = BeautifulSoup(res_if.text, "html.parser")
                            iframe.replace_with(soup_if)
                        except Exception:
                            pass

                    for a in soup.find_all("a", href=True):
                        lnk = urljoin(url_norm, a["href"])
                        lnk_n = normalizar_url(lnk)
                        if es_valida(lnk_n) and lnk_n not in visitadas:
                            cola.append((lnk_n, prof + 1))

                    for s in soup(["header", "footer", "nav", "script", "style", ".global-menu", ".bg-overlay"]):
                        s.decompose()
                    main_c = soup.find(id="cuerpo") or soup.find("main") or soup.body
                    content = markdownify.markdownify(str(main_c), heading_style="ATX")

                if not content.strip():
                    continue
                h = hashlib.md5(content.encode("utf-8")).hexdigest()
                if h in hashes_contenido:
                    continue
                hashes_contenido.add(h)

                silo = obtener_silo(url_norm)
                u_p = urlparse(url_norm)
                path_parts = [p for p in u_p.path.strip("/").split("/") if p]
                folder = path_parts[1] if len(path_parts) > 1 else (path_parts[0] if path_parts else "root")

                nombre_f = path_parts[-1] if path_parts else "index"
                if u_p.query:
                    nombre_f += "_" + hashlib.md5(u_p.query.encode()).hexdigest()[:6]

                ruta_dir = path_base / silo / folder
                ruta_dir.mkdir(parents=True, exist_ok=True)

                with open(ruta_dir / f"{nombre_f[:100]}.md", "w", encoding="utf-8") as f:
                    f.write(f"--- INFO EXTRA ---\nURL: {url_norm}\nCAPTURADO: {time.ctime()}\n---\n\n" + content)

                if len(visitadas) % 50 == 0:
                    guardar_progreso(archivo_estado, cola, visitadas, hashes_contenido)
                    print(f"Checkpoint: {len(cola)} en cola.")

            except Exception:
                continue

    finally:
        guardar_progreso(archivo_estado, cola, visitadas, hashes_contenido)
        print(f"Finalizado. Total páginas visitadas: {len(visitadas)}")

    return len(visitadas)


if __name__ == "__main__":
    rastrear()
