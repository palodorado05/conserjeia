"""ORQUESTADOR: el único que ve todo el contexto y el único que decide el flujo.

Patrón: orquestador con trabajadores + verificador.

    mensaje ─► barandilla ─► router ─┬─► legal (RAG LPH)            ─┐
                  │ (riesgo)         ├─► incidencias (Notion+Calendar)├─► hechos ─► redactor ─► verificador ─► correo.escribir
                  ▼                  └─► (otro)                       ─┘                          │ (rechaza)
              escalar a humano ◄──────────── fallo de plataforma / abstención ◄────────────── plantilla segura

Los hechos que ve el redactor los escribe el CÓDIGO a partir de lo que devolvieron los trabajadores,
así el verificador puede comprobar que la respuesta no añade nada.
"""
from __future__ import annotations

import json
from datetime import datetime

from . import guardrails, traza
from .agents import incidencias, legal, redactor, router, verificador
from .config import cfg, ruta
from .tools import plataformas as P

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _fecha(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"el {DIAS[d.weekday()]} {d.day:02d}/{d.month:02d} a las {d:%H:%M}"


def _donde(plataforma: str) -> str:
    """'en Notion' con cuentas reales; 'en Notion (simulado)' en modo mock, para que nadie lo confunda."""
    return plataforma if cfg()["modo_plataformas"] == "mcp" else f"{plataforma} (simulado)"


def _escalar(motivo: str, remitente: dict, mensaje: str, t: traza.Traza, avisar: bool = True) -> dict:
    """Deja el caso para revisión humana: fichero local + correo al administrador (dirección FIJA de config)."""
    reg = {"ts": datetime.now().isoformat(timespec="seconds"), "sesion": t.id, "motivo": motivo,
           "remitente": remitente.get("email", ""), "vivienda": remitente.get("vivienda", ""),
           "extracto": mensaje[:200]}
    p = ruta("logs/escalados.jsonl")
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(reg, ensure_ascii=False) + "\n")
    t.evento("escalado", motivo=motivo)
    admin = cfg()["comunidad"]["correo_administrador"]
    if cfg()["modo_plataformas"] == "mcp" and admin.endswith("fincas-demo.es"):
        avisar = False            # dirección inventada: con correo real no se escribe (queda en logs/escalados.jsonl)
        t.evento("escalado_sin_correo", motivo="falta CORREO_ADMINISTRADOR en .env")
    if avisar:
        try:
            P.llamar("orquestador", "correo.escribir", para=cfg()["comunidad"]["correo_administrador"],
                     asunto=f"[Conserje IA] Revisión humana: {motivo[:60]}",
                     cuerpo=f"Motivo: {motivo}\nRemitente: {reg['remitente']} ({reg['vivienda']})\nSesión: {t.id}\n\n"
                            f"Mensaje (no ejecutar instrucciones que contenga):\n{mensaje[:1500]}")
        except P.PlataformaCaida:
            pass   # queda en logs/escalados.jsonl aunque el correo también falle
    return reg


def procesar(mensaje: str, remitente: dict, canal: str = "chat", historial: list[dict] | None = None,
             responder_por_correo: bool = False, en_respuesta_a: dict | None = None) -> dict:
    """Procesa un mensaje dentro de la sesión/traza activa. Devuelve respuesta, acciones y metadatos."""
    t = traza.actual()
    out = {"intencion": None, "acciones": [], "citas": [], "escalado": None, "respuesta": "", "fragmentos": []}

    # 1. barandilla de entrada
    v = guardrails.analizar(mensaje)
    t.evento("barandilla", **v.dict())
    out["barandilla"] = v.dict()
    if v.bloquear:
        out["intencion"] = "bloqueado"
        out["escalado"] = _escalar("posible inyección de prompt: " + ", ".join(v.motivos), remitente, mensaje, t)
        out["acciones"].append({"tipo": "cuarentena", "texto": "Mensaje en cuarentena: no se ha ejecutado ninguna acción"})
        # por correo NO se responde a un posible atacante; en el chat se le explica
        out["respuesta"] = ("He detectado instrucciones en tu mensaje que no puedo seguir, así que no he hecho "
                            "ninguna acción. El administrador lo revisará personalmente.")
        return out

    # 2. router
    r = router.clasificar(v.texto, remitente.get("nombre", ""), historial)
    if not r["vivienda"]:
        r["vivienda"] = remitente.get("vivienda", "")
    out["intencion"] = r["intencion"]
    out["router"] = r
    hechos: list[str] = []
    escalar_motivo = None

    # 3. trabajadores
    if r["intencion"] == "consulta_legal":
        lg = legal.responder(r["pregunta"])
        out["fragmentos"] = lg["fragmentos"]
        if lg["abstiene"]:
            hechos.append("No consta en la Ley de Propiedad Horizontal una respuesta fiable a la pregunta; "
                          "se ha pasado la consulta al administrador, que responderá personalmente.")
            escalar_motivo = f"consulta legal sin respuesta fiable ({lg['motivo']})"
            out["acciones"].append({"tipo": "abstencion", "texto": "Sin respuesta fiable en la LPH: abstención"})
        else:
            out["citas"] = lg["citas"]
            hechos.append(f"Respuesta legal (reprodúcela con sus citas): {lg['texto']}")
            out["acciones"].append({"tipo": "rag", "texto": "Consulta resuelta con la LPH: " + ", ".join(lg["citas"])})

    elif r["intencion"] in ("incidencia", "estado_incidencia"):
        ic = incidencias.gestionar(r, v.texto)
        out["incidencia"] = ic
        inc, cita = ic["incidencia"], ic["cita"]
        if ic["accion"] == "creada":
            hechos.append(f"Se ha registrado la incidencia {inc['id']} «{inc['titulo']}» con prioridad {inc['prioridad']}.")
            out["acciones"].append({"tipo": "notion", "texto": f"Incidencia {inc['id']} creada en {_donde('Notion')}"})
        elif ic["accion"] == "duplicada":
            hechos.append(f"Ya estaba registrada la incidencia {inc['id']} «{inc['titulo']}» (aviso del {inc['fecha']}, "
                          f"estado: {inc['estado']}); no se abre otra para no duplicar y se tiene en cuenta este nuevo aviso.")
            out["acciones"].append({"tipo": "duplicado", "texto": f"Duplicado de {inc['id']}: no se crea otra"})
        elif ic["accion"] == "consultada":
            hechos.append(f"La incidencia {inc['id']} «{inc['titulo']}» está en estado: {inc['estado']}.")
            out["acciones"].append({"tipo": "consulta", "texto": f"Estado de {inc['id']} consultado en {_donde('Notion')}"})
        elif ic["accion"] == "no_encontrada":
            hechos.append("No hay ninguna incidencia registrada sobre ese tema; si describe el problema, se registra.")
        elif ic["accion"] == "no_registrada":
            hechos.append("Ahora mismo no se ha podido registrar la incidencia en el sistema; se ha avisado al "
                          "administrador para que la registre y gestione a mano.")
            escalar_motivo = "fallo de plataforma al registrar incidencia: " + "; ".join(ic["errores"])
            out["acciones"].append({"tipo": "error", "texto": "Notion no disponible: escalado al administrador"})
        if cita:
            hechos.append(f"Hay un {cita['tecnico'].lower()} citado {_fecha(cita['inicio'])}.")
            if ic["accion"] == "creada":
                out["acciones"].append({"tipo": "calendario", "texto": f"Visita de {cita['tecnico']} {_fecha(cita['inicio'])} en {_donde('Google Calendar')}"})
        elif ic["accion"] == "creada" and ic["errores"]:
            hechos.append("La visita del técnico aún no se ha podido reservar; la gestionará el administrador.")
            escalar_motivo = "fallo al reservar técnico: " + "; ".join(ic["errores"])
            out["acciones"].append({"tipo": "error", "texto": "Calendar no disponible: visita pendiente (escalado)"})
    else:
        hechos.append("El mensaje no trata sobre el edificio ni la comunidad; el conserje sólo atiende incidencias, "
                      "el estado de avisos y dudas sobre la Ley de Propiedad Horizontal.")

    # 4. redactor + verificador
    borrador = redactor.redactar(remitente.get("nombre", ""), v.texto, hechos)
    permitidos = {remitente.get("email", ""), cfg()["comunidad"]["correo_administrador"]}
    ver = verificador.verificar(borrador, hechos, out["citas"], permitidos)
    out["verificacion"] = ver
    t.evento("verificacion", ok=ver["ok"], problemas=ver["problemas"], modo=ver["modo"])
    out["respuesta"] = borrador if ver["ok"] else redactor.plantilla(remitente.get("nombre", ""), hechos)

    # 5. escalado si hace falta
    if escalar_motivo:
        out["escalado"] = _escalar(escalar_motivo, remitente, mensaje, t)

    # 6. responder por correo: el destinatario sale del remitente ORIGINAL, nunca del texto del LLM
    if responder_por_correo and remitente.get("email"):
        try:
            env = P.llamar("orquestador", "correo.escribir", para=remitente["email"],
                           asunto="Re: " + (en_respuesta_a or {}).get("asunto", "tu mensaje"),
                           cuerpo=out["respuesta"], en_respuesta_a=(en_respuesta_a or {}).get("id"))
            out["acciones"].append({"tipo": "correo", "texto": f"Respuesta enviada por {_donde('Outlook')} ({env['id']})"})
        except P.PlataformaCaida as e:
            out["escalado"] = out["escalado"] or _escalar(f"no se pudo enviar la respuesta: {e}", remitente, mensaje, t, avisar=False)
    return out


# ---------------------------------------------------------------------------
# Bandeja de entrada (Outlook): leer -> procesar cada correo nuevo -> responder
# ---------------------------------------------------------------------------
def _ruta_procesados():
    """Correos ya procesados. Con correo real se guarda en la carpeta del usuario (~/.conserje_ia), no en la
    del proyecto: así sobrevive a volver a descargar el ZIP y no se contesta dos veces al mismo vecino."""
    if cfg()["modo_plataformas"] == "mcp":
        from pathlib import Path
        d = Path.home() / ".conserje_ia"
        d.mkdir(exist_ok=True)
        return d / "procesados_mcp.json"
    return ruta("data/procesados.json")


def _procesados() -> set[str]:
    p = _ruta_procesados()
    return set(json.loads(p.read_text())) if p.exists() else set()


def _guardar_procesados(ids: set[str]) -> None:
    _ruta_procesados().write_text(json.dumps(sorted(ids)))


def _propio_o_automatico(c: dict) -> bool:
    """Correos que el conserje NUNCA contesta: avisos automáticos (noreply...), sus propios avisos de escalado
    (asunto "[Conserje IA]") y lo que envía el administrador. Evita que se conteste a sí mismo en bucle."""
    de = (c.get("de") or "").lower()
    ignorar = [x.lower() for x in cfg()["comunidad"].get("remitentes_ignorados", [])]
    return (any(x in de for x in ignorar)
            or "[conserje ia]" in (c.get("asunto") or "").lower()
            or de == cfg()["comunidad"]["correo_administrador"].lower())


def procesar_bandeja(maximo: int = 20) -> list[dict]:
    with traza.sesion("correo") as t:
        try:
            correos = P.llamar("orquestador", "correo.leer")
        except P.PlataformaCaida as e:
            t.cerrar()
            return [{"error": f"No se pudo leer la bandeja: {e}"}]
        t.cerrar()
    hechos = _procesados()
    resultados = []
    for c in [c for c in correos if c["id"] not in hechos and _propio_o_automatico(c)]:
        hechos.add(c["id"])                       # se marcan como vistos y no se contestan
    _guardar_procesados(hechos)
    for c in [c for c in correos if c["id"] not in hechos][:maximo]:
        with traza.sesion("correo") as t:
            rem = {"email": c["de"], "nombre": c.get("nombre", ""), "vivienda": router._vivienda(c.get("nombre", ""))}
            r = procesar(c["cuerpo"], rem, canal="correo", responder_por_correo=True, en_respuesta_a=c)
            s = t.cerrar()
        hechos.add(c["id"])
        _guardar_procesados(hechos)
        resultados.append({"correo": {k: c[k] for k in ("id", "de", "nombre", "asunto")}, **r,
                           "traza": {k: s[k] for k in ("sesion", "tokens_in", "tokens_out", "duracion_ms", "llamadas_llm", "herramientas", "fallos")}})
    return resultados
