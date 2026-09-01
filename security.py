"""
MRD TOOL CONTROL — Módulo centralizado de seguridad
Sprint 5.2 — Security Hardening
"""
from __future__ import annotations

import re
import secrets
from pathlib import Path
from typing import Optional, Set

# ─── CSRF ─────────────────────────────────────────────────────────────────────

CSRF_COOKIE_NAME  = "mrd_csrf"
CSRF_FIELD_NAME   = "_csrf_token"
CSRF_HEADER_NAME  = "x-csrf-token"
CSRF_TOKEN_BYTES  = 32          # 32 bytes → 64 hex chars

def generar_csrf_token() -> str:
    """Genera un token CSRF criptográficamente seguro."""
    return secrets.token_hex(CSRF_TOKEN_BYTES)

def validar_csrf(cookie_val: str, submitted_val: str) -> bool:
    """Comparación en tiempo constante para evitar timing-attacks."""
    if not cookie_val or not submitted_val:
        return False
    try:
        return secrets.compare_digest(cookie_val, submitted_val)
    except TypeError:
        return False

# ─── Política de contraseñas ──────────────────────────────────────────────────

# Contraseñas comunes que deben rechazarse explícitamente
_CONTRASENAS_COMUNES: Set[str] = {
    "password", "contraseña", "12345678", "123456789", "1234567890",
    "qwerty123", "abc123456", "admin1234", "password1", "pass1234",
    "mrd2024", "mrd2025", "mrd2026", "admin123", "admin2024",
    "123456", "password123", "password1!", "contraseña1!",
    "welcome1!", "bienvenido1!", "qwerty", "letmein",
}
# Normalizar a minúsculas para comparación insensible a mayúsculas
_CONTRASENAS_COMUNES = {p.lower() for p in _CONTRASENAS_COMUNES}

class ErrorContrasena(ValueError):
    """Error de política de contraseña. El mensaje es seguro para mostrar al usuario."""
    pass

def validar_contrasena(
    password: str,
    username: str = "",
    min_length: int = 10,
) -> None:
    """
    Valida la política de contraseñas.

    Args:
        password:   Contraseña a validar (texto plano).
        username:   Nombre de usuario (para detectar igualdad).
        min_length: Mínimo de caracteres (nunca inferior a 8 en producción).

    Raises:
        ErrorContrasena: Descripción clara y en español del requisito que no se cumple.
    """
    effective_min = max(min_length, 8)      # nunca menos de 8

    if not password or not password.strip():
        raise ErrorContrasena("La contraseña no puede estar vacía.")

    if len(password) < effective_min:
        raise ErrorContrasena(
            f"La contraseña debe tener al menos {effective_min} caracteres "
            f"(tiene {len(password)})."
        )

    if not re.search(r"[A-Z]", password):
        raise ErrorContrasena(
            "La contraseña debe contener al menos una letra mayúscula (A-Z)."
        )

    if not re.search(r"[a-z]", password):
        raise ErrorContrasena(
            "La contraseña debe contener al menos una letra minúscula (a-z)."
        )

    if not re.search(r"[0-9]", password):
        raise ErrorContrasena(
            "La contraseña debe contener al menos un número (0-9)."
        )

    if not re.search(r"[^A-Za-z0-9\s]", password):
        raise ErrorContrasena(
            "La contraseña debe contener al menos un carácter especial "
            "(!@#$%^&*-_=+.,?)."
        )

    if username and password.lower() == username.lower():
        raise ErrorContrasena(
            "La contraseña no puede ser igual al nombre de usuario."
        )

    if password.lower() in _CONTRASENAS_COMUNES:
        raise ErrorContrasena(
            "Esa contraseña es demasiado común o conocida. Elige una más segura."
        )


# ─── Validación de archivos (magic bytes portátil) ────────────────────────────

# Firmas de archivos: ext → lista de (bytes_esperados, offset)
_FIRMAS: dict[str, list[tuple[bytes, int]]] = {
    "jpg":  [(b"\xff\xd8\xff", 0)],
    "jpeg": [(b"\xff\xd8\xff", 0)],
    "png":  [(b"\x89PNG\r\n\x1a\n", 0)],
    "webp": [(b"WEBP", 8)],                # RIFF????WEBP
    "pdf":  [(b"%PDF", 0)],
    "xlsx": [(b"PK\x03\x04", 0)],          # OOXML = ZIP
    "zip":  [(b"PK\x03\x04", 0), (b"PK\x05\x06", 0)],
    "csv":  None,                           # texto plano, sin firma fija
}

# Extensiones que NUNCA se permiten independientemente del endpoint
_EXTENSIONES_BLOQUEADAS: Set[str] = {
    "exe", "bat", "cmd", "ps1", "js", "html", "htm", "svg",
    "dll", "sh", "py", "rb", "php", "asp", "aspx", "jsp",
    "msi", "com", "scr", "vbs", "jar", "class", "reg", "inf",
    "lnk", "hta", "wsf", "wsh", "pif", "vbe", "jse",
}

class ErrorArchivo(ValueError):
    """Error de validación de archivo. El mensaje es seguro para mostrar al usuario."""
    pass


def _nombre_seguro(filename: str) -> tuple[str, str]:
    """
    Devuelve (nombre_base_seguro, extension_lower).
    Elimina path traversal y caracteres peligrosos.
    """
    nombre_sin_path = Path(filename).name          # strip de directorios
    nombre_seguro  = re.sub(r"[^\w.\-]", "_", nombre_sin_path)
    partes = nombre_seguro.rsplit(".", 1)
    if len(partes) < 2 or not partes[1]:
        raise ErrorArchivo("El archivo no tiene extensión o el nombre no es válido.")
    return partes[0], partes[1].lower()


def _verificar_magic(head: bytes, ext: str) -> bool:
    """Verifica que los bytes iniciales correspondan a la extensión declarada."""
    firmas = _FIRMAS.get(ext)
    if firmas is None:                          # CSV: sin firma, se acepta
        return True
    for magic, offset in firmas:
        if head[offset : offset + len(magic)] == magic:
            return True
    return False


def validar_nombre_archivo(
    filename: str,
    extensiones_permitidas: Set[str],
) -> tuple[str, str]:
    """
    Valida nombre y extensión.
    Devuelve (nombre_base_seguro, ext_lower).
    Lanza ErrorArchivo si no pasa la validación.
    """
    _, ext = _nombre_seguro(filename)

    # Extensiones siempre bloqueadas
    if ext in _EXTENSIONES_BLOQUEADAS:
        raise ErrorArchivo(
            f"Tipo de archivo no permitido: .{ext}. "
            "Sube solo imágenes (JPG, PNG, WEBP), PDF o Excel."
        )

    # Extensión no permitida en este endpoint
    if ext not in extensiones_permitidas:
        permitidas = ", ".join(f".{e.upper()}" for e in sorted(extensiones_permitidas))
        raise ErrorArchivo(
            f"Extensión .{ext.upper()} no permitida aquí. "
            f"Formatos aceptados: {permitidas}."
        )

    return _nombre_seguro(filename)


def validar_contenido_archivo(head16: bytes, ext: str) -> None:
    """
    Verifica que los primeros bytes del archivo correspondan a la extensión.
    Lanza ErrorArchivo si el contenido no coincide.
    """
    if not _verificar_magic(head16, ext):
        nombres = {
            "jpg": "imagen JPEG", "jpeg": "imagen JPEG",
            "png": "imagen PNG",  "webp": "imagen WEBP",
            "pdf": "documento PDF", "xlsx": "hoja de cálculo Excel",
        }
        desc = nombres.get(ext, f"archivo .{ext.upper()}")
        raise ErrorArchivo(
            f"El archivo no parece ser realmente un {desc}. "
            "El contenido no coincide con la extensión. "
            "Es posible que el archivo esté dañado o sea de tipo incorrecto."
        )


def validar_tamaño_bytes(size_bytes: int, max_mb: int = 10) -> None:
    """Verifica que el tamaño no supere el máximo permitido."""
    max_bytes = max_mb * 1024 * 1024
    if size_bytes > max_bytes:
        size_mb = size_bytes / 1024 / 1024
        raise ErrorArchivo(
            f"El archivo supera el tamaño máximo permitido de {max_mb} MB "
            f"(tamaño: {size_mb:.1f} MB). "
            "Reduce el tamaño del archivo o contacta con el administrador."
        )


# ─── Cabeceras de seguridad HTTP ──────────────────────────────────────────────

def build_security_headers(is_https: bool = False) -> dict[str, str]:
    """
    Genera las cabeceras HTTP de seguridad para incluir en cada respuesta.

    Notas sobre script-src:
      Se usa 'unsafe-inline' porque el proyecto tiene ~20+ templates con scripts inline.
      La migración a nonces está planificada para Sprint 5.11 (refactorización de templates).
      El resto de directivas CSP son estrictas para proteger contra inyección de otros recursos.
    """
    csp = "; ".join([
        "default-src 'self'",
        # 'unsafe-inline' necesario hasta refactorizar templates a Sprint 5.11
        "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net cdnjs.cloudflare.com",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "media-src 'self' blob:",       # acceso a cámara para QR
        "worker-src 'self' blob:",      # PWA service worker
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    ])

    headers: dict[str, str] = {
        "Content-Security-Policy":  csp,
        "X-Frame-Options":          "DENY",
        "X-Content-Type-Options":   "nosniff",
        "X-XSS-Protection":         "1; mode=block",
        "Referrer-Policy":          "strict-origin-when-cross-origin",
        "Permissions-Policy": (
            "camera=(self), "
            "microphone=(), "
            "geolocation=(), "
            "payment=(), "
            "usb=(), "
            "bluetooth=()"
        ),
    }

    if is_https:
        headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

    return headers
