"""Extractor de "Sostenibilidad" (organizacion/sostenibilidad).

Hueco vacio del sitemap (solo `.gitkeep`, sin contenido ni extractor
previo). Caso distinto a todos los anteriores: la pagina real
(`organizacion/sostenibilidad/index-es.html` redirige a
`https://futuritat.webs.upv.es/sostenibilidad/`, un microsite WordPress
con tema "uicore") es una SPA -- via `requests` (sin ejecutar JS)
devuelve el MISMO contenido para cualquier ruta del sitio, incluida la
portada: una pagina generica "Resultado de la busqueda: 2027" sin
relacion con el contenido real, confirmado tambien en `/es/` y
`/en/home-en/`. El contenido real son dos columnas -- "Informes" (~24
PDF/paginas) y "Servicios UPV" (8 items, 4 sin enlace propio, solo
texto) -- que solo aparecen tras ejecutar JS.

Inspeccionado con un navegador real (sesion 2026-08-24), via
`document.querySelectorAll('a[href]')`: no hay ningun endpoint JSON
equivalente a `courses/grados-es.json`/`courses/institutos-es.json` que
se pueda usar en su lugar (a diferencia de estudios/grado, estudios/
master e investigacion/estructuras, donde SI existia un catalogo
estatico detras de una SPA). Como el proyecto no tiene Playwright/
Selenium instalado (solo contemplado para un posible crawler generico
futuro, no forma parte del entorno actual), el catalogo de esta
seccion se fija a mano -- mismo criterio ya usado en
`ESTRUCTURAS_APOYO` de extrae_estructuras.py o las secciones de
`becas_ayudas` de extrae_estudiante.py: no descubierto en cada
ejecucion, pero auditable (lista exacta de titulo+URL documentada
abajo, capturada en vivo). Cada ENLACE individual (el contenido real a
extraer) SI es una pagina/PDF normal sin JS -- solo el indice
necesitaba el navegador.

Cruzando la URL exacta de cada uno de los 29 enlaces reales contra el
resto del corpus ya comiteado, 4 resultaron ser duplicados exactos de
contenido ya cubierto (mismo criterio ya establecido en
investigacion/estructuras: no duplicar, referenciar el documento real
desde el resumen en vez de regenerarlo):
- "Plan Estratégico UPV 2023-2027" -> ya en
  `institucion/estrategia_upv_sirve/plan_sirve_upv_2023_2027.md`.
- "Informes rendición de cuentas" -> ya en
  `institucion/publicaciones_oficiales/cuentas_anuales.md`.
- "Unidad de Medioambiente" -> ya en `servicios/medioambiente_amapuoc.md`.
- "Centro de Cooperación al Desarrollo" -> ya en
  `servicios/cooperacion_al_desarrollo_ccd.md`.

El resto (22 informes + 3 servicios) son URLs nuevas, aunque varias
pertenezcan a una entidad ya cubierta en otro sitio del corpus (ej. la
memoria del CFP es un PDF distinto de la ficha ya extraida de
`servicios/centro_de_formacion_permanente_cfp.md` -- documento
diferente, no se descarta solo por pertenecer a la misma entidad). Los
4 servicios sin enlace propio (Unidad de Igualdad, Servicio de
Alumnado, Área de Comunicación, Área Acción Cultural -- confirmado
inspeccionando el DOM que son texto plano sin ningun `<a>` ni
`onclick` en toda la cadena de ancestros) se listan tal cual en el
resumen, sin enlace, en vez de inventar uno.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/ (config.py, common.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # src/extractores/ (motor_limpieza.py)

from bs4 import BeautifulSoup
import requests

from common import limpiar_texto
from config import SOSTENIBILIDAD_CARPETAS, SOSTENIBILIDAD_DIR, SOSTENIBILIDAD_JSON, SOSTENIBILIDAD_URL
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
CATEGORIA = "organizacion"
NIVEL = "sostenibilidad"
TIPO_RECURSO = "informacion"
RESUMEN_URL = SOSTENIBILIDAD_URL

UMBRAL_PALABRAS_POCO_CONTENIDO = 60
MAX_ENLACES_HIJOS = 5
MAX_CARACTERES_FRAGMENTO_HIJO = 800
TEXTOS_BOILERPLATE_SOSTENIBILIDAD = ml.TEXTOS_BOILERPLATE_BASE | ml.TEXTOS_BOILERPLATE_PLANTILLA_CLASICA

# Catalogo fijado a mano -- ver docstring del modulo. duplicado_en=URL
# del documento real ya existente en el corpus cuando el enlace es un
# duplicado exacto (no se genera fichero, solo se referencia desde el
# resumen).
INFORMES = [
    {"titulo": "Plan Estratégico UPV 2023-2027", "url": "https://www.upv.es/contenidos/upv_sirve/download/18245",
     "duplicado_en": "https://www.upv.es/contenidos/upv_sirve/download/18245"},
    {"titulo": "Declaración Ambiental 2024",
     "url": "https://riunet.upv.es/server/api/core/bitstreams/8acc2639-44fa-4c2e-9d8b-9fb7d58942f8/content", "duplicado_en": None},
    {"titulo": "Sistema de Gestión Ambiental",
     "url": "https://riunet.upv.es/server/api/core/bitstreams/0b5c2e7e-5de0-4350-9683-29f588d1dc2c/content", "duplicado_en": None},
    {"titulo": "Guías de Buenas Prácticas Ambientales",
     "url": "https://www.upv.es/entidades/amapuoc/download/18380", "duplicado_en": None},
    {"titulo": "Guía Gestión de Residuos UPV",
     "url": "https://www.upv.es/entidades/amapuoc/guia-de-residuos-2/", "duplicado_en": None},
    {"titulo": "Consumo de Recursos",
     "url": "https://www.upv.es/entidades/vcampus/consumo-de-recursos-en-la-upv/", "duplicado_en": None},
    {"titulo": "Memoria Cátedras de Empresa UPV",
     "url": "https://catedras.webs.upv.es/wp-content/uploads/2023/07/U0957001.pdf", "duplicado_en": None},
    {"titulo": "Política de Acceso Abierto. Editorial UPV",
     "url": "https://editorialupv.webs.upv.es/politica-acceso-abierto/", "duplicado_en": None},
    {"titulo": "Memoria Servicio de Biblioteca y Documentación Científica",
     "url": "https://riunet.upv.es/bitstream/handle/10251/199304/Memoria%20Biblioteca%202022%20Cast.pdf?sequence=1&isAllowed=y",
     "duplicado_en": None},
    {"titulo": "Memoria Acción Cultural",
     "url": "https://acts.webs.upv.es/docs/Memoria_curso_2023_2024_Accion_Cultural_red.pdf", "duplicado_en": None},
    {"titulo": "Memoria de Responsabilidad Social",
     "url": "https://riunet.upv.es/bitstream/handle/10251/165445/Memoria2020-UPV-Digital.pdf?sequence=3&isAllowed=y",
     "duplicado_en": None},
    {"titulo": "Memoria Centro de Formación Permanente",
     "url": "https://www.upv.es/entidades/CFP/info/910398normalc.html", "duplicado_en": None},
    {"titulo": "Actividad Docente e Investigadora",
     "url": "https://www.upv.es/entidades/vpt/informes-vpt/", "duplicado_en": None},
    {"titulo": "Informes de Resultados Programa Docentia",
     "url": "https://www.upv.es/entidades/aca/download/17472", "duplicado_en": None},
    {"titulo": "Manual de Calidad del SGCTI",
     "url": "https://www.upv.es/entidades/SA/ciclos/U0545220.pdf", "duplicado_en": None},
    {"titulo": "Informe de Resultados de I+D+i",
     "url": "https://innovacion.upv.es/es/cifras-idi-upv/", "duplicado_en": None},
    {"titulo": "Plan de Prevención de Riesgos Laborales",
     "url": "https://www.sprl.upv.es/pdf/Plan%20de%20prevenci%C3%B3n%20de%20riesgos%20laborales%20UPV.pdf", "duplicado_en": None},
    {"titulo": "Guía Universidades Saludables",
     "url": "https://www.upv.es/contenidos/USALUDABLE/", "duplicado_en": None},
    {"titulo": "Recomendaciones Salud Adulto Joven",
     "url": "https://www.upv.es/entidades/CSLJP/infoweb/gm/info/recomendacionesAdultoJoven.pdf", "duplicado_en": None},
    {"titulo": "III Plan de Igualdad",
     "url": "http://www.upv.es/pls/soarc/sic_prensa.GetFichero?p_id=580846&p_size=580&p_html=0&p_idioma=c&p_dossier=510344",
     "duplicado_en": None},
    {"titulo": "Código Ético",
     "url": "https://riunet.upv.es/bitstream/handle/10251/121576/C%c3%b3digo%20%c3%a9tico.pdf?sequence=2&isAllowed=y", "duplicado_en": None},
    {"titulo": "Protocolo de Atención a la Identidad y Expresión de Género",
     "url": "https://riunet.upv.es/bitstream/handle/10251/121573/Protocolo%20de%20atenci%c3%b3n%20a%20la%20identidad%20a%20la%20identidad%20y%20expresi%c3%b3n%20de%20g%c3%a9nero.pdf?sequence=1&isAllowed=y",
     "duplicado_en": None},
    {"titulo": "Protocolo de Actuación en los Supuestos de Acoso",
     "url": "https://riunet.upv.es/bitstream/handle/10251/121575/Protocolo%20de%20actuaci%c3%b3n%20en%20los%20supuestos%20de%20acoso.pdf?sequence=1&isAllowed=y",
     "duplicado_en": None},
    {"titulo": "Personas Trans: Identidad, Libertad y Respeto",
     "url": "https://riunet.upv.es/bitstream/handle/10251/138503/Puchades%3BCerd%C3%A1%3BSanz%20-%20Personas%20Trans%3A%20identidad%2C%20libertad%20y%20respeto.%20Gu%C3%ADa%20de%20buenas%20pr%C3%A1cticas.pdf?sequence=1",
     "duplicado_en": None},
    {"titulo": "Informes Rendición de Cuentas", "url": "https://www.upv.es/entidades/ger/cuentas-anuales/",
     "duplicado_en": "https://www.upv.es/entidades/ger/cuentas-anuales/"},
    {"titulo": "Estatutos de la UPV",
     "url": "https://www.upv.es/entidades/SG/infoweb/sg/info/1247892normalc.html", "duplicado_en": None},
    {"titulo": "Tablas Retributivas",
     "url": "https://futuritat.webs.upv.es/sostenibilidad/wp-content/uploads/2024/10/retribuciones-2023.pdf", "duplicado_en": None},
]

SERVICIOS = [
    {"titulo": "Unidad de Medioambiente", "url": "http://www.upv.es/entidades/AMAPUOC/index-es.html",
     "duplicado_en": "https://www.upv.es/entidades/AMAPUOC/index-es.html"},
    {"titulo": "Área de Transición Verde",
     "url": "https://www.upv.es/entidades/vcampus/area-de-transicion-verde/", "duplicado_en": None},
    {"titulo": "Servicio Integrado de Empleo", "url": "https://sie.webs.upv.es/es", "duplicado_en": None},
    {"titulo": "Centro de Cooperación al Desarrollo", "url": "https://www.upv.es/entidades/CCD/",
     "duplicado_en": "https://www.upv.es/entidades/CCD/index-es.html"},
    {"titulo": "Área de Acción Social",
     "url": "https://www.upv.es/entidades/vacts/area-de-accion-social/", "duplicado_en": None},
]

# Los 4 restantes de "Servicios UPV" no tienen ningun enlace propio en
# la pagina real (comprobado: solo texto plano, sin <a> ni onclick en
# toda la cadena de ancestros) -- se listan tal cual en el resumen.
SERVICIOS_SIN_ENLACE = ["Unidad de Igualdad", "Servicio de Alumnado", "Área de Comunicación", "Área Acción Cultural"]

INTRO_RESUMEN = (
    "Esta web recoge, a modo de espejo, iniciativas desarrolladas por la comunidad "
    "universitaria que reflejan el compromiso de la Universitat Politècnica de València "
    "con la sostenibilidad, organizadas en torno a las 5 esferas (5Ps) de los ODS "
    "(Prosperity, People, Planet, Peace, Partnerships)."
)


def _yaml_recurso(item: dict, seccion: str) -> str:
    return ml.generar_yaml_metadatos(
        fuente=FUENTE, url=item["url"], categoria=CATEGORIA, nivel=NIVEL,
        tipo_documento="recurso", tipo_recurso=TIPO_RECURSO,
        resumen=RESUMEN_URL, seccion=seccion, titulo=item["titulo"])


# ==========================================================
# 1. Catalogo -- fijado a mano (ver docstring del modulo)
# ==========================================================

def extraer_catalogo() -> dict:
    secciones = {
        "informes": [i for i in INFORMES if i["duplicado_en"] is None],
        "servicios": [s for s in SERVICIOS if s["duplicado_en"] is None],
    }
    for seccion, items in secciones.items():
        total_original = len(INFORMES) if seccion == "informes" else len(SERVICIOS)
        print(f"[{seccion}] {len(items)} nuevos ({total_original - len(items)} ya cubiertos en otra sección, no se duplican)")
    return secciones


def guardar_json(secciones: dict, ruta: Path = SOSTENIBILIDAD_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(secciones, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


# ==========================================================
# 2. Markdown por recurso -- mismo patron heterogeneo ya validado
#    (moderno / clasico con iframe / clasico sin iframe / PDF / otro)
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
        contenedor = soup.find(id="smooth-wrapper") or soup.find("main") or soup.find(id="contenido") or soup.body
        if contenedor is None:
            return None
        ml.reemplazar_tablas_por_listas(soup, contenedor)
        lineas = ml.limpiar_lineas_finales(ml.extraer_bloques_contenido(contenedor, url),
                                            textos_boilerplate=TEXTOS_BOILERPLATE_SOSTENIBILIDAD)
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
    lineas = ml.limpiar_lineas_finales(lineas, textos_boilerplate=TEXTOS_BOILERPLATE_SOSTENIBILIDAD, recortar_h1=False)
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
    titulo, url = item["titulo"], item["url"]
    print(f"  Extrayendo: {titulo} ({url})")

    try:
        respuesta = requests.get(url, headers=HEADERS, timeout=30)
        respuesta.raise_for_status()
        tipo = ml.tipo_contenido(respuesta.headers.get("Content-Type", ""))
        yaml_metadatos = _yaml_recurso(item, seccion)

        if tipo != "html":
            markdown = markdown_recurso_no_html(yaml_metadatos, titulo, url, tipo, respuesta.content)
            ruta = carpeta / ml.nombre_archivo_markdown(titulo)
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(markdown)
            print(f"  OK ({tipo}): {ruta}")
            return True

        soup = BeautifulSoup(respuesta.text, "html.parser")
        soup = ml.limpiar_contenido_html(soup)
        contenedor_moderno = soup.find(id="smooth-wrapper") or soup.find("main")
        contenido = contenedor_moderno or soup.find(id="contenido") or soup.body
        if contenido is None:
            print("  AVISO: no se ha encontrado contenido.")
            return False

        lineas_iframe, iframe_url = ([], None) if contenedor_moderno is not None else extraer_contenido_iframe_clasico(soup, url)

        ml.reemplazar_tablas_por_listas(soup, contenido)
        lineas_contenido = ml.extraer_bloques_contenido(contenido, url)
        lineas_contenido = ml.limpiar_lineas_finales(lineas_contenido, textos_boilerplate=TEXTOS_BOILERPLATE_SOSTENIBILIDAD)
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
        ruta = carpeta / ml.nombre_archivo_markdown(titulo)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(markdown)
        print(f"  OK: {ruta}")
        return True

    except Exception as error:
        print(f"  ERROR: {error}")
        return False


def generar_markdowns_recursos(secciones: dict, carpetas: dict[str, Path] = SOSTENIBILIDAD_CARPETAS) -> tuple[int, int, int]:
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
# 3. Markdown resumen (indice)
# ==========================================================

def generar_markdown_resumen() -> str:
    yaml_metadatos = ml.generar_yaml_metadatos(
        fuente=FUENTE, url=RESUMEN_URL, categoria=CATEGORIA, nivel=NIVEL,
        tipo_documento="resumen", titulo="Sostenibilidad")

    def _fila(item: dict) -> str:
        if item["duplicado_en"]:
            return f"- [{item['titulo']}]({item['url']}) — _ya cubierto en otra sección del corpus, no se duplica aquí._"
        return f"- [{item['titulo']}]({item['url']})"

    informes = "\n".join(_fila(i) for i in INFORMES)
    servicios = "\n".join(_fila(s) for s in SERVICIOS)
    servicios_sin_enlace = "\n".join(f"- {nombre} _(sin enlace propio en la página de origen)_" for nombre in SERVICIOS_SIN_ENLACE)

    cuerpo = (
        f"# Sostenibilidad\n\n{INTRO_RESUMEN}\n\n"
        f"### Informes\n\n{informes}\n\n"
        f"### Servicios UPV\n\n{servicios}\n{servicios_sin_enlace}\n"
    )
    return f"{yaml_metadatos}\n{cuerpo}"


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    secciones = extraer_catalogo()
    guardar_json(secciones)

    SOSTENIBILIDAD_DIR.mkdir(parents=True, exist_ok=True)
    with open(SOSTENIBILIDAD_DIR / "sostenibilidad.md", "w", encoding="utf-8") as f:
        f.write(generar_markdown_resumen())

    total, correctos, errores = generar_markdowns_recursos(secciones)
    print(f"Sostenibilidad: {total} · generados: {correctos} · errores: {errores}")


if __name__ == "__main__":
    main()
