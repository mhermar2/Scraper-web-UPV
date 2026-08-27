"""Orquestador interactivo de extractores.

Punto de entrada unico para actualizar data/processed/ sin tener que saber
que extractores existen ni como se invoca cada uno por separado. Pensado
para que cualquiera sin conocer el codigo pueda ejecutar

    python src/main.py

y elegir que secciones actualizar. Cada extractor ya escribe directamente
en su carpeta de data/raw|processed/ (ver config.py) e ideempotente
(sobrescribe, no acumula) -- este script no anade logica de extraccion
nueva, solo descubre, ejecuta y resume.

No detecta "hay contenido nuevo" comparando catalogos antes de hacer la
peticion de red (cada extractor ya hace la suya propia, y no merece la
pena duplicar esa logica aqui) -- ademas, los extractores escriben
directamente sobre data/processed|raw/ (los directorios de salida estan
"horneados" como valores por defecto de sus funciones, no se pueden
redirigir a una carpeta provisional sin tocar cada extractor uno a uno),
asi que no hay forma barata de generar un .md "de prueba" y comparar
antes de tocar nada real. En su lugar, para cada seccion elegida:
  1. Pide confirmacion antes de sobrescribir, y guarda una copia
     especulativa de lo que ya habia en data/legacy/ (por si acaso).
  2. Ejecuta el extractor de verdad (sobrescribe en su sitio, como
     siempre).
  3. Compara con git que cambio de verdad -- distinguiendo un cambio de
     CONTENIDO real de un simple refresco de la fecha `actualizado:` del
     YAML (el extractor la reescribe en cada ejecucion aunque la pagina
     de origen no haya cambiado, asi que un diff a secas siempre
     marcaria todo como "modificado" sin serlo de verdad).
  4. Si una seccion resulta sin novedad real, se descarta el toque (git
     checkout) y se borra la copia especulativa de data/legacy/ -- no
     hacia falta. data/legacy/ se queda solo con secciones que SI
     cambiaron.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import types
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTRACTORES_DIR = REPO_ROOT / "src" / "extractores"
LEGACY_DIR = REPO_ROOT / "data" / "legacy"

sys.path.insert(0, str(Path(__file__).resolve().parent))  # src/ (config.py)
import config


@dataclass(frozen=True)
class Seccion:
    categoria: str
    nombre: str
    ruta_extractor: str  # relativa a src/extractores/
    carpeta_processed: Path
    json_raw: Path

    @property
    def titulo(self) -> str:
        return f"{self.categoria} / {self.nombre}"


REGISTRO: list[Seccion] = [
    Seccion("Institucion", "La institucion", "institucion/extrae_institucion.py",
            config.INSTITUCION_DIR, config.INSTITUCION_JSON),
    Seccion("Servicios", "Servicios universitarios", "servicios/extrae_servicios.py",
            config.SERVICIOS_DIR, config.SERVICIOS_JSON),
    Seccion("Rankings", "Rankings", "rankings/extrae_rankings.py",
            config.RANKINGS_DIR, config.RANKINGS_JSON),
    Seccion("Orientacion", "Orientacion", "orientacion/extrae_orientacion.py",
            config.ORIENTACION_DIR, config.ORIENTACION_JSON),
    Seccion("Contacto", "Contacto", "contacto/extrae_contacto.py",
            config.CONTACTO_DIR, config.CONTACTO_JSON),
    Seccion("Admision", "Grado", "admision/extrae_grado.py",
            config.ADMISION_GRADO_DIR, config.ADMISION_GRADO_JSON),
    Seccion("Admision", "Master", "admision/extrae_master.py",
            config.ADMISION_MASTER_DIR, config.ADMISION_MASTER_JSON),
    Seccion("Admision", "Doctorado", "admision/extrae_doctorado.py",
            config.ADMISION_DOCTORADO_DIR, config.ADMISION_DOCTORADO_JSON),
    Seccion("Admision", "Internacional", "admision/extrae_internacional.py",
            config.ADMISION_INTERNACIONAL_DIR, config.ADMISION_INTERNACIONAL_JSON),
    Seccion("Estudios", "Grado", "estudios/extrae_grado.py",
            config.GRADO_KB_DIR, config.GRADO_JSON),
    Seccion("Estudios", "Master", "estudios/extrae_master.py",
            config.MASTER_KB_DIR, config.MASTER_JSON),
    Seccion("Estudios", "Doctorado", "estudios/extrae_doctorado.py",
            config.DOCTORADOS_KB_DIR, config.DOCTORADOS_JSON),
    Seccion("Estudios", "Formacion permanente", "estudios/extrae_formacion_permanente.py",
            config.FORMACION_PERMANENTE_KB_DIR, config.FORMACION_PERMANENTE_JSON),
    Seccion("Investigacion", "Estructuras", "investigacion/extrae_estructuras.py",
            config.ESTRUCTURAS_DIR, config.ESTRUCTURAS_JSON),
    Seccion("Investigacion", "Iniciativas I+D+i", "investigacion/extrae_iniciativas_idi.py",
            config.INICIATIVAS_IDI_DIR, config.INICIATIVAS_IDI_JSON),
    Seccion("Investigacion", "Innovacion", "investigacion/extrae_innovacion.py",
            config.INNOVACION_DIR, config.INNOVACION_JSON),
    Seccion("Organizacion", "Escuelas y facultades", "organizacion/extrae_escuelas.py",
            config.ESCUELAS_KB_DIR, config.ESCUELAS_JSON),
    Seccion("Organizacion", "Departamentos", "organizacion/extrae_departamentos.py",
            config.DEPARTAMENTOS_KB_DIR, config.DEPARTAMENTOS_JSON),
    Seccion("Organizacion", "Sostenibilidad", "organizacion/extrae_sostenibilidad.py",
            config.SOSTENIBILIDAD_DIR, config.SOSTENIBILIDAD_JSON),
    Seccion("Comunidad UPV", "Estudiante", "comunidad_upv/extrae_estudiante.py",
            config.ESTUDIANTE_DIR, config.ESTUDIANTE_JSON),
    Seccion("Comunidad UPV", "PTGAS, PDI y PI", "comunidad_upv/extrae_ptgas_pdi_pi.py",
            config.PTGAS_PDI_PI_DIR, config.PTGAS_PDI_PI_JSON),
]


def cargar_extractor(ruta_relativa: str) -> types.ModuleType:
    """Importa un extractor por ruta de fichero, con un nombre de modulo
    unico (derivado de la ruta) -- varias categorias reutilizan el mismo
    nombre de fichero (ej. admision/extrae_grado.py y
    estudios/extrae_grado.py), asi que un `import extrae_grado` normal
    pisaria uno con el otro en sys.modules."""
    ruta = EXTRACTORES_DIR / ruta_relativa
    nombre_modulo = "extractor_" + ruta_relativa.replace("/", "_").removesuffix(".py")
    spec = importlib.util.spec_from_file_location(nombre_modulo, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre_modulo] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def buscar_extractores_no_registrados() -> list[str]:
    """Compara los extrae_*.py que existen de verdad en src/extractores/
    contra REGISTRO -- si alguien anade un extractor nuevo y se le olvida
    darlo de alta aqui, no da ningun error, simplemente no aparece en el
    menu. Esto lo detecta para avisar en vez de fallar en silencio."""
    registrados = {s.ruta_extractor for s in REGISTRO}
    encontrados = {
        str(p.relative_to(EXTRACTORES_DIR)).replace("\\", "/")
        for p in EXTRACTORES_DIR.rglob("extrae_*.py")
    }
    return sorted(encontrados - registrados)


def avisar_si_faltan_extractores() -> None:
    faltantes = buscar_extractores_no_registrados()
    if not faltantes:
        return
    print(
        "\nAVISO: hay extractores en src/extractores/ que no estan dados de "
        "alta en REGISTRO (src/main.py) y por eso no van a aparecer en el "
        "menu de abajo:"
    )
    for ruta in faltantes:
        print(f"  - {ruta}")
    print("Anadelos a REGISTRO en src/main.py para que el orquestador los use.")


def mostrar_menu() -> None:
    print("\nSecciones disponibles:\n")
    categoria_anterior = None
    for i, seccion in enumerate(REGISTRO, start=1):
        if seccion.categoria != categoria_anterior:
            print(f"  {seccion.categoria}")
            categoria_anterior = seccion.categoria
        print(f"    {i:2d}. {seccion.nombre}")
    print()


def pedir_seleccion() -> list[Seccion]:
    mostrar_menu()
    respuesta = input(
        "Que quieres actualizar? ('todas' para todo, o numeros separados por "
        "comas, ej. 1,3,5): "
    ).strip().lower()

    if respuesta in ("", "todas", "all", "a"):
        return list(REGISTRO)

    seleccion = []
    for parte in respuesta.split(","):
        parte = parte.strip()
        if parte.isdigit() and 1 <= int(parte) <= len(REGISTRO):
            seleccion.append(REGISTRO[int(parte) - 1])
        elif parte:
            print(f"  (ignorado, no es una opcion valida: '{parte}')")
    return seleccion


def respaldar_antes_de_ejecutar(seccion: Seccion) -> bool:
    """Copia a data/legacy/ el contenido tal cual estaba justo antes de
    ejecutar esta seccion (el JSON intermedio y los .md ya generados),
    por si hace falta comparar o recuperar algo despues. Sobrescribe la
    copia anterior en data/legacy/ -- solo interesa el estado previo a la
    ULTIMA ejecucion, no un historial completo (para eso ya esta git, que
    conserva cualquier version comiteada). Devuelve True si habia algo
    que respaldar."""
    respaldado = False

    if seccion.carpeta_processed.exists():
        destino = LEGACY_DIR / "processed" / seccion.carpeta_processed.relative_to(config.DATA_PROCESSED_DIR)
        if destino.exists():
            shutil.rmtree(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(seccion.carpeta_processed, destino)
        respaldado = True

    if seccion.json_raw.exists():
        destino_json = LEGACY_DIR / "raw" / seccion.json_raw.relative_to(config.DATA_RAW_DIR)
        destino_json.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(seccion.json_raw, destino_json)
        respaldado = True

    return respaldado


def confirmar_sobrescritura(secciones: list[Seccion]) -> bool:
    con_contenido_previo = [s for s in secciones if s.carpeta_processed.exists() or s.json_raw.exists()]
    if not con_contenido_previo:
        return True  # no hay nada que sobrescribir, no hace falta preguntar

    print("\nEstas secciones ya tienen contenido guardado y se van a sobrescribir:")
    for s in con_contenido_previo:
        print(f"  - {s.titulo}")
    print(
        "Antes de sobrescribir cada una, se guarda una copia de lo que hay "
        "ahora mismo en data/legacy/ por si acaso -- si al terminar resulta "
        "que la web no tenia nada nuevo, esa copia se borra sola (no se "
        "guarda backup ni se deja nada pendiente para una seccion sin cambios)."
    )

    respuesta = input("Quieres continuar y sobrescribir? (S/n): ").strip().lower()
    return respuesta not in ("n", "no")


def ejecutar_seleccion(secciones: list[Seccion]) -> list[tuple[Seccion, bool, str]]:
    resultados = []
    for seccion in secciones:
        print(f"\n{'=' * 60}\n{seccion.titulo}\n{'=' * 60}")

        if respaldar_antes_de_ejecutar(seccion):
            print("(copia de lo que habia antes guardada en data/legacy/, por si acaso)")

        try:
            modulo = cargar_extractor(seccion.ruta_extractor)
            modulo.main()
            resultados.append((seccion, True, ""))
        except Exception as e:
            print(f"ERROR en {seccion.titulo}: {type(e).__name__}: {e}")
            resultados.append((seccion, False, f"{type(e).__name__}: {e}"))
    return resultados


def mostrar_resumen(resultados: list[tuple[Seccion, bool, str]]) -> None:
    print(f"\n{'=' * 60}\nResumen de la ejecucion\n{'=' * 60}")
    for seccion, ok, error in resultados:
        estado = "OK" if ok else f"ERROR ({error})"
        print(f"  [{estado}] {seccion.titulo}")


PATRON_LINEA_FECHA = re.compile(r"^[+-]actualizado:\s")
SOLO_FECHA = "sin cambio real (solo se refresco la fecha)"


def clasificar_cambio_git(ruta_relativa: str, codigo: str) -> str:
    """Etiqueta legible para un fichero cambiado. Para los "modificados",
    distingue si el UNICO cambio es la linea `actualizado:` del YAML del
    de un cambio de contenido real -- el extractor reescribe esa fecha en
    cada ejecucion aunque la pagina de origen no haya cambiado, asi que
    sin esto cualquier regeneracion se veria siempre como "modificado"
    aunque no haya novedad real en la web."""
    if codigo.startswith("?"):
        return "nuevo"
    if codigo.startswith("A"):
        return "nuevo (añadido)"
    if codigo.startswith("D"):
        return "borrado"
    if codigo.startswith("M"):
        resultado = subprocess.run(
            ["git", "diff", "--", ruta_relativa],
            cwd=REPO_ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        lineas_cambio = [
            l for l in resultado.stdout.splitlines()
            if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))
        ]
        if lineas_cambio and all(PATRON_LINEA_FECHA.match(l) for l in lineas_cambio):
            return SOLO_FECHA
        return "modificado (contenido nuevo)"
    return codigo or "cambiado"


SIN_CAMBIOS = "sin_cambios"
SOLO_FECHA_ESTADO = "solo_fecha"
CONTENIDO_NUEVO = "contenido_nuevo"


def mostrar_cambios_git(secciones: list[Seccion]) -> dict[Seccion, str]:
    """Compara con git que cambio en data/ tras ejecutar las secciones
    elegidas, y muestra un resumen por seccion distinguiendo contenido
    nuevo de verdad de un simple refresco de fecha. Nunca requiere que el
    usuario escriba un comando de git a mano -- este programa ya lo hace
    por dentro con subprocess. Devuelve, por seccion, uno de
    SIN_CAMBIOS/SOLO_FECHA_ESTADO/CONTENIDO_NUEVO."""
    try:
        resultado = subprocess.run(
            ["git", "status", "--porcelain", "--", "data"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        print(
            "\nNo se encuentra 'git' en este ordenador, no puedo comprobar que "
            "cambio. Los ficheros ya estan actualizados en disco igualmente."
        )
        return {s: SIN_CAMBIOS for s in secciones}
    except subprocess.CalledProcessError as e:
        print(f"\nNo se pudo consultar el estado de git: {e}")
        return {s: SIN_CAMBIOS for s in secciones}

    lineas = [l for l in resultado.stdout.splitlines() if l.strip()]
    cambios = []
    for linea in lineas:
        codigo, ruta = linea[:2].strip(), linea[3:]
        cambios.append((ruta, clasificar_cambio_git(ruta, codigo)))

    if cambios:
        print(f"\nCambios en data/ ({len(cambios)} ficheros):")
        for ruta, etiqueta in cambios:
            print(f"  [{etiqueta}] {ruta}")

    print("\nContenido nuevo por seccion:")
    resumen: dict[Seccion, str] = {}
    for seccion in secciones:
        prefijo_processed = str(seccion.carpeta_processed.relative_to(REPO_ROOT)).replace("\\", "/")
        ruta_json = str(seccion.json_raw.relative_to(REPO_ROOT)).replace("\\", "/")
        propios = [(r, e) for r, e in cambios if r.startswith(prefijo_processed) or r == ruta_json]

        if not propios:
            print(f"  - {seccion.titulo}: sin cambios (ya estaba al dia)")
            resumen[seccion] = SIN_CAMBIOS
            continue

        reales = [e for _, e in propios if e != SOLO_FECHA]
        if reales:
            print(f"  - {seccion.titulo}: CONTENIDO NUEVO ({len(reales)} de {len(propios)} ficheros)")
            resumen[seccion] = CONTENIDO_NUEVO
        else:
            print(f"  - {seccion.titulo}: sin novedad real en la web (solo se refresco la fecha de extraccion)")
            resumen[seccion] = SOLO_FECHA_ESTADO

    if not any(estado == CONTENIDO_NUEVO for estado in resumen.values()):
        print("\nNinguna de las secciones comprobadas tiene contenido nuevo respecto a lo que ya habia en el repositorio.")

    return resumen


def limpiar_seccion_sin_novedad(seccion: Seccion) -> None:
    """Deshace lo que ejecutar_seleccion() hizo especulativamente para una
    seccion que ha resultado sin contenido nuevo de verdad: descarta el
    refresco de fecha en data/processed|raw/ Y la copia de seguridad en
    data/legacy/ (no hacia falta ninguna de las dos). Asi data/legacy/ solo
    se queda con copias de secciones que SI cambiaron de verdad.

    Todo por git, nunca borrando ficheros a mano (bug real encontrado
    2026-08-27: un `shutil.rmtree()`/`unlink()` directo sobre el destino de
    data/legacy/ borraba sin mas una copia de seguridad que YA estaba
    comiteada de una ejecucion anterior -- en vez de devolverla a su
    version comiteada, la eliminaba del disco por completo). `git checkout`
    revierte cualquier ruta ya trackeada a su ultima version comiteada; si
    la copia de data/legacy/ es nueva de esta misma ejecucion (todavia sin
    comitear, `git checkout` no la toca), `git clean -fd` se encarga de
    borrar ese sobrante sin tocar nada que ya estuviera en el repo."""
    rutas = [
        str(seccion.carpeta_processed.relative_to(REPO_ROOT)),
        str(seccion.json_raw.relative_to(REPO_ROOT)),
        str((LEGACY_DIR / "processed" / seccion.carpeta_processed.relative_to(config.DATA_PROCESSED_DIR)).relative_to(REPO_ROOT)),
        str((LEGACY_DIR / "raw" / seccion.json_raw.relative_to(config.DATA_RAW_DIR)).relative_to(REPO_ROOT)),
    ]
    # Una ruta por llamada: "git checkout -- a b" falla POR COMPLETO (sin
    # revertir nada, ni siquiera las rutas validas) si una sola de las
    # rutas no esta trackeada -- ej. data/legacy/raw/<seccion>.json puede
    # no existir todavia en el repo aunque data/legacy/processed/<seccion>
    # si. Bug real encontrado 2026-08-27 al probarlo: el fallo pasaba
    # desapercibido (no se comprobaba el codigo de salida) y no revertia
    # nada en absoluto.
    for ruta in rutas:
        subprocess.run(["git", "checkout", "--", ruta], cwd=REPO_ROOT, capture_output=True)
    subprocess.run(["git", "clean", "-fd", "--", *rutas], cwd=REPO_ROOT, capture_output=True)


def preguntar_commit() -> None:
    respuesta = input("\nQuieres comitear estos cambios ahora? (s/N): ").strip().lower()
    if respuesta not in ("s", "si", "y", "yes"):
        print("De acuerdo, no se comitea nada (los cambios ya estan en disco).")
        return

    mensaje = input(
        "Mensaje de commit (enter para uno generico): "
    ).strip() or "Actualizar contenido en data/ via orquestador de extractores"

    try:
        subprocess.run(["git", "add", "--", "data"], cwd=REPO_ROOT, check=True)
        subprocess.run(["git", "commit", "-m", mensaje], cwd=REPO_ROOT, check=True)
    except FileNotFoundError:
        print("No se encuentra 'git' en este ordenador, no se puede comitear.")
        return
    except subprocess.CalledProcessError as e:
        print(f"El commit ha fallado: {e}")
        return
    print("Commit creado.")


def main() -> None:
    print("Orquestador de extractores UPV -- actualizar data/processed/")
    avisar_si_faltan_extractores()
    secciones = pedir_seleccion()
    if not secciones:
        print("Nada seleccionado, saliendo.")
        return

    if not confirmar_sobrescritura(secciones):
        print("De acuerdo, no se ejecuta nada.")
        return

    resultados = ejecutar_seleccion(secciones)
    mostrar_resumen(resultados)

    resumen_por_seccion = mostrar_cambios_git(secciones)

    # Secciones sin novedad real (o sin cambios): se descarta el toque y se
    # borra la copia de seguridad especulativa -- no hacia falta, la web no
    # tenia nada nuevo. data/legacy/ se queda solo con lo que SI cambio.
    sin_novedad = [s for s, estado in resumen_por_seccion.items() if estado != CONTENIDO_NUEVO]
    for seccion in sin_novedad:
        limpiar_seccion_sin_novedad(seccion)
    if sin_novedad:
        print(
            f"\n({len(sin_novedad)} seccion(es) sin contenido nuevo: se ha "
            "descartado el toque y no se ha guardado ningun backup para ellas.)"
        )

    if any(estado == CONTENIDO_NUEVO for estado in resumen_por_seccion.values()):
        preguntar_commit()


if __name__ == "__main__":
    main()
