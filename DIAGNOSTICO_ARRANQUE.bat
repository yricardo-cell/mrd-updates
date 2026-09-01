@echo off
setlocal enabledelayedexpansion
title MRD - Diagnostico de arranque automatico
color 0B
cd /d "%~dp0"

echo.
echo  =====================================================
echo   MRD TOOL - Comprobacion de arranque automatico
echo  =====================================================
echo.

set "OK=1"

REM --- 1) Servicio del tunel Cloudflare ---
echo  [1] Tunel Cloudflare (servicio "Cloudflared")...
sc query Cloudflared >nul 2>&1
if !errorlevel! equ 0 (
    for /f "tokens=3" %%s in ('sc query Cloudflared ^| findstr "STATE"') do set "CFSTATE=%%s"
    for /f "tokens=4" %%s in ('sc qc Cloudflared ^| findstr "START_TYPE"') do set "CFSTART=%%s"
    echo      Estado: !CFSTATE!   Arranque: !CFSTART!
    if /i "!CFSTATE!"=="RUNNING" ( echo      [OK] El tunel esta corriendo. ) else ( echo      [AVISO] El tunel NO esta corriendo. & set "OK=0" )
) else (
    echo      [ERROR] No existe el servicio Cloudflared. Instalalo con el comando de Cloudflare.
    set "OK=0"
)
echo.

REM --- 2) Tarea programada del servidor MRD ---
echo  [2] Servidor MRD (tarea "MRD Tool Control")...
schtasks /query /tn "MRD Tool Control" >nul 2>&1
if !errorlevel! equ 0 (
    echo      [OK] La tarea existe (arranca al iniciar sesion/Windows).
) else (
    echo      [AVISO] No existe la tarea "MRD Tool Control".
    echo             Ejecuta INSTALAR_SERVICIO.bat como administrador.
    set "OK=0"
)
echo.

REM --- 3) Servidor escuchando en el puerto 8000 ---
echo  [3] Servidor escuchando en el puerto 8000...
netstat -aon | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if !errorlevel! equ 0 (
    echo      [OK] Hay algo escuchando en 8000 (servidor en marcha).
) else (
    echo      [AVISO] Nadie escucha en 8000 (el servidor MRD no esta arrancado ahora).
    set "OK=0"
)
echo.

REM --- 4) venv presente ---
echo  [4] Entorno virtual (venv)...
if exist "venv\Scripts\python.exe" ( echo      [OK] venv correcto. ) else ( echo      [ERROR] Falta venv. Ejecuta INSTALAR_DEPENDENCIAS.bat & set "OK=0" )
echo.

echo  =====================================================
if "!OK!"=="1" (
    echo   RESULTADO:  TODO OK. El sistema arranca solo tras reiniciar.
) else (
    echo   RESULTADO:  Hay avisos arriba. Revisa los [AVISO]/[ERROR].
    echo   - Si falta la TAREA MRD: INSTALAR_SERVICIO.bat (como admin)
    echo   - Si falta el TUNEL: reinstala con el comando de Cloudflare
    echo   - Si el venv falta: INSTALAR_DEPENDENCIAS.bat
)
echo  =====================================================
echo.
echo  CONSEJO: para probarlo de verdad, REINICIA el PC y, sin abrir
echo  nada a mano, entra en  https://app.iasmrd.com  a los 2 minutos.
echo.
pause
