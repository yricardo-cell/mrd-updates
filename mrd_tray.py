"""
MRD TOOL CONTROL — Icono de bandeja del sistema
v2.0 — 2026-07-13

Gestiona el servidor uvicorn en segundo plano y muestra
un icono en la bandeja con menú de control.

Arrancar sin ventana CMD:
  venv\Scripts\pythonw.exe mrd_tray.py

NO registra ni expone tokens, credenciales ni rutas sensibles.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# ─── Rutas ────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent.resolve()
VENV_PY     = BASE_DIR / "venv" / "Scripts" / "pythonw.exe"
LOG_DIR     = BASE_DIR / "logs"
ICON_PATH   = BASE_DIR / "static" / "icons" / "icon-180.png"
STATUS_FILE = BASE_DIR / ".service_status"
APP_URL     = "http://localhost:8000"
PORT        = 8000

# ─── Auto-instalación silenciosa de dependencias ─────────────────────────────
def _ensure_packages():
    python = str(VENV_PY) if VENV_PY.exists() else sys.executable
    for pkg in ("pystray", "Pillow"):
        try:
            __import__(pkg.lower().replace("pillow", "PIL"))
        except ImportError:
            subprocess.run(
                [python, "-m", "pip", "install", pkg, "--quiet",
                 "--disable-pip-version-check"],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

_ensure_packages()

import pystray
from pystray import MenuItem as item, Menu
from PIL import Image, ImageDraw, ImageFont

# ─── Estado global ────────────────────────────────────────────────────────────
_server_proc: subprocess.Popen | None = None
_start_time: float | None = None
_lock = threading.Lock()

# ─── Icono ────────────────────────────────────────────────────────────────────
def _build_icon() -> Image.Image:
    """Carga el icono PNG del proyecto o genera uno si no existe."""
    if ICON_PATH.exists():
        try:
            return Image.open(ICON_PATH).convert("RGBA").resize((64, 64))
        except Exception:
            pass
    # Fallback: generar icono MRD en memoria
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, 63, 63], radius=12, fill=(30, 58, 95))
    d.rectangle([0, 53, 63, 63], fill=(224, 123, 0))
    try:
        font = ImageFont.truetype("arialbd.ttf", 18)
    except Exception:
        font = ImageFont.load_default()
    d.text((7, 18), "MRD", fill=(255, 255, 255), font=font)
    return img

# ─── Control del servidor ─────────────────────────────────────────────────────
def _get_python() -> str:
    if VENV_PY.exists():
        return str(VENV_PY)
    # Fallback: python.exe del mismo venv
    py_exe = BASE_DIR / "venv" / "Scripts" / "python.exe"
    if py_exe.exists():
        return str(py_exe)
    return sys.executable

def _is_running() -> bool:
    with _lock:
        return _server_proc is not None and _server_proc.poll() is None

def _port_in_use() -> bool:
    import socket
    try:
        with socket.create_connection(("localhost", PORT), timeout=0.5):
            return True
    except Exception:
        return False

def _start_server():
    global _server_proc, _start_time
    if _is_running():
        return
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / "tray_server.log"
    log_f = open(log_path, "a", encoding="utf-8", buffering=1)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    log_f.write(f"\n[{ts}] === MRD Tray: iniciando servidor ===\n")
    cmd = [_get_python(), "-m", "uvicorn", "main:app",
           "--host", "0.0.0.0", "--port", str(PORT),
           "--log-level", "warning", "--no-use-colors"]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,  # ← SIN ventana CMD
        )
        with _lock:
            _server_proc = proc
            _start_time = time.time()
        log_f.write(f"[{ts}] PID {proc.pid} — uvicorn arrancado\n")
    except Exception as e:
        log_f.write(f"[{ts}] ERROR al iniciar: {e}\n")

def _stop_server():
    global _server_proc, _start_time
    with _lock:
        proc = _server_proc
        _server_proc = None
        _start_time = None
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()

def _kill_port():
    """Mata cualquier proceso en el puerto 8000 (arranque limpio)."""
    try:
        r = subprocess.run(
            ["netstat", "-aon"],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW
        )
        for line in r.stdout.splitlines():
            if f":{PORT}" in line and "LISTENING" in line:
                parts = line.split()
                pid = int(parts[-1])
                if pid and pid != 0:
                    subprocess.run(["taskkill", "/f", "/pid", str(pid)],
                                   capture_output=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        pass

# ─── Información de estado ────────────────────────────────────────────────────
def _read_version() -> str:
    try:
        v = json.loads((BASE_DIR / "version.json").read_text(encoding="utf-8"))
        return v.get("version_actual", "—")
    except Exception:
        return "—"

def _uptime_str() -> str:
    if _start_time is None:
        return ""
    s = int(time.time() - _start_time)
    h, r = divmod(s, 3600)
    m, _ = divmod(r, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"

# ─── Acciones del menú ────────────────────────────────────────────────────────
def _open_browser(icon, _item):
    webbrowser.open(APP_URL)

def _restart_server(icon, _item):
    _stop_server()
    time.sleep(2)
    _kill_port()
    time.sleep(1)
    _start_server()
    # Esperar que levante y actualizar tooltip
    for _ in range(15):
        time.sleep(1)
        if _port_in_use():
            break
    _refresh_icon(icon)

def _open_logs(icon, _item):
    log = LOG_DIR / "tray_server.log"
    if log.exists():
        os.startfile(str(log))
    else:
        webbrowser.open(str(LOG_DIR))

def _quit_app(icon, _item):
    _stop_server()
    icon.stop()

# ─── Menú dinámico ────────────────────────────────────────────────────────────
def _status_label():
    if _is_running() or _port_in_use():
        ut = _uptime_str()
        return f"● Activo  {('(' + ut + ')') if ut else ''}  v{_read_version()}"
    return "○ Detenido"

def _build_menu():
    return Menu(
        item(_status_label, None, enabled=False),
        Menu.SEPARATOR,
        item("Abrir MRD Tool en el navegador", _open_browser, default=True),
        item("Reiniciar servidor", _restart_server),
        item("Ver logs", _open_logs),
        Menu.SEPARATOR,
        item("Salir", _quit_app),
    )

def _refresh_icon(icon):
    """Actualiza el tooltip y el menú del icono."""
    try:
        st = "Activo" if (_is_running() or _port_in_use()) else "Detenido"
        icon.title = f"MRD Tool Control — {st}"
        icon.menu = _build_menu()
    except Exception:
        pass

# ─── Watchdog en background ───────────────────────────────────────────────────
def _watchdog(icon: pystray.Icon):
    """Reinicia el servidor si se cae. Actualiza el icono periódicamente."""
    while True:
        time.sleep(15)
        try:
            with _lock:
                proc = _server_proc
            if proc is not None and proc.poll() is not None:
                # El proceso uvicorn terminó inesperadamente → reiniciar
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                log = LOG_DIR / "tray_server.log"
                with open(log, "a", encoding="utf-8") as f:
                    f.write(f"[{ts}] Watchdog: servidor caído (exit={proc.poll()}), reiniciando...\n")
                with _lock:
                    global _server_proc, _start_time
                    _server_proc = None
                    _start_time = None
                time.sleep(3)
                _start_server()
            _refresh_icon(icon)
        except Exception:
            pass

# ─── Punto de entrada ─────────────────────────────────────────────────────────
def main():
    LOG_DIR.mkdir(exist_ok=True)

    # Matar proceso previo en el puerto si existe
    if _port_in_use():
        _kill_port()
        time.sleep(2)

    # Arrancar servidor
    _start_server()

    # Crear icono de bandeja
    icon_img = _build_icon()
    tray = pystray.Icon(
        name="MRDToolControl",
        icon=icon_img,
        title="MRD Tool Control — Iniciando...",
        menu=_build_menu(),
    )

    # Watchdog en hilo daemon
    threading.Thread(target=_watchdog, args=(tray,), daemon=True, name="mrd-watchdog").start()

    # Actualizar estado inicial tras 3 s
    def _delayed_refresh():
        time.sleep(3)
        _refresh_icon(tray)
    threading.Thread(target=_delayed_refresh, daemon=True).start()

    # Bloquear en el hilo principal mostrando el icono
    tray.run()


if __name__ == "__main__":
    main()
