@echo off
title MRD TOOL — Crear paquete de instalacion
color 0B
chcp 65001 >nul

echo.
echo  =====================================================
echo   MRD TOOL CONTROL — Crear paquete para otro PC
echo  =====================================================
echo.

cd /d "C:\mrd tool"

set DESTINO=C:\mrd tool\MRD_PAQUETE
set ZIPFILE=C:\mrd tool\MRD_Tool_Control_INSTALABLE.zip

echo  [1/4] Limpiando paquete anterior si existe...
if exist "%DESTINO%" rmdir /s /q "%DESTINO%"
if exist "%ZIPFILE%" del /q "%ZIPFILE%"

echo  [2/4] Copiando archivos (puede tardar un minuto)...
robocopy "C:\mrd tool\mrd_tool_control" "%DESTINO%\mrd_tool_control" /E /XD venv __pycache__ .git logs temp cache releases backups updates .mypy_cache /XF "*.log" "*.bak" "*.bak_*" "desktop.ini" "*.pyc" /NFL /NDL /NJH /NJS

echo  [3/4] Creando ZIP...
powershell -NoProfile -Command "Compress-Archive -Path '%DESTINO%\*' -DestinationPath '%ZIPFILE%' -Force"

if exist "%ZIPFILE%" (
    echo.
    for %%F in ("%ZIPFILE%") do echo   Tamano del ZIP: %%~zF bytes
    echo.
    echo  [4/4] Limpiando carpeta temporal...
    rmdir /s /q "%DESTINO%"
    echo.
    echo  =====================================================
    echo   ZIP creado correctamente:
    echo   %ZIPFILE%
    echo.
    echo   Lleva ese archivo al otro ordenador y sigue
    echo   las instrucciones de INSTRUCCIONES_INSTALACION.txt
    echo  =====================================================
) else (
    echo  ERROR: No se pudo crear el ZIP.
    echo  Asegurate de tener PowerShell disponible.
)

echo.
pause
