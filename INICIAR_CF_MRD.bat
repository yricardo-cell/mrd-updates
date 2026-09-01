@echo off
title MRD TOOL — Cloudflare Tunnel
setlocal

set CF_EXE=C:\mrd tool\mrd_tool_control\cloudflared.exe

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   MRD TOOL — Cloudflare Tunnel          ║
echo  ║   Puerto 8000  (independiente de ngrok) ║
echo  ╚══════════════════════════════════════════╝
echo.

REM ── Descargar cloudflared si no existe ───────────────────────────
if not exist "%CF_EXE%" (
    echo  Descargando cloudflared.exe ...
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile '%CF_EXE%'"
    if not exist "%CF_EXE%" (
        echo  ERROR: descarga fallida.
        echo  Manual: https://github.com/cloudflare/cloudflared/releases/latest
        pause & exit /b 1
    )
    echo  OK.
    echo.
)

echo  Iniciando tunel... la URL publica aparece en unos segundos.
echo  Pulsa Ctrl+C para detener.
echo.

"%CF_EXE%" tunnel --url http://localhost:8000

pause
