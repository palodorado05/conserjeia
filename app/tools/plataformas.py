"""Pasarela única hacia las tres plataformas (Outlook, Google Calendar, Notion).

Ningún agente habla con un backend directamente: todos pasan por `llamar(agente, herramienta, **args)`, que
  1. comprueba el PERMISO del agente (config.yaml -> permisos). Si no lo tiene: 'denegado' y excepción.
  2. comprueba si la plataforma está caída (real o simulada desde la web, para enseñar el fallo).
  3. ejecuta en el backend activo: mock (data/mock/estado.json) o mcp (servidores MCP reales).
  4. pasa la barandilla por lo que DEVUELVE la herramienta (un correo o una incidencia pueden traer inyección).
  5. deja la llamada en la traza: herramienta, permiso, estado, ms, args resumidos.

Herramientas lógicas (el nombre real en cada servidor MCP está en config.yaml -> mcp.herramientas):
  correo.leer      () -> [{id, de, nombre, asunto, cuerpo, fecha}]
  correo.escribir  (para, asunto, cuerpo, en_respuesta_a=None) -> {id}
  calendario.leer  (desde, hasta) -> [{id, titulo, inicio, fin}]
  calendario.escribir (titulo, inicio, fin, descripcion) -> {id}
  notion.leer      (estado=None) -> [{id, titulo, categoria, prioridad, vivienda, estado, fecha, descripcion}]
  notion.escribir  (titulo, categoria, prioridad, vivienda, descripcion) -> {id}
"""
from __future__ import annotations

import time

from ..config import cfg
from .. import guardrails, traza

PLATAFORMA = {"correo": "outlook", "calendario": "google", "notion": "notion"}


class PermisoDenegado(PermissionError):
    pass


class PlataformaCaida(RuntimeError):
    pass


_backend = None
_caidas: set[str] = set()        # plataformas "apagadas" a mano para la demo de fallos


def backend():
    global _backend
    if _backend is None:
        if cfg()["modo_plataformas"] == "mcp":
            from .mcp_backend import BackendMCP
            _backend = BackendMCP()
        else:
            from .mock_backend import BackendMock
            _backend = BackendMock()
    return _backend


def simular_caida(plataforma: str, caida: bool) -> set[str]:
    (_caidas.add if caida else _caidas.discard)(plataforma)
    return _caidas


def caidas() -> set[str]:
    return set(_caidas)


def llamar(agente: str, herramienta: str, **args):
    t = traza.actual()
    permiso = "escritura" if herramienta.endswith(".escribir") else "lectura"
    plataforma = PLATAFORMA[herramienta.split(".")[0]]
    modo = cfg()["modo_plataformas"]
    comun = dict(agente=agente, herramienta=herramienta, permiso=permiso, plataforma=plataforma, modo=modo, args=args)

    if herramienta not in cfg()["permisos"].get(agente, []):
        if t:
            t.herramienta(**comun, estado="denegado", ms=0, error=f"{agente} no tiene permiso para {herramienta}")
        raise PermisoDenegado(f"{agente} no tiene permiso para {herramienta}")

    t0 = time.time()
    try:
        if plataforma in _caidas:
            raise PlataformaCaida(f"{plataforma} no responde (caída simulada)")
        res = backend().ejecutar(herramienta, args)
    except Exception as e:
        if t:
            t.herramienta(**comun, estado="error", ms=int((time.time() - t0) * 1000), error=str(e))
        raise PlataformaCaida(f"{plataforma}: {e}") from e

    # barandilla sobre lo que devuelve la herramienta
    marcados = 0
    if isinstance(res, list):
        for item in res:
            texto = " ".join(str(v) for v in item.values() if isinstance(v, str))
            v = guardrails.analizar(texto)
            item["_riesgo"] = v.riesgo
            marcados += v.bloquear
    resumen = f"{len(res)} elementos" if isinstance(res, list) else str(res)
    if marcados:
        resumen += f" · {marcados} marcados por la barandilla"
    if t:
        t.herramienta(**comun, estado="ok", ms=int((time.time() - t0) * 1000), resumen=resumen)
    return res
