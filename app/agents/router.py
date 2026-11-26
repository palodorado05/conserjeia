"""Agente ROUTER: decide qué quiere el vecino y extrae los campos estructurados.

Contexto que ve: el mensaje del vecino (aislado como dato no confiable) y su nombre/vivienda.
Esfuerzo: think=false (clasificar es una tarea corta y cerrada). Salida: JSON validado por código.
"""
from __future__ import annotations

import re

from .. import guardrails, llm

INTENCIONES = ["incidencia", "consulta_legal", "estado_incidencia", "otro"]
CATEGORIAS = ["fontaneria", "electricidad", "ascensor", "cerrajeria", "antena", "limpieza", "ruidos", "obras", "otros"]
PRIORIDADES = ["alta", "media", "baja"]

SISTEMA = f"""Eres el clasificador de mensajes del conserje digital de una comunidad de propietarios.
{guardrails.AVISO_SISTEMA}
Devuelve SOLO un JSON con estas claves:
- "intencion": una de {INTENCIONES}
    incidencia = avisa de una avería, daño o problema en el edificio que hay que arreglar
    consulta_legal = pregunta sobre derechos, obligaciones, juntas, cuotas, obras o normas de la comunidad
    estado_incidencia = pregunta cómo va un problema que ya se avisó antes
    otro = cualquier otra cosa (saludos, temas ajenos a la comunidad)
- "categoria": una de {CATEGORIAS} (sólo si es incidencia o estado_incidencia; si no, "otros")
- "prioridad": una de {PRIORIDADES} (alta = riesgo para personas, agua, gas, gente atrapada)
- "vivienda": piso/puerta del remitente si aparece (p. ej. "2ºA"), o "" si no aparece
- "resumen": una frase de menos de 15 palabras, sin datos personales
- "pregunta": si es consulta_legal, la pregunta reformulada de forma neutra y autocontenida; si no, ""
"""

PALABRAS = {
    "fontaneria": ["agua", "fuga", "gotera", "tuberia", "bajante", "humedad", "inund", "atasco"],
    "electricidad": ["luz", "electric", "enchufe", "fundid", "apagon", "bombilla"],
    "ascensor": ["ascensor"], "cerrajeria": ["puerta", "cerradura", "llave"],
    "antena": ["antena", "tdt", "canales", "television"], "limpieza": ["limpieza", "sucio", "basura", "papelera"],
    "ruidos": ["ruido", "musica", "fiesta"], "obras": ["obra", "reforma"],
}


def clasificar(mensaje: str, remitente: str = "", historial: list[dict] | None = None) -> dict:
    contexto = ""
    if historial:
        contexto = "Conversación previa (sólo para contexto):\n" + "\n".join(
            f"- {h['rol']}: {h['texto'][:200]}" for h in historial[-4:]) + "\n\n"
    usuario = f"{contexto}Remitente: {remitente}\nMensaje:\n{guardrails.envolver(mensaje)}"
    try:
        r = llm.chat("router", "router", [{"role": "system", "content": SISTEMA},
                                           {"role": "user", "content": usuario}], json_salida=True)
        d = r.json()
        d["_modo"] = "llm"
    except llm.LLMNoDisponible:
        d = _reglas(mensaje)
        d["_modo"] = "reglas"
    return _validar(d, mensaje)


def _validar(d: dict, mensaje: str) -> dict:
    """El LLM propone; el código valida. Cualquier valor fuera de lista se corrige."""
    out = {
        "intencion": d.get("intencion") if d.get("intencion") in INTENCIONES else "otro",
        "categoria": d.get("categoria") if d.get("categoria") in CATEGORIAS else "otros",
        "prioridad": d.get("prioridad") if d.get("prioridad") in PRIORIDADES else "media",
        "vivienda": str(d.get("vivienda") or _vivienda(mensaje))[:20],
        "resumen": str(d.get("resumen") or mensaje[:80])[:120],
        "pregunta": str(d.get("pregunta") or "")[:400],
        "_modo": d.get("_modo", "llm"),
    }
    if out["intencion"] == "consulta_legal" and not out["pregunta"]:
        out["pregunta"] = mensaje[:400]
    return out


def _vivienda(texto: str) -> str:
    m = re.search(r"\b(\d{1,2}\s?º\s?[A-Z]|[Bb]ajo\s?[A-Z]|[Áá]tico\s?[A-Z]?)\b", texto)
    return m.group(1).replace(" ", "") if m else ""


def _reglas(mensaje: str) -> dict:
    """Modo degradado (sin LLM): palabras clave. Peor, pero la app sigue funcionando."""
    n = guardrails._normalizar(mensaje)
    cat = next((c for c, ps in PALABRAS.items() if any(p in n for p in ps)), "otros")
    legal = any(p in n for p in ["junta", "ley", "cuota", "moros", "votar", "mayoria", "derecho", "obligad", "puedo", "necesito permiso", "quien paga"])
    estado = any(p in n for p in ["como va", "se sabe algo", "estado de", "que tal va"])
    if estado and cat != "otros":
        intencion = "estado_incidencia"
    elif legal:
        intencion = "consulta_legal"
    elif cat != "otros":
        intencion = "incidencia"
    else:
        intencion = "otro"
    urg = any(p in n for p in ["urgente", "inund", "encharc", "gas", "atrapad", "resbal", "riesgo"])
    return {"intencion": intencion, "categoria": cat, "prioridad": "alta" if urg else "media",
            "vivienda": _vivienda(mensaje), "resumen": mensaje[:80], "pregunta": mensaje if legal else ""}
