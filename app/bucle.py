"""Tarea en BUCLE: vigila la bandeja de Outlook y procesa los correos nuevos sin que nadie pulse nada.

Qué se repite : leer la bandeja -> procesar cada correo nuevo con los agentes -> responder.
Cada cuánto   : --cada segundos (por defecto 300 = 5 min).
Condiciones de parada (la primera que se cumpla):
  1. --vueltas N        número máximo de vueltas;
  2. --presupuesto T    tokens totales gastados por el bucle (suma MEDIDA de logs de esta ejecución);
  3. 3 vueltas seguidas con error (p. ej. Outlook caído): se para y lo deja escrito;
  4. existe el fichero STOP en la raíz del proyecto (interruptor manual: `touch STOP`);
  5. Ctrl+C.
Freno anti-desbocamiento: como mucho --max-correos por vuelta (si entra una avalancha, no se gasta
todo de golpe), y cada vuelta registra su coste en logs/bucle.jsonl.

Uso: python -m app.bucle --cada 300 --vueltas 100 --presupuesto 200000
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime

from . import orquestador
from .config import ruta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cada", type=int, default=300)
    ap.add_argument("--vueltas", type=int, default=100)
    ap.add_argument("--presupuesto", type=int, default=200_000, help="tokens máximos (entrada+salida)")
    ap.add_argument("--max-correos", type=int, default=10)
    a = ap.parse_args()
    stop = ruta("STOP")
    gastado, errores_seguidos = 0, 0
    print(f"Bucle: cada {a.cada}s · máx {a.vueltas} vueltas · presupuesto {a.presupuesto:,} tokens · `touch STOP` para parar")
    motivo = "vueltas agotadas"
    for vuelta in range(1, a.vueltas + 1):
        if stop.exists():
            motivo = "fichero STOP"
            break
        t0 = time.time()
        res = orquestador.procesar_bandeja(maximo=a.max_correos)
        error = any("error" in r for r in res)
        tokens = sum(r["traza"]["tokens_in"] + r["traza"]["tokens_out"] for r in res if "traza" in r)
        gastado += tokens
        errores_seguidos = errores_seguidos + 1 if error else 0
        reg = {"ts": datetime.now().isoformat(timespec="seconds"), "vuelta": vuelta, "correos": len([r for r in res if "traza" in r]),
               "tokens": tokens, "acumulado": gastado, "error": error, "seg": round(time.time() - t0, 1)}
        with open(ruta("logs/bucle.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(reg) + "\n")
        print(reg)
        if gastado >= a.presupuesto:
            motivo = f"presupuesto de tokens agotado ({gastado:,})"
            break
        if errores_seguidos >= 3:
            motivo = "3 vueltas seguidas con error"
            break
        try:
            time.sleep(a.cada)
        except KeyboardInterrupt:
            motivo = "Ctrl+C"
            break
    print(f"Bucle detenido: {motivo}")


if __name__ == "__main__":
    main()
