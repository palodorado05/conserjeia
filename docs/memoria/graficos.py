"""Genera los gráficos SVG de la memoria a partir de los datos MEDIDOS del repositorio.

- caja.svg   : caja acumulada a 36 meses (negocio/salida/flujo_36_meses.csv)
- tokens.svg : tokens de entrada/salida por agente en la sesión real S-687407ba (logs/trazas.jsonl)
Uso: python docs/memoria/graficos.py
"""
import csv
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
AZUL, AMBAR = "#2F5D9E", "#C27A1A"          # validados con el validador de paletas (CVD y contraste)
TINTA, SUAVE, REJILLA = "#1F2A44", "#6B7280", "#E5E1D8"
FUENTE = "font-family:'Inter',sans-serif"


def caja() -> str:
    filas = list(csv.DictReader(open(RAIZ / "negocio/salida/flujo_36_meses.csv", encoding="utf-8")))
    xs = [int(f["mes"]) for f in filas]
    ys = [float(f["caja"]) for f in filas]
    W, H, ml, mr, mt, mb = 640, 230, 58, 30, 22, 34
    y0, y1 = -15000, 55000
    def X(m): return ml + (m - 1) / 35 * (W - ml - mr)
    def Y(v): return mt + (y1 - v) / (y1 - y0) * (H - mt - mb)
    s = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" '
         f'aria-label="Caja acumulada por mes, de -10.778 € en el peor mes a {ys[-1]:,.0f} € en el mes 36">']
    for v in range(-10000, 50001, 10000):
        s.append(f'<line x1="{ml}" x2="{W-mr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{REJILLA if v else SUAVE}" stroke-width="{1 if v else 1.2}"/>')
        s.append(f'<text x="{ml-8}" y="{Y(v)+4:.1f}" text-anchor="end" font-size="11" fill="{SUAVE}" style="{FUENTE}">{v/1000:,.0f}k €</text>')
    for m in (1, 6, 12, 18, 24, 30, 36):
        s.append(f'<text x="{X(m):.1f}" y="{H-12}" text-anchor="middle" font-size="11" fill="{SUAVE}" style="{FUENTE}">mes {m}</text>')
    pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in zip(xs, ys))
    s.append(f'<polyline points="{pts}" fill="none" stroke="{AZUL}" stroke-width="2.2" stroke-linejoin="round"/>')
    imin = min(range(len(ys)), key=lambda i: ys[i])
    irec = next(i for i, v in enumerate(ys) if v >= 0)
    for i, txt, dy in ((imin, f"peor mes: {ys[imin]:,.0f} €".replace(",", "."), 18), (irec, f"mes {xs[irec]}: se recupera la inversión", 20),
                       (len(ys) - 1, f"{ys[-1]:,.0f} €".replace(",", "."), -12)):
        anchor = "end" if i == len(ys) - 1 else "start"
        s.append(f'<circle cx="{X(xs[i]):.1f}" cy="{Y(ys[i]):.1f}" r="4" fill="{AZUL}" stroke="#fff" stroke-width="2"/>')
        s.append(f'<text x="{X(xs[i]) + (6 if anchor == "start" else 0):.1f}" y="{Y(ys[i]) + dy:.1f}" text-anchor="{anchor}" '
                 f'font-size="11.5" fill="{TINTA}" style="{FUENTE};font-weight:600">{txt}</text>')
    s.append("</svg>")
    return "\n".join(s)


def tokens() -> str:
    ses = [json.loads(l) for l in open(RAIZ / "logs/trazas.jsonl", encoding="utf-8")]
    s0 = next(x for x in ses if x["sesion"] == "S-687407ba")
    filas = [(p["agente"].capitalize() + (" (razona)" if p["think"] else ""), p["tokens_in"], p["tokens_out"])
             for p in s0["pasos"] if p["tipo"] == "llm"]
    W, fila_h, ml, mr, mt = 640, 34, 150, 70, 30
    H = mt + fila_h * len(filas) + 8
    mx = max(a + b for _, a, b in filas)
    def L(v): return v / mx * (W - ml - mr)
    s = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Tokens de entrada y salida por agente">',
         f'<rect x="{ml}" y="6" width="12" height="12" rx="2" fill="{AZUL}"/><text x="{ml+18}" y="16" font-size="11.5" fill="{TINTA}" style="{FUENTE}">tokens de entrada</text>',
         f'<rect x="{ml+140}" y="6" width="12" height="12" rx="2" fill="{AMBAR}"/><text x="{ml+158}" y="16" font-size="11.5" fill="{TINTA}" style="{FUENTE}">tokens de salida (incluye razonamiento)</text>']
    for i, (nom, a, b) in enumerate(filas):
        y = mt + i * fila_h
        s.append(f'<text x="{ml-10}" y="{y+17}" text-anchor="end" font-size="12" fill="{TINTA}" style="{FUENTE}">{nom}</text>')
        s.append(f'<rect x="{ml}" y="{y+5}" width="{L(a):.1f}" height="18" rx="3" fill="{AZUL}"/>')
        s.append(f'<rect x="{ml+L(a)+2:.1f}" y="{y+5}" width="{max(L(b)-2,1):.1f}" height="18" rx="3" fill="{AMBAR}"/>')
        s.append(f'<text x="{ml+L(a)+L(b)+8:.1f}" y="{y+18}" font-size="11.5" fill="{SUAVE}" style="{FUENTE}">{a} + {b}</text>')
    s.append("</svg>")
    return "\n".join(s)


if __name__ == "__main__":
    (OUT / "caja.svg").write_text(caja(), encoding="utf-8")
    (OUT / "tokens.svg").write_text(tokens(), encoding="utf-8")
    print("ok")
