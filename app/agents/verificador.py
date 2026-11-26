"""Agente VERIFICADOR: revisa el borrador ANTES de enviarlo. No comparte contexto con el redactor:
sólo ve el borrador y la lista de hechos, para juzgar de forma independiente.

Comprobaciones:
  1. (código) toda cita [Art. N LPH] del borrador debe estar entre las citas que devolvió el agente legal;
  2. (código) no aparecen correos/teléfonos/DNI distintos de los permitidos (fuga de datos de terceros);
  3. (código) no se filtran las instrucciones internas (etiquetas, "prompt de sistema"...);
  4. (LLM, think=true) el borrador no afirma hechos que no estén en la lista (fechas u horas inventadas, etc.).
Si algo falla, el orquestador descarta el borrador y envía la plantilla segura.
"""
from __future__ import annotations

import re

from .. import guardrails, llm

SISTEMA = """Eres un verificador estricto. Recibes HECHOS y un BORRADOR de respuesta a un vecino.
Comprueba si el borrador afirma algún DATO CONCRETO que no esté en los hechos o los contradiga:
fechas, horas, plazos, importes, identificadores de incidencia, artículos de ley, nombres de empresas,
o acciones que diga haber hecho y no aparezcan en los hechos.
NO son problema: saludos, fórmulas de cortesía, empatía, consejos generales de prudencia
("ten cuidado al pasar"), ni decir que el administrador está al tanto.
Devuelve SOLO un JSON: {"fiel": true|false, "problemas": ["..."]}"""


def verificar(borrador: str, hechos: list[str], citas_permitidas: list[str], permitidos: set[str],
              usar_llm: bool = True) -> dict:
    problemas = []
    for c in re.findall(r"\[(.+?LPH)\]", borrador):
        if c not in citas_permitidas:
            problemas.append(f"cita no respaldada: {c}")
    fuga = guardrails.datos_personales(borrador, permitidos)
    if fuga:
        problemas.append(f"datos personales no permitidos: {fuga}")
    if re.search(r"datos_no_confiables|prompt de sistema|system prompt|AVISO_SISTEMA", borrador, re.I):
        problemas.append("filtra instrucciones internas")
    if len(borrador) > 1500:
        problemas.append("respuesta demasiado larga")

    modo = "reglas"
    if usar_llm and not problemas:
        try:
            r = llm.chat("verificador", "verificador", [
                {"role": "system", "content": SISTEMA},
                {"role": "user", "content": "HECHOS:\n" + "\n".join(f"- {h}" for h in hechos) + f"\n\nBORRADOR:\n{borrador}"}],
                json_salida=True)
            d = r.json()
            modo = "reglas+llm"
            if d.get("fiel") is False:
                problemas += [f"LLM: {p}" for p in d.get("problemas", [])][:3] or ["LLM: no fiel a los hechos"]
        except llm.LLMNoDisponible:
            pass
    return {"ok": not problemas, "problemas": problemas, "modo": modo}
