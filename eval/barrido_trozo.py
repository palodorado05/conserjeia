"""Barrido del tamaño de trozo del RAG (justifica rag.tam_trozo en config.yaml).

Uso: python -m eval.barrido_trozo     -> imprime la tabla y la guarda en eval/barrido_trozo.md
Al acabar reconstruye el índice con los valores de config.yaml.
"""
from app.config import cfg, ruta
from app.rag import indice as I
from eval.evaluar_rag import cargar, evaluar_modo

CONFIGS = [(500, 80), (700, 100), (900, 120), (1200, 150), (1600, 200)]


def main() -> None:
    P = cargar()
    orig = dict(cfg()["rag"])
    filas = ["| tam_trozo | nº trozos | acierto@3 híbrido | acierto@3 denso | acierto@3 léxico | abstención correcta (híbrido) | abstención indebida (híbrido) |",
             "|---|---|---|---|---|---|---|"]
    for tam, sol in CONFIGS:
        cfg()["rag"]["tam_trozo"], cfg()["rag"]["solape"] = tam, sol
        ix = I.construir(forzar=True)
        r = {m: evaluar_modo(ix, P, m) for m in ("hibrido", "denso", "lexico")}
        filas.append(f"| {tam} | {len(ix.trozos)} | {r['hibrido']['acierto@3']:.3f} | {r['denso']['acierto@3']:.3f} | "
                     f"{r['lexico']['acierto@3']:.3f} | {r['hibrido']['abstencion_correcta']:.3f} | {r['hibrido']['abstencion_indebida']:.3f} |")
        print(filas[-1], flush=True)
    cfg()["rag"].update(orig)
    I.construir(forzar=True)
    ruta("eval/barrido_trozo.md").write_text("\n".join(filas) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
