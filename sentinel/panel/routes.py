"""Rutas del panel de MRD Sentinel: login y dashboard de estado/historial.

Standalone a proposito (ver sentinel/__init__.py): usa sentinel.auth (no
auth.py de la app principal) y solo lee de sentinel.health_monitor /
sentinel.history_reader. Sin diseno visual — eso es Fase 3.
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from sentinel import auth
from sentinel.config import DEFAULT_CONFIG_PATH, SentinelConfig
from sentinel.config_store import add_app
from sentinel.health_monitor import HealthMonitor
from sentinel.history_reader import read_history, read_state
from sentinel.system_monitor import snapshot as system_snapshot

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


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


def build_panel_router(config: SentinelConfig, health_monitor: HealthMonitor, config_path: Path | None = None) -> APIRouter:
    router = APIRouter()

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
            apps_view.append({
                "id": app.id,
                "display_name": app.display_name,
                "public_hostname": app.public_hostname,
                "local_url": app.local_url,
                "healthy": health_monitor.is_healthy(app.id),
                "state": read_state(app),
                "history": read_history(app, limit=20),
            })
        return templates.TemplateResponse(
            request, "dashboard.html",
            {"request": request, "app_name": "MRD Sentinel", "user": user,
             "apps": apps_view, "system": system_snapshot(),
             "add_error": None, "now": time.strftime("%Y-%m-%d %H:%M:%S")},
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
            apps_view = [{
                "id": app.id, "display_name": app.display_name,
                "public_hostname": app.public_hostname,
                "local_url": app.local_url,
                "healthy": health_monitor.is_healthy(app.id),
                "state": read_state(app), "history": read_history(app, limit=20),
            } for app in config.apps]
            return templates.TemplateResponse(
                request, "dashboard.html",
                {"request": request, "app_name": "MRD Sentinel", "user": user,
                 "apps": apps_view, "system": system_snapshot(),
                 "add_error": str(exc), "now": time.strftime("%Y-%m-%d %H:%M:%S")},
                status_code=400,
            )

    return router
