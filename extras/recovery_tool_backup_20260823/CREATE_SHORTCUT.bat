@echo off
:: CREATE_SHORTCUT.bat
:: Creates a desktop shortcut to RUN_RECOVERY.bat
:: Run this once after deploying the recovery tool.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Este script debe ejecutarse como administrador.
    pause
    exit /b 1
)

set "TARGET=%~dp0RUN_RECOVERY.bat"
set "SHORTCUT=%USERPROFILE%\Desktop\MRD Recovery.lnk"
set "ICON=%SystemRoot%\System32\shell32.dll"

powershell -NoProfile -Command ^
    "$ws = New-Object -ComObject WScript.Shell; ^
     $lnk = $ws.CreateShortcut('%SHORTCUT%'); ^
     $lnk.TargetPath = '%TARGET%'; ^
     $lnk.WorkingDirectory = '%~dp0'; ^
     $lnk.Description = 'MRD Tool Control — Diagnostico y Recuperacion'; ^
     $lnk.IconLocation = '%ICON%,21'; ^
     $lnk.Save()"

if %errorlevel% equ 0 (
    echo Acceso directo creado en el escritorio: "%SHORTCUT%"
) else (
    echo ERROR: No se pudo crear el acceso directo.
)
pause
