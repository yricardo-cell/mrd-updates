@echo off
title MRD TOOL CONTROL - Instalar Servicio Windows
color 0A
cd /d "%~dp0"
echo.
echo  =====================================================
echo   MRD TOOL CONTROL - Instalacion de Servicio Windows
echo  =====================================================
echo.
echo  Registra MRD Tool Control para que se inicie
echo  automaticamente al iniciar sesion en Windows.
echo  Se necesitan permisos de Administrador.
echo.

:: Verificar que corremos como admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Ejecuta este archivo como Administrador.
    echo  Clic derecho sobre INSTALAR_SERVICIO.bat -^> "Ejecutar como administrador".
    echo.
    pause
    exit /b 1
)

set "TASK_NAME=MRD Tool Control"
set "PS_SCRIPT=%~dp0SERVICIO_MRD.ps1"

:: Eliminar tarea anterior si existe
echo  Eliminando tarea anterior (si existe)...
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

:: Crear tarea (comillas internas escapadas con \" para admitir el espacio de la ruta)
echo  Registrando en Programador de Tareas de Windows...
schtasks /create /tn "%TASK_NAME%" /tr "powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -NonInteractive -File \"%PS_SCRIPT%\"" /sc onlogon /rl highest /f /delay 0000:30

if %errorlevel% neq 0 (
    echo.
    echo  Reintentando con arranque al encender (onstart)...
    schtasks /create /tn "%TASK_NAME%" /tr "powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -NonInteractive -File \"%PS_SCRIPT%\"" /sc onstart /rl highest /f
)

if %errorlevel% equ 0 (
    echo.
    echo  =====================================================
    echo   OK: Servicio instalado correctamente.
    echo   Se iniciara solo al arrancar Windows / iniciar sesion.
    echo   Si se cae, se reinicia solo en 5 segundos.
    echo   Logs en: logs\servicio_mrd.log
    echo  =====================================================
    echo.
    echo  Iniciando el servicio ahora...
    schtasks /run /tn "%TASK_NAME%"
    echo  Listo. Espera unos segundos y abre  http://localhost:8000
) else (
    echo.
    echo  ERROR al instalar. Revisa que tienes permisos de Admin.
)

echo.
pause
