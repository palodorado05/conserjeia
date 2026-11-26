"""Backend MCP real: Outlook (Microsoft 365), Google Calendar y Notion a través de servidores MCP.

Cada servidor se lanza como proceso hijo (stdio) con el comando de config.yaml -> mcp.servidores y se
mantiene abierto mientras viva la app (un bucle asyncio en un hilo propio). Los agentes no ven nada de
esto: la pasarela app/tools/plataformas.py llama a `ejecutar("notion.escribir", {...})` y aquí se traduce
al nombre y los argumentos REALES de cada servidor.

Puesta en marcha (ver README, "Modo MCP"):
  1. python -m app.tools.mcp_backend --listar    -> lista las herramientas reales de cada servidor
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

from ..config import cfg, expandir


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
                env = {**os.environ, **{k: expandir(v) for k, v in s.get("env", {}).items()}}
                params = StdioServerParameters(command=s["comando"], args=s["args"], env=env)
                lectura, escritura = await self.pila.enter_async_context(stdio_client(params))
                sesion = await self.pila.enter_async_context(ClientSession(lectura, escritura))
                await asyncio.wait_for(sesion.initialize(), timeout=60)
                self.sesiones[nombre] = sesion
            return self.sesiones[nombre]

    async def _llamar(self, servidor: str, herramienta: str, args: dict):
        s = await self._sesion(servidor)
        r = await asyncio.wait_for(s.call_tool(herramienta, args), timeout=60)
        textos = [c.text for c in r.content if getattr(c, "type", "") == "text"]
        if r.isError:
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
        # TODO: confirmad los parámetros con --listar (el servidor expone la API de Microsoft Graph)
        r = self.llamar_crudo("correo.leer", {"top": 15, "select": ["id", "subject", "from", "body", "receivedDateTime"]})
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

    # --- Google Calendar (workspace-mcp) ---------------------------------------
    def calendario_leer(self, desde, hasta):
        r = self.llamar_crudo("calendario.leer", {
            "user_google_email": expandir(self.c["google_email"]), "calendar_id": "primary",
            "time_min": _rfc3339(desde), "time_max": _rfc3339(hasta), "max_results": 50})
        if isinstance(r, dict):              # si alguna versión devuelve JSON
            items = r.get("items", r.get("events", []))
            return [{"id": e.get("id", ""), "titulo": e.get("summary", ""),
                     "inicio": e.get("start", {}).get("dateTime", "")[:16], "fin": e.get("end", {}).get("dateTime", "")[:16]}
                    for e in items]
        # TODO: workspace-mcp devuelve texto; ajustad la expresión si vuestra versión cambia el formato
        eventos = []
        for m in re.finditer(r'"(?P<t>[^"]+)"\s*\(Starts?:\s*(?P<i>[\dT:\-+]+),\s*Ends?:\s*(?P<f>[\dT:\-+]+)\)(?:\s*ID:\s*(?P<id>\S+))?', str(r)):
            eventos.append({"id": m["id"] or "", "titulo": m["t"], "inicio": m["i"][:16], "fin": m["f"][:16]})
        return eventos

    def calendario_escribir(self, titulo, inicio, fin, descripcion=""):
        r = self.llamar_crudo("calendario.escribir", {
            "user_google_email": expandir(self.c["google_email"]), "calendar_id": "primary",
            "summary": titulo, "start_time": _rfc3339(inicio), "end_time": _rfc3339(fin),
            "description": descripcion, "timezone": cfg()["comunidad"]["zona_horaria"]})
        m = re.search(r"(?:ID|id)[:\s\"]+([\w\-]+)", str(r))
        return {"id": m.group(1) if m else "gcal"}

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
def _sin_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def _rfc3339(iso_local: str) -> str:
    from zoneinfo import ZoneInfo
    d = datetime.fromisoformat(iso_local)
    if d.tzinfo is None:
        d = d.replace(tzinfo=ZoneInfo(cfg()["comunidad"]["zona_horaria"]))
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--listar", action="store_true", help="lista las herramientas reales de cada servidor")
    ap.add_argument("--probar", action="store_true", help="llama una vez a cada herramienta lógica")
    a = ap.parse_args()
    b = BackendMCP()
    if a.listar:
        for srv, tools in b._correr(b._listar()).items():
            print(f"\n== {srv} ==")
            print(tools if isinstance(tools, str) else "\n".join(f"  {n:40s} {d}" for n, d in tools))
    if a.probar:
        from datetime import timedelta
        ahora = datetime.now().replace(second=0, microsecond=0)
        pruebas = [("correo.leer", {}), ("notion.leer", {}),
                   ("calendario.leer", {"desde": ahora.isoformat(), "hasta": (ahora + timedelta(days=7)).isoformat()})]
        for h, args in pruebas:
            try:
                r = b.ejecutar(h, args)
                print(f"OK  {h}: {len(r)} elementos · primero: {json.dumps(r[:1], ensure_ascii=False)[:200]}")
            except Exception as e:
                print(f"ERR {h}: {e}")
        print("(las escrituras se prueban desde la app: un aviso en el chat crea incidencia y cita)")
