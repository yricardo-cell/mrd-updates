"""Historial acotado de metricas (CPU/RAM/disco/tiempos de respuesta).

Standalone a proposito (ver sentinel/__init__.py). Guarda un fichero JSON
unico con como maximo MAX_POINTS entradas (recorte FIFO), escritura atomica
(tmp + replace) para que una lectura concurrente nunca vea un fichero a
medio escribir. No usa una base de datos nueva, solo un JSON plano.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

MAX_POINTS = 288  # a 5 min/punto, cubre 24h sin crecer sin limite
DEFAULT_PATH = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "MRDSentinel" / "metrics_history.json"


@dataclass
class MetricsPoint:
    timestamp: str
    cpu_percent: float | None
    memory_percent: float | None
    disk_percent: float | None
    response_ms: dict[str, float | None]


class MetricsHistory:
    """Mantiene en memoria + disco los ultimos MAX_POINTS puntos."""

    def __init__(self, path: Path | None = None, max_points: int = MAX_POINTS):
        self._path = path or DEFAULT_PATH
        self._max_points = max_points
        self._lock = threading.Lock()
        self._points: list[dict] = self._load()

    def _load(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data[-self._max_points:]
        except (json.JSONDecodeError, OSError):
            pass
        return []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(self._points, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path)

    def add_point(
        self,
        cpu_percent: float | None,
        memory_percent: float | None,
        disk_percent: float | None,
        response_ms: dict[str, float | None] | None = None,
    ) -> None:
        point = MetricsPoint(
            timestamp=datetime.now(timezone.utc).isoformat(),
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            disk_percent=disk_percent,
            response_ms=response_ms or {},
        )
        with self._lock:
            self._points.append(asdict(point))
            if len(self._points) > self._max_points:
                self._points = self._points[-self._max_points:]
            self._save()

    def recent(self, limit: int | None = None) -> list[dict]:
        with self._lock:
            points = list(self._points)
        if limit is not None:
            points = points[-limit:]
        return points


class MetricsSampler:
    """Hilo en background que toma una muestra periodica del sistema y de
    los tiempos de respuesta de las apps vigiladas."""

    def __init__(
        self,
        history: MetricsHistory,
        system_snapshot_fn,
        health_monitor,
        interval_seconds: float = 300.0,
    ):
        self._history = history
        self._system_snapshot_fn = system_snapshot_fn
        self._health_monitor = health_monitor
        self._interval = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="sentinel-metrics-sampler")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        self._tick()
        while not self._stop_event.wait(timeout=self._interval):
            self._tick()

    def _tick(self) -> None:
        try:
            snap = self._system_snapshot_fn()
        except Exception:
            snap = {}
        response_ms: dict[str, float | None] = {}
        try:
            for app_id, latency in self._health_monitor.latency_snapshot().items():
                response_ms[app_id] = latency
        except AttributeError:
            pass
        self._history.add_point(
            cpu_percent=snap.get("cpu_percent"),
            memory_percent=snap.get("memory_percent"),
            disk_percent=snap.get("disk_percent"),
            response_ms=response_ms,
        )
