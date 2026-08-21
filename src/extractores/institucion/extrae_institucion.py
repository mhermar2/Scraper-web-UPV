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

La logica de limpieza/generacion de Markdown (traversal por "hoja de
contenido", filtrado de boilerplate, metadatos YAML) esta en
motor_limpieza.py: al migrar extrae_servicios.ipynb se vio que duplicaba
casi identica esta misma logica, asi que se extrajo a un modulo comun
(ver motor_limpieza.py) del que institucion y servicios importan.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # src/ (config.py, common.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # src/extractores/ (motor_limpieza.py)

from bs4 import BeautifulSoup
import requests

from common import limpiar_texto
from config import INSTITUCION_CARPETAS, INSTITUCION_JSON, INSTITUCION_MD_PADRE, INSTITUCION_URL_RAIZ
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
CATEGORIA = "institucion"
TIPO_RECURSO = "informacion"

UMBRAL_PALABRAS_POCO_CONTENIDO = 60
MAX_ENLACES_HIJOS = 5
MAX_CARACTERES_FRAGMENTO_HIJO = 800

# Institucion tambien puede encontrarse con la plantilla clasica de
# fichas de entidad en /entidades/<CODIGO>/ (ver las notas internas del proyecto "Quirks
# conocidos de upv.es") -- amplia el set base con esos terminos, igual
# que hace servicios.
TEXTOS_BOILERPLATE_INSTITUCION = ml.TEXTOS_BOILERPLATE_BASE | ml.TEXTOS_BOILERPLATE_PLANTILLA_CLASICA

CONFIG_SECCIONES = {
    "Organos de gobierno": {"titulo": "Órganos de gobierno", "tipo": "organos_gobierno"},
    "Publicaciones oficiales": {"titulo": "Publicaciones oficiales", "tipo": "publicaciones_oficiales"},
    "La UPV al detalle": {"titulo": "La UPV al detalle", "tipo": "upv_al_detalle"},
    "Estrategia UPV_SIRVE": {"titulo": "Estrategia UPV_SIRVE", "tipo": "estrategia_upv_sirve"},
    "Sindicatura": {"titulo": "Sindicatura", "tipo": "sindicatura"},
}


def _yaml_resumen(url: str, titulo: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=url, categoria=CATEGORIA,
                                      tipo_documento="resumen", titulo=titulo)


def _yaml_recurso(nivel: str, recurso: dict, url_resumen: str) -> str:
    return ml.generar_yaml_metadatos(fuente=FUENTE, url=recurso.get("url", ""), categoria=CATEGORIA,
                                      nivel=nivel, tipo_documento="recurso", tipo_recurso=TIPO_RECURSO,
                                      resumen=url_resumen, seccion=nivel, titulo=recurso.get("titulo", ""),
                                      descripcion=recurso.get("descripcion", ""))


# ==========================================================
# 1. Extraccion de la estructura (JSON)
# ==========================================================

def localizar_seccion(contenedor_principal, titulo_objetivo: str):
    """Localiza la tarjeta de una seccion. En esta pagina la estructura
    HTML difiere: Organos de gobierno usa div.main-card, el resto usa
    div.secondary-card."""
    objetivo = ml.normalizar_para_comparar(titulo_objetivo)

    for encabezado in contenedor_principal.find_all(["h2", "h3"]):
        texto = limpiar_texto(encabezado.get_text(" ", strip=True))
        if ml.normalizar_para_comparar(texto) != objetivo:
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

        url = ml.normalizar_url(url, INSTITUCION_URL_RAIZ)
        if not ml.es_url_valida(url):
            continue

        if ml.normalizar_para_comparar(titulo) in {"mas informacion", "mas info", "ver mas"}:
            continue

        recursos.append(ml.crear_elemento(titulo=titulo, descripcion="", url=url, tipo="recurso", url_base=INSTITUCION_URL_RAIZ))

    return ml.deduplicar_lista(recursos, clave="url")


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
        seccion = ml.crear_seccion(titulo, configuracion["tipo"])
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
# 2. Generacion de Markdown (usa el motor de limpieza comun)
# ==========================================================

def obtener_enlaces_hijos(contenedor, url_pagina: str, maximo: int = MAX_ENLACES_HIJOS,
                           excluir: set[str] = frozenset()) -> list[tuple[str, str]]:
    enlaces, urls_vistas = [], set(excluir)
    for a in contenedor.find_all("a", href=True):
        href = a["href"]
        if not ml.es_url_valida_para_expandir(href, url_pagina, urls_vistas):
            continue
        from urllib.parse import urljoin
        absoluta = urljoin(url_pagina, href).split("#")[0]
        texto = ml.extraer_texto_limpio(a)
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
        soup, es_html = ml.descargar_soup(url, headers=HEADERS)
        if not es_html:
            return None
        soup = ml.limpiar_contenido_html(soup)
        contenedor = soup.find(id="smooth-wrapper") or soup.find("main") or soup.body
        if contenedor is None:
            return None

        ml.reemplazar_tablas_por_listas(soup, contenedor)
        lineas = ml.limpiar_lineas_finales(ml.extraer_bloques_contenido(contenedor, url),
                                            textos_boilerplate=TEXTOS_BOILERPLATE_INSTITUCION)
        fragmento = "\n\n".join(lineas)
        if len(fragmento) > MAX_CARACTERES_FRAGMENTO_HIJO:
            fragmento = fragmento[:MAX_CARACTERES_FRAGMENTO_HIJO].rstrip() + "…"
        return fragmento or None
    except Exception:
        return None


def extraer_contenido_iframe_clasico(soup: BeautifulSoup, url_pagina: str) -> tuple[list[str], str | None]:
    """Si la pagina usa la plantilla clasica (sin #smooth-wrapper ni
    <main>), sigue el <iframe> con el contenido real (contacto,
    direccion postal, telefonos...) que si no se pierde por completo --
    ver ml.buscar_iframe_contenido_clasico(). Devuelve (lineas, url del
    iframe) para poder excluirla despues en obtener_enlaces_hijos y no
    duplicar la misma pagina dos veces."""
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
    lineas = ml.limpiar_lineas_finales(lineas, textos_boilerplate=TEXTOS_BOILERPLATE_INSTITUCION, recortar_h1=False)
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
        "(por ejemplo, un vídeo). Consulta el contenido directamente en la URL indicada._\n"
    )


def generar_markdown_recurso(recurso: dict, carpeta: Path, nivel: str, url_resumen: str) -> bool:
    titulo = recurso.get("titulo", "")
    url = recurso.get("url", "")
    if not titulo or not url:
        return False

    print(f"  Extrayendo: {titulo} ({url})")

    try:
        respuesta = requests.get(url, headers=HEADERS, timeout=30)
        respuesta.raise_for_status()
        tipo = ml.tipo_contenido(respuesta.headers.get("Content-Type", ""))
        yaml_metadatos = _yaml_recurso(nivel, recurso, url_resumen)

        if tipo != "html":
            markdown = markdown_recurso_no_html(yaml_metadatos, titulo, url, tipo, respuesta.content)
            ruta_archivo = carpeta / ml.nombre_archivo_markdown(titulo)
            with open(ruta_archivo, "w", encoding="utf-8") as archivo:
                archivo.write(markdown)
            print(f"  OK ({tipo}): {ruta_archivo}")
            return True

        soup = BeautifulSoup(respuesta.text, "html.parser")
        soup = ml.limpiar_contenido_html(soup)
        contenedor_moderno = soup.find(id="smooth-wrapper") or soup.find("main")
        contenido = contenedor_moderno or soup.body
        if contenido is None:
            print("  AVISO: no se ha encontrado contenido.")
            return False

        lineas_iframe, iframe_url = ([], None) if contenedor_moderno is not None else extraer_contenido_iframe_clasico(soup, url)

        ml.reemplazar_tablas_por_listas(soup, contenido)
        lineas_contenido = ml.limpiar_lineas_finales(ml.extraer_bloques_contenido(contenido, url),
                                                       textos_boilerplate=TEXTOS_BOILERPLATE_INSTITUCION)
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

        ruta_archivo = carpeta / ml.nombre_archivo_markdown(titulo)
        with open(ruta_archivo, "w", encoding="utf-8") as archivo:
            archivo.write(markdown)
        print(f"  OK: {ruta_archivo}")
        return True

    except Exception as error:
        print(f"  ERROR: {error}")
        return False


def generar_markdowns_recursos(json_institucion: dict, carpetas: dict[str, Path] = INSTITUCION_CARPETAS,
                                catalogo_anterior: dict[str, list[dict]] | None = None) -> tuple[int, int, int]:
    """catalogo_anterior (ver ml.cargar_catalogo_anterior(), cargado por
    main() ANTES de guardar_json()) permite detectar recursos que
    cambiaron de titulo entre ejecuciones y borrar su .md antiguo -- sin
    esto se queda huerfano bajo el nombre de fichero viejo, duplicando
    el mismo recurso. Ver motor_limpieza.limpiar_ficheros_renombrados()."""
    catalogo_anterior = catalogo_anterior or {}
    total = correctos = errores = 0
    url_resumen = json_institucion.get("url", INSTITUCION_URL_RAIZ)

    for seccion in json_institucion.get("secciones", []):
        seccion_id = seccion.get("id", "")
        nivel = seccion.get("tipo", seccion_id)
        carpeta = carpetas.get(seccion_id)
        if carpeta is None:
            print(f"AVISO: no existe carpeta para id '{seccion_id}'")
            continue

        carpeta.mkdir(parents=True, exist_ok=True)
        print(f"[{seccion['titulo']}]")

        elementos_escritos = []
        for recurso in seccion.get("elementos", []):
            total += 1
            if generar_markdown_recurso(recurso, carpeta, nivel, url_resumen):
                correctos += 1
                elementos_escritos.append(recurso)
            else:
                errores += 1

        ml.limpiar_ficheros_renombrados(catalogo_anterior.get(seccion_id, []), elementos_escritos, carpeta)

    return total, correctos, errores


def generar_markdown_padre(url_raiz: str = INSTITUCION_URL_RAIZ, ruta: Path = INSTITUCION_MD_PADRE) -> str:
    soup, es_html = ml.descargar_soup(url_raiz, headers=HEADERS)
    soup = ml.limpiar_contenido_html(soup)

    contenedor = soup.find(id="smooth-wrapper")
    if contenedor is None:
        raise Exception("No se ha encontrado #smooth-wrapper.")

    lineas_contenido = ml.limpiar_lineas_finales(ml.extraer_bloques_contenido(contenedor, url_raiz), recortar_h1=False)
    resultado = [limpiar_texto(linea) for linea in lineas_contenido if limpiar_texto(linea)]

    yaml_metadatos = _yaml_resumen(url_raiz, "La institución")
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
    catalogo_anterior = ml.cargar_catalogo_anterior(INSTITUCION_JSON)
    datos = extraer_estructura()
    guardar_json(datos)
    generar_markdown_padre()
    total, correctos, errores = generar_markdowns_recursos(datos, catalogo_anterior=catalogo_anterior)
    print(f"Recursos: {total} · generados: {correctos} · errores: {errores}")


if __name__ == "__main__":
    main()
