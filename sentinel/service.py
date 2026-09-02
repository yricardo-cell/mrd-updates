"""MRD Sentinel — Servicio Windows.

Registra sentinel.app:create_app (uvicorn, factory) como servicio SCM real
'MRDSentinel', siguiendo el mismo patron subprocess+watchdog que
windows_service.py usa para el servicio principal MRDToolControl.

Standalone a proposito (ver sentinel/__init__.py): no importa windows_service.py
ni ningun modulo de la app principal.

Uso (como Administrador):
  python -m sentinel.service install    # Registrar servicio en Windows
  python -m sentinel.service start      # Iniciar servicio
  python -m sentinel.service stop       # Detener servicio
  python -m sentinel.service restart    # Reiniciar servicio
  python -m sentinel.service remove     # Desinstalar servicio
  python -m sentinel.service status     # Ver estado
  python -m sentinel.service run        # Modo standalone (sin Windows Service)
  python -m sentinel.service debug      # Debug interactivo (consola)
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

SENTINEL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SENTINEL_ROOT.parent
LOG_DIR = SENTINEL_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Cuando pywin32 arranca este archivo directamente (no via "python -m"), solo
# SENTINEL_ROOT queda en sys.path, no REPO_ROOT — sin esto "from sentinel.X
# import Y" fallaria al arrancar como servicio real.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SERVICE_NAME = "MRDSentinel"
SERVICE_DISPLAY = "MRD Sentinel"
SERVICE_DESCRIPTION = (
    "Centro de recuperacion independiente de MRD Tool Control: panel de "
    "estado/historial de failover y proxy de emergencia hacia las apps vigiladas."
)

WD_INTERVAL_SECONDS = 10
WD_MAX_RESTARTS = 5
WD_RESTART_DELAY_SECONDS = 15
WD_COOLDOWN_MINUTES = 5


def _make_logger(name: str, filename: str) -> logging.Logger:
    logger = logging.getLogger(f"sentinel_service.{name}")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        str(LOG_DIR / filename), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
    )
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)
    return logger


_log_service = _make_logger("service", "service.log")
_log_crash = _make_logger("crash", "crash.log")


def _find_python() -> str:
    candidates = [
        REPO_ROOT / "venv" / "Scripts" / "python.exe",
        REPO_ROOT / "venv" / "bin" / "python",
        REPO_ROOT / ".venv" / "Scripts" / "python.exe",
        REPO_ROOT / ".venv" / "bin" / "python",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return sys.executable


def _get_host_port() -> tuple[str, int]:
    from sentinel.config import load_config
    cfg = load_config()
    return cfg.host, cfg.port


class SentinelRunner:
    """Gestiona el proceso uvicorn de Sentinel y su watchdog. Funciona tanto
    dentro de MRDSentinelWindowsService (pywin32) como en modo standalone."""

    def __init__(self):
        self._stop_event = threading.Event()
        self._process: Optional[subprocess.Popen] = None
        self._proc_lock = threading.Lock()
        self._restart_count = 0
        self._last_restart_window_start: Optional[float] = None

    def run(self) -> None:
        _log_service.info("=" * 60)
        _log_service.info("MRD SENTINEL — Iniciando servicio")
        _log_service.info("Directorio: %s", REPO_ROOT)
        _log_service.info("=" * 60)

        self._start_uvicorn()
        threading.Thread(target=self._watchdog_loop, daemon=True, name="sentinel-watchdog").start()

        self._stop_event.wait()
        _log_service.info("Señal de parada recibida. Apagando uvicorn...")
        self._terminate_uvicorn()
        _log_service.info("Servicio detenido limpiamente.")

    def stop(self) -> None:
        self._stop_event.set()

    def _get_uvicorn_cmd(self) -> list[str]:
        python = _find_python()
        host, port = _get_host_port()
        return [
            python, "-m", "uvicorn", "sentinel.app:create_app", "--factory",
            "--host", host, "--port", str(port),
            "--log-level", "warning", "--no-use-colors",
        ]

    def _start_uvicorn(self) -> None:
        cmd = self._get_uvicorn_cmd()
        _log_service.info("Iniciando uvicorn: %s", " ".join(cmd))
        try:
            stdout_log = open(LOG_DIR / "uvicorn.log", "a", encoding="utf-8")
            with self._proc_lock:
                self._process = subprocess.Popen(
                    cmd, cwd=str(REPO_ROOT), stdout=stdout_log, stderr=subprocess.STDOUT,
                )
            _log_service.info("Uvicorn iniciado — PID %s", self._process.pid)
        except Exception as exc:
            _log_crash.error("Error al iniciar uvicorn: %s", exc)
            raise

    def _terminate_uvicorn(self) -> None:
        with self._proc_lock:
            proc = self._process
        if not proc:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception as exc:
            _log_service.warning("Error al terminar uvicorn: %s", exc)
        with self._proc_lock:
            self._process = None

    def _restart_uvicorn(self, reason: str) -> None:
        _log_service.warning("Reiniciando uvicorn — razón: %s", reason)
        self._terminate_uvicorn()
        time.sleep(2)
        self._start_uvicorn()

    def _watchdog_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._watchdog_tick()
            except Exception as exc:
                _log_service.warning("Error en watchdog: %s", exc)
            self._stop_event.wait(timeout=WD_INTERVAL_SECONDS)

    def _watchdog_tick(self) -> None:
        with self._proc_lock:
            proc = self._process
        if proc is None:
            return
        exit_code = proc.poll()
        if exit_code is None:
            return
        _log_crash.error("Uvicorn terminó inesperadamente — exit_code=%s", exit_code)
        self._handle_unexpected_exit()

    def _handle_unexpected_exit(self) -> None:
        now = time.time()
        if self._last_restart_window_start and \
                (now - self._last_restart_window_start) > (WD_COOLDOWN_MINUTES * 60):
            self._restart_count = 0
            self._last_restart_window_start = None

        self._restart_count += 1
        if self._last_restart_window_start is None:
            self._last_restart_window_start = now

        if self._restart_count > WD_MAX_RESTARTS:
            _log_crash.error(
                "Demasiados reinicios (%s). Deteniendo servicio para que "
                "Windows Recovery actúe.", self._restart_count,
            )
            self._stop_event.set()
            return

        self._stop_event.wait(timeout=WD_RESTART_DELAY_SECONDS)
        if not self._stop_event.is_set():
            self._start_uvicorn()


# ─── Modo standalone (sin Windows Service) ───────────────────────────────────

def run_standalone() -> None:
    import signal
    runner = SentinelRunner()

    def _handle_signal(sig, _frame):
        runner.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    runner.run()


# ─── Windows Service (pywin32) ────────────────────────────────────────────────

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager

    class MRDSentinelWindowsService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = SERVICE_DISPLAY
        _svc_description_ = SERVICE_DESCRIPTION

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self._stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._runner = SentinelRunner()

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            servicemanager.LogInfoMsg(f"{SERVICE_NAME}: Solicitud de parada recibida.")
            self._runner.stop()
            win32event.SetEvent(self._stop_event)

        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            try:
                self._runner.run()
            except Exception as exc:
                servicemanager.LogErrorMsg(f"{SERVICE_NAME}: excepción crítica: {exc}")
            finally:
                win32event.SetEvent(self._stop_event)

    WINDOWS_SERVICE_AVAILABLE = True

except ImportError:
    WINDOWS_SERVICE_AVAILABLE = False
    MRDSentinelWindowsService = None  # type: ignore


# ─── CLI principal ────────────────────────────────────────────────────────────

def _print_status() -> None:
    if WINDOWS_SERVICE_AVAILABLE:
        try:
            status = win32serviceutil.QueryServiceStatus(SERVICE_NAME)
            svc_state = {1: "STOPPED", 2: "START_PENDING", 3: "STOP_PENDING",
                        4: "RUNNING", 5: "CONTINUE_PENDING", 6: "PAUSE_PENDING",
                        7: "PAUSED"}.get(status[1], "UNKNOWN")
            print(f"  Servicio Windows: {svc_state}")
        except Exception:
            print("  Servicio Windows: no instalado")
    else:
        print("  pywin32 no disponible en este intérprete.")


if __name__ == "__main__":
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else ""

    if cmd == "run":
        print(f"Iniciando {SERVICE_NAME} en modo standalone...")
        run_standalone()

    elif cmd == "status":
        print(f"\n{SERVICE_NAME} — Estado:")
        _print_status()

    elif cmd in ("install", "update", "remove", "start", "stop",
                 "restart", "debug", "queryex"):
        if not WINDOWS_SERVICE_AVAILABLE:
            print("ERROR: pywin32 no instalado. Instala con: pip install pywin32")
            sys.exit(1)
        win32serviceutil.HandleCommandLine(MRDSentinelWindowsService)

    else:
        print(f"""
MRD SENTINEL — Servicio Windows
Uso: python -m sentinel.service <comando>

Comandos:
  install    Registrar el servicio en Windows (requiere admin)
  start      Iniciar el servicio
  stop       Detener el servicio
  restart    Reiniciar el servicio
  remove     Desinstalar el servicio
  status     Ver estado actual
  run        Modo standalone (sin Windows Service)
  debug      Modo debug interactivo
""")
        sys.exit(1)
