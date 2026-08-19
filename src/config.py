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
FORMACION_PERMANENTE_JSON = DATA_RAW_DIR / "formacion_permanente_upv.json"
FORMACION_PERMANENTE_KB_DIR = ESTUDIOS_DIR / "formacion_permanente"
FORMACION_PERMANENTE_ESTADO = FORMACION_PERMANENTE_KB_DIR / "_estado.pkl"

# --- estudios / doctorado ---
DOCTORADOS_JSON = DATA_RAW_DIR / "doctorados.json"
DOCTORADOS_UPV_JSON = DATA_RAW_DIR / "doctorados_upv.json"
DOCTORADOS_KB_DIR = ESTUDIOS_DIR / "doctorado"
DOCTORADOS_ESTADO = DOCTORADOS_KB_DIR / "_estado.pkl"
DOCTORADOS_INDICE_MD = DOCTORADOS_KB_DIR / "_indice.md"

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
