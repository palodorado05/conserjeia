"""Agente REDACTOR: escribe la respuesta al vecino a partir de los HECHOS que le pasa el orquestador.

Contexto que ve: el mensaje original (aislado) y una lista de hechos verificables (incidencia creada,
cita, respuesta legal...). No llama a herramientas. Esfuerzo: think=false (estilo, no lógica).
Regla: no puede añadir hechos (fechas, plazos, importes) que no estén en la lista; lo comprueba el verificador.
"""
from __future__ import annotations

from .. import guardrails, llm
from ..config import cfg

SISTEMA = f"""Eres el conserje digital de "{{comunidad}}". Redactas respuestas breves, cordiales y claras
a los vecinos, en español, tuteando con respeto.
{guardrails.AVISO_SISTEMA}
Reglas:
- Usa EXCLUSIVAMENTE los HECHOS que se te dan. No inventes fechas, horas, plazos, nombres ni importes.
- Si hay una respuesta legal, mantenla con sus citas entre corchetes tal cual, p. ej. [Art. 17 LPH].
- Si un hecho dice que algo ha fallado o se ha escalado, dilo con naturalidad (lo revisará el administrador).
- Máximo 120 palabras. Sin asunto, sin firma con datos personales: firma "Conserje IA · {{comunidad}}".
Devuelve sólo el texto de la respuesta."""


def redactar(nombre: str, mensaje: str, hechos: list[str]) -> str:
    comunidad = cfg()["comunidad"]["nombre"]
    lista = "\n".join(f"- {h}" for h in hechos) or "- (sin acciones)"
    try:
        r = llm.chat("redactor", "redactor", [
            {"role": "system", "content": SISTEMA.replace("{comunidad}", comunidad)},
            {"role": "user", "content": f"Vecino: {nombre or 'vecino/a'}\nMensaje original:\n{guardrails.envolver(mensaje)}\n\nHECHOS:\n{lista}"}])
        return r.texto.strip()
    except llm.LLMNoDisponible:
        return plantilla(nombre, hechos)


def plantilla(nombre: str, hechos: list[str]) -> str:
    """Respuesta segura sin LLM (también se usa si el verificador rechaza el borrador)."""
    comunidad = cfg()["comunidad"]["nombre"]
    cuerpo = "\n".join(f"• {h}" for h in hechos)
    return f"Hola{(' ' + nombre.split(' (')[0]) if nombre else ''}:\n\n{cuerpo}\n\nUn saludo,\nConserje IA · {comunidad}"
