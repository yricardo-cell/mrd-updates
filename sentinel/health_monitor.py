"""Sondeo en background de la salud local de cada app vigilada.

Standalone a proposito (ver sentinel/__init__.py). El check HTTP es una
copia deliberadamente pequena del de scripts/operations/failover.py — no
se importa desde ahi para no acoplar dos componentes que deben poder
romperse por separado.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from sentinel.config import SentinelConfig

DEFAULT_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_TIMEOUT_SECONDS = 3.0


@dataclass
class AppHealth:
    healthy: bool
    checked_at: str


def check_http_health(url: str, timeout: float) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "mrd-sentinel/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            try:
                payload = json.loads(resp.read().decode("utf-8"))
                return payload.get("status") == "ok"
            except (json.JSONDecodeError, UnicodeDecodeError):
                return True
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
        return False


class HealthMonitor:
    """Sondea todas las apps de la config en un hilo y cachea el resultado,
    para que el proxy y el panel nunca esperen a un health-check en vivo."""

    def __init__(
        self,
        config: SentinelConfig,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        self._config = config
        self._poll_interval = poll_interval
        self._timeout = timeout
        self._lock = threading.Lock()
        self._results: dict[str, AppHealth] = {
            app.id: AppHealth(healthy=False, checked_at="") for app in config.apps
        }
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="sentinel-health-monitor",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def is_healthy(self, app_id: str) -> bool:
        with self._lock:
            result = self._results.get(app_id)
            return bool(result and result.healthy)

    def snapshot(self) -> dict[str, AppHealth]:
        with self._lock:
            return dict(self._results)

    def _run(self) -> None:
        # Primer chequeo inmediato para no arrancar con todo en "no sano".
        self._tick()
        while not self._stop_event.wait(timeout=self._poll_interval):
            self._tick()

    def _tick(self) -> None:
        for app in self._config.apps:
            healthy = check_http_health(app.health_url, self._timeout)
            now = datetime.now(timezone.utc).isoformat()
            with self._lock:
                self._results[app.id] = AppHealth(healthy=healthy, checked_at=now)
