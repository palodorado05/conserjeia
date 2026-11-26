"""Backend simulado: las tres plataformas viven en data/mock/estado.json.

Sirve para que la app arranque en cualquier portátil sin cuentas ni tokens (modo_plataformas: mock).
Se inicializa con data/bandeja_ejemplo.json (correos de vecinos, incidencias y citas ya existentes).
"""
from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime

from ..config import ruta

ESTADO = ruta("data/mock/estado.json")
SEMILLA = ruta("data/bandeja_ejemplo.json")
_lock = threading.Lock()


def reiniciar() -> None:
    ESTADO.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(SEMILLA, ESTADO)
    p = ruta("data/procesados.json")
    if p.exists():
        p.unlink()


class BackendMock:
    def __init__(self):
        if not ESTADO.exists():
            reiniciar()

    def _leer(self) -> dict:
        return json.loads(ESTADO.read_text(encoding="utf-8"))

    def _guardar(self, e: dict) -> None:
        ESTADO.write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")

    def ejecutar(self, herramienta: str, args: dict):
        with _lock:
            e = self._leer()
            r = getattr(self, herramienta.replace(".", "_"))(e, **args)
            self._guardar(e)
            return r

    # --- correo -------------------------------------------------------------
    def correo_leer(self, e):
        return [dict(c) for c in e["correos"]]

    def correo_escribir(self, e, para, asunto, cuerpo, en_respuesta_a=None):
        n = f"ENV-{len(e['enviados']) + 1:04d}"
        e["enviados"].append({"id": n, "para": para, "asunto": asunto, "cuerpo": cuerpo,
                              "en_respuesta_a": en_respuesta_a, "fecha": datetime.now().isoformat(timespec="minutes")})
        return {"id": n}

    # --- calendario ---------------------------------------------------------
    def calendario_leer(self, e, desde, hasta):
        return [dict(ev) for ev in e["eventos"] if ev["fin"] > desde and ev["inicio"] < hasta]

    def calendario_escribir(self, e, titulo, inicio, fin, descripcion=""):
        n = f"EV-{len(e['eventos']) + 1:04d}"
        e["eventos"].append({"id": n, "titulo": titulo, "inicio": inicio, "fin": fin, "descripcion": descripcion})
        return {"id": n}

    # --- notion -------------------------------------------------------------
    def notion_leer(self, e, estado=None):
        return [dict(i) for i in e["incidencias"] if estado is None or i["estado"] == estado]

    def notion_escribir(self, e, titulo, categoria, prioridad, vivienda, descripcion):
        n = f"INC-{len(e['incidencias']) + 1:04d}"
        e["incidencias"].append({"id": n, "titulo": titulo, "categoria": categoria, "prioridad": prioridad,
                                 "vivienda": vivienda, "estado": "Abierta", "descripcion": descripcion,
                                 "fecha": datetime.now().date().isoformat()})
        return {"id": n}
