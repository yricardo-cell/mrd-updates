import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import SessionLocal
from models import Usuario
from auth import hash_password

db = SessionLocal()
try:
    # Actualizar cuenta admin -> yusniel (el administrador real)
    admin = db.query(Usuario).filter(Usuario.username == "admin").first()
    if admin:
        admin.username = "yusniel"
        admin.nombre = "Yusniel"
        admin.rol = "admin"
        admin.activo = True
        admin.password_hash = hash_password("mrd2024")
        print("OK: admin -> yusniel (admin), password=mrd2024")

    # Asegurar que erik sea almacen
    erik = db.query(Usuario).filter(Usuario.username == "erik").first()
    if erik:
        erik.nombre = "Erik"
        erik.rol = "almacen"
        print("OK: erik -> almacen")

    db.commit()
    print("\nUsuarios actualizados:")
    for u in db.query(Usuario).all():
        print(f"  {u.username!r:12} {u.nombre!r:20} rol={u.rol}")
except Exception as e:
    print(f"ERROR: {e}")
finally:
    db.close()

input("\nPresiona Enter para cerrar...")
