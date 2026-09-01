@echo off
title MRD - Arreglar 400 (hosts permitidos)
color 0E
cd /d "%~dp0"

if not exist "config" mkdir config
set "ENV=config\local.env"
if not exist "%ENV%" (
    echo # MRD TOOL CONTROL - config local> "%ENV%"
)

echo.
echo  Ajustando MRD_ALLOWED_HOSTS para permitir Cloudflare + local...

:: Quitar cualquier linea previa MRD_ALLOWED_HOSTS (con o sin #) y reescribir
set "TMP=%TEMP%\mrd_env_%RANDOM%.tmp"
> "%TMP%" (
  for /f "usebackq delims=" %%L in ("%ENV%") do (
    echo %%L | findstr /b /c:"MRD_ALLOWED_HOSTS" >nul || echo %%L
  )
)
>> "%TMP%" echo MRD_ALLOWED_HOSTS=*.trycloudflare.com,localhost,127.0.0.1
move /y "%TMP%" "%ENV%" >nul

echo.
echo  =====================================================
echo   Hecho. Contenido actual de %ENV%:
echo  =====================================================
type "%ENV%"
echo.
echo  =====================================================
echo   AHORA: reinicia el servidor para aplicar:
echo     - cierra la ventana de INICIAR_MRD.bat y vuelve a abrirla
echo     - (o reinicia el servicio)
echo   Luego recarga la URL de Cloudflare.
echo  =====================================================
echo.
pause
