@echo off
title Validación MRD TOOL CONTROL
cd /d "C:\mrd tool\mrd_tool_control"
echo.
echo ════════════════════════════════════════
echo   VALIDACIÓN DE SINTAXIS - MRD TOOL
echo ════════════════════════════════════════
echo.

set ERRORES=0

for %%f in (main.py database.py models.py auth.py config.py label_printer.py codigos.py backups.py updater.py reports.py) do (
    venv\Scripts\python.exe -c "import ast; ast.parse(open('%%f', encoding='utf-8').read()); print('  OK  %%f')" 2>nul
    if errorlevel 1 (
        echo  ERROR %%f  ^<-- REVISAR
        set ERRORES=1
    )
)

echo.
if "%ERRORES%"=="0" (
    echo ✓ Todo correcto. Arrancando servidor...
    echo.
    venv\Scripts\uvicorn.exe main:app --host 0.0.0.0 --port 8000
) else (
    echo ✗ Hay errores de sintaxis. Corrige antes de arrancar.
    pause
)
