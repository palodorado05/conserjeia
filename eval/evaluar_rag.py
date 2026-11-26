"""Evaluación del RAG sobre la LPH con preguntas anotadas (eval/preguntas.jsonl).

Métricas (todas MEDIDAS sobre este conjunto):
  - acierto@3            : % de preguntas de dominio con algún artículo esperado entre los 3 recuperados
                           (se mide SIN aplicar abstención: calidad pura del recuperador)
  - abstención correcta  : % de preguntas fuera de dominio en las que el sistema dice "no lo sé"
  - abstención indebida  : % de preguntas de dominio en las que se abstiene (respuestas perdidas)
  - acierto@3 efectivo   : acierto@3 contando como fallo las abstenciones indebidas
Además barre el umbral de abstención para justificar el valor de config.yaml.
OJO: el umbral se elige sobre este mismo conjunto (no hay conjunto de validación aparte): decidlo así en la memoria.

Uso:  python -m eval.evaluar_rag                # híbrido (RRF), denso (embeddings) y léxico (BM25)
      python -m eval.evaluar_rag --con-llm      # además, el agente legal completo (cita en la respuesta)
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime

import numpy as np

from app.config import cfg, ruta
from app.rag.indice import construir


def cargar() -> list[dict]:
    with open(ruta("eval/preguntas.jsonl"), encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def evaluar_modo(ix, preguntas, modo: str) -> dict:
    filas = []
    for p in preguntas:
        r = ix.buscar(p["pregunta"], k=3, modo=modo)
        citas = [x["cita"] for x in r["resultados"]]
        filas.append({"id": p["id"], "dominio": bool(p["esperado"]), "citas": citas, "mejor": r["mejor"],
                      "acierto": bool(set(citas) & set(p["esperado"])), "abstiene": r["abstiene"],
                      "modo_real": r["modo"]})
    umbral = r["umbral"]
    dom = [f for f in filas if f["dominio"]]
    fuera = [f for f in filas if not f["dominio"]]
    res = {
        "modo": filas[0]["modo_real"], "umbral": umbral, "n_dominio": len(dom), "n_fuera": len(fuera),
        "acierto@3": round(np.mean([f["acierto"] for f in dom]), 3),
        "abstencion_correcta": round(np.mean([f["abstiene"] for f in fuera]), 3) if fuera else None,
        "abstencion_indebida": round(np.mean([f["abstiene"] for f in dom]), 3),
        "acierto@3_efectivo": round(np.mean([f["acierto"] and not f["abstiene"] for f in dom]), 3),
        "fallos": [{"id": f["id"], "citas": f["citas"], "mejor": f["mejor"]} for f in dom if not f["acierto"]],
    }
    # barrido de umbral: dónde se separan mejor las de dominio y las de fuera
    barrido = []
    for u in sorted({round(f["mejor"], 2) for f in filas}):
        ok_fuera = np.mean([f["mejor"] < u for f in fuera]) if fuera else 0
        ok_dom = np.mean([f["acierto"] and f["mejor"] >= u for f in dom])
        barrido.append({"umbral": u, "acierto@3_efectivo": round(ok_dom, 3), "abstencion_correcta": round(ok_fuera, 3),
                        "balance": round((ok_dom + ok_fuera) / 2, 3)})
    res["mejor_umbral"] = max(barrido, key=lambda b: (b["balance"], b["acierto@3_efectivo"]))
    res["detalle"] = filas
    return res


def evaluar_llm(preguntas) -> dict:
    """Agente legal completo: ¿cita un artículo correcto? ¿se abstiene fuera de dominio?"""
    from app.agents import legal
    from app import traza
    filas = []
    for p in preguntas:
        with traza.sesion("eval") as t:
            r = legal.responder(p["pregunta"])
            s = t.cerrar()
        filas.append({"id": p["id"], "dominio": bool(p["esperado"]), "citas": r["citas"],
                      "abstiene": r["abstiene"], "acierto": bool(set(r["citas"]) & set(p["esperado"])),
                      "tokens_in": s["tokens_in"], "tokens_out": s["tokens_out"], "ms": s["duracion_ms"]})
        print(f"  [{p['id']}] abst={r['abstiene']} citas={r['citas']}")
    dom = [f for f in filas if f["dominio"]]
    fuera = [f for f in filas if not f["dominio"]]
    return {"cita_correcta": round(np.mean([f["acierto"] for f in dom]), 3),
            "abstencion_correcta": round(np.mean([f["abstiene"] for f in fuera]), 3),
            "abstencion_indebida": round(np.mean([f["abstiene"] for f in dom]), 3),
            "tokens_in_medios": round(np.mean([f["tokens_in"] for f in filas]), 1),
            "tokens_out_medios": round(np.mean([f["tokens_out"] for f in filas]), 1),
            "detalle": filas}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--con-llm", action="store_true")
    a = ap.parse_args()
    preguntas = cargar()
    ix = construir()
    salida = {"fecha": datetime.now().isoformat(timespec="seconds"), "modelo_embeddings": cfg()["ollama"]["modelo_embeddings"],
              "n_trozos": len(ix.trozos), "modos": {}}
    for modo in (["hibrido", "denso", "lexico"] if ix.matriz is not None else ["lexico"]):
        r = evaluar_modo(ix, preguntas, modo)
        salida["modos"][modo] = r
        print(f"\n== {modo.upper()} (umbral {r['umbral']}) ==")
        for k in ("acierto@3", "abstencion_correcta", "abstencion_indebida", "acierto@3_efectivo"):
            print(f"  {k:22s} {r[k]}")
        print(f"  umbral óptimo en este conjunto: {r['mejor_umbral']}")
        if r["fallos"]:
            print(f"  fallos de recuperación: {r['fallos']}")
    if a.con_llm:
        print("\n== AGENTE LEGAL COMPLETO (LLM) ==")
        salida["llm"] = evaluar_llm(preguntas)
        for k, v in salida["llm"].items():
            if k != "detalle":
                print(f"  {k:22s} {v}")
    out = ruta("eval/resultados_rag.json")
    out.write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nGuardado en {out.relative_to(ruta('.'))}")


if __name__ == "__main__":
    main()
