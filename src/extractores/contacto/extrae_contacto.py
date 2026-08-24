"""Extractor de "Contacto" (categoria `contacto`, sin subcarpeta).

Hueco vacio del sitemap, sin extractor previo. A diferencia del resto de
secciones nuevas de esta semana, no hay catalogo que recorrer: son dos
paginas fijas, conocidas de antemano.

1. `otros/contacto-es.html` (resumen): pagina moderna WordPress con los
   datos de contacto de los 4 campus (Valencia, Alcoy, Gandia, Hangzhou)
   -- direccion, telefono/WhatsApp, enlace a Google/Baidu Maps y a la web
   propia de cada campus -- bajo un `<h2>` por campus. Se extrae tal cual
   con el motor generico (mismo patron que `institucion.md`), sin
   catalogo ni carpetas de recursos.
2. `noticias-upv/noticia-8492-policonsulta-es.html` (recurso): noticia
   real que explica que es poli[Consulta], la plataforma de la UPV para
   gestionar consultas online -- enlazada desde cada campus de
   `contacto.md` ("¿Tienes alguna duda...?"). Se genera como recurso
   propio de `contacto/` (sin subcarpeta), no como parte del resumen.

Sexta variante de plantilla real encontrada (primera vez que este
proyecto scrapea una URL `noticias-upv/`): el cuerpo real del articulo
vive en `#DIVpanelIZQN3` ("panel izquierda"), como hermano de un
`div.panelDERGradN3` ("panel derecha") con un widget de "Noticias
destacadas" -- enlaces a 5 noticias SIN relacion con el contenido del
articulo (rankings, ayudas de comedor...), contenido efimero que ya se
descarta explicitamente en esta categoria (ver las notas internas del proyecto, "Cobertura
del sitemap" -- `comunidad_upv/prensa` descartado por el mismo motivo).
Sin acotar a `#DIVpanelIZQN3`, ese widget se cuela como si fuera parte
del articulo. Como de momento es la unica pagina de este patron en todo
el corpus, se resuelve aqui (local a este extractor), no en
`motor_limpieza.py` -- promover si aparece una segunda seccion con el
mismo patron (mismo criterio ya aplicado con `.mwc_contenido`/
`#contenido` sin iframe).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/ (config.py, common.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # src/extractores/ (motor_limpieza.py)

from bs4 import BeautifulSoup
import requests

from config import CONTACTO_DIR, CONTACTO_JSON, CONTACTO_URL, POLICONSULTA_URL
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
CATEGORIA = "contacto"


def extraer_lineas_pagina(url: str) -> list[str]:
    soup, es_html = ml.descargar_soup(url, headers=HEADERS)
    if not es_html:
        raise Exception(f"No se pudo descargar como HTML: {url}")
    soup = ml.limpiar_contenido_html(soup)
    # #DIVpanelIZQN3 ("panel izquierda"): cuerpo real del articulo en la
    # plantilla de noticias-upv, sin el widget de "Noticias destacadas"
    # que vive al lado en .panelDERGradN3 -- ver docstring del modulo.
    contenedor = soup.find(id="DIVpanelIZQN3") or soup.find(id="smooth-wrapper") or soup.find("main")
    if contenedor is None:
        raise Exception(f"No se ha encontrado el contenedor principal en {url}")
    ml.reemplazar_tablas_por_listas(soup, contenedor)
    lineas = ml.extraer_bloques_contenido(contenedor, url)
    return ml.limpiar_lineas_finales(lineas)


def generar_markdown_resumen() -> str:
    lineas = extraer_lineas_pagina(CONTACTO_URL)
    yaml_metadatos = ml.generar_yaml_metadatos(
        fuente=FUENTE, url=CONTACTO_URL, categoria=CATEGORIA,
        tipo_documento="resumen", titulo="Contacto")
    return f"{yaml_metadatos}\n" + "\n\n".join(lineas) + "\n"


def generar_markdown_policonsulta() -> str:
    lineas = extraer_lineas_pagina(POLICONSULTA_URL)
    yaml_metadatos = ml.generar_yaml_metadatos(
        fuente=FUENTE, url=POLICONSULTA_URL, categoria=CATEGORIA,
        tipo_documento="recurso", tipo_recurso="servicio",
        resumen=CONTACTO_URL, seccion="policonsulta", titulo="poli[Consulta]")
    return f"{yaml_metadatos}\n" + "\n\n".join(lineas) + "\n"


def guardar_json() -> None:
    catalogo = {
        "resumen": {"titulo": "Contacto", "url": CONTACTO_URL},
        "recursos": [{"titulo": "poli[Consulta]", "url": POLICONSULTA_URL}],
    }
    CONTACTO_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(CONTACTO_JSON, "w", encoding="utf-8") as f:
        json.dump(catalogo, f, ensure_ascii=False, indent=2)
    print("JSON guardado:", CONTACTO_JSON)


def main() -> None:
    CONTACTO_DIR.mkdir(parents=True, exist_ok=True)
    guardar_json()

    with open(CONTACTO_DIR / "contacto.md", "w", encoding="utf-8") as f:
        f.write(generar_markdown_resumen())
    print("OK:", CONTACTO_DIR / "contacto.md")

    with open(CONTACTO_DIR / "policonsulta.md", "w", encoding="utf-8") as f:
        f.write(generar_markdown_policonsulta())
    print("OK:", CONTACTO_DIR / "policonsulta.md")


if __name__ == "__main__":
    main()
