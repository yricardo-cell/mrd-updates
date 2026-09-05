"""Factory de la app FastAPI de MRD Sentinel.

Ensambla: panel (auth propia + dashboard), health monitor en background,
y un catch-all que hace proxy transparente hacia la app vigilada cuya
public_hostname coincide con el Host header de la peticion entrante.

Standalone a proposito (ver sentinel/__init__.py): no importa nada de
main.py/models.py/database.py de MRD Tool Control.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from sentinel.admin_actions import (
    AdminActionRunner,
    AuditLog,
    build_actions,
    build_tunnel_repair_actions,
)
from sentinel.component_checks import ComponentMonitor
from sentinel.config import SentinelConfig, load_config
from sentinel.error_log import ErrorLog
from sentinel.health_monitor import HealthMonitor
from sentinel.metrics_history import MetricsHistory, MetricsSampler
from sentinel.panel.routes import build_panel_router
from sentinel.proxy import proxy_request
from sentinel.system_monitor import snapshot as system_snapshot
from sentinel.tunnel_checks import TunnelMonitor

# Paths propios del panel (Host = el propio Sentinel, ej. rescue.iasmrd.com
# o 127.0.0.1:9100) que nunca deben pasar por el proxy hacia otra app.
_PANEL_PATH_PREFIXES = ("/login", "/logout", "/healthz", "/static")

_STATIC_DIR = Path(__file__).resolve().parent / "panel" / "static"


def create_app(config_path: Optional[Path] = None) -> FastAPI:
    config: SentinelConfig = load_config(config_path)
    health_monitor = HealthMonitor(config)
    # Si hay un config_path explicito (siempre el caso en tests, que usan un
    # tmp_path aislado), el historial de metricas vive junto a el en lugar de
    # la ruta real de ProgramData, para no escribir estado fuera del sandbox
    # de cada test.
    metrics_history_path = (config_path.parent / "metrics_history.json") if config_path else None
    metrics_history = MetricsHistory(path=metrics_history_path)
    metrics_sampler = MetricsSampler(metrics_history, system_snapshot, health_monitor)
    error_log_path = (config_path.parent / "error_log.json") if config_path else None
    error_log = ErrorLog(path=error_log_path)
    component_monitor = ComponentMonitor()
    tunnel_monitor = TunnelMonitor()
    audit_log_path = (config_path.parent / "audit_log.json") if config_path else None
    audit_log = AuditLog(path=audit_log_path)
    admin_actions = {
        **build_actions(config, health_monitor, component_monitor, tunnel_monitor),
        **build_tunnel_repair_actions(),
    }
    admin_runner = AdminActionRunner(admin_actions, audit_log)

    app = FastAPI(title="MRD Sentinel")

    @app.on_event("startup")
    def _startup() -> None:
        health_monitor.start()
        metrics_sampler.start()
        component_monitor.start()
        tunnel_monitor.start()

    @app.on_event("shutdown")
    def _shutdown() -> None:
        health_monitor.stop()
        metrics_sampler.stop()
        component_monitor.stop()
        tunnel_monitor.stop()

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "service": "mrd-sentinel"}

    app.include_router(build_panel_router(
        config, health_monitor, config_path, metrics_history, error_log,
        component_monitor, tunnel_monitor, admin_runner,
    ))
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.api_route(
        "/{full_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    )
    async def catch_all(request: Request, full_path: str):
        # Rutas propias del panel (login/dashboard/healthz) ya las capturo
        # el router de arriba; si llegamos aqui es una ruta que no es del
        # panel de Sentinel, o el Host header pertenece a una app vigilada.
        host = request.headers.get("host", "")
        target_app = config.get_app_by_hostname(host)
        if target_app is not None and target_app.proxy_enabled:
            return await proxy_request(request, target_app, health_monitor, error_log)
        return PlainTextResponse("No encontrado", status_code=404)

    return app
