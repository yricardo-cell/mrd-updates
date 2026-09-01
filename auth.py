"""
Autenticacion y autorizacion - MRD TOOL CONTROL
"""
from datetime import datetime, timedelta
from typing import Optional
import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from database import get_db
from models import Usuario

PERMISOS_ROL = {
    "admin":     [
        "ver", "crear", "editar", "borrar", "entregar", "devolver",
        "backup", "usuarios", "config", "etiquetas", "inventario",
        "stock_operar",
    ],
    "almacen":   ["ver", "crear", "editar", "entregar", "devolver", "etiquetas", "inventario"],
    "encargado": ["ver", "entregar", "devolver"],
    "encargado_patio": [
        # Toda la operativa diaria del patio, sin funciones destructivas ni
        # acceso a usuarios, copias, actualizaciones o configuración.
        "ver", "crear", "editar", "entregar", "devolver", "inventario",
        "stock_operar", "etiquetas",
    ],
    "consulta":  ["ver"],
}

ROLES_NOMBRE = {
    "admin": "Admin",
    "almacen": "Almacén",
    "encargado": "Encargado",
    "encargado_patio": "Encargado de Patio",
    "consulta": "Consulta",
}
ROLES_VALIDOS = frozenset(ROLES_NOMBRE)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def crear_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verificar_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


def obtener_usuario_por_token(token: str, db: Session) -> Optional[Usuario]:
    payload = verificar_token(token)
    if not payload:
        return None
    username = payload.get("sub")
    if not username:
        return None
    return db.query(Usuario).filter(
        Usuario.username == username,
        Usuario.activo == True
    ).first()


def usuario_actual(request: Request, db: Session = Depends(get_db)) -> Optional[Usuario]:
    token = request.cookies.get("mrd_token")
    if not token:
        return None
    return obtener_usuario_por_token(token, db)


def requiere_login(request: Request, db: Session = Depends(get_db)) -> Usuario:
    user = usuario_actual(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"}
        )
    return user


def tiene_permiso(user: Usuario, permiso: str) -> bool:
    permisos = PERMISOS_ROL.get(user.rol, [])
    return permiso in permisos
