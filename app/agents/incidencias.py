"""Agente de INCIDENCIAS: registra averías en Notion y agenda al técnico en Google Calendar.

Contexto que ve: la salida ESTRUCTURADA del router (categoría, prioridad, vivienda, resumen) y el mensaje
aislado. Sus herramientas (permisos en config.yaml): notion.leer/escribir, calendario.leer/escribir.

Qué decide el agente (y un formulario no):
  - si el aviso es un DUPLICADO de una incidencia abierta (no crea otra, informa del estado de la existente);
  - si hace falta un TÉCNICO y de qué tipo (LLM), y con qué urgencia;
  - busca el primer HUECO libre en la agenda real y lo reserva (el hueco lo calcula el CÓDIGO, no el LLM).
Si una plataforma falla, no se para: devuelve lo que ha podido hacer y los errores, y el orquestador escala.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .. import guardrails, llm
from ..config import cfg, zona
from ..tools import plataformas as P

SISTEMA = f"""Eres el gestor de incidencias de una comunidad de propietarios.
{guardrails.AVISO_SISTEMA}
A partir del aviso, devuelve SOLO un JSON:
{{"titulo": "máx. 8 palabras, sin datos personales",
  "descripcion": "1-2 frases técnicas para el profesional, sin nombres ni teléfonos",
  "requiere_tecnico": true|false,
  "tipo_tecnico": "fontanero|electricista|ascensorista|cerrajero|antenista|limpieza|albañil|ninguno"}}"""

TECNICO_POR_CATEGORIA = {"fontaneria": "fontanero", "electricidad": "electricista", "ascensor": "ascensorista",
                         "cerrajeria": "cerrajero", "antena": "antenista", "limpieza": "limpieza", "obras": "albañil"}


def _ficha(router: dict, mensaje: str) -> dict:
    try:
        r = llm.chat("incidencias", "incidencias", [
            {"role": "system", "content": SISTEMA},
            {"role": "user", "content": f"Categoría: {router['categoria']} · Prioridad: {router['prioridad']}\n"
                                        f"Aviso:\n{guardrails.envolver(mensaje)}"}], json_salida=True)
        d = r.json()
    except llm.LLMNoDisponible:
        d = {}
    tec = TECNICO_POR_CATEGORIA.get(router["categoria"], "ninguno")
    return {"titulo": str(d.get("titulo") or router["resumen"])[:80],
            "descripcion": str(d.get("descripcion") or router["resumen"])[:400],
            "requiere_tecnico": bool(d.get("requiere_tecnico", tec != "ninguno")),
            # el tipo de técnico lo fija la CATEGORÍA (código); el LLM sólo lo propone si la categoría no lo determina
            "tipo_tecnico": tec if tec != "ninguno" else str(d.get("tipo_tecnico") or "ninguno")}


def _duplicada(abiertas: list[dict], router: dict) -> dict | None:
    for inc in abiertas:
        if inc["estado"] != "Cerrada" and inc.get("categoria") == router["categoria"] and router["categoria"] != "otros":
            return inc
    return None


def _primer_hueco(eventos: list[dict], urgente: bool) -> tuple[str, str]:
    h = cfg()["comunidad"]["horario_tecnicos"]
    tz = zona()
    ahora = datetime.now(tz).replace(tzinfo=None, second=0, microsecond=0)
    dia = ahora.date() if urgente else ahora.date() + timedelta(days=1)
    ocupados = [(e["inicio"][:16], e["fin"][:16]) for e in eventos]
    for _ in range(h["dias_busqueda"] + 1):
        if dia.weekday() < 5:                                   # lunes a viernes
            for hora in range(h["inicio"], h["fin"]):
                ini = datetime.combine(dia, datetime.min.time()).replace(hour=hora)
                fin = ini + timedelta(minutes=h["duracion_min"])
                if ini <= ahora:
                    continue
                a, b = ini.isoformat(timespec="minutes"), fin.isoformat(timespec="minutes")
                if all(b <= o_ini or a >= o_fin for o_ini, o_fin in ocupados):
                    return a, b
        dia += timedelta(days=1)
    raise RuntimeError("no hay huecos libres en los próximos días")


def gestionar(router: dict, mensaje: str) -> dict:
    res = {"accion": None, "incidencia": None, "cita": None, "errores": []}

    # 1. leer incidencias abiertas (Notion)
    try:
        existentes = P.llamar("incidencias", "notion.leer")
    except P.PlataformaCaida as e:
        res["errores"].append(str(e))
        existentes = None

    # 1b. el vecino pregunta por algo ya avisado
    if router["intencion"] == "estado_incidencia":
        inc = _duplicada(existentes or [], router)
        res["accion"] = "consultada" if inc else "no_encontrada"
        res["incidencia"] = inc and {k: inc[k] for k in ("id", "titulo", "estado", "fecha")}
        if inc:
            res["cita"] = _cita_de(inc["id"])
        return res

    # 2. ¿duplicado?
    if existentes is not None:
        dup = _duplicada(existentes, router)
        if dup:
            res["accion"] = "duplicada"
            res["incidencia"] = {k: dup[k] for k in ("id", "titulo", "estado", "fecha")}
            res["cita"] = _cita_de(dup["id"])
            return res

    # 3. crear la ficha (LLM) y escribir en Notion
    ficha = _ficha(router, mensaje)
    if existentes is None:
        res["accion"] = "no_registrada"          # Notion caído: no escribimos a ciegas
        res["ficha"] = ficha
        return res
    try:
        nueva = P.llamar("incidencias", "notion.escribir", titulo=ficha["titulo"], categoria=router["categoria"],
                         prioridad=router["prioridad"], vivienda=router["vivienda"], descripcion=ficha["descripcion"])
        res["accion"] = "creada"
        res["incidencia"] = {"id": nueva["id"], "titulo": ficha["titulo"], "estado": "Abierta",
                             "prioridad": router["prioridad"]}
    except P.PlataformaCaida as e:
        res["errores"].append(str(e))
        res["accion"] = "no_registrada"
        res["ficha"] = ficha
        return res

    # 4. agendar al técnico (Google Calendar)
    if ficha["requiere_tecnico"] and ficha["tipo_tecnico"] != "ninguno":
        try:
            tz = zona()
            hoy = datetime.now(tz).replace(tzinfo=None)
            eventos = P.llamar("incidencias", "calendario.leer", desde=hoy.isoformat(timespec="minutes"),
                               hasta=(hoy + timedelta(days=cfg()["comunidad"]["horario_tecnicos"]["dias_busqueda"] + 3)).isoformat(timespec="minutes"))
            ini, fin = _primer_hueco(eventos, urgente=router["prioridad"] == "alta")
            titulo = f"{ficha['tipo_tecnico'].capitalize()} · {ficha['titulo']} ({nueva['id']})"
            ev = P.llamar("incidencias", "calendario.escribir", titulo=titulo, inicio=ini, fin=fin,
                          descripcion=f"{ficha['descripcion']} · Vivienda/zona: {router['vivienda'] or 'zonas comunes'}")
            res["cita"] = {"id": ev["id"], "inicio": ini, "fin": fin, "tecnico": ficha["tipo_tecnico"]}
        except (P.PlataformaCaida, RuntimeError) as e:
            res["errores"].append(str(e))
    return res


def _cita_de(inc_id: str) -> dict | None:
    """Busca en la agenda si ya hay técnico citado para esa incidencia."""
    try:
        hoy = datetime.now()
        evs = P.llamar("incidencias", "calendario.leer", desde=(hoy - timedelta(days=1)).isoformat(timespec="minutes"),
                       hasta=(hoy + timedelta(days=30)).isoformat(timespec="minutes"))
    except P.PlataformaCaida:
        return None
    for e in evs:
        if inc_id in e.get("titulo", ""):
            return {"id": e["id"], "inicio": e["inicio"], "fin": e["fin"], "tecnico": e["titulo"].split(" · ")[0]}
    return None
