@echo off
title MRD - Reiniciando servidor...
cd /d "C:\mrd tool\mrd_tool_control"

echo.
echo  Cerrando servidor anterior...

:: Matar pythonw del tray si existe
taskkill /f /im pythonw.exe >nul 2>&1

:: Matar proceso en puerto 8000
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo  Cerrando PID %%a en puerto 8000...
    taskkill /f /pid %%a >nul 2>&1
)

timeout /t 3 /nobreak >nul

:: Verificar que el VBS de arranque existe
if exist "INICIAR.vbs" (
    echo  Iniciando MRD Tool Control en segundo plano...
    wscript.exe "C:\mrd tool\mrd_tool_control\INICIAR.vbs"
    echo  OK - El icono aparecera en la bandeja del sistema en unos segundos.
) else (
    echo  INICIAR.vbs no encontrado, arrancando en modo consola...
    call venv\Scripts\activate
    start "" uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
    echo  Servidor iniciado en http://localhost:8000
)

timeout /t 2 /nobreak >nul
