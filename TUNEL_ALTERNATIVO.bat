@echo off
title MRD — Tunel SSH (localhost.run)
color 0B
cd /d "C:\mrd tool\mrd_tool_control"

echo.
echo  =====================================================
echo   MRD TOOL CONTROL — Tunel SSH via localhost.run
echo  =====================================================
echo.
echo  No necesita cuenta ni instalacion adicional.
echo  Usa SSH que ya viene en Windows 10/11.
echo.
echo  La URL publica aparecera en unos segundos...
echo  (Ejemplo: https://abc123.localhost.run)
echo.
echo  IMPORTANTE: Deja esta ventana abierta.
echo  -------------------------------------------------------
echo.

ssh -o StrictHostKeyChecking=no -R 80:localhost:8000 nokey@localhost.run

echo.
echo  El tunel se ha cerrado.
pause
