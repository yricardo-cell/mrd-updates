"""Rutas del panel de MRD Sentinel: login y dashboard de estado/historial.

Standalone a proposito (ver sentinel/__init__.py): usa sentinel.auth (no
auth.py de la app principal) y solo lee de sentinel.health_monitor /
sentinel.history_reader. Sin diseno visual — eso es Fase 3.
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sentinel import auth
from sentinel.admin_actions import AdminActionError, AdminActionRunner
from sentinel.component_checks import ComponentMonitor
from sentinel.config import DEFAULT_CONFIG_PATH, SentinelConfig
from sentinel.config_store import add_app
from sentinel.error_log import ErrorLog
from sentinel.health_monitor import HealthMonitor
from sentinel.history_reader import read_history, read_state
from sentinel.metrics_history import MetricsHistory
from sentinel.system_monitor import mrd_version, sentinel_uptime
from sentinel.system_monitor import snapshot as system_snapshot
from sentinel.tunnel_checks import TunnelMonitor

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _app_status(healthy: bool, state: dict | None) -> str:
    """Resume salud local + avisos de failover en un unico estado para
    el panel: 'bad' (no responde), 'warn' (responde pero con fallos
    publicos consecutivos) u 'ok'."""
    if not healthy:
        return "bad"
    if state and (state.get("consecutive_public_failures", 0) or 0) > 0:
        return "warn"
    return "ok"


def _is_https_request(request: Request) -> bool:
    return (
        request.headers.get("x-forwarded-proto", "http") == "https"
        or request.headers.get("cf-visitor", "").find("https") != -1
    )


def _is_local_request(request: Request) -> bool:
    """El alta inicial solo se permite desde el propio servidor."""
    # ``testclient`` es el origen sintetico que Starlette usa en pruebas; no
    # puede aparecer como direccion de una conexion TCP real.
    return bool(request.client and request.client.host in {"127.0.0.1", "::1", "testclient"})


def build_panel_router(
    config: SentinelConfig,
    health_monitor: HealthMonitor,
    config_path: Path | None = None,
    metrics_history: MetricsHistory | None = None,
    error_log: ErrorLog | None = None,
    component_monitor: ComponentMonitor | None = None,
    tunnel_monitor: TunnelMonitor | None = None,
    admin_runner: AdminActionRunner | None = None,
) -> APIRouter:
    router = APIRouter()

    def _sentinel_context() -> dict:
        component_result = component_monitor.snapshot() if component_monitor else None
        tunnels = tunnel_monitor.snapshot() if tunnel_monitor else {}
        return {
            "sentinel_uptime": sentinel_uptime(),
            "mrd_version": mrd_version(),
            "component_check": component_result,
            "tunnels": tunnels,
        }

    def _card_status(raw: str | None) -> str:
        """Traduce un estado interno a uno de los 4 estados publicos
        (ok/atencion/caido/desconocido), sin filtrar nunca el detalle
        tecnico original (rutas, mensajes de repair_center, etc.)."""
        if raw in ("ok", "running", "ready"):
            return "ok"
        if raw in ("error",):
            return "atencion"
        if raw in ("stopped",):
            return "caido"
        return "desconocido"

    def _public_status_payload() -> dict:
        main_app = config.apps[0] if config.apps else None
        app_healthy = health_monitor.is_healthy(main_app.id) if main_app else None
        app_health = health_monitor.get(main_app.id) if main_app else None
        component_result = component_monitor.snapshot() if component_monitor else None
        tunnels = tunnel_monitor.snapshot() if tunnel_monitor else {}
        components = component_result.components if component_result else {}

        def component_card(name: str, label: str) -> dict:
            detail = components.get(name)
            return {"label": label, "status": _card_status(detail.get("status") if detail else None)}

        cards = {
            "aplicacion_mrd": {
                "label": main_app.display_name if main_app else "Aplicación MRD",
                "status": "ok" if app_healthy else ("caido" if main_app else "desconocido"),
            },
            "base_datos": component_card("base_datos", "Base de datos"),
            "escaner_qr": component_card("escaner_qr", "Escáner y QR"),
            "acceso_remoto": component_card("acceso_remoto", "Acceso remoto"),
            "tunel_a": {
                "label": "Túnel principal (A)",
                "status": _card_status(tunnels["cloudflared"].state if "cloudflared" in tunnels else None),
            },
            "tunel_b": {
                "label": "Túnel de respaldo (B)",
                "status": _card_status(tunnels["cloudflared_backup"].state if "cloudflared_backup" in tunnels else None),
            },
            "sentinel": {"label": "Sentinel", "status": "ok", "uptime": sentinel_uptime()},
        }
        caido = any(c["status"] == "caido" for c in cards.values())
        atencion = any(c["status"] == "atencion" for c in cards.values())
        overall = "caido" if caido else ("atencion" if atencion else "ok")
        return {
            "overall": overall,
            "cards": cards,
            "checked_at": app_health.checked_at if app_health else None,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    @router.get("/status", response_class=HTMLResponse)
    def status_publico(request: Request):
        return templates.TemplateResponse(
            request, "status_publico.html",
            {"request": request, "app_name": "MRD Sentinel", **_public_status_payload()},
        )

    @router.get("/status.json")
    def status_publico_json():
        return _public_status_payload()

    @router.get("/login", response_class=HTMLResponse)
    def login_get(request: Request):
        if not auth.has_users():
            return RedirectResponse("/setup", status_code=303)
        if auth.current_user(request):
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(
            request, "login.html", {"request": request, "app_name": "MRD Sentinel"},
        )

    @router.post("/login")
    def login_post(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
    ):
        if not auth.has_users():
            return RedirectResponse("/setup", status_code=303)
        ip = request.client.host if request.client else "unknown"
        clave_rl = f"{ip}:{username}"

        if not auth.puede_intentar_login(clave_rl):
            segundos = auth.segundos_bloqueo(clave_rl)
            return templates.TemplateResponse(
                request, "login.html",
                {"request": request, "app_name": "MRD Sentinel",
                 "error": f"Demasiados intentos fallidos. Espera {segundos // 60}m {segundos % 60}s."},
                status_code=429,
            )

        if not auth.authenticate(username, password):
            auth.registrar_fallo_login(clave_rl)
            return templates.TemplateResponse(
                request, "login.html",
                {"request": request, "app_name": "MRD Sentinel",
                 "error": "Usuario o contraseña incorrectos"},
                status_code=401,
            )

        auth.limpiar_intentos_login(clave_rl)
        token = auth.create_token(username)
        is_https = _is_https_request(request)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(
            auth.COOKIE_NAME, token,
            httponly=True, secure=is_https,
            max_age=auth.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            samesite="lax", path="/",
        )
        return resp

    @router.get("/setup", response_class=HTMLResponse)
    def setup_get(request: Request):
        if auth.has_users():
            return RedirectResponse("/login", status_code=303)
        if not _is_local_request(request):
            return HTMLResponse(
                "La configuracion inicial solo puede hacerse desde este equipo.",
                status_code=403,
            )
        return templates.TemplateResponse(
            request, "setup.html", {"request": request, "app_name": "MRD Sentinel"},
        )

    @router.post("/setup")
    def setup_post(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        password_confirm: str = Form(...),
    ):
        if auth.has_users():
            return RedirectResponse("/login", status_code=303)
        if not _is_local_request(request):
            return HTMLResponse(
                "La configuracion inicial solo puede hacerse desde este equipo.",
                status_code=403,
            )
        username = username.strip()
        error = None
        if not username or len(username) > 80:
            error = "Escribe un nombre de usuario valido."
        elif len(password) < 8:
            error = "La contrasena debe tener al menos 8 caracteres."
        elif password != password_confirm:
            error = "Las contrasenas no coinciden."
        if error:
            return templates.TemplateResponse(
                request, "setup.html",
                {"request": request, "app_name": "MRD Sentinel", "error": error},
                status_code=400,
            )
        if not auth.create_initial_user(username, password):
            return RedirectResponse("/login", status_code=303)
        return RedirectResponse("/login?configured=1", status_code=303)

    @router.get("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(auth.COOKIE_NAME, path="/")
        return resp

    @router.get("/", response_class=HTMLResponse)
    def dashboard(request: Request, user: str = Depends(auth.require_login)):
        apps_view = []
        for app in config.apps:
            health = health_monitor.get(app.id)
            healthy = health_monitor.is_healthy(app.id)
            state = read_state(app)
            apps_view.append({
                "id": app.id,
                "display_name": app.display_name,
                "public_hostname": app.public_hostname,
                "local_url": app.local_url,
                "healthy": healthy,
                "status": _app_status(healthy, state),
                "checked_at": health.checked_at if health else "",
                "state": state,
                "history": read_history(app, limit=20),
            })
        return templates.TemplateResponse(
            request, "dashboard.html",
            {"request": request, "app_name": "MRD Sentinel", "user": user,
             "apps": apps_view, "system": system_snapshot(),
             "add_error": None, "checked": request.query_params.get("checked"),
             "now": time.strftime("%Y-%m-%d %H:%M:%S"),
             **_sentinel_context()},
        )

    @router.get("/metrics/history")
    def metrics_history_json(user: str = Depends(auth.require_login)):
        if metrics_history is None:
            return {"points": []}
        return {"points": metrics_history.recent(limit=100)}

    @router.get("/incidencias", response_class=HTMLResponse)
    def incidencias(request: Request, user: str = Depends(auth.require_login)):
        entries = error_log.recent() if error_log is not None else []
        return templates.TemplateResponse(
            request, "incidencias.html",
            {"request": request, "app_name": "MRD Sentinel", "user": user, "entries": entries},
        )

    @router.post("/apps/{app_id}/check")
    def check_application_now(app_id: str, user: str = Depends(auth.require_login)):
        health_monitor.check_now(app_id)
        return RedirectResponse(f"/?checked={app_id}#app-{app_id}", status_code=303)

    _ADMIN_ERROR_STATUS = {
        "accion_no_reconocida": 404,
        "confirmacion_no_coincide": 400,
        "doble_clic_bloqueado": 409,
        "limite_de_peticiones_alcanzado": 429,
        "ya_hay_una_accion_en_curso": 409,
    }

    @router.get("/admin/acciones", response_class=HTMLResponse)
    def admin_acciones(request: Request, user: str = Depends(auth.require_login)):
        acciones = admin_runner.available_actions() if admin_runner is not None else []
        return templates.TemplateResponse(
            request, "admin_acciones.html",
            {"request": request, "app_name": "MRD Sentinel", "user": user,
             "acciones": acciones, "resultado": request.query_params.get("resultado"),
             "accion_id": request.query_params.get("accion")},
        )

    @router.post("/admin/acciones/{action_id}")
    def admin_ejecutar_accion(
        request: Request,
        action_id: str,
        confirmar: str = Form(""),
        confirmacion: str = Form(""),
        user: str = Depends(auth.require_login),
    ):
        if admin_runner is None:
            raise HTTPException(status_code=404, detail="accion_no_reconocida")
        if confirmar != "si":
            raise HTTPException(status_code=400, detail="confirmacion_requerida")
        try:
            resultado = admin_runner.execute(action_id, user, confirmacion)
        except AdminActionError as exc:
            status_code = _ADMIN_ERROR_STATUS.get(str(exc), 400)
            if request.headers.get("accept", "").find("application/json") != -1:
                return JSONResponse({"ok": False, "error": str(exc)}, status_code=status_code)
            raise HTTPException(status_code=status_code, detail=str(exc))
        return RedirectResponse(
            f"/admin/acciones?accion={action_id}&resultado={'ok' if resultado.ok else 'error'}",
            status_code=303,
        )

    @router.get("/admin/auditoria", response_class=HTMLResponse)
    def admin_auditoria(request: Request, user: str = Depends(auth.require_login)):
        entries = admin_runner.audit_entries() if admin_runner is not None else []
        return templates.TemplateResponse(
            request, "auditoria.html",
            {"request": request, "app_name": "MRD Sentinel", "user": user, "entries": entries},
        )

    @router.post("/apps")
    def add_application(
        request: Request,
        id: str = Form(...),
        display_name: str = Form(...),
        local_url: str = Form(...),
        health_path: str = Form("/health"),
        public_hostname: str = Form(...),
        user: str = Depends(auth.require_login),
    ):
        try:
            updated = add_app({
                "id": id, "display_name": display_name, "local_url": local_url,
                "health_path": health_path, "public_hostname": public_hostname,
            }, path=config_path or DEFAULT_CONFIG_PATH)
            config.replace_from(updated)
            health_monitor.refresh_config(config)
            return RedirectResponse("/?added=1", status_code=303)
        except Exception as exc:
            apps_view = []
            for app in config.apps:
                health = health_monitor.get(app.id)
                healthy = health_monitor.is_healthy(app.id)
                state = read_state(app)
                apps_view.append({
                    "id": app.id, "display_name": app.display_name,
                    "public_hostname": app.public_hostname,
                    "local_url": app.local_url,
                    "healthy": healthy,
                    "status": _app_status(healthy, state),
                    "checked_at": health.checked_at if health else "",
                    "state": state, "history": read_history(app, limit=20),
                })
            return templates.TemplateResponse(
                request, "dashboard.html",
                {"request": request, "app_name": "MRD Sentinel", "user": user,
                 "apps": apps_view, "system": system_snapshot(),
                 "add_error": str(exc), "checked": None,
                 "now": time.strftime("%Y-%m-%d %H:%M:%S"),
                 **_sentinel_context()},
                status_code=400,
            )

    return router
