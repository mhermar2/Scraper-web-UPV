"""Rutas y constantes compartidas por todos los extractores.

Sustituye las rutas de Google Drive (/content/drive/MyDrive/...) que
usaban los notebooks originales. Todo es relativo a la raiz del repo.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DATA_RAW_DIR = REPO_ROOT / "data" / "raw"
DATA_PROCESSED_DIR = REPO_ROOT / "data" / "processed"

ADMISION_DIR = DATA_PROCESSED_DIR / "admision"
ESTUDIOS_DIR = DATA_PROCESSED_DIR / "estudios"
INVESTIGACION_DIR = DATA_PROCESSED_DIR / "investigacion"
INSTITUCION_DIR = DATA_PROCESSED_DIR / "institucion"
SERVICIOS_DIR = DATA_PROCESSED_DIR / "servicios"
ORGANIZACION_DIR = DATA_PROCESSED_DIR / "organizacion"
RANKINGS_DIR = DATA_PROCESSED_DIR / "rankings"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; UPV-KB-Bot/1.0)",
}

PAUSA_RED = 0.4

# --- estudios / formacion permanente ---
FORMACION_PERMANENTE_URL_RAIZ = "https://www.cfp.upv.es/formacion-permanente"
FORMACION_PERMANENTE_JSON = DATA_RAW_DIR / "formacion_permanente.json"
FORMACION_PERMANENTE_KB_DIR = ESTUDIOS_DIR / "formacion_permanente"
FORMACION_PERMANENTE_MD_PADRE = FORMACION_PERMANENTE_KB_DIR / "formacion_permanente.md"
FORMACION_PERMANENTE_ESTADO = FORMACION_PERMANENTE_KB_DIR / "_estado.pkl"

# --- estudios / doctorado ---
DOCTORADOS_URL_RAIZ = "https://www.upv.es/entidades/edoctorado/todos-los-programas-de-doctorado-ofertados-en-upv/"
DOCTORADOS_JSON = DATA_RAW_DIR / "doctorados.json"
DOCTORADOS_KB_DIR = ESTUDIOS_DIR / "doctorado"
DOCTORADOS_MD_PADRE = DOCTORADOS_KB_DIR / "doctorado.md"

# --- estudios / master ---
# Catalogo real (122 titulaciones con acronimo/centro/rama/campus/modalidad
# ya estructurados) detras del listado con "Cargar mas resultados" de
# /estudios/master/index-es.html -- descubierto inspeccionando las
# peticiones de red de esa pagina, evita tener que lidiar con la
# paginacion AJAX.
MASTER_CATALOGO_URL = "https://www.upv.es/courses/masteres-es.json"
MASTER_JSON = DATA_RAW_DIR / "master.json"
MASTER_KB_DIR = ESTUDIOS_DIR / "master"

# --- estudios / grado ---
GRADO_CATALOGO_URL = "https://www.upv.es/courses/grados-es.json"
GRADO_JSON = DATA_RAW_DIR / "grado.json"
GRADO_KB_DIR = ESTUDIOS_DIR / "grado"

# --- institucion ---
INSTITUCION_URL_RAIZ = "https://www.upv.es/organizacion/la-institucion/index-es.html"
INSTITUCION_JSON = DATA_RAW_DIR / "institucion.json"
INSTITUCION_MD_PADRE = INSTITUCION_DIR / "institucion.md"
INSTITUCION_CARPETAS = {
    "organos_de_gobierno": INSTITUCION_DIR / "organos_gobierno",
    "publicaciones_oficiales": INSTITUCION_DIR / "publicaciones_oficiales",
    "la_upv_al_detalle": INSTITUCION_DIR / "upv_al_detalle",
    "estrategia_upv_sirve": INSTITUCION_DIR / "estrategia_upv_sirve",
    "sindicatura": INSTITUCION_DIR / "sindicatura",
}

# --- servicios ---
SERVICIOS_URL = "https://www.upv.es/organizacion/servicios-universitarios/index-es.html"
SERVICIOS_JSON = DATA_RAW_DIR / "servicios_universitarios.json"
SERVICIOS_MD_PADRE = SERVICIOS_DIR / "servicios_universitarios.md"

# --- investigacion / iniciativas idi ---
INICIATIVAS_IDI_URL = "https://www.upv.es/investigacion/iniciativas-idi/index-es.html"
INICIATIVAS_IDI_JSON = DATA_RAW_DIR / "iniciativas_idi.json"
INICIATIVAS_IDI_DIR = INVESTIGACION_DIR / "iniciativas_idi"
INICIATIVAS_IDI_MD_PADRE = INICIATIVAS_IDI_DIR / "iniciativas_idi.md"
INICIATIVAS_IDI_RECURSOS_DIR = INICIATIVAS_IDI_DIR / "recursos"

# --- investigacion / innovacion ---
INNOVACION_URL = "https://innovacion.upv.es/"
INNOVACION_JSON = DATA_RAW_DIR / "innovacion.json"
INNOVACION_DIR = INVESTIGACION_DIR / "innovacion"
INNOVACION_MD_PADRE = INNOVACION_DIR / "innovacion.md"
INNOVACION_RECURSOS_DIR = INNOVACION_DIR / "recursos"

# --- investigacion / estructuras ---
# Catalogo real (67 institutos/centros/UIC con tipo/area/web ya
# estructurados) detras de los enlaces "Ver institutos universitarios"/
# "Ver centros de investigacion"/"Ver unidades de investigacion conjunta"
# de investigacion/estructuras/index-es.html, que en realidad llevan a un
# buscador JS (buscador-estructuras-es.html) sin contenido estatico --
# descubierto inspeccionando las peticiones de red de esa pagina, mismo
# patron que courses/grados-es.json / courses/masteres-es.json.
ESTRUCTURAS_URL = "https://www.upv.es/investigacion/estructuras/index-es.html"
ESTRUCTURAS_CATALOGO_URL = "https://www.upv.es/courses/institutos-es.json"
ESTRUCTURAS_JSON = DATA_RAW_DIR / "investigacion_estructuras.json"
ESTRUCTURAS_DIR = INVESTIGACION_DIR / "estructuras"
ESTRUCTURAS_CARPETAS = {
    "institutos_investigacion": ESTRUCTURAS_DIR / "institutos_investigacion",
    "centros_investigacion": ESTRUCTURAS_DIR / "centros_investigacion",
    "uic": ESTRUCTURAS_DIR / "uic",
    "estructuras_apoyo": ESTRUCTURAS_DIR / "estructuras_apoyo",
}

# --- organizacion / sostenibilidad ---
SOSTENIBILIDAD_URL = "https://www.upv.es/organizacion/sostenibilidad/index-es.html"
SOSTENIBILIDAD_JSON = DATA_RAW_DIR / "organizacion_sostenibilidad.json"
SOSTENIBILIDAD_DIR = ORGANIZACION_DIR / "sostenibilidad"
SOSTENIBILIDAD_CARPETAS = {
    "informes": SOSTENIBILIDAD_DIR / "informes",
    "servicios": SOSTENIBILIDAD_DIR / "servicios",
}

# --- contacto ---
CONTACTO_URL = "https://www.upv.es/otros/contacto-es.html"
POLICONSULTA_URL = "https://www.upv.es/noticias-upv/noticia-8492-policonsulta-es.html"
CONTACTO_JSON = DATA_RAW_DIR / "contacto.json"
CONTACTO_DIR = DATA_PROCESSED_DIR / "contacto"

# --- rankings ---
RANKINGS_URL = "https://www.upv.es/rankings/index.html"
RANKINGS_JSON = DATA_RAW_DIR / "rankings.json"
RANKINGS_MD_PADRE = RANKINGS_DIR / "rankings.md"

# --- admision / master ---
ADMISION_MASTER_URL = "https://www.upv.es/admision/admision-master/index-es.html"
ADMISION_MASTER_JSON = DATA_RAW_DIR / "admision_master.json"
ADMISION_MASTER_DIR = ADMISION_DIR / "master"
ADMISION_MASTER_RECURSOS_DIR = ADMISION_MASTER_DIR / "recursos"

# --- admision / doctorado ---
ADMISION_DOCTORADO_URL = "https://www.upv.es/admision/admision-doctorado/index-es.html"
ADMISION_DOCTORADO_JSON = DATA_RAW_DIR / "admision_doctorado.json"
ADMISION_DOCTORADO_DIR = ADMISION_DIR / "doctorado"
ADMISION_DOCTORADO_RECURSOS_DIR = ADMISION_DOCTORADO_DIR / "recursos"

# --- admision / internacional ---
ADMISION_INTERNACIONAL_URL = "https://www.upv.es/admision/internacional/"
ADMISION_INTERNACIONAL_JSON = DATA_RAW_DIR / "admision_internacional.json"
ADMISION_INTERNACIONAL_DIR = ADMISION_DIR / "internacional"
ADMISION_INTERNACIONAL_RECURSOS_DIR = ADMISION_INTERNACIONAL_DIR / "recursos"

# --- organizacion / escuelas y facultades ---
ESCUELAS_URL = "https://www.upv.es/organizacion/escuelas-facultades/index-es.html"
ESCUELAS_JSON = DATA_RAW_DIR / "escuelas_facultades.json"
ESCUELAS_KB_DIR = ORGANIZACION_DIR / "escuelas_facultades"

# --- organizacion / departamentos ---
DEPARTAMENTOS_URL = "https://www.upv.es/organizacion/departamentos/index-es.html"
DEPARTAMENTOS_JSON = DATA_RAW_DIR / "departamentos.json"
DEPARTAMENTOS_KB_DIR = ORGANIZACION_DIR / "departamentos"

# --- comunidad_upv / estudiante ---
ESTUDIANTE_URL = "https://www.upv.es/perfiles/estudiante/index-es.html"
ESTUDIANTE_BECAS_URL = "https://www.upv.es/perfiles/estudiante/introduccion-becas-es.html"
ESTUDIANTE_JSON = DATA_RAW_DIR / "comunidad_upv_estudiante.json"
COMUNIDAD_UPV_DIR = DATA_PROCESSED_DIR / "comunidad_upv"
ESTUDIANTE_DIR = COMUNIDAD_UPV_DIR / "estudiante"
ESTUDIANTE_CARPETAS = {
    "estudios": ESTUDIANTE_DIR / "estudios",
    "ventajas": ESTUDIANTE_DIR / "ventajas",
    "empleo": ESTUDIANTE_DIR / "empleo",
    "becas_ayudas": ESTUDIANTE_DIR / "becas_ayudas",
}

# --- admision / grado ---
ADMISION_GRADO_JSON = DATA_RAW_DIR / "admision_grado.json"
ADMISION_GRADO_DIR = ADMISION_DIR / "grado"
# (nombre_fuente, url, carpeta_corta) -- carpeta_corta es la ya usada en
# la reorganizacion de data/processed/admision/grado/, distinta del slug
# largo derivado del <title> de cada pagina que usaba el notebook
# original (ver extrae_grado.py para el detalle).
CRAWLER_OUTPUT_DIR = DATA_RAW_DIR / "crawler_generico"
CRAWLER_ESTADO = CRAWLER_OUTPUT_DIR / "estado_bot.pkl"

ADMISION_GRADO_FUENTES = [
    ("Bachillerato", "https://www.upv.es/admision/admision-grado/bachillerato-es.html", "bachillerato"),
    ("Ciclos formativos", "https://www.upv.es/admision/admision-grado/ciclos-formativos-es.html", "ciclos_formativos"),
    ("Titulados universitarios", "https://www.upv.es/admision/admision-grado/titulados-universitarios-es.html", "titulados_universitarios"),
    ("Mayores de 25/40/45 años", "https://www.upv.es/admision/admision-grado/mayores-25-40-45-es.html", "mayores_25_40_45"),
    ("Vengo de otra universidad", "https://www.upv.es/admision/admision-grado/vengo-de-otra-universidad-es.html", "otra_universidad"),
]
