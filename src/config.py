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
