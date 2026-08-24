"""Motor de limpieza de contenido compartido por los extractores ya
validados (institucion, servicios, rankings, formacion_permanente,
doctorado). Logica de proposito general: se amplia con capacidades
nuevas cuando hace falta, pero no se bifurca por seccion.

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


def nombre_archivo_sin_colision(titulo: str, nombres_usados: set[str], desambiguador: str = "") -> str:
    """Como nombre_archivo_markdown(), pero evita que dos recursos
    DISTINTOS con el mismo texto de enlace (ej. varios "Mas informacion"
    con URLs diferentes dentro de la misma seccion, visto en
    admision/grado) se pisen en silencio bajo el mismo nombre de fichero
    dentro de una misma ejecucion. `nombres_usados` debe ser un set
    compartido por todos los recursos de la misma carpeta, actualizado
    por esta funcion en cada llamada -- no comprueba el disco (un
    recurso que SI es el mismo de una ejecucion anterior debe poder
    sobrescribir su propio fichero con normalidad, eso no es colision).
    Intenta primero el nombre plano, luego title+desambiguador (p.ej. el
    slug de la seccion de origen), y por ultimo un contador incremental."""
    nombre = nombre_archivo_markdown(titulo)
    if nombre not in nombres_usados:
        nombres_usados.add(nombre)
        return nombre

    if desambiguador:
        candidato = nombre_archivo_markdown(f"{titulo}_{desambiguador}")
        if candidato not in nombres_usados:
            nombres_usados.add(candidato)
            return candidato

    base = nombre[:-3]  # sin ".md"
    contador = 2
    while True:
        candidato = f"{base}_{contador}.md"
        if candidato not in nombres_usados:
            nombres_usados.add(candidato)
            return candidato
        contador += 1


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
    if lector.is_encrypted:
        # PDFs de riunet.upv.es cifrados con AES y contraseña vacia (solo
        # para bloquear edicion, no lectura) -- requiere el paquete
        # "cryptography" instalado, si no pypdf lanza excepcion al leer.
        lector.decrypt("")
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
    (sin #smooth-wrapper ni <main>) no lleva el contenido real en la
    pagina index: lo carga en un <iframe> (normalmente id="marco") que
    apunta a
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


def buscar_enlace_acceso_web_externa(soup: BeautifulSoup, url_base: str) -> str | None:
    """Algunos centros con CMS propio fuera de upv.es (ASP.NET, PHP...)
    no publican ningun contenido real bajo /entidades/<codigo>/: la
    plantilla clasica de fallback que ahi aparece solo ofrece un enlace
    "Acceso a la Web" hacia el dominio externo real (caso real:
    ETSICCP -> iccp.upv.es). Sin seguir ese enlace, el corpus solo veria
    ruido de menu y ningun dato del centro."""
    enlace = soup.find("a", string=re.compile(r"acceso a la web", re.I))
    if enlace is None or not enlace.get("href"):
        return None
    return normalizar_url(enlace["href"], url_base)


# ==========================================================
# Arbol de mapa del sitio (WordPress moderno / Oracle Portal clasico /
# sitemap.xml)
#
# Anadida 2026-08-23 para organizacion/{escuelas_facultades,
# departamentos}: a diferencia del resto de secciones, aqui el tutor ya
# habia decidido (por correo) que el contenido real de cada centro es
# demasiado heterogeneo para homogeneizar con el traversal por "hoja de
# contenido" -- lo que aporta valor real es un indice navegable (que
# secciones tiene la web del centro y a que URL van) mas que el texto
# completo de cada pagina. Tres fuentes posibles segun la plantilla:
#   1. WordPress moderno: pagina dedicada <web>/mapa-del-sitio/ con un
#      arbol <ul class="sitemap"> de hasta 3 niveles (confirmado en
#      ETSIT/DISCA).
#   2. Oracle Portal clasico (paginas sin esa ruta, 404): el propio menu
#      lateral de la ficha (#mnuIzquierda) YA es ese mismo arbol de
#      categoria/subcategoria/enlace, solo que reconstruido con
#      JavaScript en vez de <ul>/<li> anidados (confirmado en
#      departamentos como DB/DCAN/DU, plantilla igual a la de
#      servicios/admision pero aqui se usa para navegacion, no para
#      seguir enlaces de contenido).
#   3. Dominio propio con generador de sitio estatico (ETSII): no hay
#      pagina "mapa del sitio" humana, pero si `sitemap.xml` estandar en
#      la raiz -- se listan las URLs agrupadas por su primer segmento de
#      ruta (sin texto humano, es lo unico que aporta el XML).
# Si ninguna de las tres existe (caso ETSICCP, CMS ASP.NET con
# navegacion por JavaScript), no se inventa nada: se deja constancia en
# el Markdown de que no hay mapa del sitio estandar disponible.
# ==========================================================

def extraer_arbol_sitemap_wp(url_mapa: str, headers: dict | None = None) -> list[dict] | None:
    """Descarga <web>/mapa-del-sitio/ (plantilla WordPress moderna) y
    devuelve su arbol de navegacion anidado, o None si la pagina no
    existe o no tiene la estructura esperada (<ul class="sitemap">)."""
    try:
        soup, es_html = descargar_soup(url_mapa, headers=headers)
    except Exception:
        return None
    if not es_html:
        return None
    raiz = soup.find("ul", class_="sitemap")
    if raiz is None:
        return None
    return _parsear_ul_sitemap(raiz, url_mapa)


def _parsear_ul_sitemap(ul, url_base: str) -> list[dict]:
    nodos = []
    for li in ul.find_all("li", recursive=False):
        enlace = li.find("a", recursive=False)
        if enlace is None or not enlace.get("href"):
            continue
        nodo = {"titulo": extraer_texto_limpio(enlace), "url": normalizar_url(enlace["href"], url_base), "hijos": []}
        sub_ul = li.find("ul", recursive=False)
        if sub_ul is not None:
            nodo["hijos"] = _parsear_ul_sitemap(sub_ul, url_base)
        nodos.append(nodo)
    return nodos


def extraer_menu_clasico(soup: BeautifulSoup, url_base: str) -> list[dict]:
    """Extrae el arbol de categorias del menu lateral de la plantilla
    Oracle Portal clasica (id="mnuIzquierda"): cada categoria de primer
    nivel es un <a id="itmN"> (dentro de un <p>) seguido de un
    <div id="divN" class="submenu"> con subcategorias
    (<span class="mnuizquierda_2donivel">, sin enlace propio, solo
    etiqueta) y enlaces reales intercalados como hermanos -- no hay
    <ul>/<li> anidados, hay que reconstruir la jerarquia a mano siguiendo
    el orden de aparicion. Devuelve [] si la pagina no usa esta
    plantilla."""
    menu = soup.find(id="mnuIzquierda")
    if menu is None:
        return []

    categorias = []
    for parrafo in menu.find_all("p", recursive=False):
        enlace_categoria = parrafo.find("a")
        if enlace_categoria is None:
            continue
        categoria = {"titulo": extraer_texto_limpio(enlace_categoria), "hijos": []}
        categorias.append(categoria)

        id_categoria = (enlace_categoria.get("id") or "")
        if not id_categoria.startswith("itm"):
            continue
        submenu = menu.find(id="div" + id_categoria[len("itm"):])
        if submenu is None:
            continue

        subcategoria_actual = None
        for hijo in submenu.find_all(["span", "a"], recursive=True):
            if hijo.name == "span" and "mnuizquierda_2donivel" in (hijo.get("class") or []):
                subcategoria_actual = {"titulo": extraer_texto_limpio(hijo), "hijos": []}
                categoria["hijos"].append(subcategoria_actual)
            elif hijo.name == "a" and hijo.get("href"):
                item = {"titulo": extraer_texto_limpio(hijo), "url": normalizar_url(hijo["href"], url_base)}
                if not item["titulo"]:
                    continue
                destino = subcategoria_actual["hijos"] if subcategoria_actual is not None else categoria["hijos"]
                destino.append(item)

        # Una subcategoria sin ningun hijo (etiqueta huerfana al final de
        # un submenu, visto en DB: "Publicaciones docentes" aparece dos
        # veces en el HTML real, una como enlace y otra como cabecera de
        # subcategoria vacia que no llega a tener ningun enlace propio
        # detras) no aporta navegacion real.
        categoria["hijos"] = [
            h for h in categoria["hijos"] if "hijos" not in h or h["hijos"]
        ]

    # Una categoria sin ningun hijo (ej. un enlace suelto "Acceso a la
    # Web" fuera del patron itmN/divN, visto en ETSICCP) no aporta
    # navegacion real -- se descarta en vez de aparecer como seccion
    # vacia en el mapa del sitio.
    return [c for c in categorias if c["hijos"]]


def extraer_urls_de_sitemap(url: str, headers: dict | None = None, maximo_subsitemaps: int = 15,
                             _profundidad: int = 0) -> list[str]:
    """Descarga y parsea un sitemap.xml estandar (protocolo sitemaps.org),
    resolviendo tambien el caso de un indice de sitemaps (<sitemapindex>,
    el formato nativo de WordPress: wp-sitemap.xml apunta a varios
    sub-sitemaps de posts/paginas/taxonomias -- confirmado en
    etsie.upv.es) siguiendo cada sub-sitemap hasta un nivel de anidamiento
    (en la practica un indice no aparece anidado mas de un nivel). Si hay
    sub-sitemaps de "paginas" y de "entradas"/taxonomias mezclados, se
    prioriza el de paginas (mejor proxy de secciones reales del sitio,
    menos ruido que un listado de posts de blog). Sin texto humano
    asociado (el XML no lo trae) -- ultimo recurso cuando ni la pagina de
    mapa del sitio WordPress ni el menu clasico existen (ver
    extraer_arbol_sitemap_wp/extraer_menu_clasico)."""
    import xml.etree.ElementTree as ET

    try:
        respuesta = requests.get(url, headers=headers or HEADERS_GENERICOS, timeout=30)
        respuesta.raise_for_status()
        raiz = ET.fromstring(respuesta.content)
    except Exception:
        return []

    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [loc.text.strip() for loc in raiz.findall(".//sm:loc", ns) if loc.text and loc.text.strip()]

    if not raiz.tag.endswith("sitemapindex") or _profundidad >= 1:
        return locs

    candidatos = [u for u in locs if "page" in u.lower()] or locs
    urls = []
    for sub_url in candidatos[:maximo_subsitemaps]:
        urls.extend(extraer_urls_de_sitemap(sub_url, headers=headers, _profundidad=_profundidad + 1))
    return urls


def agrupar_urls_sitemap_xml_por_seccion(urls: list[str], maximo_por_seccion: int = 20) -> list[dict]:
    """Agrupa las URLs planas de un sitemap.xml por su primer segmento
    de ruta (unica agrupacion tematica disponible sin texto humano),
    con el mismo formato {titulo, url, hijos} que extraer_arbol_sitemap_wp/
    extraer_menu_clasico para poder reutilizar el mismo renderizador.

    Un sitemap.xml de un CMS plano (sin la curaduria editorial del arbol
    WordPress/menu clasico) puede listar cientos de variantes casi
    identicas de la misma plantilla (ej. un horario por
    titulacion x curso x convocatoria, visto en etsii.upv.es: mas de 100
    URLs solo de horario_titulacionN.php con distintos parametros) --
    sin limite, la ficha del centro dejaria de ser un indice legible
    para convertirse en un volcado de cientos de enlaces casi iguales.
    Se trunca cada seccion a `maximo_por_seccion`, dejando constancia de
    cuantas mas hay."""
    grupos: dict[str, list[dict]] = {}
    for url in urls:
        ruta = urlparse(url).path.strip("/")
        segmento = ruta.split("/", 1)[0] if ruta else ""
        etiqueta = segmento.replace("-", " ").replace("_", " ").capitalize() if segmento else "General"
        grupos.setdefault(etiqueta, []).append({"titulo": url, "url": url})

    nodos = []
    for etiqueta, items in grupos.items():
        restantes = len(items) - maximo_por_seccion
        hijos = items[:maximo_por_seccion]
        if restantes > 0:
            hijos.append({"titulo": f"… {restantes} enlaces más en esta sección (ver sitemap.xml completo)"})
        nodos.append({"titulo": etiqueta, "hijos": hijos})
    return nodos


def arbol_sitemap_a_markdown(nodos: list[dict], nivel: int = 0) -> list[str]:
    """Convierte el arbol devuelto por extraer_arbol_sitemap_wp()/
    extraer_menu_clasico()/agrupar_urls_sitemap_xml_por_seccion() en
    lineas Markdown: categorias de primer nivel como titulo de seccion,
    el resto como lista anidada por sangria."""
    lineas = []
    for nodo in nodos:
        titulo, url, hijos = nodo.get("titulo", ""), nodo.get("url"), nodo.get("hijos") or []
        if nivel == 0:
            lineas.append(f"### [{titulo}]({url})" if url else f"### {titulo}")
        else:
            sangria = "  " * (nivel - 1)
            texto = f"[{titulo}]({url})" if url else f"**{titulo}**"
            lineas.append(f"{sangria}- {texto}")
        lineas.extend(arbol_sitemap_a_markdown(hijos, nivel + 1))
    return lineas


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
    de columnas coincide.

    Las celdas de cada fila se buscan con recursive=False: encontrado en
    paginas de fichas de titulacion (estudios/master), alguna plantilla
    UPV genera HTML invalido donde cada fila "logica" es en realidad una
    <tr> anidada dentro de un <td> de la <tr> anterior (una cadena, no
    filas hermanas). find_all("td") recursivo por fila arrastraba
    tambien las celdas de todas las filas anidadas mas adentro,
    duplicando el contenido en cascada (una linea con todas las celdas,
    otra con todas menos la primera, etc.). Con recursive=False cada
    <tr> (top-level o anidada, find_all("tr") ya las encuentra todas)
    aporta solo sus propias celdas.

    Dos formas de tabla con <th>, tratadas por separado (bug real
    encontrado 2026-08-23 en la consulta de "Asignaturas" de
    estudios/grado, clase `upv_ficha` -- la misma clase que usa el
    contacto de institucion/servicios via
    buscar_iframe_contenido_clasico(), asi que el bug podia estar
    afectando tambien alli): tabla HORIZONTAL (una unica fila de
    cabecera con todos los <th>, filas de datos solo con <td> debajo --
    el caso ya cubierto) y tabla VERTICAL/clave-valor (cada fila trae su
    propio <th> como etiqueta de esa fila, ej. "Titulacion" / "Curso").
    Antes de este fix, una tabla vertical hacia que
    `len(encabezados_globales) != len(celdas_de_una_fila)` (5 <th> en
    toda la tabla contra 1 <td> por fila) y caia siempre al fallback sin
    etiqueta -- la fila quedaba como un valor suelto sin ningun contexto
    ("Escuela Tecnica Superior de Ingenieria de Telecomunicacion" sin
    decir que ese valor es la "Ent. Resp"). Se detecta mirando el <th>
    de la PROPIA fila primero; solo si la fila no tiene <th> propio se
    usa el fallback de cabecera global (tabla horizontal)."""
    for tabla in contenedor.find_all("table"):
        encabezados_horizontal = [extraer_texto_limpio(th) for th in tabla.find_all("th")]
        lista = soup.new_tag("ul")
        for fila in tabla.find_all("tr"):
            etiquetas_fila = [extraer_texto_limpio(th) for th in fila.find_all("th", recursive=False)]
            celdas = [extraer_texto_limpio(td) for td in fila.find_all("td", recursive=False)]
            celdas = [c for c in celdas if c and c != "-" and re.search(r"[A-Za-z0-9]", c)]
            if not celdas:
                continue
            if etiquetas_fila and len(etiquetas_fila) == len(celdas):
                texto_fila = "; ".join(f"{e}: {c}" for e, c in zip(etiquetas_fila, celdas) if c)
            elif encabezados_horizontal and len(encabezados_horizontal) == len(celdas):
                texto_fila = "; ".join(f"{h}: {c}" for h, c in zip(encabezados_horizontal, celdas) if c)
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


def quitar_titulos_redundantes(lineas: list[str], titulo_esperado: str | None = None) -> list[str]:
    """Quita, del principio de `lineas`, cualquier titulo (#, ##...)
    consecutivo redundante -- patron real encontrado 2026-08-23 en
    estudios/grado y estudios/master: varias plantillas repiten el
    titulo de la pagina/titulacion al principio de su propio contenido,
    aunque el extractor ya lo antepone por su cuenta (ej.
    generar_markdown_titulacion() ya escribe "# {titulo}"). Dos
    variantes, cubiertas en el mismo bucle:
      1. El titulo inicial coincide con `titulo_esperado` (si se pasa) --
         ej. la pagina de Inicio de un master repite el nombre de la
         titulacion como su propio <h2>.
      2. El titulo inicial coincide con el SIGUIENTE titulo (auto-
         duplicado, sin necesidad de conocer el titulo de antemano) --
         ej. la consulta de Asignaturas de grado/master repite
         "Asignaturas" como <h1> y <h2> seguidos, sin nada de por medio.
    Una vez quitado el primero por cualquiera de los dos motivos, sigue
    comprobando el nuevo primero contra el mismo texto (cubre el caso de
    Asignaturas, donde hacen falta dos pasadas)."""
    objetivo = normalizar_para_comparar(titulo_esperado) if titulo_esperado else None
    while lineas and lineas[0].startswith("#"):
        texto = normalizar_para_comparar(re.sub(r"^#+\s*", "", lineas[0]))
        if objetivo is not None and texto == objetivo:
            lineas = lineas[1:]
        elif objetivo is None and len(lineas) > 1 and lineas[1].startswith("#") and \
                normalizar_para_comparar(re.sub(r"^#+\s*", "", lineas[1])) == texto:
            lineas = lineas[1:]
            objetivo = texto
        else:
            break
    return lineas


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

    # El h1 real de la pagina (primera linea, solo si recortar_h1 lo
    # identifico como tal) nunca se trata como boilerplate: el titulo de
    # una seccion a menudo coincide textualmente con su propia entrada en
    # el menu de navegacion (ej. "Servicios universitarios", "Iniciativas
    # de I+D+i"), que SI esta en textos_boilerplate por repetirse en el
    # menu de cualquier otra pagina -- sin esta excepcion el h1 real
    # desaparece en silencio. Bug real encontrado 2026-08-21: ya afectaba
    # a servicios_universitarios.md (comiteado sin su propio h1).
    if recortar_h1 and lineas and lineas[0].startswith("# "):
        titulo_real, resto = lineas[0], lineas[1:]
    else:
        titulo_real, resto = None, lineas

    resto = [linea for linea in resto if not es_linea_boilerplate(linea, textos_boilerplate)]
    lineas_finales = ([titulo_real] if titulo_real else []) + resto
    return deduplicar_global(lineas_finales)


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
# Metadatos YAML (formato definitivo del proyecto)
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

    tipo_documento distingue tres casos: "resumen" (pagina raiz de una
    categoria/nivel, sin `resumen` ni `seccion` propios), "seccion"
    (lleva `resumen` pero no `seccion`) y "recurso" (lleva ambos).
    `nivel` solo se incluye si el documento vive en una subcarpeta real
    de data/processed/<categoria>/.
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
