@echo off
title MRD TOOL CONTROL — Detener Servicio
echo.
echo  Deteniendo MRD Tool Control...

:: Detener la tarea del programador
schtasks /end /tn "MRD Tool Control" >nul 2>&1

:: Matar proceso uvicorn/python en puerto 8000
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo  Matando proceso PID %%a en puerto 8000...
    taskkill /f /pid %%a >nul 2>&1
)

:: Matar ngrok si estaba corriendo
taskkill /f /im ngrok.exe >nul 2>&1

echo  Servicio MRD detenido.
echo.
echo  Para reiniciar manualmente ejecuta INICIAR_MRD.bat
echo  Para reiniciar el servicio automatico ejecuta INSTALAR_SERVICIO.bat
echo.
pause
