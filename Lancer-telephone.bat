@echo off
title Swing Trader (acces telephone)
cd /d "%~dp0"
echo.
echo Sur ton telephone, connecte au MEME Wi-Fi que ce PC, ouvre une de ces adresses :
powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | ForEach-Object { '   http://' + $_.IPAddress + ':8000' }"
echo.
echo Puis menu du navigateur ^> "Ajouter a l'ecran d'accueil" pour avoir une icone.
echo Si Windows demande l'autorisation du pare-feu : autorise seulement les reseaux PRIVES.
echo Ferme cette fenetre pour arreter l'application.
echo.
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
pause
