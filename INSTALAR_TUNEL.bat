@echo off
:: Reiniciar como Administrador si no lo somos ya
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Solicitando permisos de administrador...
    powershell -Command "Start-Process cmd -ArgumentList '/c cd /d \"%~dp0\" && powershell -ExecutionPolicy Bypass -File scripts\setup_cloudflare_tunnel.ps1 && pause' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "scripts\setup_cloudflare_tunnel.ps1"
pause
