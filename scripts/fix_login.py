"""
MRD TOOL CONTROL — Fix rápido de contraseña
Establece usuario 'yusniel' como admin con contraseña 'mrd12'
Ejecutar: python fix_login.py
"""
import sqlite3, os, sys

HASH = "$2b$12$P0Wv6vexH4BYYx1ijknYcOtwhLKrQ.oqXAmbaOV9J0PjgkICUCsrO"  # mrd12

ROOT = os.path.dirname(os.path.abspath(__file__))
CANDIDATES = [
    os.path.join(ROOT, "data", "mrd_tool.db"),
    os.path.join(ROOT, "data", "mrd_tool_control.db"),
    os.path.join(ROOT, "instance", "mrd_tool.db"),
    os.path.join(ROOT, "mrd_tool.db"),
]

db_path = None
for c in CANDIDATES:
    if os.path.exists(c):
        db_path = c
        break

if not db_path:
    print("ERROR: No se encontró la base de datos.")
    sys.exit(1)

print(f"DB: {db_path}")

try:
    con = sqlite3.connect(db_path, timeout=10)
    cur = con.cursor()

    # Detectar columnas disponibles
    cols = [r[1] for r in cur.execute("PRAGMA table_info(usuarios)").fetchall()]
    print(f"Columnas: {cols}")

    # Verificar si yusniel existe
    row = cur.execute("SELECT id, username, rol, activo FROM usuarios WHERE username=?", ("yusniel",)).fetchone()
    if row:
        print(f"Usuario encontrado: id={row[0]}, rol={row[2]}, activo={row[3]}")
    else:
        print("AVISO: usuario 'yusniel' no encontrado en la tabla.")

    # Actualizar
    if row:
        cur.execute("UPDATE usuarios SET password_hash=?, rol='admin', activo=1 WHERE username=?", (HASH, "yusniel"))
    else:
        # Crear si no existe
        if "nombre" in cols:
            cur.execute("INSERT INTO usuarios (username, password_hash, nombre, rol, activo) VALUES (?,?,?,?,?)",
                        ("yusniel", HASH, "Yusniel", "admin", 1))
        else:
            cur.execute("INSERT INTO usuarios (username, password_hash, rol, activo) VALUES (?,?,?,?)",
                        ("yusniel", HASH, "admin", 1))
        print("Usuario 'yusniel' creado.")

    con.commit()
    con.close()
    print("OK: Contraseña actualizada. Usuario: yusniel / Contraseña: mrd12")
    print("Cambia la contraseña al entrar desde el panel de usuario.")
except sqlite3.OperationalError as e:
    if "locked" in str(e).lower():
        print("ERROR: Base de datos bloqueada por la app. Detén el servicio MRD antes de ejecutar este script:")
        print("  net stop MRDToolControl")
        print("  python fix_login.py")
        print("  net start MRDToolControl")
    else:
        print(f"ERROR: {e}")
    sys.exit(1)
