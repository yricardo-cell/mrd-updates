@echo off
title MRD TOOL — Configurar actualizaciones via GitHub
chcp 65001 >nul
color 0B

echo.
echo  =====================================================
echo   MRD TOOL — Canal de actualizaciones GitHub
echo  =====================================================
echo.
echo  Repo: https://github.com/yricardo-cell/mrd-updates
echo.

cd /d "C:\mrd tool\mrd_tool_control"

set ENV_FILE=config\local.env

:: Cambiar MRD_UPDATE_SERVER a GitHub raw
powershell -NoProfile -Command "(Get-Content '%ENV_FILE%') -replace 'MRD_UPDATE_SERVER=.*', 'MRD_UPDATE_SERVER=https://raw.githubusercontent.com/yricardo-cell/mrd-updates/main' | Set-Content '%ENV_FILE%' -Encoding UTF8"

:: Asegurar que MRD_UPDATE_VERSION_FILE apunta a version.json
powershell -NoProfile -Command "(Get-Content '%ENV_FILE%') -replace 'MRD_UPDATE_VERSION_FILE=.*', 'MRD_UPDATE_VERSION_FILE=version.json' | Set-Content '%ENV_FILE%' -Encoding UTF8"

echo.
echo  Verificando cambio...
findstr "MRD_UPDATE_SERVER" "%ENV_FILE%"

echo.
echo  =====================================================
echo   LISTO. El servidor buscara actualizaciones en:
echo   github.com/yricardo-cell/mrd-updates
echo.
echo   Reinicia el servidor para que el cambio
echo   tenga efecto (ejecuta INICIAR_MRD.bat).
echo  =====================================================
echo.
pause
