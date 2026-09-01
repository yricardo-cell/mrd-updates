@echo off
title MRD — Gestión de usuarios
color 0A
cd /d "C:\mrd tool\mrd_tool_control"

echo.
echo  =====================================================
echo   MRD TOOL CONTROL — Asignar rol ADMIN a usuario
echo  =====================================================
echo.

venv\Scripts\python.exe hacer_admin.py

echo.
pause
