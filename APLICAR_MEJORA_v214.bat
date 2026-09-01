@echo off
title MRD TOOL CONTROL - Aplicar mejora v2.1.4
color 0A
cd /d "%~dp0"

echo.
echo  =====================================================
echo   MRD TOOL CONTROL - Mejora v2.1.4
echo   - Codigos de barras en maquinaria (etiquetas+escaner)
echo   - Separacion de los dos depositos de combustible
echo  =====================================================
echo.

if not exist "MEJORA_v214.py" (
    echo  [ERROR] Falta MEJORA_v214.py en esta carpeta.
    pause
    exit /b 1
)

set "PY=venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo  Deteniendo el servidor...
schtasks /end /tn "MRD Tool Control" >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do taskkill /f /pid %%a >nul 2>&1
timeout /t 3 /nobreak >nul

echo  Aplicando la mejora...
echo.
"%PY%" MEJORA_v214.py

echo.
echo  Arrancando el servidor de nuevo...
schtasks /run /tn "MRD Tool Control" >nul 2>&1
echo  Listo. Espera 30 segundos y abre  https://app.iasmrd.com
echo.
pause
