@echo off
:: CREATE_SHORTCUT.bat
:: Creates a desktop shortcut to the standalone recovery console
:: Run this once after deploying the recovery tool.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Este script debe ejecutarse como administrador.
    pause
    exit /b 1
)

set "TARGET=C:\mrd_tool_control\venv\Scripts\pythonw.exe"
set "SCRIPT=C:\mrd_tool_control\recovery_tool\mrd_recovery.py"
set "SHORTCUT=%USERPROFILE%\Desktop\MRD - Control y Recuperacion.lnk"
set "ICON=C:\mrd_tool_control\recovery_tool\assets\mrd_rescue.ico"

powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell; ^
     $lnk = $ws.CreateShortcut('%SHORTCUT%'); ^
     $lnk.TargetPath = '%TARGET%'; ^
     $lnk.Arguments = '"%SCRIPT%"'; ^
     $lnk.WorkingDirectory = '%~dp0'; ^
     $lnk.Description = 'Encender, apagar, vigilar y recuperar MRD Tool Control'; ^
     $lnk.IconLocation = '%ICON%,0'; ^
     $lnk.Save()"

if %errorlevel% equ 0 (
    echo Acceso directo creado en el escritorio: "%SHORTCUT%"
) else (
    echo ERROR: No se pudo crear el acceso directo.
)
pause
