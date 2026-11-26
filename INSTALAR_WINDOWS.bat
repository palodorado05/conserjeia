@echo off
REM ==========================================================================
REM  Conserje IA - instalacion y arranque automatico en Windows
REM  Doble clic en este fichero. La primera vez tarda ~10-15 min (descarga ~6 GB).
REM ==========================================================================
setlocal
cd /d "%~dp0"
echo.
echo  === Conserje IA: instalacion automatica ===
echo.

REM ---- 1. Ollama ----
set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
where ollama >nul 2>nul && set "OLLAMA=ollama"
if not exist "%OLLAMA%" if not "%OLLAMA%"=="ollama" (
    echo [1/6] Instalando Ollama...
    winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
) else (
    echo [1/6] Ollama ya esta instalado.
)
where ollama >nul 2>nul && set "OLLAMA=ollama"

REM ---- 2. Python ----
where python >nul 2>nul
if errorlevel 1 (
    echo [2/6] Instalando Python 3.12...
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
) else (
    echo [2/6] Python ya esta instalado.
)

REM ---- 3. Arrancar Ollama y descargar modelos ----
echo [3/6] Arrancando Ollama y descargando modelos (la primera vez tarda)...
start "" /min "%OLLAMA%" serve
timeout /t 5 /nobreak >nul
"%OLLAMA%" pull qwen3:8b
"%OLLAMA%" pull nomic-embed-text

REM ---- 4. Entorno de Python ----
echo [4/6] Preparando el entorno de Python...
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt

REM ---- 5. Indice RAG ----
echo [5/6] Construyendo el indice de la Ley de Propiedad Horizontal...
python -m app.rag.indice --construir

REM ---- 6. Arrancar y abrir el navegador ----
echo [6/6] Abriendo http://localhost:8000 ...
start "" http://localhost:8000
python -m app
pause
