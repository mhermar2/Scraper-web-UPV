"""Utilidades compartidas por el programa de descubrimiento de contenido
nuevo (src/descubrimiento.py, al mismo nivel que main.py -- este modulo
de soporte se queda en src/crawlers/, junto a crawler_inicial.py) y por
el enganche de refresco desde src/main.py.

No se apoya en ningun extrae_*.py -- necesita generar paginas de las que
no se conoce de antemano la plantilla, asi que usa una cascada generica de
selectores ya documentados (ver encontrar_contenedor_generico) en vez de
la lista de selectores especifica de cada extractor. Reutiliza el mismo
pipeline de limpieza (extraer_bloques_contenido/limpiar_lineas_finales/
generar_yaml_metadatos) que ya usan los extractores curados -- lo nuevo
aqui es solo la busqueda del contenedor y el seguimiento de URLs.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # src/ (config.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "extractores"))  # motor_limpieza.py
sys.path.insert(0, str(Path(__file__).resolve().parent))  # src/crawlers/ (crawler_inicial.py, propio directorio)

import requests
from bs4 import BeautifulSoup, Comment

import config
import motor_limpieza as ml
import crawler_inicial as ci

HEADERS = config.HEADERS

PATRON_ENLACE_MD = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")

TEXTOS_BOILERPLATE_DESCUBRIMIENTO = ml.TEXTOS_BOILERPLATE_BASE | ml.TEXTOS_BOILERPLATE_PLANTILLA_CLASICA

UMBRAL_PALABRAS_MINIMO = 10


def leer_yaml_frontmatter(ruta_md: Path) -> dict[str, str]:
    """Lee el bloque YAML de un .md ya generado por generar_yaml_metadatos()
    -- parseo minimo (clave: valor por linea), suficiente porque ese
    formato es siempre plano (una linea por campo, sin listas/anidacion),
    no hace falta una libreria YAML completa para leerlo hacia atras."""
    texto = ruta_md.read_text(encoding="utf-8")
    if not texto.startswith("---\n"):
        return {}
    fin = texto.find("\n---\n", 4)
    if fin == -1:
        return {}
    metadatos = {}
    for linea in texto[4:fin].splitlines():
        if ":" not in linea:
            continue
        clave, _, valor = linea.partition(":")
        valor = valor.strip()
        if len(valor) >= 2 and valor.startswith('"') and valor.endswith('"'):
            valor = valor[1:-1]
        metadatos[clave.strip()] = valor
    return metadatos


def extraer_enlaces_markdown(texto_md: str) -> list[tuple[str, str]]:
    """Enlaces [texto](url) del CUERPO de un .md ya generado (tras el
    segundo `---` del YAML) -- permite minar candidatos sin descargar
    nada de nuevo."""
    if texto_md.startswith("---\n"):
        fin = texto_md.find("\n---\n", 4)
        cuerpo = texto_md[fin + 5:] if fin != -1 else texto_md
    else:
        cuerpo = texto_md
    return PATRON_ENLACE_MD.findall(cuerpo)


_ENLACES_SIN_VALOR = {
    "web", "sitio web", "pagina web", "página web", "enlace", "acceso",
    "aqui", "aquí", "leer mas", "leer más", "ver mas", "ver más",
    "descargar", "descargar archivo", "pdf", "documento",
}
_PATRON_SOLO_PARENTESIS = re.compile(r"^\(.*\)$")


def es_texto_enlace_sin_valor(texto: str | None) -> bool:
    """Filtra anclas de enlace que no sirven como titulo de un recurso
    nuevo: etiquetas genericas ("Web", "Acceso"), notas de accesibilidad
    puramente entre parentesis ("(Abre en ventana nueva)"), o fragmentos
    de una frase capturados como si fueran el enlace completo (empiezan
    en minuscula -- un titulo real, como los que ya generan los
    extractores curados, siempre empieza en mayuscula)."""
    if not texto:
        return True
    texto = texto.strip()
    if len(texto) < 3:
        return True
    if _PATRON_SOLO_PARENTESIS.match(texto):
        return True
    if texto.lower() in _ENLACES_SIN_VALOR:
        return True
    primera_letra = next((c for c in texto if c.isalpha()), None)
    if primera_letra is not None and primera_letra.islower():
        return True
    return False


def es_url_candidata(url: str) -> bool:
    """Dominio upv.es y fuera de la lista negra ya madura de
    crawler_inicial.py (dominios/rutas prohibidos, extensiones de video/
    audio/comprimido, idiomas no castellanos...) -- se reutiliza tal cual,
    no se duplica el criterio."""
    return ci.es_valida(url) and not ml.es_subdominio_fuera_de_alcance(url)


def _limpiar_pagina_segura(soup: BeautifulSoup) -> BeautifulSoup:
    """No decompone <header>/<nav>/<footer> globalmente (a diferencia de
    ml.limpiar_contenido_html) -- algunas plantillas WordPress envuelven
    el <h1> real en su propio <header class="entry-header"> de articulo,
    mismo quirk ya documentado en varios extractores curados."""
    for tag in soup.find_all(["script", "style", "noscript", "svg"]):
        tag.decompose()
    for comentario in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comentario.extract()
    return soup


def encontrar_contenedor_generico(soup: BeautifulSoup, url: str):
    """Cascada de selectores de las plantillas de upv.es ya documentadas
    (ver las notas internas del proyecto) reunidas aqui para uso generico -- no sustituye la
    lista local de ningun extractor existente, es solo para paginas de
    las que no se conoce de antemano que plantilla usan. Devuelve
    (contenedor, url_del_contenido) -- distinto de la url original cuando
    el contenido real vive en un iframe clasico."""
    iframe_url = ml.buscar_iframe_contenido_clasico(soup, url)
    if iframe_url is not None:
        soup_iframe, es_html = descargar_soup_seguro(iframe_url)
        if soup_iframe is not None:
            soup_iframe = _limpiar_pagina_segura(soup_iframe)
            contenido = soup_iframe.find(id="contenido") or soup_iframe.body
            if contenido is not None:
                return contenido, iframe_url

    for buscar in (
        lambda s: s.find(id="smooth-wrapper"),
        lambda s: s.find("main"),
        lambda s: s.find(id="contenido"),
        lambda s: s.find(id="content"),
        lambda s: s.find(class_="mwc_contenido"),
    ):
        contenedor = buscar(soup)
        if contenedor is not None:
            return contenedor, url

    return soup.body, url


def descargar_soup_seguro(url: str) -> tuple[BeautifulSoup | None, bool]:
    try:
        soup, es_html = ml.descargar_soup(url, headers=HEADERS)
        return soup, es_html
    except Exception:
        return None, False


_PATRON_ENLACE_GENERICO = re.compile(r"\[+[^\]]*\]+\([^)]*\)")


def _es_linea_solo_enlaces(linea: str) -> bool:
    if "](" not in linea:
        return False
    return not _PATRON_ENLACE_GENERICO.sub("", linea).strip()


def _es_titulo_corto(linea: str) -> bool:
    return bool(re.match(r"^#{1,6}\s+\S+(\s+\S+){0,2}\s*$", linea.strip()))


def recortar_bloque_final_tipo_menu(lineas: list[str], maximo_lineas: int = 6) -> list[str]:
    """Heuristica generica -- solo la usa generar_recurso_generico, para
    paginas de plantilla desconocida (ver encontrar_contenedor_generico).
    Si las ultimas lineas son un bloque corto de enlaces sueltos (tipico
    menu/pie de un microsite ajeno a las plantillas ya documentadas de
    upv.es, ej. un subdominio antiguo sin relacion con las 6 variantes ya
    conocidas), se recorta. Limitado a un bloque corto al final
    (maximo_lineas) para no comerse una seccion de contenido real que
    termine en una lista de enlaces legitima."""
    fin = len(lineas)
    hubo_enlaces = False
    while fin > 0 and (len(lineas) - fin) < maximo_lineas:
        linea = lineas[fin - 1]
        if _es_linea_solo_enlaces(linea):
            hubo_enlaces = True
        elif not _es_titulo_corto(linea):
            break
        fin -= 1
    return lineas[:fin] if hubo_enlaces else lineas


def generar_recurso_generico(url: str, carpeta_destino: Path, *, categoria: str, nivel: str | None,
                              seccion: str | None, resumen: str, profundidad: int,
                              nombres_usados: set[str], titulo: str | None = None) -> dict | None:
    """Genera un .md generico (sin conocer de antemano la plantilla de la
    pagina) para una URL descubierta. Reusa el mismo pipeline de limpieza
    que ya usan los extractores curados -- devuelve None (y no genera
    nada) si falla la peticion, el contenido queda vacio, o es un
    subdominio fuera de alcance -- mismo criterio de tolerancia a fallos
    que ya usan todos los extractores."""
    if ml.es_subdominio_fuera_de_alcance(url):
        return None

    url_descarga = ml.resolver_menu_url_antiguo(url)

    try:
        respuesta = requests.get(url_descarga, headers=HEADERS, timeout=30)
        respuesta.raise_for_status()
        tipo = ml.tipo_contenido(respuesta.headers.get("Content-Type", ""))

        if tipo == "pdf":
            paginas = ml.extraer_texto_pdf(respuesta.content)
            if not paginas or ml.contar_palabras(paginas) < UMBRAL_PALABRAS_MINIMO:
                return None  # PDF mayormente escaneado/sin texto real (ej. un sello o una URL suelta)
            titulo_final = (titulo or url.rsplit("/", 1)[-1]).strip()
            cuerpo = "\n\n".join(paginas)

        elif tipo == "html":
            soup = BeautifulSoup(respuesta.text, "html.parser")
            soup = _limpiar_pagina_segura(soup)
            contenedor, url_contenido = encontrar_contenedor_generico(soup, url_descarga)
            if contenedor is None:
                return None
            ml.reemplazar_tablas_por_listas(soup, contenedor)
            lineas = ml.extraer_bloques_contenido(contenedor, url_contenido)
            lineas = ml.limpiar_lineas_finales(lineas, textos_boilerplate=TEXTOS_BOILERPLATE_DESCUBRIMIENTO)
            lineas = recortar_bloque_final_tipo_menu(lineas)
            titulo_final = (titulo or (soup.title.get_text(strip=True) if soup.title else url)).strip()
            lineas = ml.quitar_titulos_redundantes(lineas, titulo_final)
            if not lineas or ml.contar_palabras(lineas) < UMBRAL_PALABRAS_MINIMO:
                return None
            cuerpo = "\n\n".join(lineas)

        else:
            return None

        if not titulo_final:
            return None

        yaml_metadatos = ml.generar_yaml_metadatos(
            fuente="UPV", url=url, categoria=categoria, nivel=nivel,
            tipo_documento="recurso", tipo_recurso="informacion",
            resumen=resumen, seccion=seccion, titulo=titulo_final,
            campos_extra={"profundidad": str(profundidad)},
        )
        nombre = ml.nombre_archivo_sin_colision(titulo_final, nombres_usados)
        carpeta_destino.mkdir(parents=True, exist_ok=True)
        ruta = carpeta_destino / nombre
        ruta.write_text(f"{yaml_metadatos}\n# {titulo_final}\n\n**URL:** {url}\n\n{cuerpo}\n", encoding="utf-8")
        return {"archivo": str(ruta.relative_to(config.DATA_PROCESSED_DIR)).replace("\\", "/")}

    except Exception as error:
        print(f"  ERROR generando {url}: {error}")
        return None


def _url_desde_yaml(ruta_md: Path) -> str | None:
    return leer_yaml_frontmatter(ruta_md).get("url") or None


def bootstrap_seguimiento(processed_dir: Path = config.DATA_PROCESSED_DIR) -> dict:
    """Puebla el fichero de seguimiento desde cero a partir de todo el
    corpus ya generado -- arranca "en reposo": cada URL ya cubierta se
    marca expandida=True (no se lanza a rastrear los ~1000 recursos ya
    existentes de golpe), y cada enlace que aparezca en su cuerpo sin
    tener ya su propio .md se anota como candidato de profundidad 1."""
    seguimiento: dict[str, dict] = {}
    rutas_por_url: dict[str, Path] = {}

    for ruta_md in processed_dir.rglob("*.md"):
        url = _url_desde_yaml(ruta_md)
        if not url:
            continue
        rutas_por_url[url] = ruta_md
        seguimiento[url] = {
            "profundidad": 0,
            "md_generado": True,
            "archivo": str(ruta_md.relative_to(processed_dir)).replace("\\", "/"),
            "padre_url": None,
            "titulo_enlace": None,
            "expandida": True,
            "descartada": False,
        }

    for url, ruta_md in rutas_por_url.items():
        texto = ruta_md.read_text(encoding="utf-8")
        for texto_enlace, url_enlace in extraer_enlaces_markdown(texto):
            url_enlace = url_enlace.split("#")[0].rstrip("/")
            if url_enlace in seguimiento or not es_url_candidata(url_enlace):
                continue
            if es_texto_enlace_sin_valor(texto_enlace):
                continue
            seguimiento[url_enlace] = {
                "profundidad": 1,
                "md_generado": False,
                "archivo": None,
                "padre_url": url,
                "titulo_enlace": texto_enlace,
                "expandida": False,
                "descartada": False,
            }

    return seguimiento


def cargar_seguimiento() -> dict:
    ruta = config.DESCUBRIMIENTO_URLS_JSON
    if not ruta.exists():
        seguimiento = bootstrap_seguimiento()
        guardar_seguimiento(seguimiento)
        print(f"Fichero de seguimiento creado desde cero: {len(seguimiento)} URLs conocidas "
              f"({sum(1 for e in seguimiento.values() if not e['md_generado'])} pendientes de generar).")
        return seguimiento
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_seguimiento(seguimiento: dict) -> None:
    ruta = config.DESCUBRIMIENTO_URLS_JSON
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(seguimiento, f, ensure_ascii=False, indent=2, sort_keys=True)


def refrescar_bajo_carpeta(carpeta_processed: Path) -> int:
    """Usada desde main.py: vuelve a generar los .md de descubrimiento ya
    existentes bajo la carpeta de una seccion, sin descubrir enlaces
    nuevos ni modificar el fichero de seguimiento (profundidad/archivo/
    padre_url no cambian al refrescar -- solo se reescribe el contenido
    del .md, igual que hace cualquier extractor al actualizarse)."""
    ruta_json = config.DESCUBRIMIENTO_URLS_JSON
    if not ruta_json.exists():
        return 0
    with open(ruta_json, "r", encoding="utf-8") as f:
        seguimiento = json.load(f)

    prefijo = str(carpeta_processed.relative_to(config.DATA_PROCESSED_DIR)).replace("\\", "/")
    refrescados = 0
    for url, entrada in seguimiento.items():
        archivo = entrada.get("archivo")
        if entrada.get("profundidad", 0) < 1:
            continue  # profundidad 0 = ya cubierto por el extractor curado, no le toca a este refresco
        if not entrada.get("md_generado") or not archivo or not archivo.startswith(prefijo):
            continue

        ruta_md = config.DATA_PROCESSED_DIR / archivo
        metadatos_previos = leer_yaml_frontmatter(ruta_md) if ruta_md.exists() else {}
        resultado = generar_recurso_generico(
            url, ruta_md.parent,
            categoria=metadatos_previos.get("categoria", ""),
            nivel=metadatos_previos.get("nivel") or None,
            seccion=metadatos_previos.get("seccion") or None,
            resumen=entrada.get("padre_url") or metadatos_previos.get("resumen", ""),
            profundidad=entrada.get("profundidad", 1),
            nombres_usados=set(),
            titulo=entrada.get("titulo_enlace") or metadatos_previos.get("titulo") or None,
        )
        if resultado is not None:
            refrescados += 1

    return refrescados
