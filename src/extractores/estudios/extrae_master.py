"""Extractor de fichas de titulacion de "Estudios de master" (estudios/master).

Sustituye el contenido entregado por el tutor (125 `.md`, metadatos YAML
propios sin normalizar -- ver "Metadatos YAML" en las notas internas del proyecto) por un
extractor propio que sigue el mismo estandar que institucion/servicios/
admision/investigacion/doctorado: motor de limpieza comun + metadatos
YAML definitivos + extraccion de tablas + limpieza de HTML. No hay
extractor anterior en este repo para esta seccion (el tutor scrapeo el
contenido por su cuenta), asi que esto es un extractor nuevo, no una
reescritura.

Descubrimiento de la estructura real del sitio (sesion 2026-08-22,
comprobado contra la web real):

- El listado `/estudios/master/index-es.html` es una SPA con "Cargar mas
  resultados" (solo ~10 de 122 titulaciones en el HTML estatico inicial,
  igual quirk que servicios universitarios) -- pero inspeccionando sus
  peticiones de red aparece `https://www.upv.es/courses/masteres-es.json`,
  el JSON estatico que alimenta ese listado con las 122 titulaciones YA
  estructuradas (acronimo, url, centro(s), rama(s), campus, modalidad),
  mas los diccionarios de traduccion codigo->nombre. Evita por completo
  la paginacion AJAX.
- Cada titulacion tiene su propio microsite WordPress
  (`/estudios/master/<acronimo>/`) con varias subpaginas fijas:
  Inicio (la propia URL), `/detalle/` ("En detalle": descripcion,
  objetivos, salidas profesionales, estructura, practicas,
  investigacion, intercambio, instalaciones, TFM, empresas
  colaboradoras), `/admision/` (requisitos, criterios, becas). Las tres
  se extraen igual que institucion/servicios: `<main>` +
  `motor_limpieza`.
- "Asignaturas"/"Competencias"/"Profesorado" (bajo `/consulta/...`) NO
  tienen contenido estatico (pagina WordPress vacia, el contenido real
  se inyecta via JS) -- pero cada una carga a su vez una URL clasica
  Oracle Portal (`pls/oalu/sic_pla.lisBloquesTodos` para asignaturas,
  `pls/oalu/sic_verificaa2.competencias`/`.profesorado` para las otras
  dos), identificada inspeccionando las peticiones de red de cada
  subpagina. Las tres usan `id="contenido"` (la CUARTA variante de
  plantilla clasica ya documentada en motor_limpieza.py, sin iframe) y
  necesitan `p_tit` (codigo numerico interno de la titulacion, ej. 2295
  para MBA) -- se obtiene sin peticion extra, ya viene embebido en un
  enlace `p_tit=` de la propia pagina de Inicio ("Registro (RUCT)" bajo
  "Calidad de titulos").

Bug real encontrado y corregido en el propio motor_limpieza.py durante
esta reescritura: `reemplazar_tablas_por_listas()` asumia filas de tabla
siempre hermanas; la tabla de datos del programa (plazas/inicio/
duracion/creditos) en la pagina de Inicio usa HTML invalido -- cada fila
"logica" es una <tr> anidada dentro de una celda de la <tr> anterior (una
cadena, no filas hermanas) -- lo que producia lineas con contenido
duplicado en cascada. Ver el fix en motor_limpieza.py, con efecto
retroactivo en cualquier extractor que ya use tablas.
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
from config import MASTER_CATALOGO_URL, MASTER_JSON, MASTER_KB_DIR
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

BASE_URL = "https://www.upv.es"

FUENTE = "UPV"
CATEGORIA = "estudios"
NIVEL = "master"
TIPO_RECURSO = "informacion"

# El contenido real de estas 3 "consultas" no esta en la pagina WordPress
# (JS puro) sino en un endpoint clasico Oracle Portal aparte, identificado
# inspeccionando las peticiones de red -- ver cabecera del modulo.
URL_ASIGNATURAS = "https://www.upv.es/pls/oalu/sic_pla.lisBloquesTodos?P_TIT={p_tit}&P_NOMBRE=&P_CEN={acronimo}&P_TIPO=plan&P_IDIOMA=c&P_ACCESO=G&P_NAVEGA=&P_VISTA=MWP"
URL_COMPETENCIAS = "https://www.upv.es/pls/oalu/sic_verificaa2.competencias?p_idioma=c&p_vista=MWP&p_tit={p_tit}"
URL_PROFESORADO = "https://www.upv.es/pls/oalu/sic_verificaa2.profesorado?p_idioma=c&p_vista=MWP&p_tit={p_tit}"

# Titulos de widgets de "ruido" (actualidad/galeria/normativa) que cortan
# el contenido util de la pagina de Inicio -- igual criterio que
# TITULOS_CORTE_PLANTILLA de motor_limpieza.py, pero propios de esta
# plantilla (no genericos de upv.es).
TITULOS_CORTE_INICIO = {"conoce el master a fondo", "conoce el máster a fondo"}

# Etiqueta de accesibilidad (sr-only) que precede al contenido real de
# "/detalle/" -- no es boilerplate de menu (no esta en
# TEXTOS_BOILERPLATE_BASE) asi que se filtra aparte.
TEXTO_RUIDO_DETALLE = {"contenido de la pagina", "contenido de la página"}

# Widget de botones "Compartir" (Facebook/Twitter/Linkedin/Pinterest) al
# final de /detalle/ y /admision/ -- ruido de plantilla, no boilerplate
# de menu generico de upv.es.
PATRON_COMPARTIR = re.compile(r"^compartir\s*:", re.IGNORECASE)

# URL real de la pagina de listado (no la API JSON) -- es la que se usa
# como `url:` del resumen y como `resumen:` de cada ficha, para que
# apunte a un documento real del corpus (la propia master.md), no a un
# endpoint de datos sin contenido navegable.
RESUMEN_URL = "https://www.upv.es/estudios/master/index-es.html"

PATRON_P_TIT = re.compile(r"[?&]p_tit=(\d+)", re.IGNORECASE)


def generar_markdown_resumen(items: list[dict]) -> str:
    """Bug real corregido (sesion 2026-08-23): antes de este fix, ninguna
    ficha de master tenia un documento "resumen" al que apuntar -- las
    122 fichas ponian `resumen: <URL del JSON de la API>`, que no
    corresponde a ningun documento real del corpus (viola el esquema
    definitivo, ver las notas internas del proyecto "resumen es siempre una URL que apunta a
    otro documento del propio corpus"). Genera una tabla-indice a partir
    del propio catalogo (siempre sincronizada, a diferencia de la
    `_indice.md` estatica que dejo el tutor)."""
    yaml_metadatos = ml.generar_yaml_metadatos(
        fuente=FUENTE, url=RESUMEN_URL, categoria=CATEGORIA, nivel=NIVEL,
        tipo_documento="resumen", titulo="Másteres universitarios")

    filas = [
        f"| [{i['acronimo']}]({i['url']}) | {i['titulo']} | {i['campus']} | {i['modalidad']} | {i['rama']} |"
        for i in items
    ]
    tabla = (
        "| Acrónimo | Título | Campus | Modalidad | Rama |\n"
        "|----------|--------|--------|-----------|------|\n" + "\n".join(filas)
    )
    return f"{yaml_metadatos}\n# Másteres universitarios\n\n{tabla}\n"


def _yaml_recurso(item: dict) -> str:
    campos_extra = {
        "acronimo": item["acronimo"],
        "campus": item["campus"],
        "modalidad": item["modalidad"],
        "centro": item["centro"],
        "rama": item["rama"],
    }
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=item["url"], categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="recurso", tipo_recurso=TIPO_RECURSO,
                                      resumen=RESUMEN_URL, seccion=NIVEL, titulo=item["titulo"],
                                      campos_extra=campos_extra)


# ==========================================================
# 1. Catalogo -- JSON estatico que alimenta el listado con filtros
# ==========================================================

def extraer_catalogo(url: str = MASTER_CATALOGO_URL) -> list[dict]:
    respuesta = requests.get(url, headers=HEADERS, timeout=30)
    respuesta.raise_for_status()
    datos = respuesta.json()

    centros_por_acro = {c["acro"]: limpiar_texto(c["nom"]) for c in datos.get("centros", [])}
    ramas_por_id = {r["id_rama"]: limpiar_texto(r["nom"]) for r in datos.get("ramas", [])}
    campus_por_id = {c["id_campus"]: limpiar_texto(c["nom"]) for c in datos.get("campus", [])}
    modalidad_por_id = {m["id_modalidad"]: limpiar_texto(m["nombre"]) for m in datos.get("modalidad", [])}

    items = []
    for t in datos.get("titulaciones", []):
        acronimo = t.get("acro", "").strip()
        if not acronimo:
            continue
        centro = "; ".join(centros_por_acro.get(c, c) for c in t.get("centros", []))
        rama = "; ".join(ramas_por_id.get(r, str(r)) for r in t.get("ramas", []))
        items.append({
            "acronimo": acronimo,
            "titulo": limpiar_texto(t.get("nom", "")),
            "url": ml.normalizar_url(t.get("url", ""), BASE_URL),
            "centro": centro,
            "rama": rama,
            "campus": campus_por_id.get(t.get("id_campus", ""), ""),
            "modalidad": modalidad_por_id.get(t.get("id_modalidad", ""), ""),
        })

    print("Másteres encontrados en el catálogo:", len(items))
    return items


def guardar_json(items: list[dict], ruta: Path = MASTER_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"titulaciones": items}, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


# ==========================================================
# 2. Contenido de cada ficha -- Inicio + En detalle + Admision (motor
#    comun) + Asignaturas/Competencias/Profesorado (endpoint clasico)
# ==========================================================

def _extraer_p_tit(soup: BeautifulSoup) -> str | None:
    """El codigo numerico interno de la titulacion (necesario para las
    consultas de asignaturas/competencias/profesorado) viene embebido
    sin peticion extra en el enlace al Registro RUCT de la pagina de
    Inicio, bajo "Calidad de títulos"."""
    enlace = soup.find("a", href=PATRON_P_TIT)
    if enlace is None:
        return None
    m = PATRON_P_TIT.search(enlace["href"])
    return m.group(1) if m else None


def _cortar_ruido_inicio(lineas: list[str]) -> list[str]:
    for indice, linea in enumerate(lineas):
        if not linea.startswith("#"):
            continue
        normalizado = ml.normalizar_para_comparar(re.sub(r"^#+\s*", "", linea))
        if normalizado in TITULOS_CORTE_INICIO:
            return lineas[:indice]
    return lineas


def extraer_inicio(url: str) -> tuple[list[str], str | None]:
    """Devuelve (lineas_utiles, p_tit). El propio <h1> real de la pagina
    no se usa como corte (recortar_h1=False): el resto de contenido util
    (tarjetas de plazas/fechas, fases de preinscripcion) viene ANTES del
    primer <h1> real de la plantilla ("Conoce el master a fondo", un
    widget, no el titulo)."""
    soup, es_html = ml.descargar_soup(url, headers=HEADERS)
    if not es_html:
        return [], None
    p_tit = _extraer_p_tit(soup)

    soup = ml.limpiar_contenido_html(soup)
    contenido = soup.find("main")
    if contenido is None:
        return [], p_tit

    ml.reemplazar_tablas_por_listas(soup, contenido)
    lineas = ml.extraer_bloques_contenido(contenido, url)
    lineas = ml.limpiar_lineas_finales(lineas, recortar_h1=False)
    lineas = _cortar_ruido_inicio(lineas)
    return lineas, p_tit


def extraer_pagina_main(url: str, recortar_h1: bool = True) -> list[str]:
    """Extraccion generica para /detalle/ y /admision/: <main> + motor
    de limpieza comun, sin logica propia de esta seccion.

    Ambas subpaginas son opcionales: los "Dobles Master" (combinacion de
    dos titulaciones ya existentes, 17/122 en el catalogo) no tienen su
    propio /detalle/ -- un 404 aqui NO debe abortar la titulacion
    completa (bug real encontrado al ejecutar: sin este guard, Inicio/
    Asignaturas/Competencias/Profesorado ya extraidos con exito se
    descartaban por el fallo de esta UNICA subpagina opcional, dejando
    17/122 masteres sin generar en absoluto). Mismo criterio que el fix
    de extraer_enlaces_subpaginas() en estudios/doctorado."""
    try:
        soup, es_html = ml.descargar_soup(url, headers=HEADERS)
    except requests.exceptions.HTTPError as error:
        if error.response is not None and error.response.status_code == 404:
            return []
        raise
    if not es_html:
        return []
    soup = ml.limpiar_contenido_html(soup)
    contenido = soup.find("main")
    if contenido is None:
        return []

    ml.reemplazar_tablas_por_listas(soup, contenido)
    lineas = ml.extraer_bloques_contenido(contenido, url)
    lineas = ml.limpiar_lineas_finales(lineas, recortar_h1=recortar_h1)
    normalizadas = [ml.normalizar_para_comparar(re.sub(r"^#+\s*|^-\s*", "", l)) for l in lineas]
    return [
        l for l, n in zip(lineas, normalizadas)
        if n not in TEXTO_RUIDO_DETALLE and not PATRON_COMPARTIR.match(n)
    ]


def extraer_consulta_clasica(url: str) -> list[str]:
    """Asignaturas/Competencias/Profesorado: sin main/article/entry-content
    (pagina WordPress vacia, contenido inyectado por JS que no se
    ejecuta) -- el contenido real esta en el endpoint clasico Oracle
    Portal aparte que carga cada subpagina (ver cabecera del modulo),
    con el marcador id="contenido" sin iframe."""
    soup, es_html = ml.descargar_soup(url, headers=HEADERS)
    if not es_html:
        return []
    soup = ml.limpiar_contenido_html(soup)
    contenido = soup.find(id="contenido")
    if contenido is None:
        return []

    ml.reemplazar_tablas_por_listas(soup, contenido)
    lineas = ml.extraer_bloques_contenido(contenido, url)
    return ml.limpiar_lineas_finales(lineas, recortar_h1=False)


# ==========================================================
# 3. Markdown por titulacion
# ==========================================================

def _bloque(titulo: str, lineas: list[str]) -> str:
    if not lineas:
        return f"## {titulo}\n\n_Sin contenido disponible._"
    return f"## {titulo}\n\n" + "\n\n".join(lineas)


def generar_markdown_titulacion(item: dict, carpeta: Path) -> bool:
    titulo, url, acronimo = item["titulo"], item["url"], item["acronimo"]
    print(f"  Extrayendo: {titulo} ({acronimo})")

    try:
        lineas_inicio, p_tit = extraer_inicio(url)
        if not lineas_inicio and p_tit is None:
            print("    AVISO: no se ha podido leer la página de inicio.")
            return False

        lineas_detalle = extraer_pagina_main(url.rstrip("/") + "/detalle/")
        time.sleep(0.3)
        lineas_admision = extraer_pagina_main(url.rstrip("/") + "/admision/")
        time.sleep(0.3)

        if p_tit:
            lineas_asignaturas = extraer_consulta_clasica(
                URL_ASIGNATURAS.format(p_tit=p_tit, acronimo=acronimo))
            time.sleep(0.3)
            lineas_competencias = extraer_consulta_clasica(URL_COMPETENCIAS.format(p_tit=p_tit))
            time.sleep(0.3)
            lineas_profesorado = extraer_consulta_clasica(URL_PROFESORADO.format(p_tit=p_tit))
            time.sleep(0.3)
        else:
            print("    AVISO: no se ha encontrado p_tit -- sin asignaturas/competencias/profesorado.")
            lineas_asignaturas = lineas_competencias = lineas_profesorado = []

        bloques = [
            f"# {titulo}",
            _bloque("Inicio", lineas_inicio),
            _bloque("En detalle", lineas_detalle),
            _bloque("Asignaturas", lineas_asignaturas),
            _bloque("Competencias", lineas_competencias),
            _bloque("Profesorado", lineas_profesorado),
            _bloque("Admisión", lineas_admision),
        ]

        yaml_metadatos = _yaml_recurso(item)
        markdown = f"{yaml_metadatos}\n" + "\n\n".join(bloques) + "\n"

        ruta_archivo = carpeta / f"{acronimo}.md"
        with open(ruta_archivo, "w", encoding="utf-8") as archivo:
            archivo.write(markdown)
        print(f"  OK: {ruta_archivo}")
        return True

    except Exception as error:
        print(f"  ERROR: {error}")
        return False


def generar_markdowns_titulaciones(items: list[dict], carpeta: Path = MASTER_KB_DIR) -> tuple[int, int, int]:
    carpeta.mkdir(parents=True, exist_ok=True)
    total = correctos = errores = 0
    for item in items:
        total += 1
        if generar_markdown_titulacion(item, carpeta):
            correctos += 1
        else:
            errores += 1
        time.sleep(0.3)
    return total, correctos, errores


# ==========================================================
# Ejecucion
# ==========================================================

def main(limite: int | None = None) -> None:
    items = extraer_catalogo()
    guardar_json(items)

    MASTER_KB_DIR.mkdir(parents=True, exist_ok=True)
    with open(MASTER_KB_DIR / "master.md", "w", encoding="utf-8") as archivo:
        archivo.write(generar_markdown_resumen(items))

    if limite is not None:
        items = items[:limite]
    total, correctos, errores = generar_markdowns_titulaciones(items)
    print(f"Másteres: {total} · generados: {correctos} · errores: {errores}")


if __name__ == "__main__":
    main()
