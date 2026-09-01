@echo off
title MRD Tool Control - Reinicio
echo.
echo  Parando servicio...
sc stop MRDToolControl
echo  Resultado stop: %errorlevel%
timeout /t 6 /nobreak >nul

echo  Iniciando servicio...
sc start MRDToolControl
echo  Resultado start: %errorlevel%
timeout /t 4 /nobreak >nul

echo.
sc query MRDToolControl
echo.
echo  Accede en http://localhost:8000
pause
