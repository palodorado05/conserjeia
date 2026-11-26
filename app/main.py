"""Servidor web (FastAPI). Arranque: `python -m app`  ->  http://localhost:8000

El chat y el procesado de la bandeja se ejecutan en un hilo aparte ("trabajo") y la web consulta su
progreso cada segundo: así se ven los pasos de los agentes en directo aunque el modelo tarde.
"""
from __future__ import annotations

import json
import threading
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import llm, orquestador, traza
from .config import cfg, ruta
from .tools import plataformas as P

app = FastAPI(title="Conserje IA")
app.mount("/static", StaticFiles(directory=ruta("app/static")), name="static")

TRABAJOS: dict[str, dict] = {}
HISTORIAL: dict[str, list[dict]] = defaultdict(list)


# ---------------------------------------------------------------------------
# Trabajos en segundo plano
# ---------------------------------------------------------------------------
def _lanzar(tipo: str, funcion) -> str:
    tid = uuid.uuid4().hex[:10]
    TRABAJOS[tid] = {"id": tid, "tipo": tipo, "estado": "en_curso", "pasos": [], "resultado": None}

    def correr():
        try:
            TRABAJOS[tid]["resultado"] = funcion(TRABAJOS[tid])
            TRABAJOS[tid]["estado"] = "hecho"
        except Exception as e:          # nunca dejar la web colgada
            TRABAJOS[tid]["estado"] = "error"
            TRABAJOS[tid]["resultado"] = {"error": f"{type(e).__name__}: {e}"}

    threading.Thread(target=correr, daemon=True).start()
    return tid


@app.get("/api/trabajo/{tid}")
def trabajo(tid: str):
    t = TRABAJOS.get(tid)
    if not t:
        raise HTTPException(404)
    vivo = t.get("_traza")
    pasos = vivo.pasos if vivo else t["pasos"]
    return {k: v for k, v in t.items() if not k.startswith("_")} | {"pasos": pasos[-30:]}


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
class Chat(BaseModel):
    mensaje: str
    conversacion: str = "web"
    nombre: str = ""
    vivienda: str = ""
    email: str = ""


@app.post("/api/chat")
def chat(c: Chat):
    if not c.mensaje.strip():
        raise HTTPException(400, "mensaje vacío")

    def tarea(job):
        with traza.sesion("chat") as t:
            job["_traza"] = t
            rem = {"nombre": c.nombre, "vivienda": c.vivienda, "email": c.email}
            r = orquestador.procesar(c.mensaje, rem, canal="chat", historial=HISTORIAL[c.conversacion])
            s = t.cerrar()
        job["pasos"], job["_traza"] = s["pasos"], None
        HISTORIAL[c.conversacion] += [{"rol": "vecino", "texto": c.mensaje}, {"rol": "conserje", "texto": r["respuesta"]}]
        return {**r, "traza": s}

    return {"trabajo": _lanzar("chat", tarea)}


# ---------------------------------------------------------------------------
# Bandeja de correo
# ---------------------------------------------------------------------------
@app.post("/api/bandeja/procesar")
def bandeja_procesar():
    return {"trabajo": _lanzar("bandeja", lambda job: orquestador.procesar_bandeja())}


def _panel(herramienta: str, **args):
    """Lectura para los paneles de la web (vista del administrador, no la hace un agente: no va a la traza)."""
    try:
        return P.backend().ejecutar(herramienta, args)
    except Exception as e:
        raise HTTPException(503, f"{herramienta}: {e}")


@app.get("/api/bandeja")
def bandeja():
    hechos = orquestador._procesados()
    return [{**c, "procesado": c["id"] in hechos} for c in _panel("correo.leer")]


@app.get("/api/enviados")
def enviados():
    if cfg()["modo_plataformas"] != "mock":
        return []
    return json.loads(ruta("data/mock/estado.json").read_text(encoding="utf-8"))["enviados"][::-1]


@app.get("/api/incidencias")
def incidencias():
    return sorted(_panel("notion.leer"), key=lambda i: i.get("fecha", ""), reverse=True)


@app.get("/api/agenda")
def agenda():
    hoy = datetime.now()
    return sorted(_panel("calendario.leer", desde=(hoy - timedelta(days=1)).isoformat(timespec="minutes"),
                         hasta=(hoy + timedelta(days=30)).isoformat(timespec="minutes")), key=lambda e: e["inicio"])


# ---------------------------------------------------------------------------
# Trazas, escalados, uso y análisis
# ---------------------------------------------------------------------------
def _jsonl(rel: str, n: int | None = None) -> list[dict]:
    p = ruta(rel)
    if not p.exists():
        return []
    filas = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return filas[-n:][::-1] if n else filas


@app.get("/api/trazas")
def trazas(n: int = 15):
    return _jsonl("logs/trazas.jsonl", n)


@app.get("/api/escalados")
def escalados(n: int = 30):
    return _jsonl("logs/escalados.jsonl", n)


@app.get("/api/analisis")
def analisis():
    """Análisis de datos dentro del producto: qué se rompe, cada cuánto, y qué decisión cambia."""
    incs = _panel("notion.leer")
    hoy = date.today()
    recientes = [i for i in incs if i.get("fecha") and (hoy - date.fromisoformat(i["fecha"][:10])).days <= 90]
    por_cat = Counter(i["categoria"] for i in recientes)
    recomendaciones = []
    for cat, n in por_cat.most_common():
        if n >= 3:
            recomendaciones.append(f"«{cat}» acumula {n} avisos en 90 días: proponer en la próxima junta una revisión "
                                   f"preventiva o un contrato de mantenimiento en lugar de pagar reparaciones sueltas.")
    if not recomendaciones:
        recomendaciones.append("Ninguna categoría supera 3 avisos en 90 días: no hace falta cambiar contratos.")
    sesiones = _jsonl("logs/trazas.jsonl")
    chat_correo = [s for s in sesiones if s["canal"] in ("chat", "correo") and s["llamadas_llm"] > 0]
    esc = _jsonl("logs/escalados.jsonl")
    return {
        "incidencias_90d": len(recientes),
        "abiertas": sum(1 for i in incs if i["estado"] != "Cerrada"),
        "por_categoria": dict(por_cat.most_common()),
        "por_mes": dict(sorted(Counter(i["fecha"][:7] for i in incs if i.get("fecha")).items())),
        "regla": "categoría con ≥ 3 avisos en 90 días -> recomendar mantenimiento preventivo",
        "recomendaciones": recomendaciones,
        "sesiones": len(chat_correo),
        "tokens_medios_in": round(sum(s["tokens_in"] for s in chat_correo) / max(len(chat_correo), 1)),
        "tokens_medios_out": round(sum(s["tokens_out"] for s in chat_correo) / max(len(chat_correo), 1)),
        "segundos_medios": round(sum(s["duracion_ms"] for s in chat_correo) / max(len(chat_correo), 1) / 1000, 1),
        "escalados": len(esc),
        "escalados_por_motivo": dict(Counter(e["motivo"].split(":")[0].split("(")[0].strip() for e in esc).most_common()),
    }


# ---------------------------------------------------------------------------
# Estado y controles de la demo
# ---------------------------------------------------------------------------
@app.get("/api/estado")
def estado():
    from .rag.indice import indice
    try:
        rag = {"modo": indice().modo, "trozos": len(indice().trozos)}
    except FileNotFoundError as e:
        rag = {"modo": "sin corpus", "error": str(e)}
    return {"llm": llm.disponible(), "modo_plataformas": cfg()["modo_plataformas"], "caidas": sorted(P.caidas()),
            "comunidad": cfg()["comunidad"]["nombre"], "rag": rag,
            "esfuerzo": {k: v["think"] for k, v in cfg()["esfuerzo"].items()}}


class Caida(BaseModel):
    plataforma: str
    caida: bool


@app.post("/api/caida")
def caida(c: Caida):
    if c.plataforma not in ("outlook", "google", "notion"):
        raise HTTPException(400)
    return {"caidas": sorted(P.simular_caida(c.plataforma, c.caida))}


@app.post("/api/reiniciar")
def reiniciar():
    if cfg()["modo_plataformas"] != "mock":
        raise HTTPException(400, "sólo en modo mock")
    from .tools.mock_backend import reiniciar as r
    r()
    HISTORIAL.clear()
    return {"ok": True}


@app.get("/")
def inicio():
    return FileResponse(ruta("app/static/index.html"))
