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
