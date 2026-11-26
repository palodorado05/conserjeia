"""Traza de cada sesión y registro de uso (usage) de tokens.

- logs/usage.jsonl  : una línea por llamada al LLM (tokens MEDIDOS por Ollama). Es el "usage" del §2.
- logs/trazas.jsonl : una línea por sesión con todos sus pasos (LLM y herramientas), en orden.

Cada llamada a herramienta guarda qué llamada LLM la decidió (`decidida_por`, la "ida") y en qué
llamada LLM entró su resultado (`consumida_por`, la "vuelta"), para poder decir cuántos tokens costó.
"""
from __future__ import annotations

import contextvars
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import ruta

_actual: contextvars.ContextVar["Traza | None"] = contextvars.ContextVar("traza", default=None)


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _anexar(fichero: str, obj: dict) -> None:
    p = ruta(fichero)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


@dataclass
class Traza:
    canal: str                     # "chat" | "correo" | "bucle" | "eval"
    id: str = field(default_factory=lambda: "S-" + uuid.uuid4().hex[:8])
    inicio: float = field(default_factory=time.time)
    pasos: list[dict] = field(default_factory=list)
    _pendientes: list[dict] = field(default_factory=list)   # herramientas cuyo resultado aún no ha leído un LLM
    _ultimo_llm: int | None = None

    # -- pasos -------------------------------------------------------------
    def llm(self, agente: str, tarea: str, tokens_in: int, tokens_out: int, ms: int,
            think: bool, modelo: str, ok: bool = True, error: str | None = None) -> int:
        n = len(self.pasos) + 1
        paso = {"n": n, "tipo": "llm", "agente": agente, "tarea": tarea, "modelo": modelo,
                "think": think, "tokens_in": tokens_in, "tokens_out": tokens_out, "ms": ms, "ok": ok}
        if error:
            paso["error"] = error
        self.pasos.append(paso)
        # el resultado de las herramientas pendientes ha entrado en ESTA llamada -> "vuelta"
        for h in self._pendientes:
            h["consumida_por"] = n
        self._pendientes.clear()
        self._ultimo_llm = n
        _anexar("logs/usage.jsonl", {"ts": _ahora(), "sesion": self.id, "canal": self.canal, **paso})
        return n

    def herramienta(self, agente: str, herramienta: str, permiso: str, estado: str, ms: int,
                    args: dict | None = None, resumen: str = "", error: str | None = None,
                    plataforma: str = "", modo: str = "") -> dict:
        paso = {"n": len(self.pasos) + 1, "tipo": "herramienta", "agente": agente,
                "herramienta": herramienta, "plataforma": plataforma, "modo": modo,
                "permiso": permiso, "estado": estado, "ms": ms,
                "args": _recortar(args or {}), "resumen": resumen[:300],
                "decidida_por": self._ultimo_llm, "consumida_por": None}
        if error:
            paso["error"] = error[:500]
        self.pasos.append(paso)
        if estado == "ok":
            self._pendientes.append(paso)
        return paso

    def evento(self, tipo: str, **datos) -> None:
        self.pasos.append({"n": len(self.pasos) + 1, "tipo": tipo, **datos})

    # -- cierre ------------------------------------------------------------
    def resumen(self) -> dict:
        llm = [p for p in self.pasos if p["tipo"] == "llm"]
        tin = sum(p["tokens_in"] for p in llm)
        tout = sum(p["tokens_out"] for p in llm)
        pasos = []
        por_n = {p["n"]: p for p in llm}
        for p in self.pasos:
            q = dict(p)
            if p["tipo"] == "herramienta":   # coste de la ida y la vuelta, leído de las llamadas enlazadas
                ida = por_n.get(p.get("decidida_por"))
                vuelta = por_n.get(p.get("consumida_por"))
                q["tokens_ida"] = (ida["tokens_in"] + ida["tokens_out"]) if ida else 0
                q["tokens_vuelta"] = (vuelta["tokens_in"] + vuelta["tokens_out"]) if vuelta else 0
            pasos.append(q)
        return {"sesion": self.id, "canal": self.canal, "ts": _ahora(),
                "duracion_ms": int((time.time() - self.inicio) * 1000),
                "llamadas_llm": len(llm), "tokens_in": tin, "tokens_out": tout,
                "herramientas": sum(1 for p in self.pasos if p["tipo"] == "herramienta"),
                "fallos": sum(1 for p in self.pasos if p.get("estado") in ("error", "denegado")),
                "pasos": pasos}

    def cerrar(self) -> dict:
        r = self.resumen()
        _anexar("logs/trazas.jsonl", r)
        return r


def _recortar(d: dict) -> dict:
    return {k: (v[:120] + "…" if isinstance(v, str) and len(v) > 120 else v) for k, v in d.items()}


def actual() -> Traza | None:
    return _actual.get()


class sesion:
    """with sesion("chat") as t: ...  -> todas las llamadas dentro quedan en la traza t."""

    def __init__(self, canal: str):
        self.t = Traza(canal)

    def __enter__(self) -> Traza:
        self._tok = _actual.set(self.t)
        return self.t

    def __exit__(self, *exc) -> None:
        _actual.reset(self._tok)
