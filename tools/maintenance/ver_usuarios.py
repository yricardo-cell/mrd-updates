import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import SessionLocal
from models import Usuario

db = SessionLocal()
usuarios = db.query(Usuario).all()
print("\n=== USUARIOS EN LA BASE DE DATOS ===")
for u in usuarios:
    print(f"  ID={u.id}  username={u.username!r}  nombre={u.nombre!r}  rol={u.rol}  activo={u.activo}")
db.close()
input("\nPresiona Enter para cerrar...")
