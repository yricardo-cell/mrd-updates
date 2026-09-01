@echo off
title MRD TOOL - Instalar dependencias
cd /d "%~dp0"
echo.
echo  Preparando el entorno virtual e instalando dependencias...
echo.

:: Detectar Python (PATH o launcher py)
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY ( where py >nul 2>&1 && set "PY=py -3" )
if not defined PY (
    echo  [ERROR] No se encuentra Python en este PC.
    echo  Instala Python 3.11 desde https://www.python.org/downloads/
    echo  y marca "Add Python to PATH" al instalar.
    pause
    exit /b 1
)

:: Crear el venv si no existe
if not exist "venv\Scripts\python.exe" (
    echo  Creando entorno virtual...
    %PY% -m venv venv
    if errorlevel 1 ( echo  [ERROR] No se pudo crear el venv. & pause & exit /b 1 )
)

:: Instalar dependencias dentro del venv
"venv\Scripts\python.exe" -m pip install --upgrade pip
"venv\Scripts\python.exe" -m pip install -r requirements.txt

echo.
echo  Listo. Ahora arranca con INICIAR_MRD.bat
pause
