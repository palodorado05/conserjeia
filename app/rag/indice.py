"""Índice RAG sobre la Ley 49/1960 de Propiedad Horizontal (texto consolidado del BOE).

1. Trocea el PDF por ARTÍCULO (la unidad que se cita). Los artículos largos (9, 10, 17, 21...) se
   parten en trozos de ~1200 caracteres con solape, y cada trozo conserva su etiqueta "Art. 17".
2. Calcula embeddings con nomic-embed-text (Ollama) y los guarda en data/indice/ (caché por hash).
3. Recupera los k trozos más parecidos (similitud coseno). Si el mejor no llega al umbral, se ABSTIENE.
4. Si Ollama no está, usa BM25 (léxico) para no dejar la app sin RAG (modo degradado).

Uso:  python -m app.rag.indice --construir      |   python -m app.rag.indice "¿quién paga el ascensor?"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

import numpy as np
from pypdf import PdfReader

from ..config import cfg, ruta
from .. import llm

NUMEROS = {
    "primero": 1, "segundo": 2, "tercero": 3, "cuarto": 4, "quinto": 5, "sexto": 6, "séptimo": 7,
    "octavo": 8, "noveno": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
    "quince": 15, "dieciséis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veintiuno": 21, "veintidós": 22, "veintitrés": 23, "veinticuatro": 24,
}
RE_CABECERA = re.compile(r"BOLETÍN OFICIAL DEL ESTADO\s+LEGISLACIÓN CONSOLIDADA\s+Página \d+")
RE_SECCION = re.compile(r"\n(Artículo [a-záéíóúñ]+\.|Disposición (?:adicional|transitoria) [a-z]+\.|Disposición final\.)")


@dataclass
class Trozo:
    id: str          # "art17-2"
    cita: str        # "Art. 17 LPH"
    texto: str


# ---------------------------------------------------------------------------
# Troceado
# ---------------------------------------------------------------------------
def _texto_pdf(pdf) -> str:
    t = "\n".join(p.extract_text() for p in PdfReader(pdf).pages)
    t = RE_CABECERA.sub(" ", t)
    # el índice del principio repite los títulos: empezamos en la SEGUNDA aparición de "Artículo primero."
    inicios = [m.start() for m in re.finditer(r"\nArtículo primero\.", t)]
    t = t[inicios[1]:] if len(inicios) > 1 else t
    fin = t.find("Este documento es de carácter informativo")
    return t[:fin] if fin > 0 else t


def _cita(titulo: str) -> tuple[str, str]:
    m = re.match(r"Artículo ([a-záéíóúñ]+)\.", titulo)
    if m:
        n = NUMEROS[m.group(1)]
        return f"art{n}", f"Art. {n} LPH"
    t = titulo.rstrip(".")
    slug = re.sub(r"\W+", "-", _sin_tildes(t.lower())).strip("-")
    return slug, f"{t} LPH"


def trocear(pdf=None) -> list[Trozo]:
    c = cfg()["rag"]
    texto = _texto_pdf(pdf or ruta(c["pdf"]))
    partes = RE_SECCION.split("\n" + texto)
    trozos: list[Trozo] = []
    for titulo, cuerpo in zip(partes[1::2], partes[2::2]):
        cuerpo = re.sub(r"\s+", " ", cuerpo).strip()
        if cuerpo.startswith("(Derogado)") and len(cuerpo) < 30:
            continue
        base, cita = _cita(titulo)
        for i, frag in enumerate(_partir(cuerpo, c["tam_trozo"], c["solape"]), 1):
            trozos.append(Trozo(f"{base}-{i}", cita, frag))
    return trozos


def _partir(texto: str, tam: int, solape: int) -> list[str]:
    if len(texto) <= tam:
        return [texto]
    frases = re.split(r"(?<=[.;:])\s+", texto)
    out, actual = [], ""
    for f in frases:
        if actual and len(actual) + len(f) > tam:
            out.append(actual.strip())
            actual = actual[-solape:] + " " + f      # solape: arrastra el final del trozo anterior
        else:
            actual += " " + f
    if actual.strip():
        out.append(actual.strip())
    return out


# ---------------------------------------------------------------------------
# Índice (denso + BM25 de reserva)
# ---------------------------------------------------------------------------
def _sin_tildes(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")


def _tokens(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", _sin_tildes(s.lower())) if len(w) > 2]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.docs = [_tokens(d) for d in docs]
        self.k1, self.b = k1, b
        self.avg = sum(map(len, self.docs)) / max(len(self.docs), 1)
        df = Counter(w for d in self.docs for w in set(d))
        n = len(self.docs)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}
        self.tf = [Counter(d) for d in self.docs]

    def puntuar(self, consulta: str) -> np.ndarray:
        q = _tokens(consulta)
        out = np.zeros(len(self.docs))
        for i, (tf, d) in enumerate(zip(self.tf, self.docs)):
            for w in q:
                if w in tf:
                    f = tf[w]
                    out[i] += self.idf[w] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avg))
        return out


class Indice:
    def __init__(self, trozos: list[Trozo], matriz: np.ndarray | None):
        self.trozos = trozos
        self.matriz = matriz          # None -> sólo BM25
        self.bm25 = BM25([t.cita + " " + t.texto for t in trozos])

    @property
    def modo(self) -> str:
        return "hibrido" if self.matriz is not None else "lexico"

    def buscar(self, pregunta: str, k: int | None = None, modo: str | None = None) -> dict:
        """Devuelve {'resultados': top-k ARTÍCULOS, 'contexto': top trozos, 'abstiene', 'modo', 'mejor'}.

        modo = "hibrido" (por defecto si hay embeddings): ordena por fusión de rangos (RRF) del denso y BM25,
               y decide la abstención con la similitud coseno (escala interpretable y calibrada).
        modo = "denso" | "lexico": un solo recuperador (para compararlos en eval/evaluar_rag.py).
        """
        c = cfg()["rag"]
        k = k or c["k"]
        modo = modo or ("hibrido" if self.matriz is not None else "lexico")
        lex = self.bm25.puntuar(pregunta)
        densos = None
        if modo in ("denso", "hibrido") and self.matriz is not None:
            try:
                q = np.array(llm.embeddings(["search_query: " + pregunta])[0], dtype=np.float32)
                q /= np.linalg.norm(q) + 1e-9
                densos = self.matriz @ q
            except llm.LLMNoDisponible:
                pass
        if densos is None:
            modo = "lexico"
        if modo == "lexico":
            orden_score, umbral, ref = lex, c["umbral_abstencion_lexico"], lex
        elif modo == "denso":
            orden_score, umbral, ref = densos, c["umbral_abstencion"], densos
        else:   # RRF: 1/(60+rango_denso) + 1/(60+rango_lexico)
            rd = np.empty(len(densos)); rd[np.argsort(-densos)] = np.arange(len(densos))
            rl = np.empty(len(lex)); rl[np.argsort(-lex)] = np.arange(len(lex))
            orden_score, umbral, ref = 1 / (60 + rd) + 1 / (60 + rl), c["umbral_abstencion"], densos
        orden = np.argsort(-orden_score)
        resultados, vistos = [], set()
        for i in orden:              # top-k de ARTÍCULOS distintos (lo que se cita es el artículo)
            t = self.trozos[i]
            if t.cita in vistos:
                continue
            vistos.add(t.cita)
            resultados.append({"id": t.id, "cita": t.cita, "texto": t.texto, "score": round(float(ref[i]), 4)})
            if len(resultados) == k:
                break
        contexto = [{"id": self.trozos[i].id, "cita": self.trozos[i].cita, "texto": self.trozos[i].texto,
                     "score": round(float(ref[i]), 4)} for i in orden[:c.get("trozos_contexto", 5)]]
        mejor = float(ref.max()) if len(ref) else 0.0
        return {"resultados": resultados, "contexto": contexto, "abstiene": mejor < umbral, "modo": modo,
                "mejor": round(mejor, 4), "umbral": umbral}


# ---------------------------------------------------------------------------
# Construcción y caché
# ---------------------------------------------------------------------------
_INDICE: Indice | None = None


def _huella(pdf_bytes: bytes) -> str:
    c = cfg()
    clave = pdf_bytes + json.dumps([c["ollama"]["modelo_embeddings"], c["rag"]["tam_trozo"], c["rag"]["solape"]]).encode()
    return hashlib.sha256(clave).hexdigest()[:16]


def construir(forzar: bool = False) -> Indice:
    c = cfg()["rag"]
    pdf = ruta(c["pdf"])
    if not pdf.exists():
        raise FileNotFoundError(f"Falta {pdf}. Descargad la LPH del BOE (ver README, paso 3).")
    huella = _huella(pdf.read_bytes())
    meta_p, mat_p = ruta("data/indice/trozos.json"), ruta("data/indice/embeddings.npy")
    trozos = trocear(pdf)
    if not forzar and meta_p.exists() and mat_p.exists():
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        if meta.get("huella") == huella:
            return Indice(trozos, np.load(mat_p))
    try:
        vecs = []
        for i in range(0, len(trozos), 16):
            lote = trozos[i:i + 16]
            vecs += llm.embeddings([f"search_document: {t.cita}. {t.texto}" for t in lote])
        m = np.array(vecs, dtype=np.float32)
        m /= np.linalg.norm(m, axis=1, keepdims=True) + 1e-9
        meta_p.parent.mkdir(parents=True, exist_ok=True)
        np.save(mat_p, m)
        meta_p.write_text(json.dumps({"huella": huella, "n": len(trozos),
                                      "trozos": [t.__dict__ for t in trozos]}, ensure_ascii=False, indent=1),
                          encoding="utf-8")
        return Indice(trozos, m)
    except llm.LLMNoDisponible:
        return Indice(trozos, None)      # modo degradado: sólo BM25


def indice() -> Indice:
    global _INDICE
    if _INDICE is None or _INDICE.matriz is None:   # reintenta denso si antes no había Ollama
        _INDICE = construir()
    return _INDICE


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pregunta", nargs="?")
    ap.add_argument("--construir", action="store_true")
    a = ap.parse_args()
    ix = construir(forzar=a.construir)
    print(f"{len(ix.trozos)} trozos · modo {ix.modo}")
    if a.pregunta:
        r = ix.buscar(a.pregunta)
        print(json.dumps({**r, "resultados": [{**x, "texto": x["texto"][:160]} for x in r["resultados"]]},
                         ensure_ascii=False, indent=1))
