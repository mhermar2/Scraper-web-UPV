"""Extractor de "Admision internacional" (alumnado internacional).

AVISO DE FIDELIDAD: el notebook original (Extrae_Admision_Internacional.ipynb)
tiene una celda perdida. El BLOQUE 6 (validacion/normalizacion) usa una
variable `datos` -- con "clases"/"titulo"/"texto"/"enlaces"/opcionalmente
"bloques"/"subsecciones" por seccion -- que nunca se construye en ninguna
celda guardada; usa ademas funciones (extraer_titulo, extraer_enlaces,
normalizar_espacios) que tampoco estan definidas. Es la misma situacion
que el get() huerfano en extrae_doctorado.py (estudios), pero aqui la
pieza que falta es mucho mas grande: toda la logica que decide "esto es
una seccion" y arma el arbol de subsecciones/bloques.

extraer_estructura_cruda() de este modulo esta RECONSTRUIDA (no
traducida) inspeccionando la web real hoy: dentro de
article > div.entry-content, los bloques de contenido real llevan la
clase "upv-section" (hay ademas separadores "wp-block-cover"/
"wp-block-spacer" que se descartan). De los 8 bloques upv-section
actuales, 6 no tienen titulo propio (se numeran "seccion_N" via el
fallback ya existente en generar_nombre_seccion) y 2 si lo tienen
("La UPV en rankings", "Proceso de admision") -- coincide exactamente
con los huecos (4 y 6) que deja la numeracion en los archivos ya
comiteados en data/processed/admision/internacional/. El bloque con
clase "upv-blocks" (calendario de plazos) no expone un titulo propio
directo: se reconstruyo asumiendo que ahi es donde entra
extraer_bloques_contenedor() (esa funcion SI esta completa en el
notebook original) para generar sus subsecciones -- probado contra la
web real, el resultado para esta seccion en concreto no coincide byte a
byte con lo comiteado (la agrupacion interna exacta de "Calendario para
grados/masteres/doctorado" no se pudo reconstruir con certeza); el resto
de secciones (7 de 8) si coinciden. Ver commit para el detalle de la
comparacion.

Todo lo posterior (BLOQUE 6 en adelante: validacion, normalizacion,
generacion de Markdown, descubrimiento y descarga de paginas enlazadas,
filtro de relevancia internacional, generacion de recursos) SI es
migracion fiel del notebook original, sin reconstruir nada.
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

from config import ADMISION_INTERNACIONAL_DIR, ADMISION_INTERNACIONAL_JSON, ADMISION_INTERNACIONAL_RECURSOS_DIR, ADMISION_INTERNACIONAL_URL

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; UPV-Admision-Bot/1.0)"}

CATEGORIA = "admision"
NIVEL = "internacional"

INTRO_DOCUMENTO = (
    "Información sobre el proceso de admisión de alumnado internacional "
    "en la Universitat Politècnica de València."
)

DOMINIOS_UPV = {"www.upv.es", "upv.es"}
URLS_DESCARTAR_MANUALMENTE = {"http://www.upv.es/es", "http://www.upv.es/index-es.html"}
URLS_ACEPTAR_MANUALMENTE = {"http://www.upv.es/rankings/index.html"}

INDICADORES_DIRECTOS = [
    "admisión internacional", "admisión de estudiantes internacionales",
    "international admission", "international admissions", "international students", "international student",
    "estudiantes internacionales", "estudiantes extranjeros", "alumnos extranjeros", "alumnado extranjero",
    "información alumnos extranjeros", "informacion alumnos extranjeros",
    "international applicants", "foreign students", "foreign applicants",
]
INDICADORES_ADMISION = [
    "preinscripción", "preinscripcion", "solicitud de admisión", "solicitud de acceso", "solicitar el acceso",
    "solicitud de plaza", "proceso de admisión", "proceso de acceso", "requisitos de acceso",
    "requisitos de admisión", "criterios de admisión", "plazo de admisión",
    "application", "apply", "admission requirements", "entry requirements", "application process",
]
INDICADORES_MATRICULA = [
    "matrícula", "matricula", "matriculación", "matriculacion", "formalizar la matrícula",
    "enrollment", "enrolment", "enrollment process", "registration",
    "documentación necesaria", "documentacion necesaria", "documentación requerida", "documentacion requerida",
    "required documents",
]
INDICADORES_INTERNACIONAL = [
    "extranjero", "extranjeros", "international", "foreign", "visa", "visado", "student visa",
    "visado de estudiante", "país de origen", "pais de origen", "estudiante internacional", "estudiantes internacionales",
]
INDICADORES_ACADEMICOS = [
    "grado", "grados", "máster", "master", "máster universitario", "master universitario",
    "bachelor", "master's degree", "degree", "programa de estudios", "programa académico", "estudios universitarios",
]


def texto_limpio(elemento) -> str:
    return " ".join(elemento.stripped_strings) if elemento is not None else ""


def url_absoluta(url: str, base: str = ADMISION_INTERNACIONAL_URL) -> str:
    return urljoin(base, url) if url else ""


def normalizar_espacios(texto: str) -> str:
    return " ".join(texto.split()) if texto else ""


def obtener_descripcion(contenedor) -> str:
    if contenedor is None:
        return ""
    parrafos = contenedor.find_all("p", recursive=False)
    return " ".join(texto_limpio(p) for p in parrafos).strip()


# ==========================================================
# Contenedores de bloques / calendarios (extraer_bloques_contenedor,
# limpiar_bloque, obtener_enlaces_subseccion) -- FIEL al notebook
# original, ya venia completa.
# ==========================================================

def extraer_titulo(elemento) -> str:
    h = elemento.find(["h1", "h2", "h3", "h4"])
    return texto_limpio(h) if h else ""


def extraer_enlaces(elemento, base: str = ADMISION_INTERNACIONAL_URL) -> list[dict]:
    return [{"texto": texto_limpio(a), "url": url_absoluta(a["href"], base)} for a in elemento.find_all("a", href=True)]


def extraer_bloques_contenedor(contenedor) -> list[dict]:
    """Extrae contenedores upv-block/upv-box/wp-block-group y los
    organiza en subsecciones semanticas: calendario para grados,
    masteres, doctorado."""
    subsecciones = []

    bloques_dom = contenedor.find_all(["div", "section", "article"], recursive=True)
    bloques_detectados = []

    for bloque_dom in bloques_dom:
        clases = bloque_dom.get("class", [])
        if not any(c in clases for c in ["upv-block", "upv-box", "wp-block-group"]):
            continue

        titulo = extraer_titulo(bloque_dom)
        texto = bloque_dom.get_text(" ", strip=True)
        enlaces = extraer_enlaces(bloque_dom)

        if not titulo and not texto and not enlaces:
            continue

        bloques_detectados.append({"titulo": titulo, "texto": texto, "enlaces": enlaces})

    if not bloques_detectados:
        return []

    grados, masteres, doctorado = [], [], []

    for bloque in bloques_detectados:
        titulo = normalizar_espacios(bloque["titulo"]).lower()
        texto = normalizar_espacios(bloque["texto"])
        texto_lower = texto.lower()

        if ("grado" in titulo or "grado" in texto_lower or "alumnado internacional" in texto_lower and "finales de julio" in texto_lower):
            grados.append(bloque)
            continue
        if ("máster" in titulo or "master" in titulo or "máster" in texto_lower or "master" in texto_lower):
            masteres.append(bloque)
            continue
        if ("doctorado" in titulo or "doctorado" in texto_lower):
            doctorado.append(bloque)
            continue

    if not grados and not masteres and not doctorado:
        grupos = []
        indice = 0
        grupo = []
        while indice < len(bloques_detectados):
            if indice == 0:
                grupo = bloques_detectados[indice:indice + 2]
                grupos.append(("Calendario para grados", grupo))
            elif indice == 2:
                grupo = bloques_detectados[indice:indice + 2]
                grupos.append(("Calendario para másteres", grupo))
            elif indice == 4:
                grupo = bloques_detectados[indice:indice + 3]
                grupos.append(("Calendario para doctorado", grupo))
            indice += len(grupo)

        for titulo_grupo, bloques in grupos:
            subsecciones.append({"clases": [], "titulo": titulo_grupo, "texto": "", "enlaces": [], "bloques": [limpiar_bloque(b) for b in bloques]})
        return subsecciones

    if grados:
        subsecciones.append({"clases": [], "titulo": "Calendario para grados", "texto": "", "enlaces": obtener_enlaces_subseccion(grados), "bloques": [limpiar_bloque(b) for b in grados]})
    if masteres:
        subsecciones.append({"clases": [], "titulo": "Calendario para másteres", "texto": "", "enlaces": obtener_enlaces_subseccion(masteres), "bloques": [limpiar_bloque(b) for b in masteres]})
    if doctorado:
        subsecciones.append({"clases": [], "titulo": "Calendario para doctorado", "texto": "", "enlaces": obtener_enlaces_subseccion(doctorado), "bloques": [limpiar_bloque(b) for b in doctorado]})

    return subsecciones


def limpiar_bloque(bloque: dict) -> dict:
    titulo = normalizar_espacios(bloque.get("titulo", ""))
    texto = normalizar_espacios(bloque.get("texto", ""))

    if titulo:
        prefijo = titulo.strip()
        if texto.lower().startswith(prefijo.lower()):
            texto = texto[len(prefijo):].strip()

    for prefijo in ["Preinscripción", "Matrícula", "Resolución"]:
        if texto.lower().startswith(prefijo.lower()):
            texto = texto[len(prefijo):].strip()

    return {"clases": [], "titulo": titulo, "texto": texto, "enlaces": bloque.get("enlaces", [])}


def obtener_enlaces_subseccion(bloques: list[dict]) -> list[dict]:
    enlaces = []
    for bloque in bloques:
        for enlace in bloque.get("enlaces", []):
            if enlace not in enlaces:
                enlaces.append(enlace)
    return enlaces


# ==========================================================
# Extraccion cruda -- RECONSTRUIDA (ver aviso de fidelidad arriba)
# ==========================================================

def extraer_seccion_cruda(bloque) -> dict:
    clases = bloque.get("class", [])

    # Los bloques "upv-blocks" (calendario) no tienen un titulo propio
    # directo: su primer <h2> pertenece a la primera subseccion interna
    # ("Calendario para grados"), no a la seccion como tal.
    es_calendario = "upv-blocks" in clases
    titulo = "" if es_calendario else extraer_titulo(bloque)
    # Para los contenedores de calendario el texto de la seccion se deja
    # vacio: el contenido real vive en las subsecciones (una por
    # grados/masteres/doctorado), no repetido tambien a nivel de seccion.
    texto = "" if es_calendario else bloque.get_text(" ", strip=True)
    enlaces = extraer_enlaces(bloque)

    resultado = {"clases": clases, "titulo": titulo, "texto": texto, "enlaces": enlaces}

    if "upv-blocks" in clases:
        subsecciones = extraer_bloques_contenedor(bloque)
        if subsecciones:
            resultado["subsecciones"] = subsecciones

    return resultado


def extraer_estructura_cruda(url: str = ADMISION_INTERNACIONAL_URL) -> dict:
    respuesta = requests.get(url, headers=HEADERS)
    respuesta.raise_for_status()
    soup = BeautifulSoup(respuesta.text, "html.parser")

    titulo_padre = texto_limpio(soup.find("h1"))

    contenido = soup.select_one("main article div.entry-content")
    if contenido is None:
        raise Exception("No se ha encontrado el contenedor principal (entry-content).")

    bloques_seccion = [c for c in contenido.find_all(recursive=False) if "upv-section" in (c.get("class") or [])]
    secciones = [extraer_seccion_cruda(b) for b in bloques_seccion]

    return {"padres": [{"titulo": titulo_padre, "url": url, "secciones": secciones}]}


# ==========================================================
# Validacion y normalizacion del JSON -- FIEL al notebook original
# ==========================================================

def validar_bloque(bloque: dict, ruta: str = "bloque") -> None:
    if not isinstance(bloque, dict):
        raise TypeError(f"{ruta} no es un diccionario.")

    for campo in ["clases", "titulo", "texto", "enlaces"]:
        if campo not in bloque:
            raise ValueError(f"Falta '{campo}' en {ruta}.")

    if not isinstance(bloque["clases"], list):
        raise TypeError(f"{ruta}.clases debe ser una lista.")
    if not isinstance(bloque["enlaces"], list):
        raise TypeError(f"{ruta}.enlaces debe ser una lista.")

    for i, enlace in enumerate(bloque["enlaces"]):
        if "texto" not in enlace:
            raise ValueError(f"Falta texto en {ruta}.enlaces[{i}]")
        if "url" not in enlace:
            raise ValueError(f"Falta url en {ruta}.enlaces[{i}]")

    if "bloques" in bloque:
        if not isinstance(bloque["bloques"], list):
            raise TypeError(f"{ruta}.bloques debe ser una lista.")
        for i, sub_bloque in enumerate(bloque["bloques"]):
            validar_bloque(sub_bloque, f"{ruta}.bloques[{i}]")

    if "subsecciones" in bloque:
        if not isinstance(bloque["subsecciones"], list):
            raise TypeError(f"{ruta}.subsecciones debe ser una lista.")
        for i, subseccion in enumerate(bloque["subsecciones"]):
            validar_bloque(subseccion, f"{ruta}.subsecciones[{i}]")


def validar_estructura(datos: dict) -> dict:
    if not isinstance(datos, dict):
        raise TypeError("El objeto 'datos' no es un diccionario.")
    if "padres" not in datos:
        raise ValueError("El JSON no contiene la clave 'padres'.")
    if not isinstance(datos["padres"], list) or len(datos["padres"]) == 0:
        raise ValueError("La clave 'padres' debe contener una lista no vacia.")

    padre = datos["padres"][0]
    for campo in ["titulo", "url", "secciones"]:
        if campo not in padre:
            raise ValueError(f"Falta el campo '{campo}' en el padre.")

    url = padre["url"]
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"La URL no parece válida: {url}")

    if not isinstance(padre["secciones"], list):
        raise TypeError("El campo 'secciones' debe ser una lista.")

    for i, seccion in enumerate(padre["secciones"]):
        validar_bloque(seccion, f"secciones[{i}]")

    return datos


def normalizar_url_texto(url: str) -> str:
    """Si viene en formato Markdown [url](url), se queda solo con la URL."""
    if not url:
        return ""
    url = url.strip()
    if url.startswith("[") and "](" in url:
        inicio = url.find("](") + 2
        fin = url.rfind(")")
        if fin > inicio:
            url = url[inicio:fin]
    return url


def normalizar_enlace(enlace: dict) -> dict:
    return {"texto": normalizar_espacios(enlace.get("texto", "")), "url": normalizar_url_texto(enlace.get("url", ""))}


def normalizar_bloque(bloque: dict) -> dict:
    resultado = {
        "titulo": normalizar_espacios(bloque.get("titulo", "")),
        "texto": normalizar_espacios(bloque.get("texto", "")),
        "enlaces": [normalizar_enlace(e) for e in bloque.get("enlaces", [])],
    }
    if bloque.get("bloques"):
        resultado["bloques"] = [normalizar_bloque(b) for b in bloque["bloques"]]
    if bloque.get("subsecciones"):
        resultado["subsecciones"] = [normalizar_bloque(s) for s in bloque["subsecciones"]]
    return resultado


def normalizar_estructura(datos: dict) -> dict:
    padre = datos["padres"][0]
    secciones_normalizadas = []

    for seccion in padre["secciones"]:
        clases = seccion.get("clases", [])
        if "upv-blocks" in clases:
            tipo = "contenedor"
        elif "upv-boxes" in clases:
            tipo = "seccion"
        else:
            tipo = "contenido"

        normalizada = {
            "tipo": tipo,
            "clases": clases,
            "titulo": normalizar_espacios(seccion.get("titulo", "")),
            "texto": normalizar_espacios(seccion.get("texto", "")),
            "enlaces": [normalizar_enlace(e) for e in seccion.get("enlaces", [])],
        }

        subsecciones = seccion.get("subsecciones", [])
        if subsecciones:
            normalizada["subsecciones"] = []
            for subseccion in subsecciones:
                sub = {
                    "titulo": normalizar_espacios(subseccion.get("titulo", "")),
                    "texto": "",
                    "enlaces": [normalizar_enlace(e) for e in subseccion.get("enlaces", [])],
                }
                bloques = subseccion.get("bloques", [])
                if bloques:
                    sub["bloques"] = [normalizar_bloque(b) for b in bloques]
                else:
                    sub["texto"] = normalizar_espacios(subseccion.get("texto", ""))
                normalizada["subsecciones"].append(sub)

        bloques = seccion.get("bloques", [])
        if bloques:
            normalizada["bloques"] = [normalizar_bloque(b) for b in bloques]

        secciones_normalizadas.append(normalizada)

    return {"padres": [{"titulo": normalizar_espacios(padre["titulo"]), "url": normalizar_url_texto(padre["url"]), "secciones": secciones_normalizadas}]}


def guardar_json(datos: dict, ruta: Path = ADMISION_INTERNACIONAL_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=4)
    print("JSON guardado:", ruta)


# ==========================================================
# Generacion de Markdown base -- FIEL al notebook original
# ==========================================================

def limpiar_nombre(nombre: str) -> str:
    if not nombre:
        return ""
    nombre = nombre.lower()
    for viejo, nuevo in {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"}.items():
        nombre = nombre.replace(viejo, nuevo)
    return re.sub(r"[^a-z0-9]+", "_", nombre).strip("_")


def generar_nombre_seccion(titulo: str, indice: int, nombres_utilizados: set) -> str:
    nombre = limpiar_nombre(titulo) or f"seccion_{indice}"
    nombre_original = nombre
    contador = 2
    while nombre in nombres_utilizados:
        nombre = f"{nombre_original}_{contador}"
        contador += 1
    nombres_utilizados.add(nombre)
    return nombre


def _escribir_metadatos(f, tipo_documento: str, seccion: str | None = None) -> None:
    f.write("---\n")
    f.write("fuente: UPV\n")
    f.write(f"categoria: {CATEGORIA}\n")
    f.write(f"nivel: {NIVEL}\n")
    f.write(f"tipo_documento: {tipo_documento}\n")
    if seccion:
        f.write(f"seccion: {seccion}\n")
    f.write("---\n\n")


def escribir_enlaces(f, enlaces: list[dict], prefijo: str = "-") -> None:
    for enlace in enlaces:
        texto = enlace.get("texto", "")
        url = enlace.get("url", "")
        if not url:
            continue
        f.write(f"{prefijo} {texto}: {url}\n" if texto else f"{prefijo} {url}\n")
    if enlaces:
        f.write("\n")


def escribir_bloque(f, bloque: dict, nivel: int = 3) -> None:
    titulo = bloque.get("titulo", "")
    texto = bloque.get("texto", "")
    enlaces = bloque.get("enlaces", [])

    if titulo:
        f.write(("#" * nivel) + f" {titulo}\n\n")
    if texto:
        f.write(texto + "\n\n")
    escribir_enlaces(f, enlaces)

    for sub_bloque in bloque.get("bloques", []):
        escribir_bloque(f, sub_bloque, nivel=min(nivel + 1, 6))
    for subseccion in bloque.get("subsecciones", []):
        escribir_subseccion(f, subseccion, nivel=min(nivel + 1, 6))


def escribir_subseccion(f, subseccion: dict, nivel: int = 2) -> None:
    titulo = subseccion.get("titulo", "")
    texto = subseccion.get("texto", "")
    enlaces = subseccion.get("enlaces", [])

    if titulo:
        f.write(("#" * nivel) + f" {titulo}\n\n")
    if texto:
        f.write(texto + "\n\n")
    escribir_enlaces(f, enlaces)

    for bloque in subseccion.get("bloques", []):
        escribir_bloque(f, bloque, nivel=min(nivel + 1, 6))
    for sub_subseccion in subseccion.get("subsecciones", []):
        escribir_subseccion(f, sub_subseccion, nivel=min(nivel + 1, 6))


def escribir_seccion(f, seccion: dict, padre: dict) -> None:
    titulo = seccion.get("titulo", "")
    texto = seccion.get("texto", "")
    enlaces = seccion.get("enlaces", [])

    f.write(f"# {titulo}\n\n" if titulo else "# Información de admisión\n\n")

    if padre.get("titulo"):
        f.write(f"Proceso de admisión: {padre['titulo']}\n\n")

    if texto:
        f.write(texto + "\n\n")

    escribir_enlaces(f, enlaces)

    for subseccion in seccion.get("subsecciones", []):
        escribir_subseccion(f, subseccion, nivel=2)
    for bloque in seccion.get("bloques", []):
        escribir_bloque(f, bloque, nivel=2)


def generar_markdowns_secciones(datos_normalizados: dict, directorio: Path = ADMISION_INTERNACIONAL_DIR) -> int:
    directorio.mkdir(parents=True, exist_ok=True)
    contador = 0

    for padre in datos_normalizados.get("padres", []):
        titulo_padre = padre.get("titulo", "")
        nombre_padre = limpiar_nombre(titulo_padre) or "padre"

        carpeta_padre = directorio / nombre_padre
        carpeta_padre.mkdir(parents=True, exist_ok=True)

        with open(directorio / f"{nombre_padre}.md", "w", encoding="utf-8") as f:
            _escribir_metadatos(f, "padre")
            if titulo_padre:
                f.write(f"# {titulo_padre}\n\n")
            f.write(INTRO_DOCUMENTO + "\n\n")

            url_padre = padre.get("url", "")
            if url_padre:
                f.write(f"Fuente oficial: {url_padre}\n\n")

            for i, seccion in enumerate(padre.get("secciones", []), start=1):
                titulo = seccion.get("titulo", "")
                f.write(f"## {titulo}\n\n" if titulo else f"## Sección {i}\n\n")

                texto = seccion.get("texto", "")
                if texto:
                    f.write(texto + "\n\n")

                escribir_enlaces(f, seccion.get("enlaces", []))

                for subseccion in seccion.get("subsecciones", []):
                    escribir_subseccion(f, subseccion, nivel=3)
                for bloque in seccion.get("bloques", []):
                    escribir_bloque(f, bloque, nivel=3)
        contador += 1

        nombres_utilizados = set()
        for i, seccion in enumerate(padre.get("secciones", []), start=1):
            nombre_seccion = generar_nombre_seccion(seccion.get("titulo", ""), i, nombres_utilizados)

            with open(carpeta_padre / f"{nombre_seccion}.md", "w", encoding="utf-8") as f:
                _escribir_metadatos(f, "seccion", nombre_seccion)
                escribir_seccion(f, seccion, padre)
            contador += 1

    print("Markdown base generado. Archivos:", contador)
    return contador


# ==========================================================
# Descubrimiento, descarga y filtrado de paginas enlazadas
# -- FIEL al notebook original
# ==========================================================

def normalizar_url_final(url: str) -> str | None:
    if not url:
        return None
    try:
        p = urlparse(url)
    except Exception:
        return None
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", "", p.query, ""))


def es_url_internacional(url: str) -> bool:
    if not url:
        return False
    try:
        dominio = urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return False
    return dominio in DOMINIOS_UPV or dominio.endswith(".upv.es")


def tratamiento_manual_url(url: str) -> str | None:
    url_normalizada = normalizar_url_final(url)
    if not url_normalizada:
        return None
    if url_normalizada in URLS_DESCARTAR_MANUALMENTE:
        return "descartar"
    if url_normalizada in URLS_ACEPTAR_MANUALMENTE:
        return "aceptar"
    return None


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


def normalizar_texto_para_comparacion(texto: str) -> str:
    return " ".join(texto.lower().split()) if texto else ""


def limpiar_texto_extraido(elemento) -> str:
    return " ".join(elemento.stripped_strings) if elemento is not None else ""


def contenido_relevante_internacional(titulo: str, texto_enlace: str, contenido: str, url: str) -> bool:
    """Filtro de relevancia para admision internacional: exige admision+
    internacional, admision+academico, matricula+internacional o
    matricula+academico (una sola senal aislada no es suficiente)."""
    texto = ((titulo or "") + " " + (texto_enlace or "") + " " + (contenido or "") + " " + (url or "")).lower()

    if any(ind in texto for ind in INDICADORES_DIRECTOS):
        return True

    coincidencias_admision = sum(1 for ind in INDICADORES_ADMISION if ind in texto)
    coincidencias_matricula = sum(1 for ind in INDICADORES_MATRICULA if ind in texto)
    coincidencias_internacional = sum(1 for ind in INDICADORES_INTERNACIONAL if ind in texto)
    coincidencias_academicas = sum(1 for ind in INDICADORES_ACADEMICOS if ind in texto)

    if coincidencias_admision >= 1 and coincidencias_internacional >= 1:
        return True
    if coincidencias_admision >= 1 and coincidencias_academicas >= 1:
        return True
    if coincidencias_matricula >= 1 and coincidencias_internacional >= 1:
        return True
    if coincidencias_matricula >= 1 and coincidencias_academicas >= 1:
        return True
    return False


def contenido_demasiado_corto(contenido: str) -> bool:
    return len(contenido.strip()) < 100


def recopilar_enlaces(datos_normalizados: dict) -> list[dict]:
    lista_enlaces = []

    def recorrer_bloque(bloque, seccion_origen="", tipo_origen="", titulo_padre=""):
        for enlace in bloque.get("enlaces", []):
            url = enlace.get("url", "")
            if not url:
                continue
            lista_enlaces.append({"texto": enlace.get("texto", ""), "url": url, "seccion_origen": seccion_origen, "padre_origen": titulo_padre, "tipo_origen": tipo_origen})
        for sub_bloque in bloque.get("bloques", []):
            recorrer_bloque(sub_bloque, seccion_origen, tipo_origen, titulo_padre)
        for subseccion in bloque.get("subsecciones", []):
            recorrer_bloque(subseccion, seccion_origen, tipo_origen, titulo_padre)

    for padre in datos_normalizados.get("padres", []):
        titulo_padre = padre.get("titulo", "")

        for seccion in padre.get("secciones", []):
            titulo_seccion = seccion.get("titulo", "")
            tipo_seccion = seccion.get("tipo", "")

            for enlace in seccion.get("enlaces", []):
                url = enlace.get("url", "")
                if not url:
                    continue
                lista_enlaces.append({"texto": enlace.get("texto", ""), "url": url, "seccion_origen": titulo_seccion, "padre_origen": titulo_padre, "tipo_origen": tipo_seccion})

            for subseccion in seccion.get("subsecciones", []):
                recorrer_bloque(subseccion, titulo_seccion, tipo_seccion, titulo_padre)
            for bloque in seccion.get("bloques", []):
                recorrer_bloque(bloque, titulo_seccion, tipo_seccion, titulo_padre)

    urls_vistas = set()
    enlaces_unicos = []
    for enlace in lista_enlaces:
        url_normalizada = normalizar_url_final(enlace.get("url", ""))
        if not url_normalizada or url_normalizada in urls_vistas:
            continue
        urls_vistas.add(url_normalizada)
        enlaces_unicos.append(enlace)

    print("Enlaces extraídos del JSON:", len(lista_enlaces))
    print("Enlaces únicos antes de descargar:", len(enlaces_unicos))
    return enlaces_unicos


def descargar_y_extraer_paginas(enlaces_unicos: list[dict]) -> list[dict]:
    paginas_extraidas = []
    vistos_urls_finales = set()
    sesion = requests.Session()
    sesion.headers.update(HEADERS)

    for enlace in enlaces_unicos:
        url_original = enlace["url"]
        print(url_original)

        if not es_url_internacional(url_original):
            print("Descartado (URL fuera del ámbito UPV)")
            continue

        try:
            respuesta = sesion.get(url_original, timeout=20, allow_redirects=True)
            respuesta.raise_for_status()
        except Exception as e:
            print("Error de descarga:", e)
            continue

        url_final = normalizar_url_final(respuesta.url)

        if not es_url_internacional(url_final):
            print("Descartado (URL final fuera del ámbito UPV)")
            continue
        if url_final in vistos_urls_finales:
            print("Descartado (URL final duplicada)")
            continue
        vistos_urls_finales.add(url_final)

        tratamiento = tratamiento_manual_url(url_final)
        if tratamiento == "descartar":
            print("Descartado (URL excluida manualmente)")
            continue
        aceptar_manualmente = tratamiento == "aceptar"

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
            titulo = limpiar_texto_extraido(h1)
        if not titulo:
            h1 = soup.find("h1")
            if h1:
                titulo = limpiar_texto_extraido(h1)
        if not titulo:
            titulo = enlace.get("texto", "")
        titulo = " ".join(titulo.split())

        bloques = []
        for elemento in contenido_principal.find_all(["h1", "h2", "h3", "h4", "p", "li", "table"]):
            texto = limpiar_texto_extraido(elemento)
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

        if not aceptar_manualmente:
            if not contenido_relevante_internacional(titulo, enlace.get("texto", ""), contenido, url_final):
                print("Descartado (sin relevancia para admisión internacional)")
                continue

        paginas_extraidas.append({
            "url_original": url_original, "url": url_final, "titulo": titulo,
            "texto_enlace": enlace.get("texto", ""), "seccion_origen": enlace.get("seccion_origen", ""),
            "padre_origen": enlace.get("padre_origen", ""), "tipo_origen": enlace.get("tipo_origen", ""),
            "contenido": contenido,
        })
        print("Página aceptada" + (" (URL aceptada manualmente)" if aceptar_manualmente else ""))

    return paginas_extraidas


# ==========================================================
# Generacion de recursos Markdown -- FIEL al notebook original
# ==========================================================

def limpiar_nombre_recurso(nombre: str) -> str:
    if not nombre:
        return "recurso"
    nombre = nombre.lower()
    for viejo, nuevo in {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"}.items():
        nombre = nombre.replace(viejo, nuevo)
    nombre = re.sub(r"[^a-z0-9]+", "_", nombre).strip("_")
    return nombre or "recurso"


def generar_nombre_recurso(titulo: str, indice: int, nombres_utilizados: set) -> str:
    nombre_base = limpiar_nombre_recurso(titulo) or f"recurso_{indice}"
    nombre = nombre_base
    contador = 2
    while nombre in nombres_utilizados:
        nombre = f"{nombre_base}_{contador}"
        contador += 1
    nombres_utilizados.add(nombre)
    return nombre


def _escribir_metadatos_recurso(f, pagina: dict) -> None:
    f.write("---\n")
    f.write("fuente: UPV\n")
    f.write("categoria: admision\n")
    f.write("nivel: internacional\n")
    f.write("tipo_documento: recurso\n")
    if pagina.get("seccion_origen"):
        f.write("seccion: " + str(pagina["seccion_origen"]) + "\n")
    if pagina.get("tipo_origen"):
        f.write("tipo_origen: " + str(pagina["tipo_origen"]) + "\n")
    f.write("---\n\n")


def generar_markdowns_recursos(paginas_extraidas: list[dict], directorio: Path = ADMISION_INTERNACIONAL_RECURSOS_DIR) -> int:
    directorio.mkdir(parents=True, exist_ok=True)

    nombres_utilizados = set()
    contador_recursos = 0

    for indice, pagina in enumerate(paginas_extraidas, start=1):
        contenido = pagina.get("contenido", "")
        if not contenido.strip():
            continue

        nombre_recurso = generar_nombre_recurso(pagina.get("titulo", ""), indice, nombres_utilizados)

        with open(directorio / f"{nombre_recurso}.md", "w", encoding="utf-8") as f:
            _escribir_metadatos_recurso(f, pagina)

            titulo = pagina.get("titulo", "")
            f.write(f"# {titulo}\n\n" if titulo else "# Recurso de admisión internacional\n\n")

            url = pagina.get("url", "")
            if url:
                f.write("Fuente oficial: " + url + "\n\n")

            texto_enlace = pagina.get("texto_enlace", "")
            if texto_enlace:
                f.write("Enlace de origen: " + texto_enlace + "\n\n")

            if pagina.get("padre_origen"):
                f.write("Página de origen: " + pagina["padre_origen"] + "\n\n")
            if pagina.get("seccion_origen"):
                f.write("Sección de origen: " + pagina["seccion_origen"] + "\n\n")
            if pagina.get("tipo_origen"):
                f.write("Tipo de origen: " + pagina["tipo_origen"] + "\n\n")

            f.write("## Contenido\n\n")
            f.write(contenido.strip() + "\n")

        contador_recursos += 1

    print("Recursos generados:", contador_recursos)
    return contador_recursos


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    datos = extraer_estructura_cruda()
    datos = validar_estructura(datos)
    datos_normalizados = normalizar_estructura(datos)
    guardar_json(datos_normalizados)

    generar_markdowns_secciones(datos_normalizados)

    enlaces_unicos = recopilar_enlaces(datos_normalizados)
    paginas_extraidas = descargar_y_extraer_paginas(enlaces_unicos)
    generar_markdowns_recursos(paginas_extraidas)


if __name__ == "__main__":
    main()
