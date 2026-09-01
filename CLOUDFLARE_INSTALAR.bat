@echo off
title MRD - Instalar Cloudflare Tunnel
color 0B
cd /d "%~dp0"

echo.
echo  =====================================================
echo   MRD TOOL CONTROL - Instalar cloudflared
echo  =====================================================
echo.

if exist "cloudflared.exe" (
    echo  [OK] cloudflared.exe ya esta instalado.
    cloudflared.exe --version
    echo.
    pause
    exit /b 0
)

echo  Descargando cloudflared.exe desde Cloudflare...
echo  (Puede tardar unos segundos)
echo.

powershell -NoProfile -Command ^
  "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'cloudflared.exe' -UseBasicParsing"

if exist "cloudflared.exe" (
    echo.
    echo  [OK] Instalado correctamente:
    cloudflared.exe --version
    echo.
    echo  Ahora ejecuta CLOUDFLARE_TUNEL.bat para activar el acceso remoto.
) else (
    echo.
    echo  [ERROR] No se pudo descargar. Comprueba tu conexion a internet.
    echo  Descarga manual: https://github.com/cloudflare/cloudflared/releases/latest
    echo  Guarda el archivo como cloudflared.exe en esta carpeta.
)

echo.
pause
