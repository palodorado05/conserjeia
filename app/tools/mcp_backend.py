"""Backend MCP real: Outlook (Microsoft 365), Google Calendar y Notion a través de servidores MCP.

Cada servidor se lanza como proceso hijo (stdio) con el comando de config.yaml -> mcp.servidores y se
mantiene abierto mientras viva la app (un bucle asyncio en un hilo propio). Los agentes no ven nada de
esto: la pasarela app/tools/plataformas.py llama a `ejecutar("notion.escribir", {...})` y aquí se traduce
al nombre y los argumentos REALES de cada servidor.

Puesta en marcha (ver README, "Modo MCP"):
  1. python -m app.tools.mcp_backend --listar --comprobar  -> herramientas reales y nombres de config.yaml
  2. corregid los nombres en config.yaml -> mcp.herramientas
  3. revisad los TODO de este fichero (forma exacta de los argumentos / del resultado)
  4. python -m app.tools.mcp_backend --probar    -> llama a las 6 herramientas lógicas una vez
  5. modo_plataformas: mcp  (o MODO_PLATAFORMAS=mcp python -m app)

Seguridad: los secretos llegan por variables de entorno (.env, nunca en el repo) y sólo se pasan al
proceso del servidor que los necesita.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import threading
from contextlib import AsyncExitStack
from datetime import datetime

from ..config import cfg, expandir, zona


class BackendMCP:
    def __init__(self):
        self.c = cfg()["mcp"]
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.sesiones: dict = {}
        self.pila = AsyncExitStack()
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ conexión
    async def _sesion(self, nombre: str):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        async with self._lock:
            if nombre not in self.sesiones:
                s = self.c["servidores"][nombre]
                # las variables vacías no se pasan: así el servidor usa sus valores por defecto
                # (p. ej. ms-365-mcp-server trae su propio registro de app si no hay MS365_MCP_CLIENT_ID)
                extra = {k: expandir(v) for k, v in s.get("env", {}).items()}
                env = {**os.environ, **{k: v for k, v in extra.items() if v}}
                params = StdioServerParameters(command=_ejecutable(s["comando"]), args=s["args"], env=env)
                lectura, escritura = await self.pila.enter_async_context(stdio_client(params))
                sesion = await self.pila.enter_async_context(ClientSession(lectura, escritura))
                await asyncio.wait_for(sesion.initialize(), timeout=60)
                self.sesiones[nombre] = sesion
            return self.sesiones[nombre]

    async def _llamar(self, servidor: str, herramienta: str, args: dict, intentos: int = 3):
        """Llama a la herramienta. Reintenta si el servidor corta la petición por tiempo
        (p. ej. el de Google Calendar da sólo 3 s a su primera consulta, cuando aún renueva el permiso)."""
        for i in range(intentos):
            try:
                return await self._llamar_una_vez(servidor, herramienta, args)
            except RuntimeError as e:
                transitorio = any(t in str(e).lower() for t in ("aborted", "timed out", "timeout", "econnreset"))
                if not transitorio or i == intentos - 1:
                    raise
                await asyncio.sleep(1 + i)

    async def _llamar_una_vez(self, servidor: str, herramienta: str, args: dict):
        s = await self._sesion(servidor)
        r = await asyncio.wait_for(s.call_tool(herramienta, args), timeout=60)
        textos = [c.text for c in r.content if getattr(c, "type", "") == "text"]
        es_error = getattr(r, "is_error", None)          # mcp >= 2.0
        if es_error is None:
            es_error = getattr(r, "isError", False)      # mcp 1.x
        if es_error:
            raise RuntimeError(" ".join(textos)[:300] or "error del servidor MCP")
        texto = "\n".join(textos)
        try:
            return json.loads(texto)
        except json.JSONDecodeError:
            return texto

    def _correr(self, corrutina):
        return asyncio.run_coroutine_threadsafe(corrutina, self.loop).result(timeout=90)

    def llamar_crudo(self, logica: str, args: dict):
        h = self.c["herramientas"][logica]
        return self._correr(self._llamar(h["servidor"], h["nombre"], args))

    async def _listar(self):
        out = {}
        for nombre in self.c["servidores"]:
            try:
                s = await self._sesion(nombre)
                out[nombre] = [(t.name, (t.description or "")[:90]) for t in (await s.list_tools()).tools]
            except Exception as e:
                out[nombre] = f"ERROR: {e}"
        return out

    # ------------------------------------------------------------------ herramientas lógicas
    def ejecutar(self, herramienta: str, args: dict):
        return getattr(self, herramienta.replace(".", "_"))(**args)

    # --- Outlook (@softeria/ms-365-mcp-server) ---------------------------------
    def correo_leer(self):
        # Solo la carpeta Bandeja de entrada ("inbox"): list-mail-messages mira TODAS las carpetas, incluida
        # Enviados, y el conserje acabaría leyendo (y contestando) sus propios correos.
        r = self.llamar_crudo("correo.leer", {"mailFolderId": "inbox", "$top": 25,
                                              "$orderby": ["receivedDateTime desc"],
                                              "$select": ["id", "subject", "from", "body", "receivedDateTime"]})
        mensajes = r.get("value", []) if isinstance(r, dict) else []
        return [{"id": m["id"],
                 "de": m.get("from", {}).get("emailAddress", {}).get("address", ""),
                 "nombre": m.get("from", {}).get("emailAddress", {}).get("name", ""),
                 "asunto": m.get("subject", ""),
                 "cuerpo": _sin_html(m.get("body", {}).get("content", "") or m.get("bodyPreview", "")),
                 "fecha": m.get("receivedDateTime", "")} for m in mensajes]

    def correo_escribir(self, para, asunto, cuerpo, en_respuesta_a=None):
        # TODO: confirmad que send-mail recibe el cuerpo de Graph dentro de "body"
        self.llamar_crudo("correo.escribir", {"body": {
            "message": {"subject": asunto, "body": {"contentType": "Text", "content": cuerpo},
                        "toRecipients": [{"emailAddress": {"address": para}}]},
            "saveToSentItems": True}})
        return {"id": f"graph-{datetime.now():%H%M%S}"}

    # --- Google Calendar (@cocal/google-calendar-mcp) -------------------------
    # list-events devuelve JSON {"events": [{"id", "summary", "start": {"dateTime"}, "end": {...}}]}
    # create-event devuelve JSON {"event": {"id", ...}}. Las horas van sin zona y se indica timeZone.
    def calendario_leer(self, desde, hasta):
        zona_txt = cfg()["comunidad"]["zona_horaria"]
        r = self.llamar_crudo("calendario.leer", {
            "calendarId": "primary", "timeMin": _local(desde), "timeMax": _local(hasta), "timeZone": zona_txt})
        items = r.get("events", r.get("items", [])) if isinstance(r, dict) else []
        def hora(x):
            x = x or {}
            return (x.get("dateTime") or x.get("date") or "")[:16]
        return [{"id": e.get("id", ""), "titulo": e.get("summary", "") or "", "inicio": hora(e.get("start")),
                 "fin": hora(e.get("end")), "descripcion": e.get("description", "") or ""} for e in items]

    def calendario_escribir(self, titulo, inicio, fin, descripcion=""):
        r = self.llamar_crudo("calendario.escribir", {
            "calendarId": "primary", "summary": titulo, "description": descripcion,
            "start": _local(inicio), "end": _local(fin), "timeZone": cfg()["comunidad"]["zona_horaria"]})
        ev = r.get("event", r) if isinstance(r, dict) else {}
        return {"id": ev.get("id", "gcal") if isinstance(ev, dict) else "gcal"}

    # --- Notion (@notionhq/notion-mcp-server) ----------------------------------
    # Base de datos "Incidencias" con propiedades: Nombre (título), Categoría (select), Prioridad (select),
    # Vivienda (texto), Estado (select: Abierta / En curso / Cerrada), Descripción (texto), Fecha (fecha).
    def notion_leer(self, estado=None):
        # TODO: en versiones antiguas del servidor la herramienta es API-post-database-query con "database_id"
        r = self.llamar_crudo("notion.leer", {"data_source_id": expandir(self.c["notion_data_source_id"])})
        out = []
        for p in (r.get("results", []) if isinstance(r, dict) else []):
            pr = p.get("properties", {})
            inc = {"id": p["id"][:8], "titulo": _txt(pr.get("Nombre")), "categoria": _sel(pr.get("Categoría")),
                   "prioridad": _sel(pr.get("Prioridad")), "vivienda": _txt(pr.get("Vivienda")),
                   "estado": _sel(pr.get("Estado")) or "Abierta", "descripcion": _txt(pr.get("Descripción")),
                   "fecha": (pr.get("Fecha", {}).get("date") or {}).get("start", "") or p.get("created_time", "")[:10]}
            if estado is None or inc["estado"] == estado:
                out.append(inc)
        return out

    def notion_escribir(self, titulo, categoria, prioridad, vivienda, descripcion):
        def texto(v):
            return {"rich_text": [{"text": {"content": v}}]}
        r = self.llamar_crudo("notion.escribir", {
            "parent": {"data_source_id": expandir(self.c["notion_data_source_id"])},   # TODO: "database_id" en v1
            "properties": {"Nombre": {"title": [{"text": {"content": titulo}}]},
                           "Categoría": {"select": {"name": categoria}}, "Prioridad": {"select": {"name": prioridad}},
                           "Vivienda": texto(vivienda), "Estado": {"select": {"name": "Abierta"}},
                           "Descripción": texto(descripcion),
                           "Fecha": {"date": {"start": datetime.now().date().isoformat()}}}})
        return {"id": (r.get("id", "") if isinstance(r, dict) else "")[:8] or "notion"}


# ---------------------------------------------------------------------- utilidades
def _ejecutable(nombre: str) -> str:
    """Ruta completa de npx/uvx. En Windows, justo después de instalarlos con winget, aún no están en el PATH."""
    import shutil
    encontrado = shutil.which(nombre)
    if encontrado:
        return encontrado
    casa = os.path.expanduser("~")
    candidatos = [os.path.join(casa, ".local", "bin", nombre + ".exe"),
                  os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links", nombre + ".exe"),
                  os.path.join(os.environ.get("ProgramFiles", ""), "nodejs", nombre + ".cmd"),
                  os.path.join(casa, ".cargo", "bin", nombre + ".exe")]
    return next((c for c in candidatos if os.path.exists(c)), nombre)


def _sin_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def _local(iso: str) -> str:
    """'2026-11-27T10:00' -> '2026-11-27T10:00:00' (hora local, sin zona: la zona va en timeZone)."""
    return datetime.fromisoformat(iso).replace(tzinfo=None).isoformat(timespec="seconds")


def _rfc3339(iso_local: str) -> str:
    d = datetime.fromisoformat(iso_local)
    if d.tzinfo is None:
        d = d.replace(tzinfo=zona())
    return d.isoformat()


def _txt(p) -> str:
    if not p:
        return ""
    partes = p.get("title") or p.get("rich_text") or []
    return "".join(x.get("plain_text") or x.get("text", {}).get("content", "") for x in partes)


def _sel(p) -> str:
    if not p:
        return ""
    v = p.get("select") or p.get("status") or {}
    return v.get("name", "")


if __name__ == "__main__":
    import sys
    try:                                   # la consola de Windows (cp1252) no imprime emojis de las descripciones
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--listar", action="store_true", help="lista las herramientas reales de cada servidor")
    ap.add_argument("--comprobar", action="store_true", help="comprueba que los nombres de config.yaml existen")
    ap.add_argument("--probar", action="store_true", help="llama una vez a cada herramienta lógica de lectura")
    a = ap.parse_args()
    b = BackendMCP()
    from datetime import timedelta
    ahora = datetime.now().replace(second=0, microsecond=0)
    leer_cal = {"desde": ahora.isoformat(), "hasta": (ahora + timedelta(days=7)).isoformat()}

    if a.listar or a.comprobar:
        listado = b._correr(b._listar())
    if a.listar:
        for srv, tools in listado.items():
            print(f"\n== {srv} ==")
            print(tools if isinstance(tools, str) else "\n".join(f"  {n:40s} {d.splitlines()[0] if d else ''}" for n, d in tools))
    if a.comprobar:
        import difflib
        print("\n== Nombres de herramientas en config.yaml ==")
        for logica, h in b.c["herramientas"].items():
            tools = listado.get(h["servidor"])
            if isinstance(tools, str):
                print(f"??  {logica:20s} -> {h['nombre']}  (servidor {h['servidor']} no responde)")
                continue
            nombres = [n for n, _ in tools]
            if h["nombre"] in nombres:
                print(f"OK  {logica:20s} -> {h['nombre']}")
            else:
                print(f"NO  {logica:20s} -> {h['nombre']}  ¿quizá? {difflib.get_close_matches(h['nombre'], nombres, n=3, cutoff=0.3)}")

    if a.probar:
        pruebas = [("correo.leer", {}), ("notion.leer", {}), ("calendario.leer", leer_cal)]
        for h, args in pruebas:
            try:
                r = b.ejecutar(h, args)
                print(f"OK  {h}: {len(r)} elementos")
            except Exception as e:
                print(f"ERR {h}: {str(e)[:300]}")
        print("(las escrituras se prueban desde la app: un aviso en el chat crea incidencia y cita)")
