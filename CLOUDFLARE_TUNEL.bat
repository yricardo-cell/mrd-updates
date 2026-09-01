@echo off
title MRD - Tunel Cloudflare Activo
color 0A
cd /d "%~dp0"

echo.
echo  =====================================================
echo   MRD TOOL CONTROL - Tunel Cloudflare
echo  =====================================================
echo.

if not exist "cloudflared.exe" (
    echo  [ERROR] cloudflared.exe no encontrado.
    echo  Ejecuta primero CLOUDFLARE_INSTALAR.bat
    echo.
    pause
    exit /b 1
)

:: Crear carpeta de datos si no existe
if not exist "data" mkdir data

:: Limpiar log anterior para que la app detecte la URL nueva
if exist "data\cloudflared.log" del /f /q "data\cloudflared.log"

echo  Iniciando tunel hacia http://localhost:8000 ...
echo  La URL publica aparecera en unos segundos.
echo.
echo  IMPORTANTE: Deja esta ventana abierta mientras uses el acceso remoto.
echo              Al cerrarla, el tunel se detiene.
echo.
echo  La URL tambien aparece en la app: Menu ^> Acceso Remoto
echo.
echo  -------------------------------------------------------

cloudflared.exe tunnel --url http://localhost:8000 --logfile data\cloudflared.log --loglevel info

echo.
echo  El tunel se ha cerrado.
pause
