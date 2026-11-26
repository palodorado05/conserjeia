"""Coste de CONSTRUIR la app, leído del usage real de Claude Code (no estimado a ojo).

Claude Code guarda cada sesión en ~/.claude/projects/<proyecto>/<sesion>.jsonl; cada respuesta del
modelo lleva su bloque `usage` (input_tokens, output_tokens, cache_creation_input_tokens,
cache_read_input_tokens). Este script los suma (sin duplicar mensajes) y les pone precio.

Uso:
  python -m negocio.coste_construccion                       # busca en ~/.claude/projects
  python -m negocio.coste_construccion --dir RUTA [--dir RUTA2]   # carpetas de cada miembro del grupo
  python -m negocio.coste_construccion --filtro conserje     # sólo proyectos cuyo nombre contenga "conserje"
Cada miembro ejecuta el script en su portátil y se suman los JSON de logs/ (opción --sumar).
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import yaml

from app.config import ruta


def leer(dirs: list[Path], filtro: str = "") -> dict:
    vistos, tot = set(), defaultdict(int)
    por_modelo = defaultdict(lambda: defaultdict(int))
    sesiones = set()
    for d in dirs:
        for f in d.rglob("*.jsonl"):
            if filtro and filtro not in str(f):
                continue
            for linea in f.open(encoding="utf-8", errors="ignore"):
                try:
                    e = json.loads(linea)
                except json.JSONDecodeError:
                    continue
                m = e.get("message") or {}
                u = m.get("usage") if isinstance(m, dict) else None
                if not u:
                    continue
                clave = (m.get("id"), e.get("requestId"))
                if clave in vistos:        # una misma respuesta aparece en varias líneas (un bloque por línea)
                    continue
                vistos.add(clave)
                sesiones.add(e.get("sessionId"))
                for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
                    tot[k] += int(u.get(k) or 0)
                    por_modelo[m.get("model", "?")][k] += int(u.get(k) or 0)
    return {"respuestas": len(vistos), "sesiones": len(sesiones - {None}), "tokens": dict(tot),
            "por_modelo": {k: dict(v) for k, v in por_modelo.items()}}


def precio(tokens: dict, s: dict) -> dict:
    p = s["precio_opus_5_5_usd_por_mtok"]
    usd = (tokens.get("input_tokens", 0) * p["entrada"] + tokens.get("output_tokens", 0) * p["salida"]
           + tokens.get("cache_creation_input_tokens", 0) * p["cache_escritura"]
           + tokens.get("cache_read_input_tokens", 0) * p["cache_lectura"]) / 1e6
    return {"usd": round(usd, 2), "eur": round(usd * s["cambio_usd_eur"], 2)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", action="append", type=Path)
    ap.add_argument("--filtro", default="")
    ap.add_argument("--sumar", nargs="*", type=Path, help="suma varios coste_construccion*.json de miembros")
    a = ap.parse_args()
    s = yaml.safe_load(ruta("negocio/supuestos.yaml").read_text(encoding="utf-8"))
    if a.sumar:
        tot = defaultdict(int)
        for f in a.sumar:
            for k, v in json.loads(f.read_text())["tokens"].items():
                tot[k] += v
        r = {"fuente": [str(f) for f in a.sumar], "tokens": dict(tot)}
    else:
        dirs = a.dir or [Path.home() / ".claude" / "projects"]
        r = {"fuente": [str(d) for d in dirs], **leer(dirs, a.filtro)}
    r["coste"] = precio(r["tokens"], s)
    r["precios_usd_mtok"] = s["precio_opus_5_5_usd_por_mtok"]
    t = r["tokens"]
    total_in = t.get("input_tokens", 0) + t.get("cache_creation_input_tokens", 0) + t.get("cache_read_input_tokens", 0)
    r["fraccion_cacheada_entrada"] = round(t.get("cache_read_input_tokens", 0) / max(total_in, 1), 3)
    out = ruta("logs/coste_construccion.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(r, indent=1), encoding="utf-8")
    print(json.dumps(r, indent=1))
    print(f"\nGuardado en {out}. Este importe entra en la inversión inicial del modelo financiero.")


if __name__ == "__main__":
    main()
