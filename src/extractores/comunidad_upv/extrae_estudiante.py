"""Extractor de "Estudiante" (comunidad_upv/estudiante).

Primera sección de la categoría `comunidad_upv` (ver las notas internas del proyecto, "Cobertura
del sitemap"). A diferencia de `organizacion/{escuelas_facultades,
departamentos}` (fichas-índice, sin seguir el contenido real de cada
enlace), aquí sí se extrae el contenido real de cada página enlazada --
mismo estándar que institución/servicios/admisión (YAML definitivo,
extracción de PDF, plantilla clásica con iframe, limpieza de ficheros
huérfanos por cambio de título).

Dos fuentes reales, con estructura distinta cada una:

1. `https://www.upv.es/perfiles/estudiante/index-es.html` (página padre):
   agrupa sus enlaces bajo tres `<h2>` reales -- "Lo primero: los
   estudios", "Aprovecha las ventajas", "Objetivo: el empleo" -- cada
   uno sin texto propio, solo una lista de enlaces. Genera el resumen
   `estudiante.md` (fuera de las 4 subcarpetas) y, en las carpetas
   `estudios/`, `ventajas/`, `empleo/`, un `.md` por cada página
   enlazada en su sección correspondiente. El enlace "Becas y ayudas"
   aparece dentro de "Aprovecha las ventajas" pero se excluye ahí a
   propósito (decisión explícita de Miguel): tiene su propia subsección
   dedicada, ver el punto 2.
2. `https://www.upv.es/perfiles/estudiante/introduccion-becas-es.html`
   rellena `becas_ayudas/`: a diferencia de la página padre, aquí cada
   `<h2>` real (Ministerio, Generalitat Valenciana, Universitat
   Politècnica de València, Ayudas de comedor, Otras becas, Más
   información) SÍ tiene texto propio ademas de enlaces. Por eso genera
   dos tipos de documento en la misma carpeta: uno `tipo_documento:
   seccion` por cada `<h2>` con texto propio (mismo patrón ya usado en
   `admision/doctorado`, ver `comienza_tu_aventura.md`: `url`/`resumen`
   apuntan a la propia página padre, no a una URL distinta) y uno
   `tipo_documento: recurso` por cada enlace de esa sección. Una sección
   sin texto propio (aquí, "Más información": solo enlaces) no genera
   documento de sección, solo los recursos.

División de cada página en bloques por `<h2>` (`dividir_bloques_h2`) y
separación de cada bloque en texto propio vs. enlaces sueltos
(`separar_texto_y_enlaces`): utilidades locales a este módulo, no en
`motor_limpieza.py` -- si aparece el mismo patrón (página con secciones
reales por `<h2>`, mezcla de texto y enlaces) en una sección futura,
valorar promoverlas ahí (mismo criterio ya aplicado con `.mwc_contenido`/
`#contenido` sin iframe: primero confirmar el patrón en 2-3 sitios, luego
generalizar).

`introduccion-becas-es.html` tiene además un bloque inicial ruidoso
específico de esta plantilla: justo debajo del `<h1>`, un `<h2>` que
repite el mismo título de la página ("Becas y ayudas") con el párrafo de
introducción real, seguido de una línea que concatena sin puntuación los
títulos de TODAS las secciones reales (un índice de anclas internas
`href="#seccion"`, convertido a texto plano porque
`extraer_bloques_contenido()` no sigue enlaces `href="#..."` -- ver
`motor_limpieza.py`). Se usa como cuerpo del resumen `becas_ayudas.md`
tras filtrar esa línea de navegación interna
(`es_linea_navegacion_interna()`).
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
from config import ESTUDIANTE_BECAS_URL, ESTUDIANTE_CARPETAS, ESTUDIANTE_DIR, ESTUDIANTE_JSON, ESTUDIANTE_URL
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
CATEGORIA = "comunidad_upv"
NIVEL = "estudiante"
TIPO_RECURSO_GENERAL = "informacion"
TIPO_RECURSO_BECAS = "ayudas"

UMBRAL_PALABRAS_POCO_CONTENIDO = 60
MAX_ENLACES_HIJOS = 5
MAX_CARACTERES_FRAGMENTO_HIJO = 800

TEXTOS_BOILERPLATE_ESTUDIANTE = ml.TEXTOS_BOILERPLATE_BASE | ml.TEXTOS_BOILERPLATE_PLANTILLA_CLASICA

# <h2> reales de /perfiles/estudiante/index-es.html -> id de seccion/carpeta.
# "Tu espacio en la UPV" (solo el enlace de boilerplate "Inicio UPV") y
# "¡Esto te interesa!" (cortado ya por recortar_en_titulo_plantilla) se
# ignoran a proposito, no estan en este diccionario.
SECCIONES_INDEX = {
    "Lo primero: los estudios": "estudios",
    "Aprovecha las ventajas": "ventajas",
    "Objetivo: el empleo": "empleo",
}

RESUMEN_URL_POR_SECCION = {
    "estudios": ESTUDIANTE_URL,
    "ventajas": ESTUDIANTE_URL,
    "empleo": ESTUDIANTE_URL,
    "becas_ayudas": ESTUDIANTE_BECAS_URL,
}

TIPO_RECURSO_POR_SECCION = {
    "estudios": TIPO_RECURSO_GENERAL,
    "ventajas": TIPO_RECURSO_GENERAL,
    "empleo": TIPO_RECURSO_GENERAL,
    "becas_ayudas": TIPO_RECURSO_BECAS,
}

PATRON_LINEA_ENLACE = re.compile(r"^-?\s*\[([^\]]+)\]\(([^)]+)\)\s*$")

# Subdominios ya documentados como fuera de alcance del scraper (ver
# las notas internas del proyecto, "Quirks conocidos de upv.es"): aplicaciones JavaScript con
# sesion (intranet, poliformat, automatricula...) sin contenido real
# scrapeable -- comprobado en esta sesion con PoliformaT: el HTML
# estatico es integramente interfaz de edicion de Sakai ("Guardar
# Cancelar", selectores de color, plantillas de pagina...), cero
# contenido real. Se genera una nota en vez de intentar extraer.
SUBDOMINIOS_FUERA_DE_ALCANCE = {
    "intranet.upv.es", "automatricula.upv.es", "poliformat.upv.es",
    "riunet.upv.es", "correo.upv.es", "search.upv.es", "sede.upv.es",
    "wiki.upv.es", "apps.upv.es",
}


def _es_subdominio_fuera_de_alcance(url: str) -> bool:
    from urllib.parse import urlparse
    netloc = urlparse(url).netloc.lower().removeprefix("www.")
    return netloc in SUBDOMINIOS_FUERA_DE_ALCANCE


def limpiar_pagina(soup: BeautifulSoup) -> BeautifulSoup:
    """No se puede usar ml.limpiar_contenido_html() tal cual antes de
    localizar el contenedor: varias plantillas WordPress de estas
    paginas envuelven su propio <h1> en un <header class="entry-header">
    de articulo (distinto del <header id="masthead"> de menu del sitio)
    -- decompose(["header"]) global se lo llevaria por delante junto con
    el titulo real (bug real encontrado 2026-08-23 probando este
    extractor: "Biblioteca General" perdia todo su contenido porque su
    unico <h1> vivia dentro de ese header). Mismo patron ya usado en
    estudios/doctorado (ver extrae_doctorado.limpiar_pagina_programa()):
    al escoger #smooth-wrapper/main/#contenido como contenedor ya quedan
    fuera el menu/pie reales del sitio, asi que el decompose de
    header/nav/footer no hace falta aqui."""
    from bs4 import Comment
    for tag in soup.find_all(["script", "style", "noscript", "svg"]):
        tag.decompose()
    for comentario in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comentario.extract()
    return soup


# Nota: no se decompone <header>/<nav>/<footer> globalmente (a
# diferencia de ml.limpiar_contenido_html()) porque el menu/pie REAL del
# sitio siempre vive fuera de #smooth-wrapper/<main>, asi que acotar a
# ese contenedor ya los excluye sin necesidad de decompose -- y la
# plantilla clasica (Oracle Portal) no usa la etiqueta <header> en
# absoluto (usa <div id="DIVcab">), asi que tampoco hace falta ahi.


def _yaml_resumen(url: str, titulo: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=url, categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="resumen", titulo=titulo)


def _yaml_seccion(url_pagina: str, titulo: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=url_pagina, categoria=CATEGORIA, nivel=NIVEL,
                                      tipo_documento="seccion", resumen=url_pagina, titulo=titulo)


def _yaml_recurso(seccion_id: str, recurso: dict) -> str:
    subseccion = recurso.get("subseccion") or seccion_id
    return ml.generar_yaml_metadatos(
        fuente=FUENTE, url=recurso.get("url", ""), categoria=CATEGORIA, nivel=NIVEL,
        tipo_documento="recurso", tipo_recurso=TIPO_RECURSO_POR_SECCION[seccion_id],
        resumen=RESUMEN_URL_POR_SECCION[seccion_id], seccion=subseccion,
        titulo=recurso.get("titulo", ""), descripcion=recurso.get("descripcion", ""))


# ==========================================================
# 1. Lectura y division de paginas en bloques por <h2>
# ==========================================================

def extraer_lineas_pagina(url: str) -> list[str]:
    soup, es_html = ml.descargar_soup(url, headers=HEADERS)
    if not es_html:
        raise Exception(f"No se pudo descargar como HTML: {url}")
    soup = limpiar_pagina(soup)
    contenedor = soup.find(id="smooth-wrapper") or soup.find("main")
    if contenedor is None:
        raise Exception(f"No se ha encontrado el contenedor principal en {url}")
    ml.reemplazar_tablas_por_listas(soup, contenedor)
    lineas = ml.extraer_bloques_contenido(contenedor, url)
    return ml.limpiar_lineas_finales(lineas, textos_boilerplate=TEXTOS_BOILERPLATE_ESTUDIANTE)


def dividir_bloques_h2(lineas: list[str]) -> list[dict]:
    """Agrupa una lista de lineas Markdown ya limpias en bloques por cada
    titulo de nivel 2 (## ...) -- los titulos de nivel 3 (### ...) se
    quedan como parte del cuerpo de su bloque de nivel 2 padre, no abren
    bloque propio (asi es como se conservan las dos subsecciones de
    "Universitat Politecnica de Valencia" en introduccion-becas-es.html
    dentro del mismo documento de seccion). El primer bloque (antes del
    primer ##) lleva titulo=None -- normalmente solo el <h1>."""
    bloques = [{"titulo": None, "lineas": []}]
    for linea in lineas:
        if linea.startswith("## "):
            bloques.append({"titulo": linea[3:].strip(), "lineas": []})
        else:
            bloques[-1]["lineas"].append(linea)
    return bloques


def separar_texto_y_enlaces(lineas: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Separa las lineas de un bloque en (texto propio, enlaces sueltos):
    una linea que es INTEGRAMENTE un enlace markdown (con o sin guion de
    lista delante) cuenta como enlace: el resto es cuerpo de texto de la
    seccion."""
    texto, enlaces = [], []
    for linea in lineas:
        coincidencia = PATRON_LINEA_ENLACE.match(linea.strip())
        if coincidencia:
            enlaces.append((coincidencia.group(1), coincidencia.group(2)))
        else:
            texto.append(linea)
    return texto, enlaces


def es_linea_navegacion_interna(linea: str, titulos_secciones: list[str]) -> bool:
    """Detecta la linea de indice-de-anclas-internas de
    introduccion-becas-es.html (ver docstring del modulo): contiene, sin
    puntuacion, los titulos de TODAS las secciones reales de la pagina
    seguidos -- una frase real de contenido no va a contener los 6
    titulos de seccion consecutivos."""
    normalizada = ml.normalizar_para_comparar(linea)
    return len(titulos_secciones) >= 3 and all(
        ml.normalizar_para_comparar(t) in normalizada for t in titulos_secciones
    )


# ==========================================================
# 2. Catalogo (JSON)
# ==========================================================

def extraer_catalogo_becas() -> dict:
    lineas = extraer_lineas_pagina(ESTUDIANTE_BECAS_URL)
    bloques = dividir_bloques_h2(lineas)

    titulos_reales = [
        b["titulo"] for b in bloques
        if b["titulo"] and ml.normalizar_para_comparar(b["titulo"]) != "becas y ayudas"
    ]

    resumen_lineas: list[str] = []
    secciones_texto = []
    for bloque in bloques:
        if bloque["titulo"] is None:
            continue

        texto, enlaces = separar_texto_y_enlaces(bloque["lineas"])
        texto = [l for l in texto if not es_linea_navegacion_interna(l, titulos_reales)]

        if ml.normalizar_para_comparar(bloque["titulo"]) == "becas y ayudas":
            # La miga de pan de esta plantilla incluye la propia pagina
            # actual como texto plano sin enlace (a diferencia de
            # "Inicio UPV"/"Estudiante", que SI son enlaces y ya caen en
            # TEXTOS_BOILERPLATE_BASE) -- se filtra por autorreferencia.
            titulo_normalizado = ml.normalizar_para_comparar(bloque["titulo"])
            resumen_lineas = [
                l for l in texto
                if ml.normalizar_para_comparar(re.sub(r"^-\s*", "", l)) != titulo_normalizado
            ]
            continue

        elementos = ml.deduplicar_lista(
            [ml.crear_elemento(titulo=t, url=u, tipo="recurso", descripcion=bloque["titulo"]) for t, u in enlaces],
            clave="url",
        )
        for elemento in elementos:
            elemento["subseccion"] = ml.normalizar_identificador(bloque["titulo"])

        secciones_texto.append({"titulo": bloque["titulo"], "lineas_texto": texto, "elementos": elementos})
        print(f"  [Becas > {bloque['titulo']}] texto: {'si' if texto else 'no'} · enlaces: {len(elementos)}")

    return {"titulo": "Becas y ayudas", "url": ESTUDIANTE_BECAS_URL,
            "resumen_lineas": resumen_lineas, "secciones": secciones_texto}


def extraer_catalogo() -> dict:
    lineas_index = extraer_lineas_pagina(ESTUDIANTE_URL)
    bloques_index = dividir_bloques_h2(lineas_index)

    secciones = []
    for bloque in bloques_index:
        seccion_id = SECCIONES_INDEX.get(bloque["titulo"] or "")
        if seccion_id is None:
            continue

        _, enlaces = separar_texto_y_enlaces(bloque["lineas"])
        elementos = []
        for texto_enlace, url in enlaces:
            if seccion_id == "ventajas" and url.rstrip("/") == ESTUDIANTE_BECAS_URL.rstrip("/"):
                continue  # "Becas y ayudas" tiene su propia seccion dedicada, no se duplica aqui
            elementos.append(ml.crear_elemento(titulo=texto_enlace, url=url, tipo="recurso"))
        elementos = ml.deduplicar_lista(elementos, clave="url")

        seccion = ml.crear_seccion(bloque["titulo"], seccion_id)
        seccion["id"] = seccion_id  # crear_seccion() deriva "id" del titulo, no del "tipo" -- lo forzamos
        seccion["elementos"] = elementos
        secciones.append(seccion)
        print(f"[{bloque['titulo']}] {len(elementos)} enlaces")

    becas = extraer_catalogo_becas()
    seccion_becas = ml.crear_seccion(becas["titulo"], "becas_ayudas")
    seccion_becas["id"] = "becas_ayudas"
    seccion_becas["elementos"] = [e for s in becas["secciones"] for e in s["elementos"]]
    secciones.append(seccion_becas)

    return {"titulo": "Estudiante", "url": ESTUDIANTE_URL, "secciones": secciones, "becas_ayudas": becas}


def guardar_json(catalogo: dict, ruta: Path = ESTUDIANTE_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(catalogo, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


# ==========================================================
# 3. Markdown de cada recurso enlazado (mismo patron heterogeneo que
#    institucion/servicios: moderno / clasico con iframe / PDF / otro)
# ==========================================================

def obtener_enlaces_hijos(contenedor, url_pagina: str, maximo: int = MAX_ENLACES_HIJOS,
                           excluir: set[str] = frozenset()) -> list[tuple[str, str]]:
    from urllib.parse import urljoin
    enlaces, urls_vistas = [], set(excluir)
    for a in contenedor.find_all("a", href=True):
        href = a["href"]
        if not ml.es_url_valida_para_expandir(href, url_pagina, urls_vistas):
            continue
        absoluta = urljoin(url_pagina, href).split("#")[0]
        if _es_subdominio_fuera_de_alcance(absoluta):
            continue
        texto = ml.extraer_texto_limpio(a)
        if not texto:
            continue
        urls_vistas.add(absoluta)
        enlaces.append((texto, absoluta))
        if len(enlaces) >= maximo:
            break
    return enlaces


def resumir_pagina_hija(url: str) -> str | None:
    try:
        soup, es_html = ml.descargar_soup(url, headers=HEADERS)
        if not es_html:
            return None
        soup = limpiar_pagina(soup)
        contenedor = soup.find(id="smooth-wrapper") or soup.find("main") or soup.body
        if contenedor is None:
            return None
        ml.reemplazar_tablas_por_listas(soup, contenedor)
        lineas = ml.limpiar_lineas_finales(ml.extraer_bloques_contenido(contenedor, url),
                                            textos_boilerplate=TEXTOS_BOILERPLATE_ESTUDIANTE)
        fragmento = "\n\n".join(lineas)
        if len(fragmento) > MAX_CARACTERES_FRAGMENTO_HIJO:
            fragmento = fragmento[:MAX_CARACTERES_FRAGMENTO_HIJO].rstrip() + "…"
        return fragmento or None
    except Exception:
        return None


def extraer_contenido_iframe_clasico(soup: BeautifulSoup, url_pagina: str) -> tuple[list[str], str | None]:
    iframe_url = ml.buscar_iframe_contenido_clasico(soup, url_pagina)
    if iframe_url is None:
        return [], None
    soup_iframe, es_html = ml.descargar_soup(iframe_url, headers=HEADERS)
    if not es_html:
        return [], iframe_url
    soup_iframe = ml.limpiar_contenido_html(soup_iframe)
    contenido_iframe = soup_iframe.find(id="contenido") or soup_iframe.body
    if contenido_iframe is None:
        return [], iframe_url
    ml.reemplazar_tablas_por_listas(soup_iframe, contenido_iframe)
    lineas = ml.extraer_bloques_contenido(contenido_iframe, iframe_url)
    lineas = ml.limpiar_lineas_finales(lineas, textos_boilerplate=TEXTOS_BOILERPLATE_ESTUDIANTE, recortar_h1=False)
    return lineas, iframe_url


def markdown_recurso_no_html(yaml_metadatos: str, titulo: str, url: str, tipo: str, contenido_pdf: bytes | None) -> str:
    if tipo == "pdf":
        paginas = ml.extraer_texto_pdf(contenido_pdf)
        if paginas:
            return f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n" + "\n\n".join(paginas) + "\n"
        return (
            f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n"
            "_PDF sin texto extraíble (probablemente escaneado sin OCR). "
            "Consulta el contenido directamente en la URL indicada._\n"
        )
    return (
        f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n"
        "_Este recurso no es una página HTML ni un PDF estándar "
        "(por ejemplo, un vídeo o un portal externo con inicio de sesión). "
        "Consulta el contenido directamente en la URL indicada._\n"
    )


def generar_markdown_recurso(recurso: dict, carpeta: Path, seccion_id: str, nombres_usados: set[str]) -> bool:
    titulo, url = recurso.get("titulo", ""), recurso.get("url", "")
    if not titulo or not url:
        return False

    print(f"  Extrayendo: {titulo} ({url})")
    try:
        yaml_metadatos = _yaml_recurso(seccion_id, recurso)
        nombre = ml.nombre_archivo_sin_colision(titulo, nombres_usados, desambiguador=seccion_id)

        if _es_subdominio_fuera_de_alcance(url):
            markdown = (
                f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n"
                "_Este enlace lleva a un subdominio con aplicación dinámica que requiere "
                "sesión de usuario (intranet, PoliformaT, automatrícula...), fuera de "
                "alcance de este scraper -- ver las notas internas del proyecto, \"Quirks conocidos de upv.es\". "
                "Consulta el contenido directamente en la URL indicada._\n"
            )
            with open(carpeta / nombre, "w", encoding="utf-8") as archivo:
                archivo.write(markdown)
            print(f"  OK (fuera de alcance, solo nota): {carpeta / nombre}")
            return True

        respuesta = requests.get(url, headers=HEADERS, timeout=30)
        respuesta.raise_for_status()
        tipo = ml.tipo_contenido(respuesta.headers.get("Content-Type", ""))

        if tipo != "html":
            markdown = markdown_recurso_no_html(yaml_metadatos, titulo, url, tipo, respuesta.content)
            with open(carpeta / nombre, "w", encoding="utf-8") as archivo:
                archivo.write(markdown)
            print(f"  OK ({tipo}): {carpeta / nombre}")
            return True

        soup = BeautifulSoup(respuesta.text, "html.parser")
        soup = limpiar_pagina(soup)
        contenedor_moderno = soup.find(id="smooth-wrapper") or soup.find("main")
        contenido = contenedor_moderno or soup.body
        if contenido is None:
            print("  AVISO: no se ha encontrado contenido.")
            return False

        lineas_iframe, iframe_url = ([], None) if contenedor_moderno is not None else extraer_contenido_iframe_clasico(soup, url)

        ml.reemplazar_tablas_por_listas(soup, contenido)
        lineas_contenido = ml.limpiar_lineas_finales(ml.extraer_bloques_contenido(contenido, url),
                                                       textos_boilerplate=TEXTOS_BOILERPLATE_ESTUDIANTE)
        lineas_contenido = lineas_iframe + lineas_contenido
        if not lineas_contenido:
            print("  AVISO: contenido vacío.")
            return False

        if ml.contar_palabras(lineas_contenido) < UMBRAL_PALABRAS_POCO_CONTENIDO:
            excluir = {iframe_url} if iframe_url else set()
            enlaces_hijos = obtener_enlaces_hijos(contenido, url, excluir=excluir)
            if enlaces_hijos:
                lineas_contenido.append("## Información relacionada")
                for texto_enlace, url_hija in enlaces_hijos:
                    time.sleep(0.5)
                    fragmento = resumir_pagina_hija(url_hija)
                    lineas_contenido.append(f"### {texto_enlace}")
                    lineas_contenido.append(f"**URL:** {url_hija}")
                    if fragmento:
                        lineas_contenido.append(fragmento)

        markdown = f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n" + "\n\n".join(lineas_contenido) + "\n"
        with open(carpeta / nombre, "w", encoding="utf-8") as archivo:
            archivo.write(markdown)
        print(f"  OK: {carpeta / nombre}")
        return True

    except Exception as error:
        print(f"  ERROR: {error}")
        return False


def generar_markdowns_recursos(catalogo: dict, catalogo_anterior: dict[str, list[dict]] | None = None,
                                nombres_usados_por_seccion: dict[str, set[str]] | None = None) -> tuple[int, int, int]:
    """catalogo_anterior (ver ml.cargar_catalogo_anterior(), cargado por
    main() ANTES de guardar_json()) permite detectar recursos que
    cambiaron de titulo entre ejecuciones y borrar su .md antiguo -- ver
    motor_limpieza.limpiar_ficheros_renombrados(). nombres_usados_por_seccion
    permite pre-sembrar la carpeta 'becas_ayudas' con los nombres ya
    ocupados por su resumen y sus documentos de seccion (Ministerio,
    Generalitat Valenciana...), que viven en la MISMA carpeta que estos
    recursos -- sin esto, un recurso podria pisar por colision de slug a
    un documento de seccion ya escrito."""
    catalogo_anterior = catalogo_anterior or {}
    nombres_usados_por_seccion = nombres_usados_por_seccion or {}
    total = correctos = errores = 0

    for seccion in catalogo["secciones"]:
        seccion_id = seccion["id"]
        carpeta = ESTUDIANTE_CARPETAS[seccion_id]
        carpeta.mkdir(parents=True, exist_ok=True)
        print(f"[{seccion['titulo']}]")

        nombres_usados = nombres_usados_por_seccion.setdefault(seccion_id, set())
        elementos_escritos = []
        for recurso in seccion["elementos"]:
            total += 1
            if generar_markdown_recurso(recurso, carpeta, seccion_id, nombres_usados):
                correctos += 1
                elementos_escritos.append(recurso)
            else:
                errores += 1
            time.sleep(0.3)

        ml.limpiar_ficheros_renombrados(catalogo_anterior.get(seccion_id, []), elementos_escritos, carpeta)

    return total, correctos, errores


# ==========================================================
# 4. Markdown de las secciones con texto propio de becas_ayudas
#    (Ministerio, Generalitat Valenciana... -- tipo_documento: seccion)
# ==========================================================

def generar_markdown_seccion_becas(seccion_texto: dict, carpeta: Path, nombres_usados: set[str]) -> bool:
    if not seccion_texto["lineas_texto"]:
        return False  # solo enlaces, sin texto propio (ej. "Mas informacion") -> no genera doc de seccion
    yaml_metadatos = _yaml_seccion(ESTUDIANTE_BECAS_URL, seccion_texto["titulo"])
    markdown = f"{yaml_metadatos}\n# {seccion_texto['titulo']}\n\n" + "\n\n".join(seccion_texto["lineas_texto"]) + "\n"
    nombre = ml.nombre_archivo_sin_colision(seccion_texto["titulo"], nombres_usados, desambiguador="seccion")
    with open(carpeta / nombre, "w", encoding="utf-8") as archivo:
        archivo.write(markdown)
    print(f"  OK (sección): {carpeta / nombre}")
    return True


def generar_markdowns_secciones_becas(becas: dict, nombres_usados: set[str]) -> int:
    carpeta = ESTUDIANTE_CARPETAS["becas_ayudas"]
    carpeta.mkdir(parents=True, exist_ok=True)
    generadas = 0
    for seccion_texto in becas["secciones"]:
        if generar_markdown_seccion_becas(seccion_texto, carpeta, nombres_usados):
            generadas += 1
    return generadas


# ==========================================================
# 5. Markdown de los dos resumenes (estudiante.md, becas_ayudas.md)
# ==========================================================

def generar_markdown_resumen(catalogo: dict) -> str:
    yaml_metadatos = _yaml_resumen(ESTUDIANTE_URL, "Estudiante")
    cuerpo = (
        "Punto de entrada de la web de la UPV dirigido al alumnado: estudios, ventajas "
        "y servicios disponibles como estudiante, y orientación hacia el empleo. Cada "
        "apartado remite a las páginas reales enlazadas desde la web oficial de "
        '"Estudiante", agrupadas en las carpetas de abajo.'
    )
    filas = "\n".join(
        f"- **{seccion['titulo']}** — {len(seccion['elementos'])} recursos (carpeta `{seccion['id']}/`)"
        for seccion in catalogo["secciones"]
    )
    return f"{yaml_metadatos}\n# Estudiante\n\n{cuerpo}\n\n{filas}\n"


def generar_markdown_resumen_becas(becas: dict) -> str:
    yaml_metadatos = _yaml_resumen(ESTUDIANTE_BECAS_URL, "Becas y ayudas")
    cuerpo = "\n\n".join(becas["resumen_lineas"]) if becas["resumen_lineas"] else (
        "Becas y ayudas disponibles para el estudiantado de la UPV, por organismo convocante."
    )
    def _resumen_fila(s: dict) -> str:
        partes = [f"{len(s['elementos'])} enlaces"] if s["elementos"] else []
        if not s["lineas_texto"]:
            partes.append("sin texto propio")
        detalle = f" ({', '.join(partes)})" if partes else ""
        return f"- **{s['titulo']}**{detalle}"

    filas = "\n".join(_resumen_fila(s) for s in becas["secciones"])
    return f"{yaml_metadatos}\n# Becas y ayudas\n\n{cuerpo}\n\n{filas}\n"


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    catalogo_anterior = ml.cargar_catalogo_anterior(ESTUDIANTE_JSON)
    catalogo = extraer_catalogo()
    guardar_json(catalogo)

    ESTUDIANTE_DIR.mkdir(parents=True, exist_ok=True)
    with open(ESTUDIANTE_DIR / "estudiante.md", "w", encoding="utf-8") as archivo:
        archivo.write(generar_markdown_resumen(catalogo))

    becas = catalogo["becas_ayudas"]
    carpeta_becas = ESTUDIANTE_CARPETAS["becas_ayudas"]
    carpeta_becas.mkdir(parents=True, exist_ok=True)
    nombres_usados_becas: set[str] = {"becas_ayudas.md"}
    with open(carpeta_becas / "becas_ayudas.md", "w", encoding="utf-8") as archivo:
        archivo.write(generar_markdown_resumen_becas(becas))
    secciones_generadas = generar_markdowns_secciones_becas(becas, nombres_usados_becas)

    nombres_usados_por_seccion = {"becas_ayudas": nombres_usados_becas}
    total, correctos, errores = generar_markdowns_recursos(
        catalogo, catalogo_anterior=catalogo_anterior, nombres_usados_por_seccion=nombres_usados_por_seccion)
    print(f"Estudiante: {total} recursos · generados: {correctos} · errores: {errores} "
          f"· secciones de becas con texto propio: {secciones_generadas}")


if __name__ == "__main__":
    main()
