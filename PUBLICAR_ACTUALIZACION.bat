@echo off
title MRD - Publicar actualizacion (PC de desarrollo)
color 0A
cd /d "%~dp0"
set "PORT=8100"
set "RELDIR=releases"

set "PY=python"
where python >nul 2>&1 || set "PY=py -3"

if not exist "%RELDIR%" ( echo  No existe la carpeta "releases". Pulsa antes "Empaquetar" en la app. & pause & exit /b 1 )

set "ZIP="
for /f "delims=" %%F in ('dir /b /a-d /o-d "%RELDIR%\*.zip" 2^>nul') do if not defined ZIP set "ZIP=%%F"
if not defined ZIP ( echo  No hay ningun .zip en releases. Pulsa "Empaquetar" en la app. & pause & exit /b 1 )

echo  Release detectada: %ZIP%
for /f "delims=" %%H in ('%PY% -c "import hashlib;print(hashlib.sha256(open(r'%RELDIR%\%ZIP%','rb').read()).hexdigest())"') do set "SHA=%%H"
set "VER=%ZIP:mrd_tool_control_v=%"
set "VER=%VER:.zip=%"
for /f "delims=" %%I in ('%PY% -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('8.8.8.8',80));print(s.getsockname()[0]);s.close()"') do set "IP=%%I"

> "%RELDIR%\version.json" echo {
>>"%RELDIR%\version.json" echo   "version": "%VER%",
>>"%RELDIR%\version.json" echo   "latest_version": "%VER%",
>>"%RELDIR%\version.json" echo   "version_disponible": "%VER%",
>>"%RELDIR%\version.json" echo   "version_actual": "%VER%",
>>"%RELDIR%\version.json" echo   "download_url": "http://%IP%:%PORT%/%ZIP%",
>>"%RELDIR%\version.json" echo   "url": "http://%IP%:%PORT%/%ZIP%",
>>"%RELDIR%\version.json" echo   "sha256": "%SHA%",
>>"%RELDIR%\version.json" echo   "hash": "%SHA%",
>>"%RELDIR%\version.json" echo   "release_notes": "Actualizacion %VER%"
>>"%RELDIR%\version.json" echo }

echo.
echo  =====================================================
echo   Version:  %VER%
echo   Archivo:  %ZIP%
echo   SHA256:   %SHA%
echo  =====================================================
echo.
echo   EN EL SERVIDOR, pon esta linea en  config\local.env :
echo.
echo        MRD_UPDATE_SERVER=http://%IP%:%PORT%
echo.
echo   Sirviendo releases en  http://%IP%:%PORT%  (deja esta ventana abierta)
echo  =====================================================
echo.
cd /d "%~dp0%RELDIR%"
%PY% -m http.server %PORT%
pause
