"""python -m app  ->  arranca la web y la abre en el navegador.

Usa el puerto 8000; si está ocupado por otro programa, prueba 8001, 8002... hasta 8020.
Se puede fijar uno con la variable PUERTO (p. ej. PUERTO=8080 python -m app).
"""
import os
import socket
import threading
import webbrowser

import uvicorn


def puerto_libre(inicial: int) -> int:
    for p in range(inicial, inicial + 21):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise SystemExit(f"No hay ningún puerto libre entre {inicial} y {inicial + 20}.")


if __name__ == "__main__":
    puerto = puerto_libre(int(os.environ.get("PUERTO", "8000")))
    url = f"http://localhost:{puerto}"
    print(f"\n  Conserje IA en  {url}\n  (deja esta ventana abierta mientras uses la app)\n")
    if os.environ.get("NO_NAVEGADOR") != "1":
        threading.Timer(2.0, lambda: webbrowser.open(url)).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=puerto, log_level="warning")
