#!/bin/bash
# ==========================================================================
#  Conserje IA - instalación y arranque automático en Mac
#  Doble clic en este fichero. La primera vez tarda ~10-15 min (descarga ~6 GB).
#  Si macOS lo bloquea: clic derecho -> Abrir -> Abrir.
# ==========================================================================
set -e
cd "$(dirname "$0")"
echo; echo " === Conserje IA: instalación automática ==="; echo

# ---- 1. Ollama ----
if ! command -v ollama >/dev/null 2>&1 && [ ! -d /Applications/Ollama.app ]; then
  echo "[1/6] Instalando Ollama..."
  curl -fL -o /tmp/Ollama.zip https://ollama.com/download/Ollama-darwin.zip
  unzip -q -o /tmp/Ollama.zip -d /Applications
fi
open -a Ollama || true
OLLAMA=ollama
command -v ollama >/dev/null 2>&1 || OLLAMA=/Applications/Ollama.app/Contents/Resources/ollama
echo "[1/6] Ollama listo."

# ---- 2. Python ----
if ! command -v python3 >/dev/null 2>&1; then
  echo "[2/6] Falta Python: se abre el instalador de Python (Command Line Tools)."
  xcode-select --install || true
  echo "Cuando termine, vuelve a hacer doble clic en este fichero."; read -r; exit 1
fi
echo "[2/6] Python listo."

# ---- 3. Modelos ----
echo "[3/6] Descargando modelos (la primera vez tarda)..."
for i in 1 2 3 4 5 6 7 8 9 10; do "$OLLAMA" list >/dev/null 2>&1 && break; sleep 2; done
"$OLLAMA" pull qwen3:8b
"$OLLAMA" pull nomic-embed-text

# ---- 4. Entorno de Python ----
echo "[4/6] Preparando el entorno de Python..."
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

# ---- 5. Índice RAG ----
echo "[5/6] Construyendo el índice de la Ley de Propiedad Horizontal..."
python -m app.rag.indice --construir

# ---- 6. Arrancar y abrir el navegador ----
echo "[6/6] Abriendo http://localhost:8000 ..."
(sleep 3; open http://localhost:8000) &
python -m app
