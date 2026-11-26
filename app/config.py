"""Carga config.yaml (y .env si existe) una sola vez y lo expone como diccionario."""
from __future__ import annotations

import os
import random
import re
from functools import lru_cache
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent


def _cargar_env() -> None:
    """Lee un .env sencillo (CLAVE=valor) sin dependencias externas. No pisa variables ya definidas."""
    env = RAIZ / ".env"
    if not env.exists():
        return
    for linea in env.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def expandir(valor: str) -> str:
    """Sustituye ${VAR} por la variable de entorno (cadena vacía si no existe)."""
    return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), valor)


@lru_cache(maxsize=1)
def cfg() -> dict:
    _cargar_env()
    with open(RAIZ / "config.yaml", encoding="utf-8") as f:
        c = yaml.safe_load(f)
    # Permite cambiar el modo sin tocar el fichero: MODO_PLATAFORMAS=mcp python -m app
    c["modo_plataformas"] = os.environ.get("MODO_PLATAFORMAS", c["modo_plataformas"])
    c["ollama"]["url"] = os.environ.get("OLLAMA_URL", c["ollama"]["url"])
    c["ollama"]["modelo"] = os.environ.get("OLLAMA_MODELO", c["ollama"]["modelo"])
    random.seed(c["semilla"])
    return c


def ruta(rel: str) -> Path:
    return RAIZ / rel
