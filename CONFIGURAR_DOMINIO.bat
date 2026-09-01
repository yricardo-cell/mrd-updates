@echo off
title MRD - Fijar dominio (hosts + URL publica)
color 0E
cd /d "%~dp0"

REM ============================================================
REM   Cambia aqui el subdominio si no quieres app.iasmrd.com
REM ============================================================
set "DOMINIO=app.iasmrd.com"

if not exist "config" mkdir config
set "ENV=config\local.env"
if not exist "%ENV%" ( echo # MRD TOOL CONTROL - config local> "%ENV%" )

echo  Fijando dominio: %DOMINIO%
set "TMP=%TEMP%\mrd_env_%RANDOM%.tmp"
> "%TMP%" (
  for /f "usebackq delims=" %%L in ("%ENV%") do (
    echo %%L | findstr /b /c:"MRD_ALLOWED_HOSTS" /c:"MRD_PUBLIC_URL" >nul || echo %%L
  )
)
>> "%TMP%" echo MRD_ALLOWED_HOSTS=%DOMINIO%,localhost,127.0.0.1
>> "%TMP%" echo MRD_PUBLIC_URL=https://%DOMINIO%
move /y "%TMP%" "%ENV%" >nul

echo.
echo  =====================================================
echo   Contenido actual de %ENV%:
echo  =====================================================
type "%ENV%"
echo.
echo   AHORA reinicia el servidor para aplicar.
echo  =====================================================
pause
