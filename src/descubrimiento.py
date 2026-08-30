"""Programa de descubrimiento de contenido nuevo de upv.es (interactivo,
sin flags, mismo estilo que src/actualizar.py).

Dos acciones independientes sobre el mismo fichero de seguimiento
(data/raw/descubrimiento_urls.json, ver descubrimiento_comun.py):
  1. Scrapear: genera .md para candidatos ya descubiertos y pendientes,
     en lotes de TAMANO_LOTE con confirmacion explicita. Se puede elegir
     en que profundidad trabajar (solo entre las que YA tienen algo
     pendiente -- nunca una que no exista todavia, para no romper del
     todo el avance ordenado) y opcionalmente acotar a una sola seccion
     (categoria/nivel) en vez de trabajar sobre todo el corpus a la vez.
  2. Descubrir: mina los enlaces de CUALQUIER .md ya generado que
     todavia no se haya explorado (sea cual sea su profundidad), no solo
     lo generado en la sesion actual -- se pone al dia con todo lo que
     se pueda de una vez.

No sustituye a ningun extrae_*.py ni se registra en src/actualizar.py como una
seccion mas -- genera contenido nuevo siempre al mismo nivel que la
pagina padre de la que cuelga, heredando su categoria/nivel/seccion.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # src/ (config.py)
sys.path.insert(0, str(Path(__file__).resolve().parent / "crawlers"))  # descubrimiento_comun.py

import config
import descubrimiento_comun as dc

TAMANO_LOTE = 10

Seccion = tuple[str, "str | None"]  # (categoria, nivel)


def _conteo_pendientes_por_profundidad(seguimiento: dict) -> dict[int, int]:
    conteo: dict[int, int] = {}
    for e in seguimiento.values():
        if not e["md_generado"] and not e["descartada"]:
            conteo[e["profundidad"]] = conteo.get(e["profundidad"], 0) + 1
    return conteo


def _categoria_nivel_de_padre(padre_url: str | None, seguimiento: dict, cache: dict) -> Seccion | None:
    """Seccion (categoria, nivel) a la que pertenece un candidato, leida
    del YAML de su pagina padre (que, por construccion, ya tiene .md
    generado). Memoriza por padre_url dentro de una misma llamada para no
    releer el mismo .md una y otra vez."""
    if not padre_url:
        return None
    if padre_url in cache:
        return cache[padre_url]
    padre = seguimiento.get(padre_url)
    if not padre or not padre.get("archivo"):
        cache[padre_url] = None
        return None
    metadatos = dc.leer_yaml_frontmatter(config.DATA_PROCESSED_DIR / padre["archivo"])
    resultado = (metadatos.get("categoria", ""), metadatos.get("nivel") or None) if metadatos.get("categoria") else None
    cache[padre_url] = resultado
    return resultado


def _pendientes_de(seguimiento: dict, profundidad: int, filtro_seccion: Seccion | None = None) -> list[str]:
    cache: dict = {}
    urls = []
    for url, e in seguimiento.items():
        if e["profundidad"] != profundidad or e["md_generado"] or e["descartada"]:
            continue
        if filtro_seccion is not None:
            if _categoria_nivel_de_padre(e.get("padre_url"), seguimiento, cache) != filtro_seccion:
                continue
        urls.append(url)
    return urls


def _secciones_disponibles(seguimiento: dict, profundidad: int) -> list[Seccion]:
    cache: dict = {}
    vistas: set[Seccion] = set()
    for url, e in seguimiento.items():
        if e["profundidad"] != profundidad or e["md_generado"] or e["descartada"]:
            continue
        cn = _categoria_nivel_de_padre(e.get("padre_url"), seguimiento, cache)
        if cn is not None:
            vistas.add(cn)
    return sorted(vistas, key=lambda s: (s[0], s[1] or ""))


def _etiqueta_seccion(seccion: Seccion | None) -> str:
    if seccion is None:
        return "todas las secciones"
    categoria, nivel = seccion
    return f"{categoria}/{nivel}" if nivel else categoria


def _elegir_profundidad(conteo: dict[int, int]) -> int:
    profundidades = sorted(conteo)
    if len(profundidades) == 1:
        return profundidades[0]
    resumen = ", ".join(f"{p} ({conteo[p]} pendientes)" for p in profundidades)
    print(f"\nProfundidades con candidatos pendientes: {resumen}")
    try:
        respuesta = input(f"¿En cual quieres trabajar? (enter para la mas baja, {profundidades[0]}): ").strip()
    except EOFError:
        respuesta = ""
    if respuesta.isdigit() and int(respuesta) in profundidades:
        return int(respuesta)
    if respuesta:
        print("  (opcion no valida, se usa la mas baja)")
    return profundidades[0]


def _elegir_filtro_seccion(seguimiento: dict, profundidad: int) -> Seccion | None:
    secciones = _secciones_disponibles(seguimiento, profundidad)
    if len(secciones) <= 1:
        return None  # no tiene sentido filtrar si solo hay una (o ninguna con seccion conocida)
    print("\nSecciones con candidatos pendientes en esta profundidad:")
    print("   0. (todas)")
    for i, seccion in enumerate(secciones, start=1):
        print(f"  {i:2d}. {_etiqueta_seccion(seccion)}")
    try:
        respuesta = input("¿Acotar a cual? (enter o 0 para todas): ").strip()
    except EOFError:
        respuesta = ""
    if respuesta.isdigit() and 1 <= int(respuesta) <= len(secciones):
        return secciones[int(respuesta) - 1]
    return None


def _pedir_eleccion(urls_lote: list[str], seguimiento: dict) -> set[str] | None:
    """Devuelve None si el usuario quiere parar aqui (ver 'salir' abajo) --
    distinto de un set vacio, que significa "ninguna de este lote, sigue
    con el siguiente"."""
    print()
    for i, url in enumerate(urls_lote, start=1):
        padre = seguimiento[url].get("padre_url") or "(raiz)"
        print(f"  {i:2d}. {url}")
        print(f"      encontrada en: {padre}")
    try:
        respuesta = input(
            "\nGenerar .md para cuales? ('todas', 'ninguna', 'salir' para parar "
            "aqui, o numeros separados por comas, ej. 1,3,5): "
        ).strip().lower()
    except EOFError:
        return None
    if respuesta in ("salir", "parar", "exit", "quit", "q"):
        return None
    if respuesta in ("todas", "all", "a"):
        return set(urls_lote)
    if respuesta in ("", "ninguna", "no", "n"):
        return set()
    elegidas = set()
    for parte in respuesta.split(","):
        parte = parte.strip()
        if parte.isdigit() and 1 <= int(parte) <= len(urls_lote):
            elegidas.add(urls_lote[int(parte) - 1])
        elif parte:
            print(f"  (ignorado, no es una opcion valida: '{parte}')")
    return elegidas


def _generar_candidato(url: str, entrada: dict, seguimiento: dict,
                        nombres_usados_por_carpeta: dict[str, set[str]]) -> None:
    padre_url = entrada.get("padre_url")
    padre = seguimiento.get(padre_url, {}) if padre_url else {}
    ruta_padre = config.DATA_PROCESSED_DIR / padre["archivo"] if padre.get("archivo") else None

    if ruta_padre is None or not ruta_padre.exists():
        print(f"  AVISO: no se encuentra la pagina padre de {url}, se descarta.")
        entrada["descartada"] = True
        return

    metadatos_padre = dc.leer_yaml_frontmatter(ruta_padre)
    carpeta = ruta_padre.parent
    carpeta_id = str(carpeta)
    if carpeta_id not in nombres_usados_por_carpeta:
        nombres_usados_por_carpeta[carpeta_id] = {p.stem for p in carpeta.glob("*.md")}
    nombres_usados = nombres_usados_por_carpeta[carpeta_id]

    resultado = dc.generar_recurso_generico(
        url, carpeta,
        categoria=metadatos_padre.get("categoria", ""),
        nivel=metadatos_padre.get("nivel") or None,
        seccion=metadatos_padre.get("seccion") or None,
        resumen=padre_url,
        profundidad=entrada["profundidad"],
        nombres_usados=nombres_usados,
        titulo=entrada.get("titulo_enlace") or None,
    )

    if resultado is not None:
        entrada["md_generado"] = True
        entrada["archivo"] = resultado["archivo"]
        print(f"  OK: {resultado['archivo']}")
    else:
        entrada["descartada"] = True
        print(f"  ERROR: no se ha podido generar {url}, se descarta (no se reintenta solo).")


def _procesar_profundidad(seguimiento: dict, profundidad: int, filtro_seccion: Seccion | None) -> list[str]:
    """Agota los pendientes de esta profundidad/seccion en lotes de
    TAMANO_LOTE (o hasta que el usuario escriba 'salir'). Devuelve las
    URLs generadas con exito."""
    generadas: list[str] = []
    nombres_usados_por_carpeta: dict[str, set[str]] = {}

    while True:
        pendientes = _pendientes_de(seguimiento, profundidad, filtro_seccion)
        if not pendientes:
            break
        lote = pendientes[:TAMANO_LOTE]
        print(f"\n=== Profundidad {profundidad} ({_etiqueta_seccion(filtro_seccion)}) "
              f"-- {len(pendientes)} pendientes, mostrando {len(lote)} ===")
        elegidas = _pedir_eleccion(lote, seguimiento)
        if elegidas is None:
            print("Parando aqui -- el resto queda pendiente para la proxima vez.")
            break

        for url in lote:
            entrada = seguimiento[url]
            if url in elegidas:
                _generar_candidato(url, entrada, seguimiento, nombres_usados_por_carpeta)
                if entrada["md_generado"]:
                    generadas.append(url)
            else:
                entrada["descartada"] = True

        dc.guardar_seguimiento(seguimiento)

    return generadas


def _descubrir_pendientes(seguimiento: dict) -> tuple[dict[int, int], dict[int, int]]:
    """Mina los enlaces de CUALQUIER .md ya generado que todavia no se
    haya explorado (md_generado=true, expandida=false), sea cual sea su
    profundidad -- se pone al dia con todo lo que se pueda de una vez, no
    solo con lo generado en la sesion actual ni solo con la profundidad
    mas alta. Asi, si en una sesion anterior se genero contenido pero no
    se llego a "descubrir" a partir de el, esta pasada lo recoge igual,
    y puede abrir mas de una profundidad nueva a la vez si habia varias
    sin minar.

    Devuelve (explorados_por_profundidad, nuevos_por_profundidad):
    cuantos documentos se han minado agrupados por SU PROPIA profundidad
    (de donde partia la busqueda), y cuantos candidatos nuevos han caido
    en cada profundidad RESULTANTE (siempre origen + 1)."""
    objetivos = [
        (url, e) for url, e in seguimiento.items()
        if e["md_generado"] and not e["expandida"] and e.get("archivo")
    ]
    if not objetivos:
        return {}, {}

    explorados_por_profundidad: dict[int, int] = {}
    nuevos_por_profundidad: dict[int, int] = {}
    for url, entrada in objetivos:
        explorados_por_profundidad[entrada["profundidad"]] = explorados_por_profundidad.get(entrada["profundidad"], 0) + 1
        ruta_md = config.DATA_PROCESSED_DIR / entrada["archivo"]
        if not ruta_md.exists():
            entrada["expandida"] = True
            continue
        texto = ruta_md.read_text(encoding="utf-8")
        for texto_enlace, url_enlace in dc.extraer_enlaces_markdown(texto):
            url_enlace = url_enlace.split("#")[0].rstrip("/")
            if url_enlace in seguimiento or not dc.es_url_candidata(url_enlace):
                continue
            if dc.es_texto_enlace_sin_valor(texto_enlace):
                continue
            profundidad_nueva = entrada["profundidad"] + 1
            seguimiento[url_enlace] = {
                "profundidad": profundidad_nueva,
                "md_generado": False,
                "archivo": None,
                "padre_url": url,
                "titulo_enlace": texto_enlace,
                "expandida": False,
                "descartada": False,
            }
            nuevos_por_profundidad[profundidad_nueva] = nuevos_por_profundidad.get(profundidad_nueva, 0) + 1
        entrada["expandida"] = True

    dc.guardar_seguimiento(seguimiento)
    return explorados_por_profundidad, nuevos_por_profundidad


def _elegir_accion() -> str:
    print("\n¿Que quieres hacer?")
    print("  1. Scrapear candidatos ya descubiertos (generar .md)")
    print("  2. Descubrir enlaces nuevos en lo ya generado")
    try:
        return input("Elige (1/2): ").strip()
    except EOFError:
        return ""


def main() -> None:
    seguimiento = dc.cargar_seguimiento()
    accion = _elegir_accion()

    if accion == "2":
        explorados, nuevos = _descubrir_pendientes(seguimiento)
        if not explorados:
            print("\nNo hay ningun .md generado pendiente de explorar todavia.")
            return
        print("\nDocumentos explorados (por su propia profundidad):")
        for p in sorted(explorados):
            print(f"  - profundidad {p}: {explorados[p]} documento(s)")
        if nuevos:
            print("Candidatos nuevos anadidos al fichero de seguimiento (por profundidad resultante):")
            for p in sorted(nuevos):
                print(f"  - profundidad {p}: {nuevos[p]} candidato(s)")
        else:
            print("Ningun candidato nuevo -- todos los enlaces encontrados ya eran conocidos, "
                  "estaban en la lista negra, o su texto no aportaba como titulo.")
        return

    conteo = _conteo_pendientes_por_profundidad(seguimiento)
    if not conteo:
        print("No hay ninguna URL pendiente de generar. Prueba la opcion 2 "
              "(Descubrir) si hay .md ya generados sin explorar todavia.")
        return

    profundidad = _elegir_profundidad(conteo)
    filtro_seccion = _elegir_filtro_seccion(seguimiento, profundidad)

    print(f"\nProfundidad elegida: {profundidad} -- {_etiqueta_seccion(filtro_seccion)}")
    generadas = _procesar_profundidad(seguimiento, profundidad, filtro_seccion)
    restantes = len(_pendientes_de(seguimiento, profundidad, filtro_seccion))
    print(f"\n{len(generadas)} generadas. Quedan {restantes} pendientes en esta combinacion de profundidad/seccion.")


if __name__ == "__main__":
    main()
