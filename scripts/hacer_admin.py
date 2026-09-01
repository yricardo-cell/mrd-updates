"""
Herramienta de gestión de usuarios — MRD TOOL CONTROL
Ejecuta con: venv\Scripts\python.exe hacer_admin.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

try:
    from config import DATABASE_URL
    from sqlalchemy import create_engine, text

    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

    with engine.connect() as conn:
        # Listar usuarios
        rows = conn.execute(text(
            "SELECT id, username, nombre, rol, activo FROM usuarios ORDER BY id"
        )).fetchall()

        if not rows:
            print("No hay usuarios en la base de datos.")
            sys.exit(0)

        print("\n  Usuarios registrados:")
        print(f"  {'ID':<4} {'Username':<20} {'Nombre':<25} {'Rol':<15} {'Activo'}")
        print("  " + "-"*68)
        for r in rows:
            activo = "Sí" if r[4] else "No"
            print(f"  {r[0]:<4} {str(r[1]):<20} {str(r[2] or ''):<25} {str(r[3]):<15} {activo}")

        print()
        user_input = input("  Escribe el USERNAME del usuario al que dar rol ADMIN: ").strip()

        if not user_input:
            print("  Cancelado.")
            sys.exit(0)

        # Verificar que existe
        existing = conn.execute(
            text("SELECT id, nombre, rol FROM usuarios WHERE username = :u"),
            {"u": user_input}
        ).fetchone()

        if not existing:
            print(f"\n  ERROR: No se encontró el usuario '{user_input}'.")
            sys.exit(1)

        print(f"\n  Usuario: {existing[1]} — Rol actual: {existing[2]}")
        confirm = input("  ¿Confirmar cambio a rol 'admin'? (s/n): ").strip().lower()

        if confirm != "s":
            print("  Cancelado.")
            sys.exit(0)

        conn.execute(
            text("UPDATE usuarios SET rol = 'admin' WHERE username = :u"),
            {"u": user_input}
        )
        conn.commit()

        print(f"\n  ✓ El usuario '{user_input}' ahora tiene rol ADMIN.")
        print("  Cierra sesión en el navegador y vuelve a entrar para que surta efecto.")

except Exception as e:
    print(f"\n  ERROR: {e}")
    print("\n  Si el servidor está corriendo, ciérralo antes de ejecutar este script.")
    sys.exit(1)
