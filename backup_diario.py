import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

SOURCE = Path(r"C:\mrd tool\mrd-tool-control-2.5.0\data\mrd_tool.db")
BACKUP_ROOT = Path(r"D:\BACKUP_MRD_TOOL_CONTROL")
RETENTION_DAYS = 90

today = datetime.now()
folder = BACKUP_ROOT / today.strftime("%Y-%m-%d")
folder.mkdir(parents=True, exist_ok=True)

destination = folder / "mrd_tool.db"

source_db = sqlite3.connect(str(SOURCE))
backup_db = sqlite3.connect(str(destination))

try:
    source_db.backup(backup_db)
finally:
    backup_db.close()
    source_db.close()

# Comprobar integridad de la copia
check_db = sqlite3.connect(str(destination))
try:
    result = check_db.execute("PRAGMA integrity_check;").fetchone()[0]
finally:
    check_db.close()

if result.lower() != "ok":
    raise RuntimeError(f"Backup SQLite no valido: {result}")

# Eliminar copias con mas de 90 dias
limit = today - timedelta(days=RETENTION_DAYS)

for item in BACKUP_ROOT.iterdir():
    if not item.is_dir():
        continue

    try:
        date = datetime.strptime(item.name, "%Y-%m-%d")
    except ValueError:
        continue

    if date < limit:
        for file in item.iterdir():
            file.unlink()
        item.rmdir()

print(f"BACKUP OK: {destination}")
