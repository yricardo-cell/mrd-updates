@echo off
title DIAGNOSTICO MRD
cd /d C:\mrd_tool_control

echo === Que proceso ocupa el puerto 8000? ===
netstat -ano | findstr ":8000"
echo.

echo === Servicios Windows con nombre MRD o uvicorn ===
sc query type= all state= all | findstr /i "mrd uvicorn python"
echo.

echo === Lista de servicios con descripcion (buscar mrd) ===
wmic service where "name like '%%mrd%%' or name like '%%uvicorn%%' or name like '%%python%%'" get name,state,startmode 2>nul
echo.

pause
