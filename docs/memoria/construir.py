"""Construye memoria.pdf: rellena memoria.html con las cifras MEDIDAS del repositorio y lo imprime con Chromium.

Uso (desde la raíz del proyecto):
  python -m negocio.coste_construccion && python -m negocio.modelo_financiero   # cifras al día
  python docs/memoria/construir.py                                             # -> memoria.pdf
"""
import json
import re
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
AQUI = Path(__file__).resolve().parent


def eur(v: float, dec: int = 0) -> str:
    s = f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s + " €"


def fila_md(md: str, concepto: str) -> str:
    for l in md.splitlines():
        if l.startswith("| " + concepto):
            return l.split("|")[2].strip()
    raise KeyError(concepto)


def main() -> None:
    import graficos
    html = (AQUI / "memoria.html").read_text(encoding="utf-8")
    html = html.replace("<!--TOKENS-->", graficos.tokens()).replace("<!--CAJA-->", graficos.caja())

    # barrido del tamaño de trozo
    filas = [l for l in (RAIZ / "eval/barrido_trozo.md").read_text(encoding="utf-8").splitlines() if re.match(r"\| \d", l)]
    tabla = ['<table><tr><th class="num">Tamaño de trozo</th><th class="num">Nº trozos</th><th class="num">acierto@3 híbrido</th>'
             '<th class="num">acierto@3 embeddings</th><th class="num">acierto@3 BM25</th></tr>']
    for l in filas:
        c = [x.strip() for x in l.strip("|").split("|")]
        pct = lambda x: f"{float(x)*100:.1f} %".replace(".", ",")
        b = c[0] == "1200"
        tabla.append("<tr>" + "".join(f'<td class="num">{"<b>" if b else ""}{v}{"</b>" if b else ""}</td>'
                                      for v in (c[0], c[1], pct(c[2]), pct(c[3]), pct(c[4]))) + "</tr>")
    tabla.append("</table>")
    html = html.replace("<!--BARRIDO-->", '<p>Además probamos cinco tamaños de trozo (<code>python -m eval.barrido_trozo</code>); '
                        'con 1.200 caracteres se obtiene el mejor acierto:</p>' + "".join(tabla))

    # coste de construcción
    cc = json.loads((RAIZ / "logs/coste_construccion.json").read_text())
    t, p = cc["tokens"], cc["precios_usd_mtok"]
    conceptos = [("Entrada sin caché", t.get("input_tokens", 0), p["entrada"]),
                 ("Salida", t.get("output_tokens", 0), p["salida"]),
                 ("Escritura en caché", t.get("cache_creation_input_tokens", 0), p["cache_escritura"]),
                 ("Lectura de caché", t.get("cache_read_input_tokens", 0), p["cache_lectura"])]
    def miles(n): return f"{n:,}".replace(",", ".")
    def dec(x, d=2): return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    f = "".join(f'<tr><td>{n}</td><td class="num">{miles(tok)}</td><td class="num">{dec(pr)}</td><td class="num">{dec(tok*pr/1e6)}</td></tr>'
                for n, tok, pr in conceptos)
    f += (f'<tr><th colspan="3">Total · {cc["respuestas"]} respuestas del modelo · {dec(cc["fraccion_cacheada_entrada"]*100, 1)} % de la entrada '
          f'desde caché</th><th class="num">{dec(cc["coste"]["usd"])} $ = {dec(cc["coste"]["eur"])} €</th></tr>')
    html = html.replace("<!--COSTE_FILAS-->", f)

    # cifras del modelo financiero (las escribe negocio/modelo_financiero.py)
    md = (RAIZ / "negocio/salida/modelo_financiero.md").read_text(encoding="utf-8")
    html = html.replace("<!--INVERSION-->", fila_md(md, "Inversión antes").replace(",", "."))
    html = html.replace("<!--NECESIDAD-->", fila_md(md, "Necesidad máxima").replace(",", "."))
    html = html.replace("<!--CAJA36-->", fila_md(md, "Caja acumulada").replace(",", "."))
    html = html.replace("<!--ROI-->", fila_md(md, "ROI a 3 años").replace(".", ",").replace("x", " veces"))
    # la primera fila de cada tabla pasa a <thead>: Chromium la repite al partir la tabla y no la deja sola
    html = re.sub(r"(<table[^>]*>\s*)(<tr>\s*<th.*?</tr>)", r"\1<thead>\2</thead>", html, flags=re.S)
    (AQUI / "memoria_final.html").write_text(html, encoding="utf-8")
    subprocess.run(["node", str(AQUI / "imprimir.js"), str(AQUI / "memoria_final.html"), str(RAIZ / "memoria.pdf")], check=True)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(AQUI))
    main()
