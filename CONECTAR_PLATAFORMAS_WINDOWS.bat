@echo off
REM ==========================================================================
REM  Conserje IA - conectar Outlook, Google Calendar y Notion (modo MCP)
REM  Antes: tener el fichero .env con las llaves (ver README, seccion 4).
REM ==========================================================================
setlocal
cd /d "%~dp0"
echo.
echo  === Conserje IA: conectar las 3 plataformas ===
echo.
if not exist .env (
    echo Falta el fichero .env con las llaves. Crealo primero (ver instrucciones).
    pause & exit /b 1
)

REM ---- 1. Herramientas que usan los servidores MCP ----
where npx >nul 2>nul || (
    echo [1/6] Instalando Node.js...
    winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
    set "PATH=%ProgramFiles%\nodejs;%PATH%"
)
where uvx >nul 2>nul || (
    echo [1/6] Instalando uv...
    winget install -e --id astral-sh.uv --accept-source-agreements --accept-package-agreements
    set "PATH=%USERPROFILE%\.local\bin;%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
)
echo [1/6] Node.js y uv listos.

REM ---- 2. Entorno de Python (por si esta carpeta es nueva) ----
if not exist .venv (
    echo [2/6] Preparando el entorno de Python...
    python -m venv .venv
    call .venv\Scripts\activate.bat
    python -m pip install -q -r requirements.txt
    python -m app.rag.indice --construir
) else (
    call .venv\Scripts\activate.bat
)
echo [2/6] Python listo.

REM ---- 3. Notion: crear la base de datos Incidencias ----
echo [3/6] Creando la base de datos Incidencias en Notion...
python -m app.tools.preparar_notion
if errorlevel 1 ( pause & exit /b 1 )

REM ---- 4. Outlook: iniciar sesion (una sola vez) ----
echo.
echo [4/6] Outlook: abajo aparecera una direccion web y un CODIGO.
echo        Abre la direccion, pega el codigo y entra con el correo de Outlook del conserje.
echo.
call npx -y @softeria/ms-365-mcp-server --login

REM ---- 5. Listar las herramientas reales de cada servidor ----
echo.
echo [5/6] Comprobando los 3 servidores (puede tardar 1-2 minutos)...
python -m app.tools.mcp_backend --listar > logs\herramientas_mcp.txt 2>&1
type logs\herramientas_mcp.txt

REM ---- 6. Prueba de lectura ----
echo.
echo [6/6] Probando a leer de las 3 plataformas...
python -m app.tools.mcp_backend --probar >> logs\herramientas_mcp.txt 2>&1
type logs\herramientas_mcp.txt | findstr /B "OK ERR"
echo.
echo  Listo. Manda a Claude el fichero logs\herramientas_mcp.txt (no contiene llaves).
pause
