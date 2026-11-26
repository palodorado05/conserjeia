"""Agente LEGAL: responde dudas sobre la Ley de Propiedad Horizontal con RAG, CITA y ABSTENCIÓN.

Contexto que ve: SÓLO la pregunta reformulada por el router y los 3 fragmentos recuperados.
No ve quién pregunta ni su correo (minimización de datos: el corpus legal no necesita datos personales).
Esfuerzo: think=true (interpretar la ley y decidir si los fragmentos la responden compensa razonar).

Abstención en dos capas:
  1. recuperación: si el mejor fragmento no supera el umbral de similitud, ni se llama al modelo.
  2. modelo: si los fragmentos no responden la pregunta, debe devolver "consta": false.
Además, el código descarta cualquier cita que no esté entre los fragmentos recuperados.
"""
from __future__ import annotations

import re

from .. import llm
from ..rag.indice import indice

SISTEMA = """Eres el asistente jurídico de una comunidad de propietarios en España.
Respondes ÚNICAMENTE con lo que dicen los fragmentos de la Ley 49/1960 de Propiedad Horizontal (LPH)
que se te dan. No uses conocimiento externo ni inventes plazos, mayorías o importes.
Devuelve SOLO un JSON:
{"consta": true|false, "respuesta": "...", "citas": ["Art. N LPH", ...]}
- "consta": false si los fragmentos no permiten responder la pregunta. En ese caso "respuesta" = "" y "citas" = [].
- "respuesta": 2-5 frases claras para un vecino sin formación jurídica, en español. Cita entre corchetes
  el artículo de donde sale cada afirmación, p. ej. [Art. 17 LPH].
- "citas": las etiquetas exactas de los fragmentos usados.
Recuerda que no sustituyes a un abogado; si el caso es complejo dilo en una frase."""

ABSTENCION = ("No he encontrado en la Ley de Propiedad Horizontal una respuesta fiable a esta pregunta, "
              "así que prefiero no improvisar. Se la paso al administrador para que la revise.")


def responder(pregunta: str) -> dict:
    b = indice().buscar(pregunta)
    frags = b["resultados"]
    base = {"pregunta": pregunta, "fragmentos": [{"cita": f["cita"], "score": f["score"], "texto": f["texto"][:300]} for f in b["contexto"]],
            "modo_rag": b["modo"], "mejor": b["mejor"], "umbral": b["umbral"]}
    if b["abstiene"]:
        return {**base, "abstiene": True, "motivo": f"similitud {b['mejor']} < umbral {b['umbral']}",
                "texto": ABSTENCION, "citas": [], "modo": "umbral"}

    ctx = b["contexto"]
    contexto = "\n\n".join(f"[{f['cita']}]\n{f['texto']}" for f in ctx)
    permitidas = {f["cita"] for f in ctx}
    try:
        r = llm.chat("legal", "legal", [
            {"role": "system", "content": SISTEMA},
            {"role": "user", "content": f"Fragmentos de la LPH:\n{contexto}\n\nPregunta: {pregunta}"}],
            json_salida=True)
        d = r.json()
    except llm.LLMNoDisponible:
        # modo degradado: extracto literal del mejor artículo, siempre citado
        f = frags[0]
        return {**base, "abstiene": False, "modo": "extracto",
                "texto": f"Lo más relevante que he encontrado es el {f['cita']}: «{f['texto'][:450]}…» "
                         f"(respuesta automática sin el modelo de lenguaje; revísela el administrador).",
                "citas": [f["cita"]]}

    texto = str(d.get("respuesta", "")).strip()
    citas = [c for c in d.get("citas", []) if c in permitidas]
    citas += [c for c in re.findall(r"\[(.+?LPH)\]", texto) if c in permitidas and c not in citas]
    inventadas = [c for c in re.findall(r"\[(.+?LPH)\]", texto) if c not in permitidas]
    for c in inventadas:           # una cita que no viene de los fragmentos se elimina del texto
        texto = texto.replace(f"[{c}]", "")
    citas = list(dict.fromkeys(citas))          # sin duplicados, en orden
    if not d.get("consta", False) or not texto or not citas:
        return {**base, "abstiene": True, "motivo": "el modelo indica que los fragmentos no responden",
                "texto": ABSTENCION, "citas": [], "modo": "modelo"}
    return {**base, "abstiene": False, "texto": texto, "citas": citas, "modo": "llm",
            "citas_eliminadas": inventadas}
