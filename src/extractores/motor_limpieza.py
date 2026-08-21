"""Motor de limpieza de contenido compartido por los extractores ya
validados (institucion, servicios) -- ver las notas internas del proyecto: "Motor de limpieza
de contenido (reutilizar, no reescribir por seccion)".

Extraido al comparar extrae_institucion.py y extrae_servicios.py durante
su migracion desde notebooks: ambos duplicaban (casi) identica esta
misma logica de traversal por "hoja de contenido", filtrado de
boilerplate de plantilla y generacion de metadatos YAML. Lo que sí
difiere entre secciones (filtros de enlaces hijos, resolucion de URLs de
plantilla antigua, deduplicacion por codigo de entidad...) se queda en
cada modulo, no aqui.

Resumen del algoritmo:
  1. extraer_bloques_contenido(): recorre el HTML y convierte cada
     "hoja de contenido" (elemento sin bloques anidados dentro, incluidos
     <a> sueltos) en una linea Markdown, preservando enlaces como
     [texto](url).
  2. limpiar_lineas_finales(): recorta desde el primer <h1> real, corta
     en títulos de plantilla ("Esto te interesa", "Recursos",
     "Instalaciones", "Media"), filtra líneas de menú/pie/breadcrumbs
     conocidas, y deduplica globalmente.
  3. generar_yaml_metadatos(): cabecera YAML homogenea para todos los .md.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from common import limpiar_texto
from config import HEADERS as HEADERS_GENERICOS

TAGS_TITULO = {"h1", "h2", "h3", "h4", "h5", "h6"}

# Tags que consideramos "contenedores de bloque": si un elemento tiene
# alguno de estos como descendiente, NO es una hoja de contenido (evita
# procesar el mismo texto dos veces, en el contenedor y en el hijo).
TAGS_BLOQUE = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "li", "div", "ul", "ol",
    "table", "section", "article", "blockquote",
}

TAGS_CANDIDATAS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "div", "span", "a"]

# Textos de menu, accesos rapidos y pie de pagina que aparecen igual en
# (casi) cualquier pagina de upv.es -- valido para cualquier seccion. Es
# el conjunto BASE; cada seccion puede ampliarlo (ver TEXTOS_BOILERPLATE
# en extrae_servicios.py, que anade los terminos de la plantilla antigua
# de fichas de entidad) y pasarlo explicitamente a limpiar_lineas_finales
# / es_linea_boilerplate -- no hay un unico set fijo para todas las
# secciones, cada una filtra solo lo que su propia plantilla repite.
TEXTOS_BOILERPLATE_BASE = {
    "accesibilidad", "mapa web", "buscar", "directorio",
    "iniciar sesion", "emergencias", "inicio upv",
    "admision", "estudios", "investigacion", "organizacion",
    "comunidad upv",
    "admision a grado", "admision a master", "admision a doctorado",
    "internacional",
    "estudios de grado", "estudios de posgrado", "oferta academica",
    "estructuras de investigacion", "iniciativas de i+d+i", "innovacion",
    "la institucion", "vida universitaria", "escuelas y facultades",
    "departamentos", "servicios universitarios",
    "estudiante", "pas, pdi y pi", "ptgas, pdi y pi", "prensa", "titulados",
    "alumni upv", "orientador",
    "como llegar", "planos", "planos 2d", "contacto",
    "habla con nosotros",
    "tienes dudas", "contacta con nosotros",
    "quieres enviar una sugerencia, queja o felicitacion",
    "no has encontrado lo que buscas",
    "dinos que opinas", "consultanos",
    "sala de prensa", "noticias de la upv", "buscar un cargo docente",
    "area de comunicacion", "transparencia", "perfil del contratante",
    "aviso legal", "politica de cookies", "politica de privacidad",
    "gestion de cookies", "descarga nuestras apps",
}

# Solo cuentan como corte de plantilla si aparecen como TITULO, para no
# arriesgarnos a cortar contenido real que use esa misma palabra suelta.
TITULOS_CORTE_PLANTILLA = {"esto te interesa", "recursos", "instalaciones", "media"}

# Ruido propio de la plantilla clasica Oracle Portal/PL-SQL de fichas de
# entidad (menu lateral de idioma/accesibilidad, botones de plegado...),
# que institucion/servicios no necesitan filtrar en la plantilla moderna
# WordPress -- cada extractor decide si lo suma a su propio set de
# boilerplate (ver TEXTOS_BOILERPLATE_SERVICIOS en extrae_servicios.py).
TEXTOS_BOILERPLATE_PLANTILLA_CLASICA = {
    "idioma", "idioma · language", "language",
    "valencia", "valencian", "english", "castellano",
    "cercar", "search", "directory", "directori",
    "contacte", "contact",
    "otros", "donde estamos", "¿donde estamos?",
    "informacion general", "organigrama", "expandir", "contraer",
}


# ==========================================================
# Identificadores, URLs, estructura JSON
# ==========================================================

def normalizar_identificador(texto: str) -> str:
    """'Órganos de gobierno' -> 'organos_de_gobierno'."""
    texto = limpiar_texto(texto)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    return re.sub(r"[^a-z0-9]+", "_", texto).strip("_")


def normalizar_url(url: str, url_base: str) -> str:
    if not url:
        return ""
    return urljoin(url_base, url.strip())


def es_url_valida(url: str) -> bool:
    if not url:
        return False
    try:
        return urlparse(url).scheme in {"http", "https"}
    except Exception:
        return False


def deduplicar_lista(elementos: list[dict], clave: str = "url") -> list[dict]:
    resultado, vistos = [], set()
    for elemento in elementos:
        if not isinstance(elemento, dict):
            continue
        valor = elemento.get(clave, "")
        if valor in vistos:
            continue
        vistos.add(valor)
        resultado.append(elemento)
    return resultado


def crear_seccion(titulo: str, tipo: str = "seccion") -> dict:
    return {"id": normalizar_identificador(titulo), "titulo": limpiar_texto(titulo), "tipo": tipo, "descripcion": "", "elementos": []}


def crear_elemento(titulo: str = "", descripcion: str = "", url: str = "", tipo: str = "recurso", url_base: str = "") -> dict:
    return {"tipo": tipo, "titulo": limpiar_texto(titulo), "descripcion": limpiar_texto(descripcion), "url": normalizar_url(url, url_base)}


def nombre_archivo_markdown(titulo: str) -> str:
    return normalizar_identificador(titulo) + ".md"


# ==========================================================
# Limpieza de ficheros huerfanos por cambio de titulo
#
# El nombre de fichero de cada recurso sale del titulo (ver
# nombre_archivo_markdown), pero el titulo puede cambiar en la web entre
# una ejecucion y la siguiente -- sin este paso, el .md antiguo se queda
# huerfano en la carpeta (el mismo recurso duplicado bajo dos nombres),
# porque nada mas que el propio nombre de fichero identifica de que
# recurso se trata. La url SI es una identidad estable (es la clave que
# ya usan crear_elemento()/deduplicar_lista()), asi que sirve para
# detectar el mismo recurso con un titulo distinto.
# ==========================================================

def cargar_catalogo_anterior(ruta_json: Path) -> dict[str, list[dict]]:
    """Carga, agrupado por id de seccion, el catalogo JSON que dejo la
    ejecucion anterior en data/raw/ -- debe llamarse ANTES de que
    guardar_json() lo sobreescriba con el catalogo nuevo. Usado por
    limpiar_ficheros_renombrados(). Si no existe o esta corrupto,
    devuelve {} (equivale a "primera ejecucion", no hay nada que
    limpiar)."""
    if not ruta_json.exists():
        return {}
    try:
        with open(ruta_json, encoding="utf-8") as f:
            datos = json.load(f)
    except Exception:
        return {}
    return {
        seccion.get("id", ""): seccion.get("elementos", [])
        for seccion in datos.get("secciones", [])
        if isinstance(seccion, dict)
    }


def limpiar_ficheros_renombrados(elementos_anteriores: list[dict], elementos_escritos: list[dict], carpeta: Path) -> int:
    """Borra el .md antiguo de un recurso cuyo titulo cambio de una
    ejecucion a la siguiente (mismo url, nombre de fichero distinto).

    `elementos_escritos` debe contener SOLO los recursos que se acaban
    de escribir con exito en esta ejecucion (no la lista completa del
    catalogo) -- si la extraccion de un recurso falla, su fichero
    anterior se conserva tal cual en vez de borrarse sin reemplazo.
    Ademas, nunca borra un nombre de fichero que algun otro recurso del
    catalogo nuevo siga usando (evita pisarse entre si por una
    coincidencia de slug). Devuelve cuantos ficheros se limpiaron."""
    if not elementos_anteriores or not elementos_escritos:
        return 0

    titulos_anteriores_por_url = {
        e["url"]: e["titulo"] for e in elementos_anteriores if e.get("url") and e.get("titulo")
    }
    nombres_nuevos_en_uso = {
        nombre_archivo_markdown(e["titulo"]) for e in elementos_escritos if e.get("titulo")
    }

    borrados = 0
    for elemento in elementos_escritos:
        url, titulo_nuevo = elemento.get("url"), elemento.get("titulo")
        if not url or not titulo_nuevo:
            continue

        titulo_anterior = titulos_anteriores_por_url.get(url)
        if not titulo_anterior or titulo_anterior == titulo_nuevo:
            continue

        nombre_anterior = nombre_archivo_markdown(titulo_anterior)
        if nombre_anterior == nombre_archivo_markdown(titulo_nuevo) or nombre_anterior in nombres_nuevos_en_uso:
            continue

        ruta_anterior = carpeta / nombre_anterior
        if ruta_anterior.exists():
            ruta_anterior.unlink()
            borrados += 1
            print(f"  Renombrado detectado: '{titulo_anterior}' -> '{titulo_nuevo}' (borrado {nombre_anterior})")

    return borrados


# ==========================================================
# Descarga y limpieza estructural del HTML
# ==========================================================

def descargar_soup(url: str, headers: dict | None = None):
    """Descarga una pagina. Devuelve (soup, es_html); si el recurso no
    es HTML (PDF, video...) es_html sera False y soup None."""
    respuesta = requests.get(url, headers=headers or HEADERS_GENERICOS, timeout=30)
    respuesta.raise_for_status()
    content_type = respuesta.headers.get("Content-Type", "")
    if "html" not in content_type.lower():
        return None, False
    return BeautifulSoup(respuesta.text, "html.parser"), True


def tipo_contenido(content_type: str) -> str:
    """Clasifica un Content-Type de respuesta HTTP en 'html'/'pdf'/'otro'
    (video, imagen...). Usado por los extractores para decidir como
    procesar un recurso antes de descargarlo por completo."""
    content_type = (content_type or "").lower()
    if "pdf" in content_type:
        return "pdf"
    if "html" in content_type:
        return "html"
    return "otro"


def extraer_texto_pdf(contenido: bytes) -> list[str]:
    """Extrae el texto de un PDF pagina a pagina via pypdf. Cada entrada
    de la lista devuelta es el texto (limpio) de una pagina; las paginas
    sin texto extraible (escaneadas sin OCR, solo imagenes...) se omiten
    en vez de devolver una cadena vacia."""
    import io

    from pypdf import PdfReader

    lector = PdfReader(io.BytesIO(contenido))
    paginas = []
    for pagina in lector.pages:
        try:
            texto = limpiar_texto(pagina.extract_text() or "")
        except Exception:
            texto = ""
        if texto:
            paginas.append(texto)
    return paginas


def buscar_iframe_contenido_clasico(soup: BeautifulSoup, url_base: str) -> str | None:
    """La plantilla clasica Oracle Portal/PL-SQL de fichas de entidad
    (sin #smooth-wrapper ni <main>, ver las notas internas del proyecto "Quirks conocidos de
    upv.es") no lleva el contenido real en la pagina index: lo carga en
    un <iframe> (normalmente id="marco") que apunta a
    pls/oalu/sic_infoent.*MS?P_ENTIDAD=.... Sin ejecutar JS, requests
    nunca ve ese contenido (datos de contacto, direccion postal,
    telefonos...) salvo que se siga el iframe explicitamente y se
    descargue su src aparte."""
    iframe = soup.find("iframe", src=re.compile(r"pls/oalu|oalu/sic_", re.I))
    if iframe is None or not iframe.get("src"):
        return None
    src = iframe["src"].strip()
    if src.startswith("//"):
        return "https:" + src
    return urljoin(url_base, src)


def limpiar_contenido_html(soup: BeautifulSoup) -> BeautifulSoup:
    from bs4 import Comment

    for elemento in soup.find_all(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        elemento.decompose()
    # Comment es subclase de NavigableString: sin este filtro,
    # .get_text()/extraer_texto_limpio() cuelan comentarios HTML
    # (notas de desarrollo tipo <!-- quitamos capitalizacion... -->)
    # como si fueran texto real de la pagina.
    for comentario in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comentario.extract()
    return soup


def extraer_texto_limpio(elemento) -> str:
    if elemento is None:
        return ""
    return limpiar_texto(elemento.get_text(" ", strip=True))


# ==========================================================
# Traversal por "hoja de contenido"
# ==========================================================

def es_hoja_de_contenido(tag) -> bool:
    """Candidato a texto propio sin bloques anidados dentro."""
    if tag.name not in TAGS_CANDIDATAS:
        return False
    if tag.name == "a":
        return True
    return len(tag.find_all(TAGS_BLOQUE, recursive=True)) == 0


def _identidad(url: str) -> str:
    return url


def texto_markdown_de_elemento(tag, url_pagina: str, resolver_url=_identidad) -> str:
    """Convierte el contenido de una hoja a texto, respetando los
    enlaces que contenga como [texto](url). resolver_url() permite a
    cada seccion post-procesar la URL absoluta (ej. servicios resuelve
    los enlaces de menu de la plantilla antigua)."""
    partes = []
    for nodo in tag.children:
        nombre_nodo = getattr(nodo, "name", None)

        if nombre_nodo == "a":
            texto_enlace = extraer_texto_limpio(nodo)
            href = (nodo.get("href") or "").strip()
            if not texto_enlace:
                continue
            if href and not href.startswith(("javascript:", "#")):
                partes.append(f"[{texto_enlace}]({resolver_url(urljoin(url_pagina, href))})")
            else:
                partes.append(texto_enlace)
        elif nombre_nodo is not None:
            texto = extraer_texto_limpio(nodo)
            if texto:
                partes.append(texto)
        else:
            texto = limpiar_texto(str(nodo))
            if texto:
                partes.append(texto)

    return limpiar_texto(" ".join(partes))


def _tiene_ancestro_hoja(tag, contenedor) -> bool:
    """True si algun ancestro de tag (hasta contenedor) ya califica como
    hoja de contenido. texto_markdown_de_elemento() es recursivo via
    get_text(), asi que ese ancestro ya capturara el texto de tag como
    parte del suyo -- volver a emitirlo aqui aparte duplicaria la linea.
    Tipico con <a>/<span> anidados dentro de un <h1-h6>/<p>/<li> que ya
    es hoja por si mismo (ej. un <h4><a>...</a></h4>: sin este filtro
    sale el titulo Y, justo debajo, el mismo enlace suelto otra vez)."""
    ancestro = tag.parent
    while ancestro is not None and ancestro is not contenedor:
        if es_hoja_de_contenido(ancestro):
            return True
        ancestro = ancestro.parent
    return False


def extraer_bloques_contenido(contenedor, url_pagina: str, resolver_url=_identidad) -> list[str]:
    """Recorre el contenedor y devuelve lineas Markdown: titulos,
    parrafos, items de lista y enlaces sueltos (nombres, telefonos,
    emails, "Mas informacion"...)."""
    lineas = []
    linea_anterior = None

    for tag in contenedor.find_all(TAGS_CANDIDATAS, recursive=True):
        if not es_hoja_de_contenido(tag):
            continue
        if _tiene_ancestro_hoja(tag, contenedor):
            continue

        if tag.name == "a":
            texto = extraer_texto_limpio(tag)
            href = (tag.get("href") or "").strip()
            if not texto:
                continue
            if href and not href.startswith(("javascript:", "#")):
                linea = f"[{texto}]({resolver_url(urljoin(url_pagina, href))})"
            else:
                linea = texto
        else:
            texto = texto_markdown_de_elemento(tag, url_pagina, resolver_url)
            if not texto:
                continue
            if tag.name in TAGS_TITULO:
                linea = ("#" * int(tag.name[1])) + " " + texto
            elif tag.name == "li":
                linea = f"- {texto}"
            else:
                linea = texto

        if linea == linea_anterior:
            continue
        lineas.append(linea)
        linea_anterior = linea

    return lineas


def contar_palabras(lineas: list[str]) -> int:
    return sum(len(linea.split()) for linea in lineas)


def reemplazar_tablas_por_listas(soup: BeautifulSoup, contenedor) -> None:
    """Convierte cada <table> del contenedor en un <ul><li> equivalente,
    in-place. extraer_bloques_contenido() no recorre table/tr/td (no
    estan en TAGS_CANDIDATAS/TAGS_BLOQUE) para no romper el traversal
    generico con la semantica de filas/columnas, asi que sin esto
    cualquier tabla HTML (precios, horarios, listados de asignaturas...)
    se pierde en silencio. Cada fila se convierte en un <li> con sus
    celdas unidas por '; ', usando los <th> como etiquetas si el numero
    de columnas coincide."""
    for tabla in contenedor.find_all("table"):
        encabezados = [extraer_texto_limpio(th) for th in tabla.find_all("th")]
        lista = soup.new_tag("ul")
        for fila in tabla.find_all("tr"):
            celdas = [extraer_texto_limpio(td) for td in fila.find_all("td")]
            celdas = [c for c in celdas if c and c != "-" and re.search(r"[A-Za-z0-9]", c)]
            if not celdas:
                continue
            if encabezados and len(encabezados) == len(celdas):
                texto_fila = "; ".join(f"{h}: {c}" for h, c in zip(encabezados, celdas) if c)
            else:
                texto_fila = "; ".join(celdas)
            if not texto_fila:
                continue
            item = soup.new_tag("li")
            item.string = texto_fila
            lista.append(item)

        if lista.find("li"):
            tabla.replace_with(lista)
        else:
            tabla.decompose()


# ==========================================================
# Filtrado de plantilla (menu, migas, pie, widgets)
# ==========================================================

def normalizar_para_comparar(texto: str) -> str:
    texto = texto.strip().lower().strip("¡¿!?: ")
    texto = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip()


def es_linea_boilerplate(linea: str, textos_boilerplate: set[str] = TEXTOS_BOILERPLATE_BASE) -> bool:
    texto_plano = re.sub(r"^#+\s*", "", linea)
    texto_plano = re.sub(r"^-\s*", "", texto_plano)

    match_enlace = re.match(r"^\[([^\]]+)\]\([^)]+\)$", texto_plano.strip())
    if match_enlace:
        texto_plano = match_enlace.group(1)

    normalizado = normalizar_para_comparar(texto_plano)

    if normalizado in textos_boilerplate:
        return True
    if normalizado and not re.search(r"[a-z0-9]", normalizado):
        return True

    if "universitat politecnica de valencia" in normalizado and "©" in linea:
        return True
    if re.match(r"^tel\.?\s*\(?\+?34", normalizado):
        return True
    if "::" in linea:
        return True
    if linea.startswith("#") and normalizado in TITULOS_CORTE_PLANTILLA:
        return True
    return False


def recortar_desde_primer_h1(lineas: list[str]) -> list[str]:
    """El contenido real de cualquier pagina de upv.es empieza en su
    <h1>; todo lo anterior es menu, migas o barra lateral."""
    for indice, linea in enumerate(lineas):
        if linea.startswith("# "):
            return lineas[indice:]
    return lineas


def recortar_en_titulo_plantilla(lineas: list[str]) -> list[str]:
    """Corta en cuanto aparece un titulo de pie/widget promocional."""
    for indice, linea in enumerate(lineas):
        if not linea.startswith("#"):
            continue
        normalizado = normalizar_para_comparar(re.sub(r"^#+\s*", "", linea))
        if normalizado in TITULOS_CORTE_PLANTILLA:
            return lineas[:indice]
    return lineas


def deduplicar_global(lineas: list[str]) -> list[str]:
    """Elimina lineas exactamente repetidas en todo el documento (no
    solo consecutivas) -- plantillas antiguas duplican el pie completo."""
    resultado, vistos = [], set()
    for linea in lineas:
        if linea in vistos:
            continue
        vistos.add(linea)
        resultado.append(linea)
    return resultado


def limpiar_lineas_finales(lineas: list[str], recortar_h1: bool = True, textos_boilerplate: set[str] = TEXTOS_BOILERPLATE_BASE) -> list[str]:
    if recortar_h1:
        lineas = recortar_desde_primer_h1(lineas)
    lineas = recortar_en_titulo_plantilla(lineas)
    lineas = [linea for linea in lineas if not es_linea_boilerplate(linea, textos_boilerplate)]
    return deduplicar_global(lineas)


def es_url_valida_para_expandir(href: str, url_pagina: str, urls_ya_usadas: set) -> bool:
    if not href:
        return False
    href = href.strip()
    if href.startswith(("mailto:", "tel:", "javascript:", "#")):
        return False
    absoluta = urljoin(url_pagina, href).split("#")[0]
    if absoluta == url_pagina.split("#")[0]:
        return False
    if absoluta in urls_ya_usadas:
        return False
    return "upv.es" in urlparse(absoluta).netloc


# ==========================================================
# Metadatos YAML (formato definitivo, ver las notas internas del proyecto "Metadatos YAML")
# ==========================================================

CARACTERES_INICIALES_YAML = tuple("-?:[]{},&*!|>'\"%@`#")


def _yaml_valor(valor: str) -> str:
    """Formatea un valor como escalar YAML seguro. Los titulos/descripciones
    extraidos de la web son texto libre y a menudo contienen ': ' (ej.
    titulares de noticias tipo 'THE: La UPV es...'), que en YAML sin
    comillas se interpreta como un mapping anidado y rompe el parseo --
    hay que entrecomillar en ese caso (y en cualquier otro caracter
    especial al inicio, o cadena vacia)."""
    valor = str(valor)
    necesita_comillas = (
        valor == ""
        or ": " in valor
        or valor.endswith(":")
        or valor.startswith(CARACTERES_INICIALES_YAML)
        or "\n" in valor
    )
    if not necesita_comillas:
        return valor
    escapado = valor.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escapado}"'


def generar_yaml_metadatos(*, fuente: str, url: str, categoria: str, tipo_documento: str, titulo: str,
                            nivel: str | None = None, tipo_recurso: str | None = None,
                            resumen: str | None = None, seccion: str | None = None,
                            descripcion: str = "", actualizado: str | None = None,
                            campos_extra: dict[str, str] | None = None) -> str:
    """Cabecera YAML homogenea para todo el corpus.

    tipo_documento distingue tres casos (ver tabla de presencia en
    las notas internas del proyecto): "resumen" (pagina raiz de una categoria/nivel, sin
    `resumen` ni `seccion` propios), "seccion" (lleva `resumen` pero no
    `seccion`) y "recurso" (lleva ambos). `nivel` solo se incluye si el
    documento vive en una subcarpeta real de data/processed/<categoria>/.
    """
    if actualizado is None:
        actualizado = date.today().strftime("%Y-%m-%d")

    campos = [("fuente", fuente), ("url", url), ("categoria", categoria)]
    if nivel:
        campos.append(("nivel", nivel))
    campos.append(("tipo_documento", tipo_documento))
    if tipo_recurso:
        campos.append(("tipo_recurso", tipo_recurso))
    if resumen:
        campos.append(("resumen", resumen))
    if seccion:
        campos.append(("seccion", seccion))
    campos.append(("titulo", titulo))
    campos.append(("descripcion", descripcion))
    campos.append(("actualizado", actualizado))
    if campos_extra:
        campos.extend(campos_extra.items())

    lineas = [f"{clave}: {_yaml_valor(valor)}" for clave, valor in campos]
    return "---\n" + "\n".join(lineas) + "\n---\n"
