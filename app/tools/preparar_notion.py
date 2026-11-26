"""Crea la base de datos "Incidencias" en Notion y guarda su id en .env (NOTION_DATA_SOURCE_ID).

Requisitos: NOTION_TOKEN en .env y una página de Notion compartida con la integración
(en la página: "..." -> Conexiones -> Conserje IA).
Uso: python -m app.tools.preparar_notion
"""
from __future__ import annotations

import os
import re
import sys

import httpx

from ..config import RAIZ, cfg

API = "https://api.notion.com/v1"
VERSION = "2025-09-03"     # versión con "data sources" (la que usa el servidor MCP oficial)


def _guardar_env(clave: str, valor: str) -> None:
    env = RAIZ / ".env"
    texto = env.read_text(encoding="utf-8") if env.exists() else ""
    if re.search(rf"^{clave}=.*$", texto, flags=re.M):
        texto = re.sub(rf"^{clave}=.*$", f"{clave}={valor}", texto, flags=re.M)
    else:
        texto = texto.rstrip("\n") + f"\n{clave}={valor}\n"
    env.write_text(texto, encoding="utf-8")


def main() -> None:
    cfg()   # carga .env
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        sys.exit("Falta NOTION_TOKEN en el fichero .env")
    h = {"Authorization": f"Bearer {token}", "Notion-Version": VERSION, "Content-Type": "application/json"}
    if os.environ.get("NOTION_DATA_SOURCE_ID"):
        print("NOTION_DATA_SOURCE_ID ya está en .env: no se crea otra base de datos.")
        return
    r = httpx.post(f"{API}/search", headers=h, json={"filter": {"property": "object", "value": "page"}}, timeout=30)
    if r.status_code == 401:
        sys.exit("Notion rechaza el token: revisad NOTION_TOKEN en .env")
    paginas = r.json().get("results", [])
    if not paginas:
        sys.exit("La integración no ve ninguna página. En Notion, abrid la página 'Conserje IA' -> '...' -> "
                 "Conexiones -> añadid 'Conserje IA', y volved a ejecutar.")
    padre = paginas[0]["id"]

    def sel(*ops):
        return {"select": {"options": [{"name": o} for o in ops]}}
    cuerpo = {
        "parent": {"type": "page_id", "page_id": padre},
        "title": [{"type": "text", "text": {"content": "Incidencias"}}],
        "initial_data_source": {"properties": {
            "Nombre": {"title": {}},
            "Categoría": sel("fontaneria", "electricidad", "ascensor", "cerrajeria", "antena", "limpieza", "ruidos", "obras", "otros"),
            "Prioridad": sel("alta", "media", "baja"),
            "Vivienda": {"rich_text": {}},
            "Estado": sel("Abierta", "En curso", "Cerrada"),
            "Descripción": {"rich_text": {}},
            "Fecha": {"date": {}},
        }},
    }
    r = httpx.post(f"{API}/databases", headers=h, json=cuerpo, timeout=30)
    if r.status_code >= 300:
        sys.exit(f"Notion no pudo crear la base de datos: {r.status_code} {r.text[:300]}")
    d = r.json()
    fuentes = d.get("data_sources") or []
    ds = fuentes[0]["id"] if fuentes else d["id"]
    _guardar_env("NOTION_DATA_SOURCE_ID", ds)
    print(f"Base de datos 'Incidencias' creada en Notion. Id guardado en .env ({ds[:8]}…).")


if __name__ == "__main__":
    main()
