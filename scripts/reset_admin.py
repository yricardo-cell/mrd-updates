"""
Reset admin password - ejecutar una sola vez
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from models import Usuario
from auth import hash_password

db = SessionLocal()
try:
    admin = db.query(Usuario).filter(Usuario.username == "admin").first()
    if admin:
        admin.password_hash = hash_password("mrd2024")
        admin.rol = "admin"
        admin.activo = True
        db.commit()
        print("OK: contraseña admin reseteada a 'mrd2024'")
    else:
        from datetime import datetime
        admin = Usuario(
            username="admin",
            password_hash=hash_password("mrd2024"),
            nombre="Administrador",
            rol="admin",
            activo=True,
        )
        db.add(admin)
        db.commit()
        print("OK: usuario admin creado con contraseña 'mrd2024'")
except Exception as e:
    print(f"ERROR: {e}")
finally:
    db.close()

input("\nPresiona Enter para cerrar...")
