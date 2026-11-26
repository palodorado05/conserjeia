@echo off
REM Conserje IA - arrancar (cuando ya se ha instalado una vez con INSTALAR_WINDOWS.bat)
cd /d "%~dp0"
set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
where ollama >nul 2>nul && set "OLLAMA=ollama"
start "" /min "%OLLAMA%" serve
timeout /t 3 /nobreak >nul
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt
python -m app
pause
