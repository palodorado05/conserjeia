"""python -m app  ->  arranca la web en http://localhost:8000"""
import os

import uvicorn

if __name__ == "__main__":
    puerto = int(os.environ.get("PUERTO", "8000"))
    print(f"\n  Conserje IA en  http://localhost:{puerto}\n")
    uvicorn.run("app.main:app", host="127.0.0.1", port=puerto, log_level="warning")
