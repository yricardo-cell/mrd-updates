import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import SessionLocal
from models import Usuario

db = SessionLocal()
try:
    # Borrar el usuario 'admin' fantasma (nombre=Administrador, creado por startup)
    ghost = db.query(Usuario).filter(Usuario.username == "admin").first()
    if ghost:
        print(f"Borrando: ID={ghost.id} username={ghost.username!r} nombre={ghost.nombre!r} rol={ghost.rol}")
        db.delete(ghost)
        db.commit()
        print("OK: usuario 'admin' fantasma eliminado.")
    else:
        print("No existe usuario 'admin' — nada que borrar.")

    print("\nUsuarios actuales:")
    for u in db.query(Usuario).all():
        print(f"  ID={u.id}  {u.username!r:12}  {u.nombre!r:20}  rol={u.rol}  activo={u.activo}")
except Exception as e:
    print(f"ERROR: {e}")
    db.rollback()
finally:
    db.close()

input("\nPresiona Enter para cerrar...")
