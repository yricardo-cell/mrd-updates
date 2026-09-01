@echo off
title MRD TOOL — Instalar arranque automatico
color 0A
cd /d "C:\mrd tool\mrd_tool_control"

echo.
echo  =====================================================
echo   MRD TOOL CONTROL — Instalacion de arranque
echo   Sin ventanas CMD. Arranca solo con Windows.
echo  =====================================================
echo.

:: ─── 1. Instalar pystray y Pillow SIN ventana ──────────────────────────────
echo  [1/4] Instalando dependencias...
venv\Scripts\pip.exe install pystray Pillow --quiet --disable-pip-version-check 2>nul
if %errorlevel% neq 0 (
    pip install pystray Pillow --quiet --disable-pip-version-check 2>nul
)
echo        OK.

:: ─── 2. Borrar tarea anterior si existe ────────────────────────────────────
schtasks /delete /tn "MRDToolControl" /f >nul 2>&1
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "MRDToolControl" /f >nul 2>&1

:: ─── 3. Registrar en Programador de Tareas (arranque al iniciar sesion) ───
echo  [2/4] Registrando tarea de arranque automatico...
schtasks /create ^
  /tn "MRDToolControl" ^
  /tr "wscript.exe \"C:\mrd tool\mrd_tool_control\INICIAR.vbs\"" ^
  /sc onlogon ^
  /ru "%USERNAME%" ^
  /f >nul 2>&1

if %errorlevel% equ 0 (
    echo        OK — arrancara solo cada vez que inicies sesion.
) else (
    echo        Probando con clave de registro...
    reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" ^
        /v "MRDToolControl" ^
        /t REG_SZ ^
        /d "wscript.exe \"C:\mrd tool\mrd_tool_control\INICIAR.vbs\"" ^
        /f >nul
    echo        OK via registro.
)

:: ─── 4. Cerrar servidor anterior si habia uno ──────────────────────────────
echo  [3/4] Cerrando instancia anterior...
taskkill /f /im pythonw.exe >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul
echo        OK.

:: ─── 5. Lanzar ahora mismo SIN ventana ────────────────────────────────────
echo  [4/4] Lanzando MRD Tool Control ahora...
wscript.exe "C:\mrd tool\mrd_tool_control\INICIAR.vbs"
timeout /t 4 /nobreak >nul

echo.
echo  =====================================================
echo   LISTO.
echo.
echo   - Busca el icono MRD en la bandeja del sistema
echo     (esquina inferior derecha, junto al reloj)
echo   - La proxima vez que inicies Windows arranca solo
echo   - Sin ninguna ventana CMD visible
echo  =====================================================
echo.
pause
