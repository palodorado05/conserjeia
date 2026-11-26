@echo off
REM ==========================================================================
REM  Conserje IA - conectar Outlook, Google Calendar y Notion (modo MCP)
REM  Antes: tener el fichero .env con las llaves (ver README, seccion 4).
REM ==========================================================================
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
chcp 65001 >nul
echo.
echo  === Conserje IA: conectar las 3 plataformas ===
echo.
REM ---- 0. Fichero .env con las llaves ----
if not exist .env if exist .env.txt ren .env.txt .env
if not exist .env (
    copy /y .env.example .env >nul
    echo Se va a abrir el Bloc de notas con el fichero de llaves.
    echo Rellena detras de cada = tus llaves, pulsa Ctrl+G para guardar y CIERRA el Bloc de notas.
    echo.
    pause
    notepad .env
)
findstr /R /C:"^NOTION_TOKEN=..*" .env >nul || (
    echo Falta NOTION_TOKEN en el fichero .env - vuelve a ejecutar y rellenalo.
    notepad .env
    pause
    exit /b 1
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
    python -m pip install -q -r requirements.txt
)
echo [2/6] Python listo.

REM ---- 3. Notion: crear la base de datos Incidencias ----
echo [3/6] Creando la base de datos Incidencias en Notion...
python -m app.tools.preparar_notion
if errorlevel 1 ( pause & exit /b 1 )

REM ---- 4. Outlook: iniciar sesion solo si hace falta ----
echo.
echo [4/6] Outlook: comprobando la sesion...
call npx -y @softeria/ms-365-mcp-server --verify-login > logs\outlook.txt 2>&1
findstr /C:"\"success\":true" logs\outlook.txt >nul
if errorlevel 1 (
    echo        Abajo aparecera una direccion web y un CODIGO.
    echo        Abre la direccion, pega el codigo y entra con el correo de Outlook del conserje.
    echo.
    call npx -y @softeria/ms-365-mcp-server --login
) else (
    echo        Outlook ya estaba conectado.
)

REM ---- 5. Google Calendar: iniciar sesion ----
echo.
echo [5/6] Google Calendar: se abrira el navegador. Entra con el Gmail del conserje y pulsa Continuar/Permitir.
echo        Si sale "Google no ha verificado esta aplicacion": pulsa Continuar.
python -m app.tools.preparar_google
if errorlevel 1 ( pause & exit /b 1 )
set "GOOGLE_OAUTH_CREDENTIALS=%CD%\data\google_oauth.json"
call npx -y @cocal/google-calendar-mcp auth

REM ---- 6. Comprobacion final ----
echo.
echo [6/6] Comprobando nombres de herramientas y lectura de las 3 plataformas...
python -m app.tools.mcp_backend --listar --comprobar > logs\herramientas_mcp.txt 2>&1
python -m app.tools.mcp_backend --probar >> logs\herramientas_mcp.txt 2>&1
findstr /B "OK NO ?? ERR" logs\herramientas_mcp.txt
echo.
echo  Listo. Manda a Claude una captura de esta ventana.
pause
