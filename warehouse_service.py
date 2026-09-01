"""Reglas comunes de almacén para evitar existencias sin destino."""
import unicodedata

from sqlalchemy.orm import Session

from models import Almacen, Usuario


def get_default_warehouse(db: Session) -> Almacen | None:
    """Devuelve Almacén Madrid; solo usa otro activo si todavía no existe."""
    activos = db.query(Almacen).filter(Almacen.activo == True).order_by(Almacen.id).all()

    def normalizar(nombre: str) -> str:
        texto = unicodedata.normalize("NFKD", (nombre or "").strip().casefold())
        return " ".join("".join(c for c in texto if not unicodedata.combining(c)).split())

    madrid = next((a for a in activos if normalizar(a.nombre) == "almacen madrid"), None)
    principal = next((a for a in activos if "principal" in normalizar(a.nombre)), None)
    return madrid or principal or (activos[0] if activos else None)


def get_user_warehouse(db: Session, user: Usuario, requested_id: int | None = None) -> Almacen | None:
    """Devuelve el almacén efectivo sin permitir cruces entre centros."""
    if user.rol == "admin":
        if requested_id:
            requested = db.query(Almacen).filter(
                Almacen.id == requested_id, Almacen.activo == True,
            ).first()
            if requested:
                return requested
        return get_default_warehouse(db)
    assigned_id = getattr(user, "almacen_id", None)
    if assigned_id:
        return db.query(Almacen).filter(
            Almacen.id == assigned_id, Almacen.activo == True,
        ).first()
    # Compatibilidad segura para usuarios históricos: Madrid hasta que un
    # administrador les asigne expresamente Barcelona.
    return get_default_warehouse(db)


def visible_warehouses(db: Session, user: Usuario) -> list[Almacen]:
    if user.rol == "admin":
        return db.query(Almacen).filter(Almacen.activo == True).order_by(Almacen.nombre).all()
    warehouse = get_user_warehouse(db, user)
    return [warehouse] if warehouse else []


def can_access_warehouse(user: Usuario, warehouse_id: int | None) -> bool:
    if user.rol == "admin":
        return True
    if getattr(user, "almacen_id", None) is None:
        # Compatibilidad con registros históricos y bases temporales. En el
        # arranque real todos los usuarios antiguos quedan asignados a Madrid.
        return True
    return bool(warehouse_id and getattr(user, "almacen_id", None) == warehouse_id)
