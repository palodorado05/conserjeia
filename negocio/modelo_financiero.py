"""Modelo financiero de Conserje IA.

Entradas MEDIDAS (de la propia app):
  - logs/usage.jsonl           tokens de entrada/salida y ms de cada llamada al LLM, agrupados por sesión
  - logs/coste_construccion.json  tokens de Claude Code usados para construir la app (negocio/coste_construccion.py)
Entradas ESTIMADAS: negocio/supuestos.yaml (cada una con su supuesto).

Salidas: negocio/salida/modelo_financiero.md (tabla con etiqueta MEDIDO / ESTIMACIÓN / CALCULADO)
         negocio/salida/flujo_36_meses.csv
Uso: python -m negocio.modelo_financiero
"""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from statistics import mean, median

import yaml

from app.config import ruta

M, E, C = "MEDIDO", "ESTIMACIÓN", "CALCULADO"


def consumo_medido() -> dict:
    p = ruta("logs/usage.jsonl")
    if not p.exists():
        raise SystemExit("No hay logs/usage.jsonl: usad la app (chat o bandeja) antes de calcular el modelo.")
    ses = defaultdict(lambda: {"in": 0, "out": 0, "ms": 0, "llm": 0})
    for l in p.read_text(encoding="utf-8").splitlines():
        u = json.loads(l)
        if u.get("canal") not in ("chat", "correo") or not u.get("ok", True):
            continue
        s = ses[u["sesion"]]
        s["in"] += u["tokens_in"]; s["out"] += u["tokens_out"]; s["ms"] += u["ms"]; s["llm"] += 1
    v = [s for s in ses.values() if s["llm"] > 0]
    if not v:
        raise SystemExit("logs/usage.jsonl no tiene sesiones de chat/correo con el modelo.")
    return {"n_sesiones": len(v), "in": mean(s["in"] for s in v), "out": mean(s["out"] for s in v),
            "in_mediana": median(s["in"] for s in v), "out_mediana": median(s["out"] for s in v),
            "llm_por_sesion": mean(s["llm"] for s in v), "seg_llm": mean(s["ms"] for s in v) / 1000}


def coste_construccion() -> tuple[float, str]:
    p = ruta("logs/coste_construccion.json")
    if p.exists():
        return json.loads(p.read_text())["coste"]["eur"], M
    return 0.0, "FALTA (ejecutad python -m negocio.coste_construccion)"


def main() -> None:
    s = yaml.safe_load(ruta("negocio/supuestos.yaml").read_text(encoding="utf-8"))
    c = consumo_medido()
    build_eur, build_tag = coste_construccion()
    g = s["gpu"]
    filas: list[tuple[str, str, str, str]] = []
    def f(nombre, valor, etiqueta, nota=""):
        filas.append((nombre, valor, etiqueta, nota))

    # ---------------- consumo por usuario (comunidad) ----------------
    ses_mes = s["viviendas_por_comunidad"] * s["sesiones_por_vivienda_mes"]
    f("Sesiones medidas", f"{c['n_sesiones']}", M, "logs/usage.jsonl, canales chat y correo")
    f("Tokens de entrada por sesión (media / mediana)", f"{c['in']:.0f} / {c['in_mediana']:.0f}", M, "prompt_eval_count de Ollama")
    f("Tokens de salida por sesión (media / mediana)", f"{c['out']:.0f} / {c['out_mediana']:.0f}", M, "eval_count de Ollama, incluye razonamiento (think)")
    f("Llamadas al modelo por sesión", f"{c['llm_por_sesion']:.1f}", M)
    f("Fracción cacheada", "0 %", M, "Ollama no factura caché; se asume 0 (conservador). Reutiliza KV del prefijo, pero no lo reporta")
    f("Segundos de modelo por sesión (máquina de medida)", f"{c['seg_llm']:.1f} s", M)
    f("Sesiones por comunidad y mes", f"{ses_mes:.0f}", E, f"{s['viviendas_por_comunidad']} viviendas x {s['sesiones_por_vivienda_mes']}")
    tok_mes = ses_mes * (c["in"] + c["out"])
    f("Tokens por comunidad y mes", f"{tok_mes:,.0f}", C)

    # ---------------- servidor (modelo abierto) ----------------
    seg_gpu = c["seg_llm"] / s["aceleracion_gpu_vs_medido"]
    capacidad = g["horas_mes"] * 3600 * g["concurrencia"] * g["utilizacion_objetivo"] / seg_gpu
    gpu_mes = g["eur_hora"] * g["horas_mes"]
    coste_sesion = gpu_mes / capacidad
    coste_var_com = coste_sesion * ses_mes
    f("GPU", f"{g['nombre']}, {g['vram_gb']} GB VRAM", E, "qwen3:8b cuantizado ocupa ~5-6 GB")
    f("Factura GPU al mes", f"{gpu_mes:,.0f} €", E, f"{g['eur_hora']} €/h x {g['horas_mes']} h")
    f("Segundos de GPU por sesión", f"{seg_gpu:.1f} s", E, f"medido / {s['aceleracion_gpu_vs_medido']} (aceleración supuesta)")
    f("Capacidad de una GPU", f"{capacidad:,.0f} sesiones/mes", C, f"concurrencia {g['concurrencia']}, utilización {g['utilizacion_objetivo']:.0%}")
    f("Comunidades que caben en una GPU", f"{capacidad / ses_mes:,.0f}", C)
    f("Coste de modelo por sesión (GPU llena)", f"{coste_sesion * 100:.3f} céntimos", C)
    f("Coste de modelo por comunidad y mes (GPU llena)", f"{coste_var_com:.3f} €", C)
    a = s["alternativa_api"]
    api_sesion = (c["in"] * a["usd_mtok_entrada"] + c["out"] * a["usd_mtok_salida"]) / 1e6 * s["cambio_usd_eur"]
    f(f"Mismo consumo con {a['nombre']}", f"{api_sesion * ses_mes:.3f} €/comunidad/mes", C, "comparativa: precio público por token")

    # ---------------- precio y margen ----------------
    precio = s["precio_comunidad_mes_eur"]
    fijos = sum(s["costes_fijos_mes_eur"].values())
    margen_contrib = precio - coste_var_com
    f("Precio por comunidad y mes", f"{precio} €", E)
    f("Margen de contribución por comunidad", f"{margen_contrib:.2f} € ({margen_contrib / precio:.1%})", C, "sin contar la GPU como fijo")
    f("Costes fijos al mes (sin GPU)", f"{fijos} €", E)
    eq_com = math.ceil((fijos + gpu_mes) / margen_contrib)
    f("Punto de equilibrio", f"{eq_com} comunidades", C, "(fijos + 1 GPU) / margen de contribución")

    # ---------------- simulación 36 meses ----------------
    inversion = build_eur + s["inversion_inicial_extra_eur"] + s["horas_equipo_construccion"] * s["coste_hora_equipo_eur"]
    f("Coste de construcción con Claude Code (Opus 5.5)", f"{build_eur:,.2f} €", build_tag, "logs/coste_construccion.json")
    f("Inversión antes del primer euro de ingreso", f"{inversion:,.0f} €", C, "construcción + legal/marca/piloto (estimación)")
    caja, minimo, clientes = -inversion, -inversion, 0.0
    mes_equilibrio = mes_recupera = None
    flujo = []
    for mes in range(1, s["meses_horizonte"] + 1):
        altas = s["comunidades_mes_1"] if mes == 1 else s["altas_nuevas_mes"]
        clientes = clientes * (1 - s["bajas_mensuales"]) + altas
        sesiones = clientes * ses_mes
        n_gpu = max(1, math.ceil(sesiones / capacidad))
        ingresos = clientes * precio
        costes = n_gpu * gpu_mes + fijos + altas * s["cac_eur_por_comunidad"]
        beneficio = ingresos - costes
        caja += beneficio
        minimo = min(minimo, caja)
        if mes_equilibrio is None and beneficio > 0:
            mes_equilibrio = mes
        if mes_recupera is None and caja >= 0:
            mes_recupera = mes
        flujo.append({"mes": mes, "comunidades": round(clientes, 1), "sesiones": round(sesiones), "gpus": n_gpu,
                      "ingresos": round(ingresos), "costes": round(costes), "beneficio": round(beneficio), "caja": round(caja)})
    f("Mes con beneficio mensual positivo", str(mes_equilibrio or "> 36"), C)
    f("Mes en que se recupera la inversión (caja ≥ 0)", str(mes_recupera or "> 36"), C)
    f("Necesidad máxima de caja (lo que hay que poner)", f"{-minimo:,.0f} €", C)
    f("Caja acumulada a 36 meses", f"{caja:,.0f} €", C)
    f("ROI a 3 años sobre el capital necesario", f"{caja / -minimo:.1f}x", C, "caja final / necesidad máxima de caja")

    # ---------------- sensibilidad: proveedor +50 % ----------------
    gpu50 = gpu_mes * 1.5
    eq50 = math.ceil((fijos + gpu50) / (precio - coste_var_com * 1.5))
    f("Si la GPU sube un 50 %: punto de equilibrio", f"{eq50} comunidades", C, f"factura GPU {gpu50:,.0f} €/mes")

    # ---------------- salida ----------------
    out = ruta("negocio/salida")
    out.mkdir(exist_ok=True)
    with open(out / "flujo_36_meses.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(flujo[0]))
        w.writeheader(); w.writerows(flujo)
    md = ["# Modelo financiero — Conserje IA", "",
          "Generado por `python -m negocio.modelo_financiero`. Etiquetas: **MEDIDO** (sale de los logs de la app), "
          "**ESTIMACIÓN** (supuesto de `negocio/supuestos.yaml`), **CALCULADO** (combina los anteriores).", "",
          "| Concepto | Valor | Tipo | Nota |", "|---|---|---|---|"]
    md += [f"| {a} | {b} | {t} | {n} |" for a, b, t, n in filas]
    md += ["", "Flujo mensual completo: `negocio/salida/flujo_36_meses.csv`."]
    (out / "modelo_financiero.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    ancho = max(len(a) for a, *_ in filas)
    for a, b, t, n in filas:
        print(f"{a:<{ancho}}  {b:>28}  [{t}]")
    print(f"\nGuardado en negocio/salida/modelo_financiero.md y flujo_36_meses.csv")


if __name__ == "__main__":
    main()
