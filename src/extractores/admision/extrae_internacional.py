"""Extractor de "Admision internacional" (alumnado internacional).

Reescritura completa (2026-08-21) que sustituye el YAML propio
(fuente/categoria/nivel/tipo_documento sin resumen/seccion) y la
extraccion de recursos con un loop h1-h4/p/li/table ad-hoc -- por el
patron ya validado en el resto de admision/investigacion: metadatos YAML
definitivos + motor_limpieza.py para el contenido de cada pagina
ENLAZADA (traversal, PDF, plantilla clasica, limpieza de renombrados).

La extraccion de la ESTRUCTURA cruda (extraer_estructura_cruda(),
extraer_bloques_contenedor(), validar_estructura(),
normalizar_estructura()) se mantiene tal cual: es una reconstruccion ya
verificada contra la web real (ver AVISO DE FIDELIDAD mas abajo, sin
cambios respecto a la version anterior) de una maquetacion con bloques
"upv-section"/"upv-blocks"/"upv-boxes" que no encaja en el motor de
"hoja de contenido" de institucion/servicios. Lo que se sustituye es
unicamente el paso 4 (descubrir/descargar/extraer las paginas enlazadas
desde esos bloques) y el formato de metadatos YAML de los tres tipos de
documento (padre/seccion/recurso).

AVISO DE FIDELIDAD (heredado, sin cambios): el notebook original
(Extrae_Admision_Internacional.ipynb) tenia una celda perdida -- el
BLOQUE 6 (validacion/normalizacion) usaba una variable `datos` que nunca
se construia en ninguna celda guardada. extraer_estructura_cruda() esta
RECONSTRUIDA (no traducida) inspeccionando la web real: dentro de
article > div.entry-content, los bloques de contenido real llevan la
clase "upv-section" (comprobado 2026-08-21: siguen siendo 8 bloques). El
bloque "upv-blocks" (calendario de plazos) se reconstruyo asumiendo que
ahi entra extraer_bloques_contenedor() (esa funcion SI estaba completa
en el notebook original); el resultado para esa seccion en concreto no
se pudo verificar byte a byte contra lo comiteado en su momento.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/ (config.py, common.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # src/extractores/ (motor_limpieza.py)

from bs4 import BeautifulSoup
import requests

from common import limpiar_texto
from config import ADMISION_INTERNACIONAL_DIR, ADMISION_INTERNACIONAL_JSON, ADMISION_INTERNACIONAL_RECURSOS_DIR, ADMISION_INTERNACIONAL_URL
import motor_limpieza as ml

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; UPV-Admision-Bot/1.0)"}

FUENTE = "UPV"
CATEGORIA = "admision"
NIVEL = "internacional"
TIPO_RECURSO = "informacion"

INTRO_DOCUMENTO = (
    "Información sobre el proceso de admisión de alumnado internacional "
    "en la Universitat Politècnica de València."
)

DOMINIOS_UPV = {"www.upv.es", "upv.es"}
URLS_DESCARTAR_MANUALMENTE = {"http://www.upv.es/es", "http://www.upv.es/index-es.html"}
URLS_ACEPTAR_MANUALMENTE = {"http://www.upv.es/rankings/index.html"}

SELECTORES_CONTENIDO = ["main", "article", ".entry-content", "#content", ".content", ".entry", ".mwc_contenido"]

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


def _yaml_resumen(url: str, titulo: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=url, categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="resumen", titulo=titulo)


def _yaml_seccion(url_resumen: str, titulo: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=url_resumen, categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="seccion", resumen=url_resumen, titulo=titulo)


def _yaml_recurso(pagina: dict, seccion_slug: str, url_resumen: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=pagina["url"], categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="recurso", tipo_recurso=TIPO_RECURSO,
                                      resumen=url_resumen, seccion=seccion_slug or "", titulo=pagina["titulo"])


def texto_limpio(elemento) -> str:
    return " ".join(elemento.stripped_strings) if elemento is not None else ""


def url_absoluta(url: str, base: str = ADMISION_INTERNACIONAL_URL) -> str:
    return ml.normalizar_url(url, base) if url else ""


def normalizar_espacios(texto: str) -> str:
    return " ".join(texto.split()) if texto else ""


def obtener_descripcion(contenedor) -> str:
    if contenedor is None:
        return ""
    parrafos = contenedor.find_all("p", recursive=False)
    return " ".join(texto_limpio(p) for p in parrafos).strip()


# ==========================================================
# Contenedores de bloques / calendarios -- sin cambios respecto a la
# version anterior (ver AVISO DE FIDELIDAD en la cabecera del modulo).
# ==========================================================

def extraer_titulo(elemento) -> str:
    h = elemento.find(["h1", "h2", "h3", "h4"])
    return texto_limpio(h) if h else ""


def extraer_enlaces(elemento, base: str = ADMISION_INTERNACIONAL_URL) -> list[dict]:
    return [{"texto": texto_limpio(a), "url": url_absoluta(a["href"], base)} for a in elemento.find_all("a", href=True)]


def extraer_bloques_contenedor(contenedor) -> list[dict]:
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
# Extraccion cruda -- sin cambios (ver AVISO DE FIDELIDAD)
# ==========================================================

def extraer_seccion_cruda(bloque) -> dict:
    clases = bloque.get("class", [])
    es_calendario = "upv-blocks" in clases
    titulo = "" if es_calendario else extraer_titulo(bloque)
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
# Validacion y normalizacion -- sin cambios
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
        json.dump(datos, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


# ==========================================================
# Markdown base (padre + secciones) -- vuelca el JSON, YAML definitivo
# ==========================================================

def generar_nombre_seccion(titulo: str, indice: int, nombres_utilizados: set) -> str:
    nombre = ml.normalizar_identificador(titulo) or f"seccion_{indice}"
    nombre_original = nombre
    contador = 2
    while nombre in nombres_utilizados:
        nombre = f"{nombre_original}_{contador}"
        contador += 1
    nombres_utilizados.add(nombre)
    return nombre


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
        nombre_padre = ml.normalizar_identificador(titulo_padre) or "padre"

        carpeta_padre = directorio / nombre_padre
        carpeta_padre.mkdir(parents=True, exist_ok=True)

        with open(directorio / f"{nombre_padre}.md", "w", encoding="utf-8") as f:
            f.write(_yaml_resumen(padre.get("url", ADMISION_INTERNACIONAL_URL), titulo_padre or "Admisión internacional"))
            if titulo_padre:
                f.write(f"\n# {titulo_padre}\n\n")
            else:
                f.write("\n")
            f.write(INTRO_DOCUMENTO + "\n\n")

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
                f.write(_yaml_seccion(padre.get("url", ADMISION_INTERNACIONAL_URL), seccion.get("titulo", "") or f"Sección {i}"))
                f.write("\n")
                escribir_seccion(f, seccion, padre)
            contador += 1

    print("Markdown base generado. Archivos:", contador)
    return contador


# ==========================================================
# Descubrimiento de enlaces -- sin cambios
# ==========================================================

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


# ==========================================================
# Markdown de los recursos enlazados -- motor_limpieza
# ==========================================================

def encontrar_contenedor(soup: BeautifulSoup):
    contenedor_moderno = soup.find(id="smooth-wrapper") or soup.find("main")
    if contenedor_moderno is not None:
        return contenedor_moderno
    for selector in SELECTORES_CONTENIDO:
        elemento = soup.select_one(selector)
        if elemento is not None and len(elemento.get_text(" ", strip=True)) >= 100:
            return elemento
    return None


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


def generar_markdown_recurso(enlace: dict, carpeta: Path, url_resumen: str) -> dict | None:
    """Descarga y filtra un recurso enlazado; escribe el .md si pasa el
    filtro de relevancia internacional y devuelve {"titulo","url"} (para
    el catalogo de limpieza de renombrados), o None si se descarta."""
    url_original = enlace["url"]

    if not es_url_internacional(url_original):
        print("Descartado (URL fuera del ámbito UPV):", url_original)
        return None

    print(f"  Extrayendo: {enlace.get('texto', '')} ({url_original})")
    try:
        respuesta = requests.get(url_original, headers=HEADERS, timeout=30, allow_redirects=True)
        respuesta.raise_for_status()
    except Exception as error:
        print("    ERROR descargando:", error)
        return None

    url_final = normalizar_url_final(respuesta.url)
    if not es_url_internacional(url_final):
        print("    Descartado (URL final fuera del ámbito UPV)")
        return None

    tratamiento = tratamiento_manual_url(url_final)
    if tratamiento == "descartar":
        print("    Descartado (URL excluida manualmente)")
        return None
    aceptar_manualmente = tratamiento == "aceptar"

    tipo = ml.tipo_contenido(respuesta.headers.get("Content-Type", ""))
    titulo = enlace.get("texto", "") or url_final

    if tipo == "pdf":
        paginas = ml.extraer_texto_pdf(respuesta.content)
        cuerpo = "\n\n".join(paginas) if paginas else "_PDF sin texto extraíble (probablemente escaneado sin OCR)._"
    elif tipo != "html":
        print("    Descartado (recurso no HTML ni PDF)")
        return None
    else:
        soup = BeautifulSoup(respuesta.text, "html.parser")
        soup = ml.limpiar_contenido_html(soup)
        contenedor = encontrar_contenedor(soup)
        if contenedor is not None:
            ml.reemplazar_tablas_por_listas(soup, contenedor)
            lineas = ml.extraer_bloques_contenido(contenedor, url_final)
            lineas = ml.limpiar_lineas_finales(lineas)
        else:
            lineas = extraer_contenido_iframe_clasico(soup, url_final)
            if not lineas and soup.body is not None:
                # Ultimo recurso, igual que institucion/servicios/rankings:
                # alguna pagina aceptada manualmente (ej. rankings/index.html,
                # ver URLS_ACEPTAR_MANUALMENTE) no tiene main/smooth-wrapper
                # ni encaja en ningun selector conocido ni tiene iframe
                # clasico -- limpiar_lineas_finales() filtra el boilerplate
                # de menu si el body no aporta contenido real.
                ml.reemplazar_tablas_por_listas(soup, soup.body)
                lineas = ml.extraer_bloques_contenido(soup.body, url_final)
                lineas = ml.limpiar_lineas_finales(lineas)
        if not lineas:
            print("    Descartado (contenido insuficiente)")
            return None

        titulo = lineas[0].lstrip("# ").strip() if lineas[0].startswith("#") else titulo
        cuerpo = "\n\n".join(lineas)

        if not aceptar_manualmente and not contenido_relevante_internacional(titulo, enlace.get("texto", ""), cuerpo, url_final):
            print("    Descartado (sin relevancia para admisión internacional)")
            return None

    pagina = {"titulo": titulo, "url": url_final}
    yaml_metadatos = _yaml_recurso(pagina, enlace.get("seccion_origen", ""), url_resumen)
    markdown = f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url_final}\n\n{cuerpo}\n"

    ruta_archivo = carpeta / ml.nombre_archivo_markdown(titulo)
    with open(ruta_archivo, "w", encoding="utf-8") as archivo:
        archivo.write(markdown)
    print(f"  OK ({tipo}): {ruta_archivo}" + (" (URL aceptada manualmente)" if aceptar_manualmente else ""))
    return pagina


def generar_markdowns_recursos(enlaces_unicos: list[dict], carpeta: Path = ADMISION_INTERNACIONAL_RECURSOS_DIR,
                                url_resumen: str = ADMISION_INTERNACIONAL_URL,
                                catalogo_anterior: list[dict] | None = None) -> tuple[int, int, int]:
    carpeta.mkdir(parents=True, exist_ok=True)

    total = correctos = 0
    elementos_escritos = []
    for enlace in enlaces_unicos:
        total += 1
        pagina = generar_markdown_recurso(enlace, carpeta, url_resumen)
        if pagina is not None:
            correctos += 1
            elementos_escritos.append(pagina)
        time.sleep(0.3)

    borrados = ml.limpiar_ficheros_renombrados(catalogo_anterior or [], elementos_escritos, carpeta)
    return total, correctos, borrados


def cargar_recursos_anteriores(ruta: Path = ADMISION_INTERNACIONAL_JSON) -> list[dict]:
    """El catalogo JSON de este extractor es la estructura normalizada
    (padre/secciones/bloques), no una lista de recursos -- se usa en su
    lugar el listado de ficheros .md ya existentes en la carpeta de
    recursos como catalogo "anterior" (titulo derivado del nombre de
    fichero no sirve para comparar url->titulo, asi que en la practica
    esta seccion no aplica limpieza de renombrados: no hay una fuente de
    verdad anterior url->titulo sin volver a descargar todo). Se deja la
    funcion (devuelve siempre []) para mantener la misma forma de main()
    que el resto de extractores y documentar la limitacion."""
    return []


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    catalogo_anterior = cargar_recursos_anteriores()

    datos = extraer_estructura_cruda()
    datos = validar_estructura(datos)
    datos_normalizados = normalizar_estructura(datos)
    guardar_json(datos_normalizados)

    generar_markdowns_secciones(datos_normalizados)

    enlaces_unicos = recopilar_enlaces(datos_normalizados)
    url_resumen = datos_normalizados["padres"][0].get("url", ADMISION_INTERNACIONAL_URL)
    total, correctos, borrados = generar_markdowns_recursos(enlaces_unicos, url_resumen=url_resumen, catalogo_anterior=catalogo_anterior)
    print(f"Admisión internacional: recursos {total} · generados: {correctos} · renombrados limpiados: {borrados}")


if __name__ == "__main__":
    main()
