@echo off
REM ==========================================================================
REM  Conserje IA - medir las cifras de la memoria en este ordenador
REM  1) evalua el RAG (acierto@3)  2) coste de construccion (usage de Claude Code)
REM  3) modelo financiero con los tokens medidos en logs\usage.jsonl
REM  Al final crea resultados_medidos.zip para mandarselo a Claude.
REM ==========================================================================
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
chcp 65001 >nul
set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
where ollama >nul 2>nul && set "OLLAMA=ollama"
start "" /min "%OLLAMA%" serve
timeout /t 3 /nobreak >nul
call .venv\Scripts\activate.bat

echo.
echo [1/3] Evaluando el RAG sobre la Ley de Propiedad Horizontal...
python -m eval.evaluar_rag

echo.
echo [2/3] Coste de construccion leido del usage de Claude Code de este ordenador...
python -m negocio.coste_construccion > nul
python -c "import json;d=json.load(open('logs/coste_construccion.json'));print('   tokens:',d['tokens'],' coste:',d['coste'])"
copy /y logs\coste_construccion.json "logs\coste_construccion_%COMPUTERNAME%.json" >nul

echo.
echo [3/3] Modelo financiero con los tokens medidos...
python -m negocio.modelo_financiero

echo.
echo Empaquetando resultados...
powershell -NoProfile -Command "Compress-Archive -Force -Path logs\usage.jsonl,logs\trazas.jsonl,logs\escalados.jsonl,logs\coste_construccion_*.json,eval\resultados_rag.json,negocio\salida\* -DestinationPath resultados_medidos.zip" 2>nul
echo.
echo  Listo. Manda a Claude el fichero resultados_medidos.zip de esta carpeta.
pause
