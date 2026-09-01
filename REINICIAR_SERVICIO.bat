@echo off
echo Reiniciando MRD TOOL CONTROL...
sc.exe stop MRDToolControl >nul 2>&1
timeout /t 4 /nobreak >nul
sc.exe start MRDToolControl >nul 2>&1
timeout /t 5 /nobreak >nul
sc.exe query MRDToolControl | findstr "ESTADO"
echo.
echo Listo. La app estara disponible en http://localhost:8000
pause
