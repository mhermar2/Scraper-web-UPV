"""Extractor de "Orientación" (categoría `orientacion`, sin subcarpeta).

Hueco vacío del sitemap, sin extractor previo. A diferencia de
`organizacion/{escuelas_facultades,departamentos}` (fichas-índice),
Miguel decidió que esta categoría se scrapea "con cierta profundidad" --
se sigue el contenido real de cada página enlazada, mismo estándar que
`comunidad_upv/estudiante`.

`contenidos/orienta/` es un microsite propio (plantilla WordPress
distinta de la de upv.es: `<main class="site-main">` con `<article>`,
sin `#smooth-wrapper`). Sus 6 enlaces reales no están en el cuerpo de la
página (`<main>` solo trae un hero con la última Jornada de Orientación)
sino en el mega-menú superior (`li.accessible-megamenu-top-nav-item`):

- 4 son páginas directas: "Actividades para secundaria", "Acciones
  para universitarios", "IA orientadora", "Jornadas de Puertas
  Abiertas".
- "Jornada de Orientación" es un desplegable con una edición por año
  (2025/2024/2023/anteriores) -- se coge siempre la PRIMERA (la más
  reciente, actualmente 2025), no una URL fija, para que la siguiente
  ejecución recoja sola la 2026 en cuanto la web la publique (petición
  explícita de Miguel).
- "Material informativo" es un desplegable sin página propia, solo 2
  hijas reales ("Material audiovisual", "Material impreso") -- decisión
  explícita de Miguel: fusionar ambas en un único `material_informativo.md`
  en vez de generar dos ficheros.

Dos quirks de plantilla encontrados al probar los recursos:
1. Mismo bug ya conocido de `<header class="entry-header">` envolviendo
   el `<h1>` real (visto antes en `estudios/doctorado` y
   `comunidad_upv/estudiante`) -- se usa el mismo patrón de
   `limpiar_pagina()` local que no decompone `<header>` globalmente.
2. Widget de "Compartir" (Facebook/X/WhatsApp...) que
   `extraer_bloques_contenido()` capta como una única línea larga
   ("Compartir : [Compartir Facebook](...)...") -- se filtra localmente
   por prefijo, primera vez que aparece en el corpus (no promovido a
   `motor_limpieza.py` todavía).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/ (config.py, common.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # src/extractores/ (motor_limpieza.py)

from bs4 import BeautifulSoup, Comment
import requests

from config import ORIENTACION_DIR, ORIENTACION_JSON, ORIENTACION_URL
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
CATEGORIA = "orientacion"
TIPO_RECURSO = "informacion"

# <a title="..."> del mega-menu -> slug del recurso.
ENLACES_DIRECTOS = {
    "Actividades para secundaria": "actividades_secundaria",
    "Acciones para universitarios": "acciones_universitarios",
    "IA orientadora": "ia_orientadora",
    "Jornadas de Puertas Abiertas": "jornadas_puertas_abiertas",
}


def limpiar_pagina(soup: BeautifulSoup) -> BeautifulSoup:
    """No se decompone <header> globalmente: esta plantilla WordPress
    envuelve el <h1> real en su propio <header class="entry-header">
    (mismo bug ya visto en estudios/doctorado y comunidad_upv/estudiante)."""
    for tag in soup.find_all(["script", "style", "noscript", "svg"]):
        tag.decompose()
    for comentario in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comentario.extract()
    return soup


def _filtrar_widget_compartir(lineas: list[str]) -> list[str]:
    return [l for l in lineas if not l.strip().lower().startswith("compartir :")]


# ==========================================================
# 1. Catalogo -- resuelto del mega-menu real, no fijado a mano (salvo
#    "Material informativo", sin pagina propia -- ver docstring)
# ==========================================================

def extraer_catalogo() -> dict:
    respuesta = requests.get(ORIENTACION_URL, headers=HEADERS, timeout=30)
    respuesta.raise_for_status()
    soup = BeautifulSoup(respuesta.text, "html.parser")

    recursos = {}
    pendientes = dict(ENLACES_DIRECTOS)
    for a in soup.find_all("a", href=True):
        titulo = a.get("title") or ""
        if titulo in pendientes and a["href"] not in ("", "#"):
            slug = pendientes.pop(titulo)
            recursos[slug] = {"titulo": titulo, "url": a["href"]}
    if pendientes:
        print("AVISO: no se encontraron en el mega-menu:", list(pendientes))

    material_informativo = None
    for li in soup.find_all("li", class_="folder-item"):
        encabezado = li.find("h2")
        enlace_encabezado = encabezado.find("a") if encabezado else None
        titulo_folder = (enlace_encabezado.get("title") if enlace_encabezado else "") or ""
        panel = li.find("div", class_="accessible-megamenu-panel")
        hijos = [
            (a.get_text(" ", strip=True), a["href"])
            for a in (panel.find_all("a", href=True) if panel else [])
        ]

        if titulo_folder == "Jornada de Orientación" and hijos:
            texto, url = hijos[0]  # el primero = la edicion mas reciente
            recursos["jornada_orientacion"] = {"titulo": texto, "url": url}
        elif titulo_folder == "Material informativo" and hijos:
            material_informativo = {"titulo": "Material informativo", "hijos": hijos}

    if material_informativo is None:
        print("AVISO: no se encontro el desplegable 'Material informativo'")

    return {"recursos": recursos, "material_informativo": material_informativo}


def guardar_json(catalogo: dict, ruta: Path = ORIENTACION_JSON) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(catalogo, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", ruta)


# ==========================================================
# 2. Markdown de cada recurso (mismo patron heterogeneo que
#    institucion/servicios: moderno / clasico con iframe / PDF / otro)
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
    lineas = ml.limpiar_lineas_finales(lineas)
    return _filtrar_widget_compartir(lineas)


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
        "_Este recurso no es una página HTML ni un PDF estándar. "
        "Consulta el contenido directamente en la URL indicada._\n"
    )


def _yaml_recurso(url: str, titulo: str, seccion: str) -> str:
    return ml.generar_yaml_metadatos(
        fuente=FUENTE, url=url, categoria=CATEGORIA, tipo_documento="recurso",
        tipo_recurso=TIPO_RECURSO, resumen=ORIENTACION_URL, seccion=seccion, titulo=titulo)


def generar_markdown_recurso_html_o_pdf(titulo: str, url: str, seccion: str) -> str | None:
    respuesta = requests.get(url, headers=HEADERS, timeout=30)
    respuesta.raise_for_status()
    tipo = ml.tipo_contenido(respuesta.headers.get("Content-Type", ""))
    yaml_metadatos = _yaml_recurso(url, titulo, seccion)

    if tipo != "html":
        return markdown_recurso_no_html(yaml_metadatos, titulo, url, tipo, respuesta.content)

    soup = BeautifulSoup(respuesta.text, "html.parser")
    soup = limpiar_pagina(soup)
    contenedor = soup.find(id="smooth-wrapper") or soup.find("main")
    if contenedor is None:
        return None
    ml.reemplazar_tablas_por_listas(soup, contenedor)
    lineas = ml.limpiar_lineas_finales(ml.extraer_bloques_contenido(contenedor, url))
    lineas = _filtrar_widget_compartir(lineas)
    lineas = ml.quitar_titulos_redundantes(lineas, titulo)
    if not lineas:
        return None
    return f"{yaml_metadatos}\n# {titulo}\n\n**URL:** {url}\n\n" + "\n\n".join(lineas) + "\n"


def _bajar_nivel_titulos(lineas: list[str]) -> list[str]:
    """Baja un nivel cualquier titulo Markdown (## -> ###, ### -> ####...)
    para que los titulos propios de una pagina hija no queden al mismo
    nivel que el titulo de bloque (## {texto_enlace}) bajo el que se
    fusiona -- evita ambiguedad de jerarquia al fusionar dos paginas en
    un unico documento (ver generar_markdown_material_informativo)."""
    return [f"#{l}" if l.startswith("#") else l for l in lineas]


def generar_markdown_material_informativo(material: dict) -> str | None:
    """Fusiona las dos paginas hijas (audiovisual + impreso) en un unico
    documento -- "Material informativo" no tiene pagina propia en la web
    real, solo el desplegable del mega-menu (decision explicita de
    Miguel: un solo .md en vez de dos)."""
    bloques = []
    for texto_enlace, url_hija in material["hijos"]:
        try:
            lineas = extraer_lineas_pagina(url_hija)
        except Exception as error:
            print(f"  AVISO: no se pudo extraer {texto_enlace} ({url_hija}): {error}")
            continue
        lineas = ml.quitar_titulos_redundantes(lineas, texto_enlace)
        lineas = _bajar_nivel_titulos(lineas)
        if lineas:
            bloques.append(f"## {texto_enlace}\n\n**URL:** {url_hija}\n\n" + "\n\n".join(lineas))
    if not bloques:
        return None
    yaml_metadatos = _yaml_recurso(ORIENTACION_URL, "Material informativo", "material_informativo")
    return f"{yaml_metadatos}\n# Material informativo\n\n" + "\n\n".join(bloques) + "\n"


def generar_markdowns_recursos(catalogo: dict) -> tuple[int, int, int]:
    total = correctos = errores = 0
    for slug, recurso in catalogo["recursos"].items():
        total += 1
        titulo, url = recurso["titulo"], recurso["url"]
        print(f"  Extrayendo: {titulo} ({url})")
        try:
            markdown = generar_markdown_recurso_html_o_pdf(titulo, url, slug)
            if markdown is None:
                print("  AVISO: contenido vacío.")
                errores += 1
                continue
            ruta = ORIENTACION_DIR / ml.nombre_archivo_markdown(titulo)
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(markdown)
            print(f"  OK: {ruta}")
            correctos += 1
        except Exception as error:
            print(f"  ERROR: {error}")
            errores += 1

    if catalogo["material_informativo"] is not None:
        total += 1
        print("  Extrayendo: Material informativo (fusion de 2 paginas)")
        try:
            markdown = generar_markdown_material_informativo(catalogo["material_informativo"])
            if markdown is None:
                print("  AVISO: contenido vacío.")
                errores += 1
            else:
                ruta = ORIENTACION_DIR / "material_informativo.md"
                with open(ruta, "w", encoding="utf-8") as f:
                    f.write(markdown)
                print(f"  OK: {ruta}")
                correctos += 1
        except Exception as error:
            print(f"  ERROR: {error}")
            errores += 1

    return total, correctos, errores


# ==========================================================
# 3. Markdown resumen (indice)
# ==========================================================

def generar_markdown_resumen(catalogo: dict) -> str:
    yaml_metadatos = ml.generar_yaml_metadatos(
        fuente=FUENTE, url=ORIENTACION_URL, categoria=CATEGORIA,
        tipo_documento="resumen", titulo="Orientación")

    cuerpo = (
        "Punto de entrada de ORIENTA, el portal de orientación preuniversitaria y "
        "vocacional de la UPV: actividades para centros de secundaria, acciones para "
        "estudiantes universitarios, un asistente de IA orientador, Jornadas de Puertas "
        "Abiertas, la Jornada de Orientación anual (dirigida a personal orientador y "
        "tutor) y material informativo descargable."
    )

    filas = []
    for recurso in catalogo["recursos"].values():
        filas.append(f"- [{recurso['titulo']}]({recurso['url']})")
    if catalogo["material_informativo"] is not None:
        filas.append("- **Material informativo** — " + ", ".join(
            f"[{texto}]({url})" for texto, url in catalogo["material_informativo"]["hijos"]))

    return f"{yaml_metadatos}\n# Orientación\n\n{cuerpo}\n\n" + "\n\n".join(filas) + "\n"


# ==========================================================
# Ejecucion
# ==========================================================

def main() -> None:
    catalogo = extraer_catalogo()
    guardar_json(catalogo)

    ORIENTACION_DIR.mkdir(parents=True, exist_ok=True)
    with open(ORIENTACION_DIR / "orientacion.md", "w", encoding="utf-8") as f:
        f.write(generar_markdown_resumen(catalogo))
    print("OK:", ORIENTACION_DIR / "orientacion.md")

    total, correctos, errores = generar_markdowns_recursos(catalogo)
    print(f"Orientación: {total} · generados: {correctos} · errores: {errores}")


if __name__ == "__main__":
    main()
