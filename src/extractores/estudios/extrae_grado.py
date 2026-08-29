"""Extractor de fichas de titulacion de "Estudios de grado" (estudios/grado).

Hueco vacio del sitemap (solo `.gitkeep`, sin contenido ni extractor
previo -- a diferencia de estudios/master, aqui no habia ni siquiera
contenido previo que sustituir). Mismo estandar que el resto de
secciones ya definitivas: motor de limpieza comun + metadatos YAML
definitivos + limpieza de tablas.

Descubrimiento de la estructura real del sitio (sesion 2026-08-22,
comprobado contra la web real) -- mismo patron general que
estudios/master (ver ese modulo), con diferencias reales:

- El catalogo estatico es `https://www.upv.es/courses/grados-es.json`
  (63 titulaciones), pero a diferencia del de master NO incluye
  campus/modalidad por titulacion directamente.
  - `campus` SI se puede derivar de forma fiable: cada uno de los 14
    centros que aparecen en grado tambien aparece en
    `masteres-es.json` (que si trae `id_campus` por titulacion), y el
    cruce es sin ambiguedad -- cada centro (instalacion fisica) esta
    en un unico campus en los dos catalogos. `CENTRO_CAMPUS` (abajo)
    es esa tabla, verificada por sesion 2026-08-23 cruzando ambos
    JSON en vivo (0 centros ambiguos de 38 en total, los 14 de grado
    incluidos). Se usa para las 51/63 titulaciones de campus unico
    (para las 12 con itinerarios ya sale directo del `<h3>` del
    selector, ver `_expandir_itinerarios`).
  - `modalidad` NO tiene ninguna fuente verificable (ni en el JSON del
    catalogo ni mencionada en el contenido real de las fichas
    comprobadas) -- se sigue omitiendo del YAML, mismo criterio que
    acronimo/campus/modalidad/centro en estudios/doctorado (mejor
    omitir que inventar un valor no verificable).
- La URL del catalogo no siempre lleva a la ficha real: 12 de las 63
  titulaciones se ofertan en mas de un campus y el catalogo apunta a una
  pagina "selector" (`/estudios/grado/<ACRO>-itinerarios-es.html`) con
  un enlace por campus hacia la ficha real
  (`/titulaciones/<ACRO>[-sufijo]/`) -- se sigue ese selector y se
  genera UN recurso por cada campus (ej. GADE.md y GADE-A.md), cada uno
  con su propio campo `campus` derivado del texto del enlace. El resto
  (51/63) enlaza directamente a `/titulaciones/<ACRO>/indexc.html`.
- La ficha en si NO es un microsite WordPress (a diferencia de
  estudios/master): es la plantilla clasica Oracle Portal ya conocida
  (`id="contenido"`, sin iframe -- misma variante que las "consultas" de
  master), con las secciones reales (Presentacion, Salidas
  profesionales, Movilidad internacional y practicas, Continuacion de
  estudios, Plan de estudios/Creditos) TODAS en una unica pagina -- no
  hace falta seguir subpaginas separadas para eso, a diferencia de
  master (Inicio/En detalle si eran paginas distintas).
- Asignaturas/Competencias/Profesorado usan los MISMOS endpoints clasicos
  que estudios/master (`sic_pla.lisBloquesTodos`,
  `sic_verificaa2.competencias`/`.profesorado`), con `p_vista=MSE` en vez
  de `MWP` (la variante nativa de esta plantilla, comprobado que
  `lisBloquesTodos` con estos parametros funciona igual de bien que en
  master). El `p_tit` se obtiene igual que en master: sin peticion
  extra, embebido en un enlace de la propia ficha ("Datos generales").
- Deliberadamente NO se sigue una seccion de "Admision" propia de la
  ficha (a diferencia de master): su URL real esta detras de un menu
  `menu_XXXXXc.html` que no expone el contenido directamente (necesita
  inspeccionar peticiones de red con un navegador real para localizar su
  endpoint, a diferencia de asignaturas/competencias/profesorado, cuyo
  patron ya se conocia de master) y el contenido de admision a grado ya
  esta cubierto en detalle por `admision/grado/*` -- no se duplica aqui.
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
from config import GRADO_CATALOGO_URL, GRADO_JSON, GRADO_KB_DIR
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
NIVEL = "grado"
TIPO_RECURSO = "informacion"

URL_ASIGNATURAS = "https://www.upv.es/pls/oalu/sic_pla.lisBloquesTodos?P_TIT={p_tit}&P_NOMBRE=&P_CEN={acronimo}&P_TIPO=plan&P_IDIOMA=c&P_ACCESO=G&P_NAVEGA=&P_VISTA=MSE"
URL_COMPETENCIAS = "https://www.upv.es/pls/oalu/sic_verificaa2.competencias?p_idioma=c&p_vista=MSE&p_tit={p_tit}"
URL_PROFESORADO = "https://www.upv.es/pls/oalu/sic_verificaa2.profesorado?p_idioma=c&p_vista=MSE&p_tit={p_tit}"

PATRON_P_TIT = re.compile(r"[?&]p_tit=(\d+)", re.IGNORECASE)

# Centro (instalacion fisica) -> campus, cruzado desde masteres-es.json
# (grados-es.json no trae campus). Ver docstring del modulo.
CENTRO_CAMPUS = {
    "EPSA": "Campus de Alcoy",
    "EPSG": "Campus de Gandia",
    "ETSA": "Campus de Valencia",
    "ETSIAMN": "Campus de Valencia",
    "ETSIADI": "Campus de Valencia",
    "ETSIE": "Campus de Valencia",
    "ETSIGCT": "Campus de Valencia",
    "ETSINF": "Campus de Valencia",
    "ETSICCP": "Campus de Valencia",
    "ETSII": "Campus de Valencia",
    "ETSIT": "Campus de Valencia",
    "ADE": "Campus de Valencia",
    "BBAA": "Campus de Valencia",
    "BVPI": "Campus de Hangzhou",
}

# El <h3> de las paginas selector de itinerarios usa texto crudo e
# inconsistente entre paginas para el mismo campus real ("Campus de Vera
# (Valencia)" en una, "Campus de Valencia (Valencia)" en otra) -- se
# normaliza contra el mismo nombre canonico de 4 campus que usa
# masteres-es.json (ver CENTRO_CAMPUS), buscando la ciudad dentro del texto.
CAMPUS_CANONICOS = {
    "alcoy": "Campus de Alcoy",
    "gandia": "Campus de Gandia",
    "gandía": "Campus de Gandia",
    "valencia": "Campus de Valencia",
    "valència": "Campus de Valencia",
    "vera": "Campus de Valencia",
    "hangzhou": "Campus de Hangzhou",
}


def _normalizar_campus(texto: str) -> str:
    texto_normalizado = texto.lower()
    for clave, canonico in CAMPUS_CANONICOS.items():
        if clave in texto_normalizado:
            return canonico
    return texto


# URL real de la pagina de listado (no la API JSON) -- misma logica que
# RESUMEN_URL en extrae_master.py: apunta a un documento real navegable,
# no a un endpoint de datos sin contenido propio.
RESUMEN_URL = "https://www.upv.es/estudios/grado/index-es.html"

# "Profesiones reguladas" -- enlazada desde el sitemap oficial dentro de
# "Estudios de grado" (hermana de "Dobles titulaciones internacionales"/
# "Videos de grados"), pero sin contenido propio en el corpus hasta ahora
# (a peticion de Miguel, 2026-08-23). Pagina moderna estandar (motor de
# limpieza generico, sin patron especial), con contenido real y util:
# que grados/masteres habilitan para el ejercicio de cada profesion
# regulada (arquitecto/a, ingeniero/a tecnico/a...).
URL_PROFESIONES_REGULADAS = "https://www.upv.es/estudios/profesiones-reguladas/index-es.html"


def generar_markdown_resumen(items: list[dict]) -> str:
    """Bug real corregido (sesion 2026-08-23, mismo hallazgo que en
    extrae_master.py): sin este documento, las fichas de grado ponian
    `resumen: <URL del JSON de la API>`, que no corresponde a ningun
    documento real del corpus (viola el esquema YAML definitivo)."""
    yaml_metadatos = ml.generar_yaml_metadatos(
        fuente=FUENTE, url=RESUMEN_URL, categoria=CATEGORIA, nivel=NIVEL,
        tipo_documento="resumen", titulo="Grados universitarios")

    filas = [
        f"| [{i['codigo']}]({i['url']}) | {i['titulo']} | {i['campus']} | {i['centro']} | {i['rama']} |"
        for i in items
    ]
    tabla = (
        "| Código | Título | Campus | Centro | Rama |\n"
        "|--------|--------|--------|--------|------|\n" + "\n".join(filas)
    )
    return f"{yaml_metadatos}\n# Grados universitarios\n\n{tabla}\n"


def generar_markdown_profesiones_reguladas(carpeta: Path = GRADO_KB_DIR) -> bool:
    try:
        soup, es_html = ml.descargar_soup(URL_PROFESIONES_REGULADAS, headers=HEADERS)
        if not es_html:
            print("  AVISO: profesiones-reguladas no es HTML.")
            return False
        soup = ml.limpiar_contenido_html(soup)
        contenedor = soup.find(id="smooth-wrapper") or soup.find("main")
        if contenedor is None:
            print("  AVISO: no se ha encontrado contenido en profesiones-reguladas.")
            return False

        ml.reemplazar_tablas_por_listas(soup, contenedor)
        lineas = ml.extraer_bloques_contenido(contenedor, URL_PROFESIONES_REGULADAS)
        lineas = ml.limpiar_lineas_finales(lineas)
        if not lineas:
            print("  AVISO: profesiones-reguladas sin contenido.")
            return False

        yaml_metadatos = ml.generar_yaml_metadatos(
            fuente=FUENTE, url=URL_PROFESIONES_REGULADAS, categoria=CATEGORIA, nivel=NIVEL,
            tipo_documento="recurso", tipo_recurso=TIPO_RECURSO, resumen=RESUMEN_URL, seccion=NIVEL,
            titulo="Profesiones reguladas")
        markdown = f"{yaml_metadatos}\n" + "\n\n".join(lineas) + "\n"

        ruta = carpeta / "profesiones_reguladas.md"
        with open(ruta, "w", encoding="utf-8") as archivo:
            archivo.write(markdown)
        print(f"  OK: {ruta}")
        return True
    except Exception as error:
        print(f"  ERROR (profesiones-reguladas): {error}")
        return False


def _yaml_recurso(item: dict) -> str:
    campos_extra = {"acronimo": item["codigo"], "centro": item["centro"], "rama": item["rama"]}
    if item.get("campus"):
        campos_extra["campus"] = item["campus"]
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=item["url"], categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="recurso", tipo_recurso=TIPO_RECURSO,
                                      resumen=RESUMEN_URL, seccion=NIVEL, titulo=item["titulo"],
                                      campos_extra=campos_extra)


# ==========================================================
# 1. Catalogo -- JSON estatico + expansion de titulaciones multi-campus
# ==========================================================

def _expandir_itinerarios(acro: str, titulo: str, url_selector: str) -> list[dict]:
    """Las titulaciones ofertadas en mas de un campus enlazan desde el
    catalogo a una pagina selector con un <h3>Campus de X</h3> seguido
    del enlace a la ficha real de ese campus -- se convierte en un item
    por campus, cada uno con su propia URL real y campo `campus` (sacado
    del propio <h3>; el TEXTO del enlace en si es el nombre del centro,
    no del campus, ya cubierto por separado en el campo `centro`)."""
    try:
        respuesta = requests.get(url_selector, headers=HEADERS, timeout=30)
        respuesta.raise_for_status()
    except Exception as error:
        print(f"  AVISO: no se pudo leer el selector de {acro}: {error}")
        return []

    soup = BeautifulSoup(respuesta.text, "html.parser")
    items = []
    vistos = set()
    for h3 in soup.find_all("h3"):
        campus = _normalizar_campus(limpiar_texto(h3.get_text(" ", strip=True)))
        enlace = h3.find_next("a", href=re.compile(r"/titulaciones/[A-Za-z0-9\-]+/?$"))
        if enlace is None:
            continue
        href = ml.normalizar_url(enlace["href"], url_selector)
        if href in vistos:
            continue
        vistos.add(href)
        codigo = href.rstrip("/").rsplit("/", 1)[-1]
        items.append({"codigo": codigo, "titulo": titulo, "url": href.rstrip("/") + "/", "campus": campus})
    return items


def extraer_catalogo(url: str = GRADO_CATALOGO_URL) -> list[dict]:
    respuesta = requests.get(url, headers=HEADERS, timeout=30)
    respuesta.raise_for_status()
    datos = respuesta.json()

    centros_por_acro = {c["acro"]: limpiar_texto(c["nom"]) for c in datos.get("centros", [])}
    ramas_por_id = {r["id_rama"]: limpiar_texto(r["nom"]) for r in datos.get("ramas", [])}

    items = []
    for t in datos.get("titulaciones", []):
        acro = t.get("acro", "").strip()
        if not acro:
            continue
        titulo = limpiar_texto(t.get("nom", ""))
        centro = "; ".join(centros_por_acro.get(c, c) for c in t.get("centros", []))
        rama = "; ".join(ramas_por_id.get(r, str(r)) for r in t.get("ramas", []))
        url_catalogo = ml.normalizar_url(t.get("url", ""), BASE_URL)

        if "itinerarios" in url_catalogo.lower():
            expandidos = _expandir_itinerarios(acro, titulo, url_catalogo)
            for e in expandidos:
                e["centro"] = centro
                e["rama"] = rama
            items.extend(expandidos)
        else:
            campus = "; ".join(dict.fromkeys(
                CENTRO_CAMPUS[c] for c in t.get("centros", []) if c in CENTRO_CAMPUS
            ))
            items.append({
                "codigo": acro, "titulo": titulo, "url": url_catalogo,
                "centro": centro, "rama": rama, "campus": campus,
            })

    print("Titulaciones de grado encontradas:", len(items))
    return items


def guardar_json(items: list[dict], ruta: Path = GRADO_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump({"titulaciones": items}, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


# ==========================================================
# 2. Contenido de cada ficha
# ==========================================================

def _extraer_p_tit(soup: BeautifulSoup) -> str | None:
    enlace = soup.find("a", href=PATRON_P_TIT)
    if enlace is None:
        return None
    m = PATRON_P_TIT.search(enlace["href"])
    return m.group(1) if m else None


def extraer_ficha(url: str) -> tuple[list[str], str | None]:
    """Pagina principal de la titulacion: plantilla clasica,
    id="contenido" (no <main>), con Presentacion/Salidas profesionales/
    Movilidad/Continuacion de estudios/Plan de estudios en una unica
    pagina. Devuelve (lineas, p_tit)."""
    soup, es_html = ml.descargar_soup(url, headers=HEADERS)
    if not es_html:
        return [], None
    p_tit = _extraer_p_tit(soup)

    soup = ml.limpiar_contenido_html(soup)
    contenido = soup.find(id="contenido")
    if contenido is None:
        return [], p_tit

    ml.reemplazar_tablas_por_listas(soup, contenido)
    lineas = ml.extraer_bloques_contenido(contenido, url)
    lineas = ml.limpiar_lineas_finales(lineas)
    return lineas, p_tit


def _con_pausa(func, *args, pausa: float = 0.3, **kwargs):
    """Ejecuta func(*args, **kwargs) y garantiza la pausa despues, incluso
    si func lanza una excepcion -- mismo bug real que en estudios/master
    (2026-08-27): con time.sleep() suelto tras cada llamada dentro del
    mismo try, un fallo a mitad de una titulacion (ej. un 503 del backend
    clasico) saltaba las pausas pendientes, haciendo que el extractor
    insistiera MAS rapido justo cuando el servidor estaba fallando."""
    try:
        return func(*args, **kwargs)
    finally:
        time.sleep(pausa)


def extraer_consulta_clasica(url: str) -> list[str]:
    """Asignaturas/Competencias/Profesorado -- mismo patron que
    estudios/master, ver cabecera del modulo."""
    soup, es_html = ml.descargar_soup(url, headers=HEADERS)
    if not es_html:
        return []
    soup = ml.limpiar_contenido_html(soup)
    contenido = soup.find(id="contenido")
    if contenido is None:
        return []

    ml.reemplazar_tablas_por_listas(soup, contenido)
    lineas = ml.extraer_bloques_contenido(contenido, url)
    lineas = ml.limpiar_lineas_finales(lineas, recortar_h1=False)
    # La plantilla clasica de estas consultas siempre trae su propio
    # <h1 class="cabpagina"> con el titulo de la pagina ("Asignaturas",
    # "Resultados"...), redundante con el "## {titulo}" que ya antepone
    # generar_markdown_titulacion(); "Asignaturas" ademas lo repite una
    # segunda vez como <h2> justo despues (bug real visto probando
    # contra la web real). Ver motor_limpieza.quitar_titulos_redundantes().
    return ml.quitar_titulos_redundantes(lineas)


PATRON_PLAN_ESTUDIOS = re.compile(r"plan de estudios", re.IGNORECASE)
PATRON_PLAN_ESTUDIOS_INICIO = re.compile(r"^plan de estudios", re.IGNORECASE)
PATRON_MENU_URL_ANTIGUO = re.compile(r"menu_url\w*\.html\?(//.+)$", re.IGNORECASE)


def _resolver_menu_url_antiguo(url_absoluta: str) -> str:
    """La plantilla clasica usa a veces enlaces
    '.../menu_urlc.html?//www.upv.es/...': la URL real va incrustada en
    la query string tras '?//', un patron ya visto en otras secciones
    con esta misma plantilla -- confirmado en GIA, donde el propio enlace de menu "Plan
    de estudios" ya apunta asi directamente al PDF, sin subpagina
    intermedia. Sin resolver esto, se intentaria descargar la URL
    ofuscada como si fuera HTML y fallaria en silencio. Mismo patron ya
    resuelto por separado en extrae_servicios.py -- si aparece en una
    tercera seccion, valorar promoverlo a motor_limpieza.py."""
    m = PATRON_MENU_URL_ANTIGUO.search(url_absoluta)
    if not m:
        return url_absoluta
    interno = m.group(1)
    return "https:" + interno if interno.startswith("//") else interno


def buscar_pdf_plan_estudios(url_ficha: str) -> str | None:
    """Busca el PDF esquematico del plan de estudios (el mas util para
    ver de un vistazo las asignaturas de la carrera, a peticion expresa
    de Miguel) siguiendo, si existe, el enlace "Plan de Estudios y
    Competencias" (o variantes) del propio menu de la ficha hacia una
    subpagina con varios PDF, de la que se coge el que empieza por "Plan
    de estudios". Bug real evitado al probarlo: esa subpagina repite el
    mismo enlace de menu que la trajo hasta ahi ("Plan de Estudios y
    Competencias" tambien empieza por "Plan de estudios"), asi que hay
    que descartar explicitamente los enlaces sin extension .pdf.

    Cobertura real (probado 2026-08-23 contra las 75 fichas): solo
    4/75 -- el enlace de menu solo existe en unas pocas escuelas
    (confirmado en ETSIT/GITT, IDEAS/GIA y los dobles con Matematicas
    GDMATIC/GDMATEL) -- en la mayoria "Plan de estudios" del menu es
    solo una categoria plegable (href="#") que agrupa las mismas
    consultas de Asignaturas/Competencias/Profesorado ya seguidas por
    separado, sin PDF propio. Se devuelve None en ese caso -- mejor no
    encontrar el PDF que inventar una URL.

    No se usa el parametro `string=` de BeautifulSoup con estos patrones
    (bug real encontrado probando GDMATIC: `<a>.string` es None en
    cuanto el enlace tiene mas de un nodo de texto interno -- p.ej.
    "Plan de estudios 2023. Actual" con un salto de linea de por medio
    -- asi que `find(string=patron)` no lo encontraba nunca aunque
    `get_text()` si diera el texto completo). Se filtra siempre sobre
    `get_text()` en Python."""
    def _texto(a) -> str:
        return a.get_text(" ", strip=True)

    try:
        soup, es_html = ml.descargar_soup(url_ficha, headers=HEADERS)
    except Exception:
        return None
    if not es_html:
        return None

    enlaces_menu = [a for a in soup.find_all("a", href=True)
                    if a["href"] != "#" and PATRON_PLAN_ESTUDIOS.search(_texto(a))]
    if not enlaces_menu:
        return None
    url_subpagina = _resolver_menu_url_antiguo(ml.normalizar_url(enlaces_menu[0]["href"], url_ficha))
    if url_subpagina.lower().endswith(".pdf"):
        return url_subpagina  # el propio enlace de menu ya era el PDF (caso GIA)

    try:
        soup_sub, es_html_sub = ml.descargar_soup(url_subpagina, headers=HEADERS)
    except Exception:
        return None
    if not es_html_sub:
        return None

    candidatos = [a for a in soup_sub.find_all("a", href=True)
                  if a["href"].lower().endswith(".pdf") and PATRON_PLAN_ESTUDIOS_INICIO.search(_texto(a))]
    if not candidatos:
        return None
    # Si hay varios (visto en GDMATIC: "Plan de estudios 2023. Actual" +
    # una version "Anterior" del mismo documento), se prioriza el que
    # dice "actual" explicitamente; si ninguno lo dice, el primero.
    elegido = next((c for c in candidatos if "actual" in _texto(c).lower()), candidatos[0])
    return ml.normalizar_url(elegido["href"], url_subpagina)


# ==========================================================
# 3. Markdown por titulacion
# ==========================================================

def _bloque(titulo: str, lineas: list[str]) -> str:
    if not lineas:
        return f"## {titulo}\n\n_Sin contenido disponible._"
    return f"## {titulo}\n\n" + "\n\n".join(lineas)


def generar_markdown_titulacion(item: dict, carpeta: Path) -> bool:
    titulo, url, codigo = item["titulo"], item["url"], item["codigo"]
    print(f"  Extrayendo: {titulo} ({codigo})")

    try:
        lineas_ficha, p_tit = extraer_ficha(url)
        if not lineas_ficha and p_tit is None:
            print("    AVISO: no se ha podido leer la ficha.")
            return False
        # La ficha repite su propio <h1> con el titulo de la titulacion --
        # redundante con el "# {titulo}" que se antepone mas abajo (bug
        # real preexistente en el corpus comiteado, encontrado 2026-08-23:
        # las 75 fichas de grado repetian el titulo dos veces seguidas).
        lineas_ficha = ml.quitar_titulos_redundantes(lineas_ficha, titulo)

        if p_tit:
            lineas_asignaturas = _con_pausa(
                extraer_consulta_clasica, URL_ASIGNATURAS.format(p_tit=p_tit, acronimo=codigo))
            lineas_competencias = _con_pausa(extraer_consulta_clasica, URL_COMPETENCIAS.format(p_tit=p_tit))
            lineas_profesorado = _con_pausa(extraer_consulta_clasica, URL_PROFESORADO.format(p_tit=p_tit))
        else:
            print("    AVISO: no se ha encontrado p_tit -- sin asignaturas/competencias/profesorado.")
            lineas_asignaturas = lineas_competencias = lineas_profesorado = []

        pdf_plan_estudios = buscar_pdf_plan_estudios(url)
        if pdf_plan_estudios:
            print(f"    Plan de estudios (PDF): {pdf_plan_estudios}")

        bloques = [f"# {titulo}"]
        if pdf_plan_estudios:
            bloques.append(f"**[Plan de estudios (PDF)]({pdf_plan_estudios})** -- esquema completo de asignaturas por curso y cuatrimestre.")
        bloques += [
            "\n\n".join(lineas_ficha) if lineas_ficha else "_Sin contenido disponible._",
            _bloque("Asignaturas", lineas_asignaturas),
            _bloque("Competencias", lineas_competencias),
            _bloque("Profesorado", lineas_profesorado),
        ]

        yaml_metadatos = _yaml_recurso(item)
        markdown = f"{yaml_metadatos}\n" + "\n\n".join(bloques) + "\n"

        ruta_archivo = carpeta / f"{codigo}.md"
        with open(ruta_archivo, "w", encoding="utf-8") as archivo:
            archivo.write(markdown)
        print(f"  OK: {ruta_archivo}")
        return True

    except Exception as error:
        print(f"  ERROR: {error}")
        return False


def generar_markdowns_titulaciones(items: list[dict], carpeta: Path = GRADO_KB_DIR) -> tuple[int, int, int]:
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

    GRADO_KB_DIR.mkdir(parents=True, exist_ok=True)
    with open(GRADO_KB_DIR / "grado.md", "w", encoding="utf-8") as archivo:
        archivo.write(generar_markdown_resumen(items))
    generar_markdown_profesiones_reguladas()

    if limite is not None:
        items = items[:limite]
    total, correctos, errores = generar_markdowns_titulaciones(items)
    print(f"Grados: {total} · generados: {correctos} · errores: {errores}")


if __name__ == "__main__":
    main()
