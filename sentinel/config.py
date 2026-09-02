"""Carga la configuracion de MRD Sentinel desde sentinel/config/apps.yaml.

Standalone a proposito (ver sentinel/__init__.py): solo depende de pyyaml,
ya presente en requirements.txt para el resto del proyecto.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

SENTINEL_ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SENTINEL_ROOT / "config" / "apps.yaml"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class WatchedApp:
    id: str
    display_name: str
    local_url: str
    health_path: str
    public_hostname: str
    failover_state_root: Path
    proxy_enabled: bool

    @property
    def health_url(self) -> str:
        return self.local_url.rstrip("/") + self.health_path

    @property
    def state_path(self) -> Path:
        return self.failover_state_root / "state.json"

    @property
    def history_path(self) -> Path:
        return self.failover_state_root / "history.jsonl"


@dataclass(frozen=True)
class SentinelConfig:
    host: str
    port: int
    apps: tuple[WatchedApp, ...]

    def get_app(self, app_id: str) -> WatchedApp | None:
        for app in self.apps:
            if app.id == app_id:
                return app
        return None

    def get_app_by_hostname(self, hostname: str) -> WatchedApp | None:
        """Busca por Host header (sin puerto, insensible a mayusculas)."""
        host = hostname.split(":", 1)[0].lower()
        for app in self.apps:
            if app.public_hostname.lower() == host:
                return app
        return None


REQUIRED_APP_FIELDS = (
    "id", "display_name", "local_url", "health_path",
    "public_hostname", "failover_state_root",
)


def load_config(path: Path | None = None) -> SentinelConfig:
    cfg_path = path or DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise ConfigError(f"No existe el archivo de configuracion {cfg_path}.")

    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

    sentinel_raw = raw.get("sentinel") or {}
    host = sentinel_raw.get("host", "0.0.0.0")
    port = int(sentinel_raw.get("port", 9100))

    apps_raw = raw.get("apps") or []
    if not apps_raw:
        raise ConfigError(f"{cfg_path} no define ninguna app en 'apps'.")

    seen_ids: set[str] = set()
    apps: list[WatchedApp] = []
    for entry in apps_raw:
        missing = [f for f in REQUIRED_APP_FIELDS if not entry.get(f)]
        if missing:
            raise ConfigError(
                f"Entrada de app incompleta en {cfg_path} (faltan {missing}): {entry}"
            )
        app_id = entry["id"]
        if app_id in seen_ids:
            raise ConfigError(f"Id de app duplicado en {cfg_path}: '{app_id}'.")
        seen_ids.add(app_id)
        apps.append(WatchedApp(
            id=app_id,
            display_name=entry["display_name"],
            local_url=entry["local_url"],
            health_path=entry["health_path"],
            public_hostname=entry["public_hostname"],
            failover_state_root=Path(entry["failover_state_root"]),
            proxy_enabled=bool(entry.get("proxy_enabled", True)),
        ))

    return SentinelConfig(host=host, port=port, apps=tuple(apps))
