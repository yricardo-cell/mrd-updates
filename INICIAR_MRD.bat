@echo off
title MRD TOOL CONTROL v2.1.0
color 0A
cd /d "%~dp0"

echo.
echo  =====================================================
echo   MRD TOOL CONTROL v2.1.0
echo  =====================================================
echo.

:: Matar proceso anterior en puerto 8000
echo  Verificando puerto 8000...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo  Cerrando proceso anterior PID %%a...
    taskkill /f /pid %%a >nul 2>&1
)

:: Matar pythonw huerfanos del tray
taskkill /f /im pythonw.exe >nul 2>&1

timeout /t 2 /nobreak >nul

:: Comprobar que el venv existe
if not exist "venv\Scripts\python.exe" (
    echo  ERROR: venv no encontrado. Ejecuta INSTALAR_DEPENDENCIAS.bat primero.
    pause
    exit /b 1
)

echo  Arrancando servidor...
echo.
"venv\Scripts\python.exe" -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
pause
