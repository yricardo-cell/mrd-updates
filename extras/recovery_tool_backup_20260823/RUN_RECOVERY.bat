@echo off
cd /d C:\mrd_tool_control\recovery_tool

:: Check if running as admin
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Solicitando permisos de administrador...
    powershell -Command "Start-Process cmd -ArgumentList '/c cd /d C:\mrd_tool_control\recovery_tool ^&^& ..\venv\Scripts\python.exe mrd_recovery.py' -Verb RunAs"
    exit /b
)

..\venv\Scripts\python.exe mrd_recovery.py
