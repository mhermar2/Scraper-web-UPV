"""Funciones auxiliares compartidas por los extractores.

Reune la logica que aparecia duplicada (casi) identica en varios de los
notebooks originales: peticiones HTTP con pausa/errores, checkpoints de
progreso en pickle, y extraccion de metadatos por regex.
"""

from __future__ import annotations

import pickle
import re
import time
from pathlib import Path

import requests

from config import HEADERS, PAUSA_RED


def get_response(url: str, headers: dict | None = None, timeout: int = 20, pausa: float = PAUSA_RED):
    """GET con pausa y manejo de errores. Devuelve el objeto Response o None si falla."""
    try:
        r = requests.get(url, headers=headers or HEADERS, timeout=timeout)
        r.raise_for_status()
        time.sleep(pausa)
        return r
    except Exception as e:
        print(f"Error: {url} -> {e}")
        return None


def get(url: str, headers: dict | None = None, timeout: int = 20, pausa: float = PAUSA_RED) -> str | None:
    """Igual que get_response(), pero devuelve directamente el HTML (o None)."""
    r = get_response(url, headers=headers, timeout=timeout, pausa=pausa)
    return r.text if r is not None else None


def get_soup(url: str, headers: dict | None = None, timeout: int = 20, pausa: float = PAUSA_RED):
    """Igual que get(), pero ya parseado con BeautifulSoup."""
    from bs4 import BeautifulSoup

    html = get(url, headers=headers, timeout=timeout, pausa=pausa)
    if html is None:
        return None
    return BeautifulSoup(html, "html.parser")


def cargar_estado(path: Path) -> set:
    """Carga el checkpoint de IDs ya procesados (si existe)."""
    if path.exists():
        with open(path, "rb") as f:
            return pickle.load(f)
    return set()


def guardar_estado(path: Path, procesados: set) -> None:
    """Guarda el checkpoint de IDs ya procesados."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(procesados, f)


def limpiar_texto(texto: str) -> str:
    """Colapsa espacios/saltos de linea repetidos."""
    return re.sub(r"\s+", " ", texto).strip()


def buscar_patron(texto: str, patrones: list[str]) -> str | None:
    """Devuelve el primer grupo capturado por el primer patron que matchee."""
    for p in patrones:
        m = re.search(p, texto, re.I)
        if m:
            return m.group(1).strip()
    return None
