"""Cliente mínimo de Ollama (API REST, sin SDK).

Cada llamada:
  - usa la semilla fija y la temperatura del tipo de tarea (config.yaml -> esfuerzo),
  - activa o no el razonamiento (`think`) según el tipo de tarea,
  - registra los tokens que DEVUELVE Ollama (prompt_eval_count / eval_count) en la traza y en
    logs/usage.jsonl. Esos son los tokens MEDIDOS que usa el modelo financiero.

Si Ollama no responde se lanza LLMNoDisponible: los agentes la capturan y pasan a modo degradado
(reglas + extractos literales), para que la app siga funcionando y lo diga.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

import httpx

from .config import cfg
from . import traza


class LLMNoDisponible(RuntimeError):
    pass


@dataclass
class Respuesta:
    texto: str
    razonamiento: str
    tokens_in: int
    tokens_out: int
    ms: int

    def json(self) -> dict:
        return extraer_json(self.texto)


def disponible() -> dict:
    """Estado de Ollama y de los modelos necesarios (para la cabecera de la web)."""
    c = cfg()["ollama"]
    try:
        r = httpx.get(f"{c['url']}/api/tags", timeout=3)
        nombres = {m["name"] for m in r.json().get("models", [])}
        def tiene(m: str) -> bool:
            return m in nombres or f"{m}:latest" in nombres
        return {"ollama": True, "modelo": c["modelo"], "modelo_ok": tiene(c["modelo"]),
                "embeddings_ok": tiene(c["modelo_embeddings"])}
    except Exception:
        return {"ollama": False, "modelo": c["modelo"], "modelo_ok": False, "embeddings_ok": False}


def chat(agente: str, tarea: str, mensajes: list[dict], *, json_salida: bool = False) -> Respuesta:
    """Llama al modelo con el esfuerzo configurado para `tarea` (router, legal, ...)."""
    c = cfg()
    oc = c["ollama"]
    esf = c["esfuerzo"][tarea]
    cuerpo = {
        "model": oc["modelo"],
        "messages": mensajes,
        "stream": False,
        "think": esf["think"],
        "options": {"seed": c["semilla"], "temperature": esf["temperatura"], "num_ctx": oc["num_ctx"]},
    }
    if json_salida:
        cuerpo["format"] = "json"
    t0 = time.time()
    t = traza.actual()
    try:
        r = httpx.post(f"{oc['url']}/api/chat", json=cuerpo, timeout=oc["timeout_s"])
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        ms = int((time.time() - t0) * 1000)
        if t:
            t.llm(agente, tarea, 0, 0, ms, esf["think"], oc["modelo"], ok=False, error=str(e)[:200])
        raise LLMNoDisponible(str(e)) from e
    ms = int((time.time() - t0) * 1000)
    msg = d.get("message", {})
    resp = Respuesta(
        texto=_limpiar(msg.get("content", "")),
        razonamiento=msg.get("thinking", "") or "",
        tokens_in=int(d.get("prompt_eval_count", 0)),
        tokens_out=int(d.get("eval_count", 0)),
        ms=ms,
    )
    if t:
        t.llm(agente, tarea, resp.tokens_in, resp.tokens_out, ms, esf["think"], oc["modelo"])
    return resp


def embeddings(textos: list[str]) -> list[list[float]]:
    oc = cfg()["ollama"]
    try:
        r = httpx.post(f"{oc['url']}/api/embed",
                       json={"model": oc["modelo_embeddings"], "input": textos}, timeout=oc["timeout_s"])
        r.raise_for_status()
        return r.json()["embeddings"]
    except Exception as e:
        raise LLMNoDisponible(str(e)) from e


def _limpiar(texto: str) -> str:
    # por si alguna versión devuelve el razonamiento dentro del contenido
    return re.sub(r"<think>.*?</think>", "", texto, flags=re.S).strip()


def extraer_json(texto: str) -> dict:
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", texto, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {}
