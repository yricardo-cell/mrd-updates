"""Validacion y escritura controlada de apps.yaml desde el panel."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

from sentinel.config import DEFAULT_CONFIG_PATH, ConfigError, SentinelConfig, load_config

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,48}$")
_HOST_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,252}$", re.IGNORECASE)


def _validate_app(data: dict, existing: SentinelConfig) -> dict:
    app_id = str(data.get("id", "")).strip().lower()
    name = str(data.get("display_name", "")).strip()
    local_url = str(data.get("local_url", "")).strip().rstrip("/")
    health_path = str(data.get("health_path", "/health")).strip()
    hostname = str(data.get("public_hostname", "")).strip().lower()
    if not _ID_RE.fullmatch(app_id):
        raise ConfigError("El identificador debe usar letras, numeros, guion o guion bajo.")
    if any(app.id == app_id for app in existing.apps):
        raise ConfigError("Ya existe una aplicacion con ese identificador.")
    if not name or len(name) > 120:
        raise ConfigError("Escribe un nombre valido para la aplicacion.")
    parsed = urlparse(local_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ConfigError("La URL local debe apuntar a localhost, 127.0.0.1 o ::1.")
    if not health_path.startswith("/") or len(health_path) > 200 or ".." in health_path:
        raise ConfigError("La ruta de salud no es valida.")
    if not _HOST_RE.fullmatch(hostname):
        raise ConfigError("El dominio publico no es valido.")
    state_root = Path(r"C:\ProgramData\MRDSentinel\apps") / app_id / "failover"
    return {
        "id": app_id,
        "display_name": name,
        "local_url": local_url,
        "health_path": health_path,
        "public_hostname": hostname,
        "failover_state_root": str(state_root),
        "proxy_enabled": bool(data.get("proxy_enabled", True)),
    }


def add_app(data: dict, path: Path = DEFAULT_CONFIG_PATH) -> SentinelConfig:
    current = load_config(path)
    entry = _validate_app(data, current)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw.setdefault("apps", []).append(entry)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    tmp.replace(path)
    return load_config(path)
