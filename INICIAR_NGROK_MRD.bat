@echo off
title MRD TOOL — ngrok Tunnel
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   MRD TOOL CONTROL — Acceso Remoto      ║
echo  ║   Publicando puerto 8000 via ngrok...   ║
echo  ╚══════════════════════════════════════════╝
echo.
echo  Asegurate de que el servidor MRD esta corriendo.
echo  (Si no, abre INICIAR_MRD.bat primero)
echo.

REM Usa el ngrok y la cuenta ya configurada en JarvisMRD
"C:\JarvisMRD\tools\ngrok.exe" http 8000 --config="C:\JarvisMRD\tools\ngrok.yml"

pause
