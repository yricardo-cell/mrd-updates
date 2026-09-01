@echo off
title MRD TOOL CONTROL — Desinstalar Servicio Windows
echo.
echo  Desinstalando servicio MRD Tool Control de Windows...
echo.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Ejecuta como Administrador.
    pause
    exit /b 1
)

:: Detener y eliminar tarea
schtasks /end /tn "MRD Tool Control" >nul 2>&1
schtasks /delete /tn "MRD Tool Control" /f >nul 2>&1

:: Matar proceso en puerto 8000
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
)

taskkill /f /im ngrok.exe >nul 2>&1

echo  OK: Servicio desinstalado. MRD ya no arrancara con Windows.
echo.
pause
