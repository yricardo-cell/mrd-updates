@echo off
title Diagnostico MRD TOOL CONTROL
cd /d "C:\mrd_tool_control"

echo Parando servicio MRDToolControl...
net stop MRDToolControl >nul 2>&1
timeout /t 3 /nobreak >nul

echo.
echo === Probando uvicorn directamente ===
echo.
call venv\Scripts\activate.bat
venv\Scripts\uvicorn.exe main:app --host 0.0.0.0 --port 8000 --workers 1

echo.
echo === Fin - revisa los errores arriba ===
pause
