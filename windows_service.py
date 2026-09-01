"""
MRD TOOL CONTROL — Servicio Windows
Sprint 5.3 — Servicios de Producción
v1.9.3-alpha

Uso (como Administrador):
  python windows_service.py install    # Registrar servicio en Windows
  python windows_service.py start      # Iniciar servicio
  python windows_service.py stop       # Detener servicio
  python windows_service.py restart    # Reiniciar servicio
  python windows_service.py remove     # Desinstalar servicio
  python windows_service.py status     # Ver estado
  python windows_service.py run        # Modo standalone (sin Windows Service)
  python windows_service.py debug      # Debug interactivo (consola)

Arquitectura:
  MRDWindowsService (pywin32)
    └── MRDServiceRunner
          ├── _start_uvicorn()     → subprocess uvicorn
          ├── _watchdog_loop()     → thread que monitorea uvicorn
          └── _cleanup_loop()      → thread de limpieza diaria

Restricciones de seguridad:
  - No ejecutar comandos arbitrarios de entrada de usuario
  - No registrar contraseñas, tokens, claves ni datos personales
  - Validar rutas antes de operaciones de archivo
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# ─── Directorio base ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.resolve()

# ─── Cargar configuración YAML ────────────────────────────────────────────────
def _load_config() -> dict:
    cfg_path = BASE_DIR / "service.yaml"
    try:
        import yaml
        with open(cfg_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        # pyyaml no instalado — usar defaults
        pass
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return {}

_CFG = _load_config()

def _cfg(*keys, default=None):
    """Acceso seguro a configuración anidada."""
    node = _CFG
    for k in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(k, default)
        if node is None:
            return default
    return node


# ─── Constantes de configuración ──────────────────────────────────────────────
SERVICE_NAME         = _cfg("service", "name",         default="MRDToolControl")
SERVICE_DISPLAY      = _cfg("service", "display_name", default="MRD Tool Control")
SERVICE_DESCRIPTION  = _cfg("service", "description",  default="MRD Tool Control Production Service")

SERVER_HOST          = _cfg("server", "host",    default="0.0.0.0")
SERVER_PORT          = int(_cfg("server", "port", default=8000))
# SQLite solo soporta 1 escritor concurrente — no subir a >1 sin migrar a PostgreSQL
SERVER_WORKERS       = max(1, int(_cfg("server", "workers", default=1)))
SERVER_LOG_LEVEL     = _cfg("server", "log_level", default="warning")
SERVER_KEEPALIVE     = int(_cfg("server", "timeout_keep_alive", default=30))

WD_ENABLED           = bool(_cfg("watchdog", "enabled", default=True))
WD_INTERVAL          = int(_cfg("watchdog", "check_interval_seconds", default=10))
WD_MAX_RESTARTS      = int(_cfg("watchdog", "max_restarts", default=5))
WD_RESTART_DELAY     = int(_cfg("watchdog", "restart_delay_seconds", default=30))
WD_MEM_LIMIT_MB      = int(_cfg("watchdog", "memory_limit_mb", default=512))
WD_COOLDOWN_MIN      = int(_cfg("watchdog", "cooldown_minutes", default=5))

CLEANUP_HOUR         = int(_cfg("cleanup", "schedule_hour", default=2))
CLEANUP_TEMP_DAYS    = int(_cfg("cleanup", "temp_max_age_days", default=7))
CLEANUP_LOG_DAYS     = int(_cfg("cleanup", "log_max_age_days", default=30))
CLEANUP_CACHE_DAYS   = int(_cfg("cleanup", "cache_max_age_days", default=3))

LOG_DIR              = BASE_DIR / "logs"
LOG_MAX_MB           = int(_cfg("logging", "max_size_mb", default=10))
LOG_BACKUP_COUNT     = int(_cfg("logging", "backup_count", default=5))

# Archivo de señal para reinicio suave de uvicorn desde la API
RESTART_FLAG_FILE    = BASE_DIR / ".service_restart"
# Archivo de estado (PID y uptime del runner) para la API
STATUS_FILE          = BASE_DIR / ".service_status"


# ─── Logging estructurado del servicio ────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)

def _make_logger(name: str, filename: str) -> logging.Logger:
    logger = logging.getLogger(f"mrd_service.{name}")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    path = LOG_DIR / filename
    h = RotatingFileHandler(
        str(path),
        maxBytes=LOG_MAX_MB * 1024 * 1024,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    h.setFormatter(fmt)
    logger.addHandler(h)
    # También a consola
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger

_log_service  = _make_logger("service",  "service.log")
_log_startup  = _make_logger("startup",  "startup.log")
_log_shutdown = _make_logger("shutdown", "shutdown.log")
_log_crash    = _make_logger("crash",    "crash.log")
_log_rotation = _make_logger("rotation", "rotation.log")


def log_service(msg: str, level: str = "info"):
    getattr(_log_service, level)(msg)

def log_startup(msg: str):
    _log_startup.info(msg)

def log_shutdown(msg: str):
    _log_shutdown.info(msg)

def log_crash(msg: str):
    _log_crash.error(msg)

def log_rotation(msg: str):
    _log_rotation.info(msg)


# ─── Escritura de estado ───────────────────────────────────────────────────────
def _write_status(data: dict):
    """Escribe estado del servicio a archivo JSON para la API."""
    import json
    try:
        STATUS_FILE.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass

def _read_status() -> dict:
    """Lee estado del servicio desde archivo JSON."""
    import json
    try:
        if STATUS_FILE.exists():
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def clear_status():
    try:
        if STATUS_FILE.exists():
            STATUS_FILE.unlink()
    except Exception:
        pass


# ─── Runner del servicio ──────────────────────────────────────────────────────

class MRDServiceRunner:
    """
    Gestiona el proceso uvicorn y el watchdog interno.
    Funciona tanto dentro de MRDWindowsService (pywin32) como standalone.
    """

    def __init__(self):
        self._stop_event = threading.Event()
        self._process: Optional[subprocess.Popen] = None
        self._proc_lock = threading.Lock()
        self._restart_count = 0
        self._last_restart_window_start: Optional[float] = None
        self.start_time: Optional[float] = None
        self._pid: Optional[int] = None

    # ── Arranque ──────────────────────────────────────────────────────────────

    def run(self):
        """Punto de entrada principal. Bloquea hasta que se llame a stop()."""
        self.start_time = time.time()
        log_startup("=" * 60)
        log_startup(f"MRD TOOL CONTROL — Iniciando servicio v1.9.3-alpha")
        log_startup(f"Directorio: {BASE_DIR}")
        log_startup(f"Host: {SERVER_HOST}  Puerto: {SERVER_PORT}  Workers: {SERVER_WORKERS}")
        log_startup(f"Watchdog: {'activo' if WD_ENABLED else 'desactivado'}")
        log_startup("=" * 60)

        self._update_status_file()
        self._start_uvicorn()

        # Threads auxiliares
        if WD_ENABLED:
            threading.Thread(target=self._watchdog_loop, daemon=True, name="mrd-watchdog").start()
        threading.Thread(target=self._cleanup_loop, daemon=True, name="mrd-cleanup").start()
        threading.Thread(target=self._status_updater_loop, daemon=True, name="mrd-status").start()

        # Esperar señal de parada
        self._stop_event.wait()

        log_shutdown(f"Señal de parada recibida. Apagando uvicorn...")
        self._terminate_uvicorn()
        log_shutdown("Servicio detenido limpiamente.")
        clear_status()

    def stop(self):
        """Solicita parada del runner (llamado desde SvcStop o señal del SO)."""
        self._stop_event.set()

    # ── Gestión de uvicorn ────────────────────────────────────────────────────

    def _get_uvicorn_cmd(self) -> list[str]:
        """Construye el comando uvicorn para producción."""
        python = _find_python()
        cmd = [
            python, "-m", "uvicorn", "main:app",
            "--host",    SERVER_HOST,
            "--port",    str(SERVER_PORT),
            "--workers", str(SERVER_WORKERS),
            "--log-level", SERVER_LOG_LEVEL,
            "--access-log",
            "--no-use-colors",
            "--timeout-keep-alive", str(SERVER_KEEPALIVE),
        ]
        if _cfg("server", "proxy_headers", default=True):
            cmd.append("--proxy-headers")
            fwd = _cfg("server", "forwarded_allow_ips", default="*")
            cmd.extend(["--forwarded-allow-ips", fwd])
        return cmd

    def _start_uvicorn(self):
        """Inicia uvicorn como subproceso."""
        cmd = self._get_uvicorn_cmd()
        log_service(f"Iniciando uvicorn: {' '.join(cmd)}")
        try:
            log_dir = LOG_DIR
            stdout_log = open(log_dir / "uvicorn.log", "a", encoding="utf-8")
            with self._proc_lock:
                self._process = subprocess.Popen(
                    cmd,
                    cwd=str(BASE_DIR),
                    stdout=stdout_log,
                    stderr=subprocess.STDOUT,
                    env=_get_service_env(),
                )
                self._pid = self._process.pid
            log_service(f"Uvicorn iniciado — PID {self._pid}")
            log_startup(f"Uvicorn PID {self._pid} iniciado en {SERVER_HOST}:{SERVER_PORT}")
            self._update_status_file()
        except Exception as exc:
            log_crash(f"Error al iniciar uvicorn: {exc}")
            raise

    def _terminate_uvicorn(self):
        """Detiene uvicorn limpiamente."""
        with self._proc_lock:
            proc = self._process
        if not proc:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=30)
                log_shutdown(f"Uvicorn PID {proc.pid} terminado limpiamente.")
            except subprocess.TimeoutExpired:
                proc.kill()
                log_shutdown(f"Uvicorn PID {proc.pid} terminado forzosamente.")
        except Exception as exc:
            log_shutdown(f"Error al terminar uvicorn: {exc}")
        with self._proc_lock:
            self._process = None
            self._pid = None

    def _restart_uvicorn(self, reason: str = ""):
        """Detiene y vuelve a lanzar uvicorn."""
        log_service(f"Reiniciando uvicorn — razón: {reason or 'sin especificar'}")
        log_service(f"Fecha/hora del reinicio: {datetime.now().isoformat(timespec='seconds')}")
        self._terminate_uvicorn()
        time.sleep(2)
        self._start_uvicorn()

    # ── Watchdog ──────────────────────────────────────────────────────────────

    def _watchdog_loop(self):
        """Monitorea uvicorn y actúa ante fallos o señales de reinicio."""
        log_service("Watchdog iniciado.")
        while not self._stop_event.is_set():
            try:
                self._watchdog_tick()
            except Exception as exc:
                log_service(f"Error en watchdog: {exc}", level="warning")
            self._stop_event.wait(timeout=WD_INTERVAL)
        log_service("Watchdog detenido.")

    def _watchdog_tick(self):
        """Una iteración del watchdog."""
        # 1. Señal de reinicio desde la API
        if RESTART_FLAG_FILE.exists():
            try:
                RESTART_FLAG_FILE.unlink()
            except Exception:
                pass
            log_service("Señal de reinicio recibida desde API.")
            self._restart_uvicorn("restart_api")
            return

        # 2. ¿Uvicorn sigue vivo?
        with self._proc_lock:
            proc = self._process
        if proc is None:
            return

        exit_code = proc.poll()
        if exit_code is not None:
            # Proceso terminó de forma inesperada
            log_crash(f"Uvicorn terminó inesperadamente — exit_code={exit_code} — {datetime.now().isoformat()}")
            self._handle_unexpected_exit(exit_code)
            return

        # 3. Control de uso de RAM
        self._check_memory_usage(proc)

    def _handle_unexpected_exit(self, exit_code: int):
        """Gestiona la caída de uvicorn, respetando límite de reinicios."""
        now = time.time()

        # Resetear contador si han pasado más de WD_COOLDOWN_MIN minutos
        if self._last_restart_window_start and \
                (now - self._last_restart_window_start) > (WD_COOLDOWN_MIN * 60):
            self._restart_count = 0
            self._last_restart_window_start = None

        self._restart_count += 1
        if self._last_restart_window_start is None:
            self._last_restart_window_start = now

        log_service(f"Intento de reinicio {self._restart_count}/{WD_MAX_RESTARTS}")

        if self._restart_count > WD_MAX_RESTARTS:
            log_crash(
                f"Demasiados reinicios ({self._restart_count}). "
                "Deteniendo servicio para que Windows Recovery actúe."
            )
            self._stop_event.set()
            return

        log_service(f"Esperando {WD_RESTART_DELAY} s antes de reiniciar...")
        self._stop_event.wait(timeout=WD_RESTART_DELAY)
        if not self._stop_event.is_set():
            self._start_uvicorn()

    def _check_memory_usage(self, proc: subprocess.Popen):
        """Alerta (y reinicia si es crítico) ante uso excesivo de RAM."""
        try:
            import psutil
            try:
                p = psutil.Process(proc.pid)
                mem_mb = p.memory_info().rss / (1024 ** 2)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return

            if mem_mb > WD_MEM_LIMIT_MB * 2:
                # RAM crítica: más del doble del límite → reiniciar
                log_crash(f"RAM crítica: {mem_mb:.0f} MB (límite {WD_MEM_LIMIT_MB * 2} MB). Reiniciando.")
                self._restart_uvicorn(f"memoria_critica_{mem_mb:.0f}mb")
            elif mem_mb > WD_MEM_LIMIT_MB:
                log_service(f"Alerta RAM: {mem_mb:.0f} MB (límite {WD_MEM_LIMIT_MB} MB)", level="warning")
        except ImportError:
            pass  # psutil no disponible

    # ── Limpieza automática ───────────────────────────────────────────────────

    def _cleanup_loop(self):
        """Ejecuta limpieza diaria a la hora configurada (CLEANUP_HOUR)."""
        log_service(f"Loop de limpieza iniciado — ejecución diaria a las {CLEANUP_HOUR:02d}:00")
        while not self._stop_event.is_set():
            now = datetime.now()
            # Calcular próxima ejecución
            next_run = now.replace(hour=CLEANUP_HOUR, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            wait_secs = (next_run - now).total_seconds()
            log_rotation(f"Próxima limpieza: {next_run.strftime('%Y-%m-%d %H:%M')}")
            self._stop_event.wait(timeout=wait_secs)
            if not self._stop_event.is_set():
                self._run_cleanup()

    def _run_cleanup(self):
        """Limpia archivos temporales, caché y logs antiguos."""
        log_rotation(f"=== Inicio de limpieza automática {datetime.now().isoformat(timespec='seconds')} ===")
        total_removed = 0

        # Directorios seguros para limpiar — NUNCA backups, data, uploads, config
        safe_dirs = [
            (BASE_DIR / "temp",  CLEANUP_TEMP_DAYS,  "temp"),
            (BASE_DIR / "cache", CLEANUP_CACHE_DAYS, "cache"),
        ]

        now = datetime.now()
        for dirpath, max_days, label in safe_dirs:
            if not dirpath.exists():
                continue
            cutoff = now - timedelta(days=max_days)
            removed = 0
            for f in dirpath.rglob("*"):
                if f.is_file():
                    try:
                        mtime = datetime.fromtimestamp(f.stat().st_mtime)
                        if mtime < cutoff:
                            f.unlink()
                            removed += 1
                    except Exception:
                        pass
            if removed:
                log_rotation(f"  {label}: eliminados {removed} archivos (>{max_days} días)")
            total_removed += removed

        # Rotar logs antiguos
        log_cutoff = now - timedelta(days=CLEANUP_LOG_DAYS)
        rotated = 0
        for f in LOG_DIR.glob("*.log.*"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if mtime < log_cutoff:
                    f.unlink()
                    rotated += 1
            except Exception:
                pass
        if rotated:
            log_rotation(f"  logs: eliminados {rotated} archivos de rotación antiguos")

        # Limpiar archivos .tmp sueltos en la raíz del proyecto
        for f in BASE_DIR.glob("*.tmp"):
            try:
                f.unlink()
            except Exception:
                pass

        log_rotation(f"=== Limpieza completada — {total_removed + rotated} archivos eliminados ===")

    # ── Estado ────────────────────────────────────────────────────────────────

    def _status_updater_loop(self):
        """Actualiza el archivo de estado cada 30 s para que la API lo lea."""
        while not self._stop_event.is_set():
            self._update_status_file()
            self._stop_event.wait(timeout=30)

    def _update_status_file(self):
        uptime = int(time.time() - self.start_time) if self.start_time else 0
        data = {
            "status": "running",
            "pid": self._pid,
            "uptime_seconds": uptime,
            "port": SERVER_PORT,
            "host": SERVER_HOST,
            "workers": SERVER_WORKERS,
            "restart_count": self._restart_count,
            "start_time": datetime.fromtimestamp(self.start_time).isoformat(timespec="seconds")
            if self.start_time else None,
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "version": "1.9.3-alpha",
        }
        _write_status(data)


# ─── Utilidades ───────────────────────────────────────────────────────────────

def _find_python() -> str:
    """Localiza el ejecutable Python del venv o del sistema."""
    candidates = [
        BASE_DIR / "venv" / "Scripts" / "python.exe",    # Windows venv
        BASE_DIR / "venv" / "bin" / "python",             # Linux venv
        BASE_DIR / ".venv" / "Scripts" / "python.exe",
        BASE_DIR / ".venv" / "bin" / "python",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return sys.executable  # fallback: Python actual


def _get_service_env() -> dict:
    """Variables de entorno para el proceso uvicorn — sin secretos en el ambiente."""
    env = os.environ.copy()
    env.setdefault("MRD_ENV", "production")
    # Cargar desde archivo de config si existe
    config_env = BASE_DIR / "config" / "local.env"
    if config_env.exists():
        try:
            for line in config_env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    env.setdefault(key.strip(), val.strip())
        except Exception:
            pass
    return env


# ─── Modo standalone (sin Windows Service) ───────────────────────────────────

def run_standalone():
    """Arranca el runner directamente en la consola (desarrollo / fallback)."""
    import signal
    runner = MRDServiceRunner()

    def _handle_signal(sig, _frame):
        log_service(f"Señal {sig} recibida — deteniendo...")
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

    class MRDWindowsService(win32serviceutil.ServiceFramework):
        _svc_name_         = SERVICE_NAME
        _svc_display_name_ = SERVICE_DISPLAY
        _svc_description_  = SERVICE_DESCRIPTION

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self._stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._runner = MRDServiceRunner()

        def SvcStop(self):
            """Llamado por el SCM para detener el servicio."""
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            servicemanager.LogInfoMsg(f"{SERVICE_NAME}: Solicitud de parada recibida.")
            win32event.SetEvent(self._stop_event)
            self._runner.stop()

        def SvcDoRun(self):
            """Punto de entrada del servicio Windows."""
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            try:
                self._runner.run()
            except Exception as exc:
                log_crash(f"Excepción crítica en SvcDoRun: {exc}")
                servicemanager.LogErrorMsg(f"{SERVICE_NAME}: {exc}")
            finally:
                win32event.SetEvent(self._stop_event)

    WINDOWS_SERVICE_AVAILABLE = True

except ImportError:
    WINDOWS_SERVICE_AVAILABLE = False
    MRDWindowsService = None  # type: ignore


# ─── CLI principal ────────────────────────────────────────────────────────────

def _print_status():
    """Muestra estado del servicio en consola."""
    import json

    # Estado del servicio Windows
    if WINDOWS_SERVICE_AVAILABLE:
        try:
            status = win32serviceutil.QueryServiceStatus(SERVICE_NAME)
            svc_state = {1: "STOPPED", 2: "START_PENDING", 3: "STOP_PENDING",
                        4: "RUNNING", 5: "CONTINUE_PENDING", 6: "PAUSE_PENDING",
                        7: "PAUSED"}.get(status[1], "UNKNOWN")
            print(f"  Servicio Windows: {svc_state}")
        except Exception:
            print("  Servicio Windows: no instalado")

    # Estado del runner desde archivo
    data = _read_status()
    if data:
        uptime = data.get("uptime_seconds", 0)
        h, rem = divmod(uptime, 3600)
        m, s = divmod(rem, 60)
        print(f"  Estado runner:    {data.get('status', '?')}")
        print(f"  PID uvicorn:      {data.get('pid', 'N/A')}")
        print(f"  Uptime:           {h}h {m}m {s}s")
        print(f"  Puerto:           {data.get('port', 'N/A')}")
        print(f"  Versión:          {data.get('version', 'N/A')}")
        print(f"  Reinicios:        {data.get('restart_count', 0)}")
    else:
        print("  Runner: sin datos (¿servicio detenido?)")


if __name__ == "__main__":
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else ""

    if cmd == "run":
        # Modo standalone — útil en desarrollo o si pywin32 no está disponible
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
        win32serviceutil.HandleCommandLine(MRDWindowsService)

    else:
        print(f"""
MRD TOOL CONTROL — Servicio Windows v1.9.3-alpha
Uso: python windows_service.py <comando>

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
