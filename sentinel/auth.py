"""Autenticacion propia de MRD Sentinel — separada de MRD Tool Control.

Standalone a proposito (ver sentinel/__init__.py): usuarios en un JSON
propio (sentinel/config/users.json, gitignored), clave JWT propia
(sentinel/config/secret.key, gitignored, autogenerada). No usa
database.py/models.py/auth.py de la app principal, para seguir
funcionando aunque esa base de datos este rota.

Uso para crear la primera cuenta (o anadir mas):
    python -m sentinel.auth create-admin
"""
from __future__ import annotations

import getpass
import json
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request, status
from jose import JWTError, jwt

SENTINEL_ROOT = Path(__file__).resolve().parent
USERS_PATH = SENTINEL_ROOT / "config" / "users.json"
SECRET_KEY_PATH = SENTINEL_ROOT / "config" / "secret.key"

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 720  # 12 horas — panel de emergencia, sesion mas corta que la app principal
COOKIE_NAME = "sentinel_token"

_MAX_INTENTOS = 5
_BLOQUEO_SEGUNDOS = 300  # 5 minutos

_login_attempts: dict = {}  # {ip_o_user: {"count": int, "locked_until": float}}
_login_lock = threading.Lock()
_users_lock = threading.Lock()


def _get_secret_key() -> str:
    """Clave JWT propia de Sentinel; se autogenera en el primer uso."""
    if SECRET_KEY_PATH.exists():
        key = SECRET_KEY_PATH.read_text(encoding="utf-8").strip()
        if key:
            return key
    SECRET_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    SECRET_KEY_PATH.write_text(key, encoding="utf-8")
    return key


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _load_users() -> dict:
    if not USERS_PATH.exists():
        return {}
    try:
        return json.loads(USERS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_users(users: dict) -> None:
    USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = USERS_PATH.with_name(USERS_PATH.name + ".tmp")
    tmp.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(USERS_PATH)


def create_user(username: str, password: str) -> None:
    with _users_lock:
        users = _load_users()
        users[username] = {
            "password_hash": hash_password(password),
            "created_at": datetime.utcnow().isoformat(),
            "token_version": 0,
        }
        _save_users(users)


def has_users() -> bool:
    """Indica si Sentinel ya tiene al menos una cuenta configurada."""
    return bool(_load_users())


def create_initial_user(username: str, password: str) -> bool:
    """Crea la primera cuenta una sola vez.

    Devuelve ``False`` si otra peticion o el administrador ya habia creado
    una cuenta. El bloqueo evita que dos aperturas simultaneas del asistente
    inicial sobrescriban la configuracion.
    """
    with _users_lock:
        users = _load_users()
        if users:
            return False
        users[username] = {
            "password_hash": hash_password(password),
            "created_at": datetime.utcnow().isoformat(),
            "token_version": 0,
        }
        _save_users(users)
        return True


def authenticate(username: str, password: str) -> bool:
    users = _load_users()
    entry = users.get(username)
    if not entry:
        return False
    return verify_password(password, entry["password_hash"])


def change_password(username: str, current_password: str, new_password: str) -> bool:
    """Cambia la contrasena de ``username`` si ``current_password`` es
    correcta. Incrementa ``token_version``, lo que invalida de inmediato
    cualquier sesion abierta (en cualquier dispositivo, incluido el que
    hace el cambio): la proxima comprobacion de token la rechaza y exige
    volver a iniciar sesion con la contrasena nueva."""
    with _users_lock:
        users = _load_users()
        entry = users.get(username)
        if not entry or not verify_password(current_password, entry["password_hash"]):
            return False
        entry["password_hash"] = hash_password(new_password)
        entry["token_version"] = int(entry.get("token_version", 0)) + 1
        users[username] = entry
        _save_users(users)
        return True


def create_token(username: str) -> str:
    entry = _load_users().get(username)
    token_version = entry.get("token_version", 0) if entry else 0
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": username, "exp": expire, "tv": token_version}
    return jwt.encode(payload, _get_secret_key(), algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[str]:
    """Devuelve el username si el token es valido, o None.

    Si el usuario todavia existe, la version de token del JWT (``tv``)
    debe coincidir con la guardada en users.json; un cambio de
    contrasena la incrementa, así que los tokens emitidos antes de ese
    cambio dejan de ser validos. Si el usuario ya no existe en el
    fichero (comportamiento previo a este cambio, usado por pruebas que
    solo verifican la cookie), no se exige esa comprobacion."""
    try:
        payload = jwt.decode(token, _get_secret_key(), algorithms=[ALGORITHM])
    except JWTError:
        return None
    username = payload.get("sub")
    if username is None:
        return None
    entry = _load_users().get(username)
    if entry is not None and payload.get("tv", 0) != entry.get("token_version", 0):
        return None
    return username


def current_user(request: Request) -> Optional[str]:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return verify_token(token)


def require_login(request: Request) -> str:
    user = current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return user


# ─── Rate limiting de login (mismo patron que main.py) ───────────────────────

def puede_intentar_login(clave: str) -> bool:
    with _login_lock:
        data = _login_attempts.get(clave, {"count": 0, "locked_until": 0.0})
        return time.time() >= data["locked_until"]


def registrar_fallo_login(clave: str) -> None:
    with _login_lock:
        data = _login_attempts.get(clave, {"count": 0, "locked_until": 0.0})
        data["count"] += 1
        if data["count"] >= _MAX_INTENTOS:
            data["locked_until"] = time.time() + _BLOQUEO_SEGUNDOS
            data["count"] = 0
        _login_attempts[clave] = data


def limpiar_intentos_login(clave: str) -> None:
    with _login_lock:
        _login_attempts.pop(clave, None)


def segundos_bloqueo(clave: str) -> int:
    with _login_lock:
        data = _login_attempts.get(clave, {"locked_until": 0.0})
        resto = data["locked_until"] - time.time()
        return max(0, int(resto))


# ─── CLI: creacion de cuentas de administrador ───────────────────────────────

def _cli_create_admin() -> int:
    username = input("Usuario para MRD Sentinel: ").strip()
    if not username:
        print("Usuario vacio, cancelado.")
        return 1
    password = getpass.getpass("Contrasena: ")
    if len(password) < 8:
        print("La contrasena debe tener al menos 8 caracteres.")
        return 1
    confirm = getpass.getpass("Confirma la contrasena: ")
    if password != confirm:
        print("Las contrasenas no coinciden.")
        return 1
    create_user(username, password)
    print(f"Usuario '{username}' creado/actualizado en {USERS_PATH}.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "create-admin":
        sys.exit(_cli_create_admin())
    print("Uso: python -m sentinel.auth create-admin")
    sys.exit(1)
