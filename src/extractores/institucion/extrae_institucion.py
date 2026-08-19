"""Extractor de "La institucion" -- seccion de referencia (motor de
limpieza validado, ver las notas internas del proyecto).

Pipeline (mismo orden que el notebook original):
  1. extraer_estructura()      -> JSON con las 5 secciones + recursos
  2. guardar_json()
  3. generar_markdown_padre()  -> institucion.md
  4. generar_markdowns_recursos() -> un .md por recurso, motor de limpieza
     por "hoja de contenido" + filtrado de boilerplate + metadatos YAML

Migrado desde src/extractores/institucion/extrae_institucion.ipynb (antes
"Copia de Copia de Extrae_Institucion.ipynb" -- la version con los fixes
que documenta las notas internas del proyecto: bug organos_gobierno/organos_de_gobierno,
traversal por hoja de contenido, metadatos YAML homogeneos).

Se descartaron: SECCIONES_VALIDAS (definida pero nunca usada), el
"BLOQUE EXTRA. GENERAR UNICAMENTE ORGANOS DE GOBIERNO" (llamaba a
generar_markdown_recurso() con un argumento de menos -- le faltaba
seccion_id -- nunca pudo ejecutarse tal cual), y el "BLOQUE 11.
CORRECCION Y MEJORA DEFINITIVA" (regeneraba equipo_rectoral.md y
gerencia.md con mas detalle). Se comprobo contra la web real que este
ultimo bloque NUNCA llego a producir el contenido que hay comiteado en
organos_gobierno/: ese contenido coincide byte a byte con lo que genera
el motor generico (generar_markdown_recurso), no con la logica
especializada del BLOQUE 11 -- pese a que el notebook lo llama
"definitivo" y lo ejecuta al final, aparentemente nunca se aplico de
verdad. Se descarta por completo para reflejar fielmente lo que el
pipeline hace hoy; si en el futuro se quiere mejorar esas dos paginas
concretas, el codigo original sigue disponible en src/legacy/.
"""

from __future__ import annotations

import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bs4 import BeautifulSoup
import requests

from common import limpiar_texto
from config import INSTITUCION_CARPETAS, INSTITUCION_JSON, INSTITUCION_MD_PADRE, INSTITUCION_URL_RAIZ

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
CATEGORIA = "institucion"
NIVEL = "institucional"
PADRE_SLUG = "la_institucion"

UMBRAL_PALABRAS_POCO_CONTENIDO = 60
MAX_ENLACES_HIJOS = 5
MAX_CARACTERES_FRAGMENTO_HIJO = 800

TAGS_TITULO = {"h1", "h2", "h3", "h4", "h5", "h6"}
TAGS_BLOQUE = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "div", "ul", "ol", "table", "section", "article", "blockquote"}
TAGS_CANDIDATAS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "div", "span", "a"]

CONFIG_SECCIONES = {
    "Organos de gobierno": {"titulo": "Órganos de gobierno", "tipo": "organos_gobierno"},
    "Publicaciones oficiales": {"titulo": "Publicaciones oficiales", "tipo": "publicaciones_oficiales"},
    "La UPV al detalle": {"titulo": "La UPV al detalle", "tipo": "upv_al_detalle"},
    "Estrategia UPV_SIRVE": {"titulo": "Estrategia UPV_SIRVE", "tipo": "estrategia_upv_sirve"},
    "Sindicatura": {"titulo": "Sindicatura", "tipo": "sindicatura"},
}

# Textos de menu, accesos rapidos y pie de pagina que aparecen igual en
# (casi) cualquier pagina de upv.es -- valido para cualquier seccion, no
# solo institucion (ver las notas internas del proyecto).
TEXTOS_BOILERPLATE = {
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


# ==========================================================
# Funciones auxiliares generales
# ==========================================================

def normalizar_identificador(texto: str) -> str:
    """'Órganos de gobierno' -> 'organos_de_gobierno'."""
    texto = limpiar_texto(texto)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    return re.sub(r"[^a-z0-9]+", "_", texto).strip("_")


def normalizar_url(url: str, url_base: str = INSTITUCION_URL_RAIZ) -> str:
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


def crear_elemento(titulo: str = "", descripcion: str = "", url: str = "", tipo: str = "recurso") -> dict:
    return {"tipo": tipo, "titulo": limpiar_texto(titulo), "descripcion": limpiar_texto(descripcion), "url": normalizar_url(url)}


def titulo_normalizado(texto: str) -> str:
    texto = limpiar_texto(texto)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.lower().strip()


# ==========================================================
# 1. Extraccion de la estructura (JSON)
# ==========================================================

def localizar_seccion(contenedor_principal, titulo_objetivo: str):
    """Localiza la tarjeta de una seccion. En esta pagina la estructura
    HTML difiere: Organos de gobierno usa div.main-card, el resto usa
    div.secondary-card."""
    objetivo = titulo_normalizado(titulo_objetivo)

    for encabezado in contenedor_principal.find_all(["h2", "h3"]):
        texto = limpiar_texto(encabezado.get_text(" ", strip=True))
        if titulo_normalizado(texto) != objetivo:
            continue

        tarjeta_principal = encabezado.find_parent(class_="main-card")
        if tarjeta_principal is not None:
            return tarjeta_principal

        tarjeta_secundaria = encabezado.find_parent(class_="secondary-card")
        if tarjeta_secundaria is not None:
            return tarjeta_secundaria

        section = encabezado.find_parent("section")
        if section is not None:
            return section

    return None


def extraer_recursos_seccion(elemento, titulo_seccion: str) -> list[dict]:
    """Enlaces EXCLUSIVAMENTE dentro de la tarjeta de esta seccion, para
    que no absorba los enlaces de tarjetas posteriores."""
    recursos = []

    for enlace in elemento.find_all("a"):
        titulo = limpiar_texto(enlace.get_text(" ", strip=True))
        url = enlace.get("href", "")

        if not titulo or not url:
            continue

        url = normalizar_url(url, INSTITUCION_URL_RAIZ)
        if not es_url_valida(url):
            continue

        if titulo_normalizado(titulo) in {"mas informacion", "mas info", "ver mas"}:
            continue

        recursos.append(crear_elemento(titulo=titulo, descripcion="", url=url, tipo="recurso"))

    return deduplicar_lista(recursos, clave="url")


def extraer_estructura(url_raiz: str = INSTITUCION_URL_RAIZ) -> dict:
    respuesta = requests.get(url_raiz, headers=HEADERS, timeout=30)
    respuesta.raise_for_status()
    soup = BeautifulSoup(respuesta.text, "html.parser")

    contenedor_principal = soup.find(id="smooth-wrapper")
    if contenedor_principal is None:
        raise Exception("No se ha encontrado el contenedor principal #smooth-wrapper.")

    secciones_extraidas = []
    for clave, configuracion in CONFIG_SECCIONES.items():
        titulo = configuracion["titulo"]
        elemento = localizar_seccion(contenedor_principal, titulo)

        if elemento is None:
            print(f"AVISO: no se ha encontrado: {titulo}")
            continue

        recursos = extraer_recursos_seccion(elemento, titulo)
        seccion = crear_seccion(titulo, configuracion["tipo"])
        seccion["elementos"] = recursos
        secciones_extraidas.append(seccion)

    return {"titulo": "La institución", "url": url_raiz, "tipo": "padre", "secciones": secciones_extraidas}


def guardar_json(datos: dict, ruta: Path = INSTITUCION_JSON) -> None:
    import json
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


# ==========================================================
# 2. Motor de limpieza / generacion de Markdown (reutilizable)
# ==========================================================

def descargar_soup(url: str):
    """Descarga una pagina. Devuelve (soup, es_html)."""
    respuesta = requests.get(url, headers=HEADERS, timeout=30)
    respuesta.raise_for_status()
    content_type = respuesta.headers.get("Content-Type", "")
    if "html" not in content_type.lower():
        return None, False
    return BeautifulSoup(respuesta.text, "html.parser"), True


def limpiar_contenido_html(soup: BeautifulSoup) -> BeautifulSoup:
    for elemento in soup.find_all(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        elemento.decompose()
    return soup


def es_hoja_de_contenido(tag) -> bool:
    """Candidato a texto propio sin bloques anidados dentro (evita
    procesar el mismo texto dos veces, en el contenedor y en el hijo)."""
    if tag.name not in TAGS_CANDIDATAS:
        return False
    if tag.name == "a":
        return True
    return len(tag.find_all(TAGS_BLOQUE, recursive=True)) == 0


def texto_markdown_de_elemento(tag, url_pagina: str) -> str:
    """Convierte el contenido de una hoja a texto, respetando los
    enlaces que contenga como [texto](url)."""
    partes = []
    for nodo in tag.children:
        nombre_nodo = getattr(nodo, "name", None)

        if nombre_nodo == "a":
            texto_enlace = extraer_texto_limpio(nodo)
            href = (nodo.get("href") or "").strip()
            if not texto_enlace:
                continue
            if href and not href.startswith(("javascript:", "#")):
                partes.append(f"[{texto_enlace}]({urljoin(url_pagina, href)})")
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


def extraer_texto_limpio(elemento) -> str:
    if elemento is None:
        return ""
    return limpiar_texto(elemento.get_text(" ", strip=True))


def extraer_bloques_contenido(contenedor, url_pagina: str) -> list[str]:
    """Recorre el contenedor y devuelve lineas Markdown: titulos,
    parrafos, items de lista y enlaces sueltos (nombres, telefonos,
    emails, "Mas informacion"...)."""
    lineas = []
    linea_anterior = None

    for tag in contenedor.find_all(TAGS_CANDIDATAS, recursive=True):
        if not es_hoja_de_contenido(tag):
            continue

        if tag.name == "a":
            texto = extraer_texto_limpio(tag)
            href = (tag.get("href") or "").strip()
            if not texto:
                continue
            if href and not href.startswith(("javascript:", "#")):
                linea = f"[{texto}]({urljoin(url_pagina, href)})"
            else:
                linea = texto
        else:
            texto = texto_markdown_de_elemento(tag, url_pagina)
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


def normalizar_para_comparar(texto: str) -> str:
    texto = texto.strip().lower().strip("¡¿!?: ")
    texto = "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", texto).strip()


def es_linea_boilerplate(linea: str) -> bool:
    texto_plano = re.sub(r"^#+\s*", "", linea)
    texto_plano = re.sub(r"^-\s*", "", texto_plano)

    match_enlace = re.match(r"^\[([^\]]+)\]\([^)]+\)$", texto_plano.strip())
    if match_enlace:
        texto_plano = match_enlace.group(1)

    normalizado = normalizar_para_comparar(texto_plano)

    if normalizado in TEXTOS_BOILERPLATE:
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
    """Corta en cuanto aparece un titulo de pie/widget promocional
    ("Esto te interesa", "Recursos", "Instalaciones", "Media")."""
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


def limpiar_lineas_finales(lineas: list[str], recortar_h1: bool = True) -> list[str]:
    if recortar_h1:
        lineas = recortar_desde_primer_h1(lineas)
    lineas = recortar_en_titulo_plantilla(lineas)
    lineas = [linea for linea in lineas if not es_linea_boilerplate(linea)]
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


def obtener_enlaces_hijos(contenedor, url_pagina: str, maximo: int = MAX_ENLACES_HIJOS) -> list[tuple[str, str]]:
    enlaces, urls_vistas = [], set()
    for a in contenedor.find_all("a", href=True):
        href = a["href"]
        if not es_url_valida_para_expandir(href, url_pagina, urls_vistas):
            continue
        absoluta = urljoin(url_pagina, href).split("#")[0]
        texto = extraer_texto_limpio(a)
        if not texto:
            continue
        urls_vistas.add(absoluta)
        enlaces.append((texto, absoluta))
        if len(enlaces) >= maximo:
            break
    return enlaces


def resumir_pagina_hija(url: str) -> str | None:
    """Descarga una pagina hija y devuelve un fragmento corto de su
    contenido, o None si no se puede."""
    try:
        soup, es_html = descargar_soup(url)
        if not es_html:
            return None
        soup = limpiar_contenido_html(soup)
        contenedor = soup.find(id="smooth-wrapper") or soup.find("main") or soup.body
        if contenedor is None:
            return None

        lineas = limpiar_lineas_finales(extraer_bloques_contenido(contenedor, url))
        fragmento = "\n\n".join(lineas)
        if len(fragmento) > MAX_CARACTERES_FRAGMENTO_HIJO:
            fragmento = fragmento[:MAX_CARACTERES_FRAGMENTO_HIJO].rstrip() + "…"
        return fragmento or None
    except Exception:
        return None


def generar_yaml_metadatos(seccion_id: str, recurso: dict, tipo_documento: str = "recurso") -> str:
    campos = [
        ("fuente", FUENTE),
        ("categoria", CATEGORIA),
        ("nivel", NIVEL),
        ("tipo_documento", tipo_documento),
        ("tipo_recurso", "informacion"),
        ("padre", PADRE_SLUG),
        ("seccion", seccion_id),
        ("url", recurso.get("url", "")),
    ]
    lineas = [f"{clave}: {valor}" for clave, valor in campos]
    return "---\n" + "\n\n".join(lineas) + "\n---\n"


def nombre_archivo_markdown(titulo: str) -> str:
    return normalizar_identificador(titulo) + ".md"


def generar_markdown_recurso(recurso: dict, carpeta: Path, seccion_id: str) -> bool:
    titulo = recurso.get("titulo", "")
    url = recurso.get("url", "")
    if not titulo or not url:
        return False

    print(f"  Extrayendo: {titulo} ({url})")

    try:
        soup, es_html = descargar_soup(url)
        yaml_metadatos = generar_yaml_metadatos(seccion_id, recurso)

        if not es_html:
            markdown = (
                f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n"
                "_Este recurso no es una página HTML estándar "
                "(por ejemplo, un PDF o un vídeo). "
                "Consulta el contenido directamente en la URL indicada._\n"
            )
            ruta_archivo = carpeta / nombre_archivo_markdown(titulo)
            with open(ruta_archivo, "w", encoding="utf-8") as archivo:
                archivo.write(markdown)
            print(f"  OK (no HTML): {ruta_archivo}")
            return True

        soup = limpiar_contenido_html(soup)
        contenido = soup.find(id="smooth-wrapper") or soup.find("main") or soup.body
        if contenido is None:
            print("  AVISO: no se ha encontrado contenido.")
            return False

        lineas_contenido = limpiar_lineas_finales(extraer_bloques_contenido(contenido, url))
        if not lineas_contenido:
            print("  AVISO: contenido vacío.")
            return False

        if contar_palabras(lineas_contenido) < UMBRAL_PALABRAS_POCO_CONTENIDO:
            enlaces_hijos = obtener_enlaces_hijos(contenido, url)
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

        ruta_archivo = carpeta / nombre_archivo_markdown(titulo)
        with open(ruta_archivo, "w", encoding="utf-8") as archivo:
            archivo.write(markdown)
        print(f"  OK: {ruta_archivo}")
        return True

    except Exception as error:
        print(f"  ERROR: {error}")
        return False


def generar_markdowns_recursos(json_institucion: dict, carpetas: dict[str, Path] = INSTITUCION_CARPETAS) -> tuple[int, int, int]:
    total = correctos = errores = 0

    for seccion in json_institucion.get("secciones", []):
        seccion_id = seccion.get("id", "")
        carpeta = carpetas.get(seccion_id)
        if carpeta is None:
            print(f"AVISO: no existe carpeta para id '{seccion_id}'")
            continue

        carpeta.mkdir(parents=True, exist_ok=True)
        print(f"[{seccion['titulo']}]")

        for recurso in seccion.get("elementos", []):
            total += 1
            if generar_markdown_recurso(recurso, carpeta, seccion_id):
                correctos += 1
            else:
                errores += 1

    return total, correctos, errores


def generar_markdown_padre(url_raiz: str = INSTITUCION_URL_RAIZ, ruta: Path = INSTITUCION_MD_PADRE) -> str:
    soup, es_html = descargar_soup(url_raiz)
    soup = limpiar_contenido_html(soup)

    contenedor = soup.find(id="smooth-wrapper")
    if contenedor is None:
        raise Exception("No se ha encontrado #smooth-wrapper.")

    lineas_contenido = limpiar_lineas_finales(extraer_bloques_contenido(contenedor, url_raiz), recortar_h1=False)
    resultado = [limpiar_texto(linea) for linea in lineas_contenido if limpiar_texto(linea)]

    yaml_metadatos = generar_yaml_metadatos(seccion_id="", recurso={"url": url_raiz}, tipo_documento="padre")
    markdown = f"{yaml_metadatos}\n# La institución\n\n" + "\n\n".join(resultado) + "\n"

    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as archivo:
        archivo.write(markdown)
    print("OK: Markdown padre generado:", ruta)
    return markdown


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    datos = extraer_estructura()
    guardar_json(datos)
    generar_markdown_padre()
    total, correctos, errores = generar_markdowns_recursos(datos)
    print(f"Recursos: {total} · generados: {correctos} · errores: {errores}")


if __name__ == "__main__":
    main()
