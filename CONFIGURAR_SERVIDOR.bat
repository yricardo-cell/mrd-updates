@echo off
title MRD - Configurar este PC como SERVIDOR (produccion)
color 0B
cd /d "%~dp0"
echo.
echo  =====================================================
echo   Configurar ESTE equipo como SERVIDOR (produccion)
echo  =====================================================
echo.
if not exist "config" mkdir config
if exist "config\local.env" (
    echo  Ya existe config\local.env  -  no lo sobreescribo.
    echo  Si quieres regenerarlo, borralo primero.
    echo.
    type "config\local.env"
    echo.
    pause
    exit /b 0
)
set "KEY="
for /f "delims=" %%K in ('python -c "import secrets;print(secrets.token_hex(32))" 2^>nul') do set "KEY=%%K"
if not defined KEY for /f "delims=" %%K in ('py -3 -c "import secrets;print(secrets.token_hex(32))" 2^>nul') do set "KEY=%%K"
if not defined KEY ( echo  [ERROR] No se pudo generar la clave (falta Python). & pause & exit /b 1 )
> "config\local.env" echo # MRD TOOL CONTROL - SERVIDOR (produccion). NO copiar al PC de desarrollo.
>>"config\local.env" echo MRD_ENV=production
>>"config\local.env" echo MRD_SECRET_KEY=%KEY%
>>"config\local.env" echo # --- Cloudflare (acceso publico por tunel) ---
>>"config\local.env" echo MRD_TRUST_PROXY_HEADERS=true
>>"config\local.env" echo MRD_HTTPS_ONLY=false
>>"config\local.env" echo # MRD_PUBLIC_URL=https://tu-url.trycloudflare.com
>>"config\local.env" echo # --- Boton de actualizaciones ---
>>"config\local.env" echo # Pon aqui la URL que te imprime PUBLICAR_ACTUALIZACION.bat en el PC viejo:
>>"config\local.env" echo MRD_UPDATE_SERVER=
echo  [OK] Creado config\local.env  -  este equipo es el SERVIDOR (produccion).
echo  Reinicia el servidor para aplicar.
echo.
pause
