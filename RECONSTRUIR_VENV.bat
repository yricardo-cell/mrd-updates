@echo off
title Reconstruyendo venv MRD TOOL CONTROL
cd /d "C:\mrd_tool_control"

echo [1/4] Eliminando venv antiguo...
rmdir /s /q venv

echo [2/4] Creando venv nuevo en la ruta correcta...
python -m venv venv
if errorlevel 1 (
    echo ERROR: Python no encontrado en PATH. Instala Python 3.x primero.
    pause
    exit /b 1
)

echo [3/4] Instalando dependencias...
venv\Scripts\pip.exe install -r requirements.txt
if errorlevel 1 (
    echo ERROR al instalar dependencias.
    pause
    exit /b 1
)

echo [4/4] Probando arranque...
echo.
echo Si arranca correctamente veras: "Application startup complete."
echo Pulsa Ctrl+C para cerrar cuando lo veas.
echo.
venv\Scripts\uvicorn.exe main:app --host 0.0.0.0 --port 8000 --workers 1

pause
