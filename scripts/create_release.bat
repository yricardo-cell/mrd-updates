@echo off
cd /d "C:\mrd tool\mrd_tool_control"
echo Creando release v1.1.0...
venv\Scripts\python.exe -c "
import zipfile, os, shutil
from pathlib import Path

src = Path('.')
out = Path('releases/mrd_tool_control_v1.1.0.zip')
out.parent.mkdir(exist_ok=True)

EXCLUIR = {
    'data', 'backups', 'uploads', 'logs', 'venv',
    '__pycache__', '.git', 'releases', 'exports',
    'get_access_info.bat', 'get_access_info.py',
    'create_release.bat', 'access_info.txt',
}

with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
    for f in src.rglob('*'):
        parts = f.relative_to(src).parts
        if not parts or parts[0] in EXCLUIR:
            continue
        if any(p == '__pycache__' for p in parts):
            continue
        if any(p.startswith('_update_tmp') for p in parts):
            continue
        if f.is_file():
            arcname = 'mrd_tool_control/' + str(f.relative_to(src))
            zf.write(f, arcname)

size_kb = out.stat().st_size // 1024
print(f'OK: {out.name} ({size_kb} KB) - Listo para distribuir')
"
echo.
echo Hecho. Pulsa una tecla para cerrar.
pause
