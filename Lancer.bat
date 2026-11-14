@echo off
title Swing Trader
cd /d "%~dp0"
echo Demarrage de Swing Trader... (ferme cette fenetre pour arreter l'application)
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000"
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
pause
