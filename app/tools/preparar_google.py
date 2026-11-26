"""Genera data/google_oauth.json (formato "Desktop app" de Google) a partir de .env.

El servidor MCP de Google Calendar (@cocal/google-calendar-mcp) lee ese fichero (GOOGLE_OAUTH_CREDENTIALS).
Contiene el secreto de cliente: está en .gitignore y nunca se sube al repo.
Uso: python -m app.tools.preparar_google
"""
import json
import os
import sys

from ..config import cfg, ruta


def main() -> None:
    cfg()   # carga .env
    cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    sec = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not cid or not sec:
        sys.exit("Faltan GOOGLE_OAUTH_CLIENT_ID o GOOGLE_OAUTH_CLIENT_SECRET en el fichero .env")
    p = ruta("data/google_oauth.json")
    p.write_text(json.dumps({"installed": {
        "client_id": cid, "client_secret": sec,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "redirect_uris": ["http://localhost"]}}, indent=1), encoding="utf-8")
    print(f"Credenciales de Google listas en {p}")


if __name__ == "__main__":
    main()
