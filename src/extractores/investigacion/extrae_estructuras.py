"""Extractor de "Estructuras de investigacion" (investigacion/estructuras).

Hueco vacio del sitemap (solo `.gitkeep`, sin contenido ni extractor
previo). Descubrimiento de la estructura real (sesion 2026-08-23,
comprobado contra la web real):

- `investigacion/estructuras/index-es.html` agrupa el contenido en 6
  bloques bajo <h3>: "Departamentos universitarios", "Institutos
  universitarios de investigacion", "Estructuras propias de
  investigacion", "Unidades de investigacion conjunta (UIC)",
  "Institutos y centros de investigacion por areas de trabajo" y
  "Estructuras de apoyo a la investigacion". Los primeros cinco NO
  traen un listado de enlaces: cada uno trae UN UNICO enlace "Ver X"/
  "Buscar por area de trabajo" -- y los tres del medio (institutos,
  centros, UIC) llevan a `buscador-estructuras-es.html`, un buscador en
  JavaScript SIN contenido estatico. Inspeccionando sus peticiones de
  red aparece `https://www.upv.es/courses/institutos-es.json`, el
  catalogo estatico que alimenta ese buscador (67 institutos/centros/
  UIC, ya con `tipo`/`area`/`web` estructurados, mismo patron que
  courses/grados-es.json) -- evita depender del buscador JS por
  completo. Solo "Estructuras de apoyo a la investigacion" trae 5
  enlaces reales directamente en el propio HTML.
- El catalogo trae 7 `tipo` distintos (IUP/IUM/CPI/IMI/CII/OEI/UIC), pero
  el index-es.html solo enlaza 3 combinaciones: IUP+IUM ("Institutos
  universitarios"), CPI+IMI+CII ("Estructuras propias"/centros) y UIC
  -- el 7º tipo, OEI ("Otras entidades de investigacion", 5 items), no
  esta enlazado desde ningun sitio del index y se descarta.
- "Departamentos universitarios" enlaza literalmente a
  `/organizacion/departamentos/index-es.html` -- el mismo indice que ya
  cubre `organizacion/departamentos` por completo. Decision explicita de
  Miguel (2026-08-23): no duplicar, el resumen de esta seccion referencia
  el documento real ya existente en vez de generar una copia.
- De los 5 enlaces reales de "Estructuras de apoyo a la investigacion",
  3 (Microscopia Electronica/SME, I2T, Servicio de Investigacion
  Aerodinamica/SIA) ya estan cubiertos en `servicios/` -- comprobado
  cruzando el codigo de entidad de cada URL contra los `url:` YAML ya
  comiteados en servicios/organizacion/institucion. Mismo criterio que
  departamentos: no duplicar, solo referenciar. Solo se generan fichas
  nuevas para los 2 que de verdad no estan cubiertos en ningun otro
  sitio (Servicio de Radiaciones/SR, Servicio de Gestion de la
  I+D+i/CTT).
- El widget final "Sabias que..." (datos institucionales genericos:
  presupuesto, tasas de exito, sostenibilidad...) no es un titulo real
  (no hay ningun <h2>/<h3> que lo preceda, a diferencia de "!Esto te
  interesa!" que si corta motor_limpieza.recortar_en_titulo_plantilla())
  -- se trunca aparte, de forma local a este extractor.
- Las fichas de cada institutos/centro/UIC son heterogeneas (mismo
  patron ya conocido: WordPress moderno / clasico con iframe / clasico
  sin iframe), asi que se reutiliza el mismo patron de
  generar_markdown_recurso() ya validado en institucion/servicios.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/ (config.py, common.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # src/extractores/ (motor_limpieza.py)

from bs4 import BeautifulSoup
import requests

from common import limpiar_texto
from config import ESTRUCTURAS_CARPETAS, ESTRUCTURAS_CATALOGO_URL, ESTRUCTURAS_DIR, ESTRUCTURAS_JSON, ESTRUCTURAS_URL
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
CATEGORIA = "investigacion"
NIVEL = "estructuras"
TIPO_RECURSO = "informacion"
RESUMEN_URL = ESTRUCTURAS_URL

UMBRAL_PALABRAS_POCO_CONTENIDO = 60
MAX_ENLACES_HIJOS = 5
MAX_CARACTERES_FRAGMENTO_HIJO = 800

TEXTOS_BOILERPLATE_ESTRUCTURAS = ml.TEXTOS_BOILERPLATE_BASE | ml.TEXTOS_BOILERPLATE_PLANTILLA_CLASICA

# tipo (del catalogo institutos-es.json) -> carpeta. OEI deliberadamente
# fuera: no esta enlazado desde ningun sitio de index-es.html (ver
# cabecera del modulo).
CARPETA_POR_TIPO = {
    "IUP": "institutos_investigacion", "IUM": "institutos_investigacion",
    "CPI": "centros_investigacion", "IMI": "centros_investigacion", "CII": "centros_investigacion",
    "UIC": "uic",
}

# Estructuras de apoyo a la investigacion enlazadas directamente desde
# index-es.html (no vienen del catalogo JSON). Las 3 marcadas como
# duplicadas ya tienen ficha real en servicios/ -- comprobado cruzando
# el codigo de entidad de su URL contra los `url:` ya comiteados alli;
# no se regeneran aqui, solo se referencian desde el resumen.
ESTRUCTURAS_APOYO = [
    {"titulo": "Microscopía Electrónica", "url": "https://www.upv.es/entidades/SME/index-es.html",
     "duplicado_en": "https://www.upv.es/entidades/SME/index-es.html"},
    {"titulo": "Servicio de Radiaciones", "url": "https://www.upv.es/entidades/SR/index-es.html",
     "duplicado_en": None},
    {"titulo": "Servicio de Investigación Aerodinámica", "url": "https://www.upv.es/entidades/SIA/index-es.html",
     "duplicado_en": "https://www.upv.es/entidades/SIA/index-es.html"},
    {"titulo": "Servicio de Promoción y Apoyo a la Investigación, Innovación y Transferencia",
     "url": "https://www.upv.es/entidades/I2T/indexc.html",
     "duplicado_en": "https://www.upv.es/entidades/I2T/indexc.html"},
    {"titulo": "Servicio de Gestión de la I+D+i", "url": "https://www.upv.es/entidades/CTT/indexc.html",
     "duplicado_en": None},
]

URL_DEPARTAMENTOS_RESUMEN = "https://www.upv.es/organizacion/departamentos/index-es.html"


def _yaml_recurso(item: dict, seccion: str) -> str:
    campos_extra = {"acronimo": item["acronimo"]}
    if item.get("tipo_nombre"):
        campos_extra["tipo_estructura"] = item["tipo_nombre"]
    if item.get("area_nombre"):
        campos_extra["area"] = item["area_nombre"]
    return ml.generar_yaml_metadatos(
        fuente=FUENTE, url=item["url"], categoria=CATEGORIA, nivel=NIVEL,
        tipo_documento="recurso", tipo_recurso=TIPO_RECURSO,
        resumen=RESUMEN_URL, seccion=seccion, titulo=item["titulo"],
        campos_extra=campos_extra)


# ==========================================================
# 1. Catalogo -- JSON estatico (institutos/centros/UIC) + 5 enlaces
#    directos de "Estructuras de apoyo"
# ==========================================================

def extraer_catalogo() -> dict:
    respuesta = requests.get(ESTRUCTURAS_CATALOGO_URL, headers=HEADERS, timeout=30)
    respuesta.raise_for_status()
    datos = respuesta.json()

    tipos_por_codigo = {t["tipo"]: limpiar_texto(t["nombre"]) for t in datos.get("tipos", [])}
    areas_por_id = {a["area"]: limpiar_texto(a["nombre"]) for a in datos.get("areas", [])}

    secciones: dict[str, list[dict]] = {"institutos_investigacion": [], "centros_investigacion": [], "uic": []}
    for i in datos.get("institutos", []):
        carpeta = CARPETA_POR_TIPO.get(i.get("tipo"))
        if carpeta is None:
            continue  # OEI, sin enlace desde index-es.html
        acronimo = i.get("acronimo", "").strip()
        web = i.get("web", "").strip()
        if not acronimo or not web:
            continue
        secciones[carpeta].append({
            "acronimo": acronimo,
            "titulo": limpiar_texto(i.get("nombre", "")),
            "url": ml.normalizar_url(web, ESTRUCTURAS_URL).rstrip("/") + "/",
            "tipo_nombre": tipos_por_codigo.get(i.get("tipo"), ""),
            "area_nombre": areas_por_id.get(i.get("area"), "") if i.get("area") else "",
        })

    for seccion, items in secciones.items():
        print(f"[{seccion}] {len(items)} entidades")

    apoyo_nuevos = [
        {"acronimo": re.search(r"/entidades/([A-Za-z0-9_\-]+)", e["url"]).group(1).upper(),
         "titulo": e["titulo"], "url": e["url"]}
        for e in ESTRUCTURAS_APOYO if e["duplicado_en"] is None
    ]
    secciones["estructuras_apoyo"] = apoyo_nuevos
    print(f"[estructuras_apoyo] {len(apoyo_nuevos)} entidades nuevas ({len(ESTRUCTURAS_APOYO) - len(apoyo_nuevos)} ya cubiertas en servicios/, no se duplican)")

    return secciones


def guardar_json(secciones: dict, ruta: Path = ESTRUCTURAS_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(secciones, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


# ==========================================================
# 2. Markdown por entidad -- mismo patron heterogeneo que
#    institucion/servicios (moderno / clasico con iframe / clasico sin
#    iframe / PDF / otro), reutilizado casi verbatim.
# ==========================================================

def obtener_enlaces_hijos(contenedor, url_pagina: str, maximo: int = MAX_ENLACES_HIJOS,
                           excluir: set[str] = frozenset()) -> list[tuple[str, str]]:
    candidatos, urls_vistas = [], set(excluir)
    for a in contenedor.find_all("a", href=True):
        href = a["href"]
        if not ml.es_url_valida_para_expandir(href, url_pagina, urls_vistas):
            continue
        texto = ml.extraer_texto_limpio(a)
        if not texto or len(texto.strip()) <= 2:
            continue
        absoluta = urljoin(url_pagina, href).split("#")[0]
        urls_vistas.add(absoluta)
        candidatos.append((texto, absoluta))
        if len(candidatos) >= maximo:
            break
    return candidatos


def resumir_pagina_hija(url: str) -> str | None:
    try:
        soup, es_html = ml.descargar_soup(url, headers=HEADERS)
        if not es_html:
            return None
        soup = ml.limpiar_contenido_html(soup)
        contenedor = soup.find(id="smooth-wrapper") or soup.find("main") or soup.body
        if contenedor is None:
            return None
        ml.reemplazar_tablas_por_listas(soup, contenedor)
        lineas = ml.limpiar_lineas_finales(ml.extraer_bloques_contenido(contenedor, url),
                                            textos_boilerplate=TEXTOS_BOILERPLATE_ESTRUCTURAS)
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
    lineas = ml.limpiar_lineas_finales(lineas, textos_boilerplate=TEXTOS_BOILERPLATE_ESTRUCTURAS, recortar_h1=False)
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
        "_Este recurso no es una página HTML ni un PDF estándar. Consulta el contenido directamente en la URL indicada._\n"
    )


def generar_markdown_recurso(item: dict, carpeta: Path, seccion: str) -> bool:
    titulo, url, acronimo = item["titulo"], item["url"], item["acronimo"]
    print(f"  Extrayendo: {titulo} ({acronimo})")

    try:
        respuesta = requests.get(url, headers=HEADERS, timeout=30)
        respuesta.raise_for_status()
        tipo = ml.tipo_contenido(respuesta.headers.get("Content-Type", ""))
        yaml_metadatos = _yaml_recurso(item, seccion)

        if tipo != "html":
            markdown = markdown_recurso_no_html(yaml_metadatos, titulo, url, tipo, respuesta.content)
            ruta = carpeta / f"{acronimo.lower()}.md"
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(markdown)
            print(f"  OK ({tipo}): {ruta}")
            return True

        soup = BeautifulSoup(respuesta.text, "html.parser")
        soup = ml.limpiar_contenido_html(soup)
        contenedor_moderno = soup.find(id="smooth-wrapper") or soup.find("main")
        # Cuarta variante de plantilla clasica ya documentada en
        # las notas internas del proyecto ("#contenido sin iframe", ej. VALGRAI): sin este
        # fallback explicito a #contenido, caer directo a soup.body
        # arrastra tambien el menu/cabecera de la plantilla clasica
        # (que no usa <header>/<nav>, asi que limpiar_contenido_html no
        # lo filtra) -- bug real encontrado probando este extractor,
        # visto como enlaces sueltos "Como llegar"/"Planos" colandose en
        # una seccion sin relacion.
        contenido = contenedor_moderno or soup.find(id="contenido") or soup.body
        if contenido is None:
            print("  AVISO: no se ha encontrado contenido.")
            return False

        lineas_iframe, iframe_url = ([], None) if contenedor_moderno is not None else extraer_contenido_iframe_clasico(soup, url)

        ml.reemplazar_tablas_por_listas(soup, contenido)
        lineas_contenido = ml.extraer_bloques_contenido(contenido, url)
        lineas_contenido = ml.limpiar_lineas_finales(lineas_contenido, textos_boilerplate=TEXTOS_BOILERPLATE_ESTRUCTURAS)
        lineas_contenido = lineas_iframe + lineas_contenido
        lineas_contenido = ml.quitar_titulos_redundantes(lineas_contenido, titulo)

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
        ruta = carpeta / f"{acronimo.lower()}.md"
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(markdown)
        print(f"  OK: {ruta}")
        return True

    except Exception as error:
        print(f"  ERROR: {error}")
        return False


def generar_markdowns_recursos(secciones: dict, carpetas: dict[str, Path] = ESTRUCTURAS_CARPETAS) -> tuple[int, int, int]:
    total = correctos = errores = 0
    for seccion, items in secciones.items():
        carpeta = carpetas[seccion]
        carpeta.mkdir(parents=True, exist_ok=True)
        for item in items:
            total += 1
            if generar_markdown_recurso(item, carpeta, seccion):
                correctos += 1
            else:
                errores += 1
            time.sleep(0.3)
    return total, correctos, errores


# ==========================================================
# 3. Markdown resumen (indice) -- a partir del contenido real de
#    index-es.html, con las secciones ya cubiertas en otro sitio
#    (departamentos, 3/5 de estructuras de apoyo) referenciando el
#    documento real en vez de duplicarlo.
# ==========================================================

PATRON_LINEA_ENLACE = re.compile(r"^-?\s*\[([^\]]+)\]\(([^)]+)\)\s*$")


def dividir_bloques_h3(lineas: list[str]) -> list[dict]:
    bloques = [{"titulo": None, "lineas": []}]
    for linea in lineas:
        if linea.startswith("### "):
            bloques.append({"titulo": linea[4:].strip(), "lineas": []})
        else:
            bloques[-1]["lineas"].append(linea)
    return bloques


def generar_markdown_resumen() -> str:
    soup, es_html = ml.descargar_soup(ESTRUCTURAS_URL, headers=HEADERS)
    soup = ml.limpiar_contenido_html(soup)
    contenedor = soup.find("main") or soup.find(id="smooth-wrapper")
    if contenedor is None:
        raise Exception("No se ha encontrado el contenedor principal.")

    ml.reemplazar_tablas_por_listas(soup, contenedor)
    lineas = ml.extraer_bloques_contenido(contenedor, ESTRUCTURAS_URL)
    lineas = ml.limpiar_lineas_finales(lineas)

    # El widget final "Sabias que..." (datos institucionales genericos)
    # no tiene ningun titulo real por delante que motor_limpieza sepa
    # cortar -- se trunca a mano en cuanto aparece.
    for indice, linea in enumerate(lineas):
        if ml.normalizar_para_comparar(linea) == "sabias que":
            lineas = lineas[:indice]
            break

    bloques = dividir_bloques_h3(lineas)
    cuerpo = []
    for bloque in bloques:
        if bloque["titulo"] is None:
            cuerpo.extend(bloque["lineas"])
            continue
        cuerpo.append(f"### {bloque['titulo']}")
        cuerpo.extend(bloque["lineas"])
        if ml.normalizar_para_comparar(bloque["titulo"]) == "departamentos universitarios":
            cuerpo.append(
                f"_Ya cubierto por completo en `organizacion/departamentos` -- "
                f"ver [Departamentos]({URL_DEPARTAMENTOS_RESUMEN})._"
            )
        elif ml.normalizar_para_comparar(bloque["titulo"]) == "estructuras de apoyo a la investigacion":
            duplicados = [e for e in ESTRUCTURAS_APOYO if e["duplicado_en"]]
            if duplicados:
                lista = "; ".join(f"[{e['titulo']}]({e['url']})" for e in duplicados)
                cuerpo.append(f"_{lista} ya están cubiertos en `servicios/`, no se duplican aquí._")

    yaml_metadatos = ml.generar_yaml_metadatos(
        fuente=FUENTE, url=ESTRUCTURAS_URL, categoria=CATEGORIA, nivel=NIVEL,
        tipo_documento="resumen", titulo="Estructuras de investigación")
    return f"{yaml_metadatos}\n" + "\n\n".join(cuerpo) + "\n"


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    secciones = extraer_catalogo()
    guardar_json(secciones)

    ESTRUCTURAS_DIR.mkdir(parents=True, exist_ok=True)
    with open(ESTRUCTURAS_DIR / "estructuras.md", "w", encoding="utf-8") as f:
        f.write(generar_markdown_resumen())

    total, correctos, errores = generar_markdowns_recursos(secciones)
    print(f"Estructuras de investigación: {total} · generados: {correctos} · errores: {errores}")


if __name__ == "__main__":
    main()
