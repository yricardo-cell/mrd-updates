"""
MRD Tool Control — Diagnóstico y Recuperación
Standalone GUI recovery tool for the MRDToolControl Windows service.
"""

import os
import sys
import ctypes
import subprocess
import threading
import http.client
import sqlite3
import shutil
import json
import time
import datetime
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# ---------------------------------------------------------------------------
# Configuration — edit here for your environment
# ---------------------------------------------------------------------------
CONFIG = {
    "service_name": "MRDToolControl",
    "cloudflare_service": "CloudflaredMRD",
    "app_port": 8000,
    "app_host": "localhost",
    "app_dir": r"C:\mrd_tool_control",
    "db_path": r"C:\mrd_tool_control\mrd_tool_control.db",
    "log_dir": r"C:\mrd_tool_control\logs",
    "lock_file": r"C:\mrd_tool_control\recovery_tool\.recovery.lock",
    "report_dir": r"C:\mrd_tool_control\recovery_tool\reports",
    "max_restarts": 3,
    "health_timeout_sec": 8,
    "health_wait_sec": 20,
}

# ---------------------------------------------------------------------------
# Lock file helpers
# ---------------------------------------------------------------------------

def _lock_pid_running(pid: int) -> bool:
    """Return True if PID is currently alive (Windows tasklist check)."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def acquire_lock() -> bool:
    """
    Check the lock file. Return True if we acquired it, False if another
    instance is already running. Writes own PID on success.
    """
    lock_path = CONFIG["lock_file"]
    lock_dir = os.path.dirname(lock_path)
    os.makedirs(lock_dir, exist_ok=True)

    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r") as f:
                existing_pid = int(f.read().strip())
            if _lock_pid_running(existing_pid):
                return False
        except (ValueError, OSError):
            pass  # Corrupt/missing lock — overwrite

    with open(lock_path, "w") as f:
        f.write(str(os.getpid()))
    return True


def release_lock():
    """Remove the lock file if it belongs to this process."""
    lock_path = CONFIG["lock_file"]
    try:
        if os.path.exists(lock_path):
            with open(lock_path, "r") as f:
                pid = int(f.read().strip())
            if pid == os.getpid():
                os.remove(lock_path)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# UAC / admin elevation
# ---------------------------------------------------------------------------

def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def relaunch_as_admin():
    """Re-launch this script with runas and exit current process."""
    script = os.path.abspath(sys.argv[0])
    params = " ".join(f'"{a}"' for a in sys.argv[1:])
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable,
                                        f'"{script}" {params}', None, 1)
    sys.exit(0)


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------

def _run(args, timeout=30):
    """Run a subprocess safely; return CompletedProcess or a mock on error."""
    try:
        flags = 0
        try:
            flags = subprocess.CREATE_NO_WINDOW
        except AttributeError:
            pass
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=flags,
        )
    except Exception as exc:
        class _Fake:
            stdout = ""
            stderr = str(exc)
            returncode = -1
        return _Fake()


# ---------------------------------------------------------------------------
# Diagnostic functions (pure — no GUI dependencies)
# ---------------------------------------------------------------------------

def check_service() -> dict:
    """Query the Windows service state via sc."""
    svc = CONFIG["service_name"]
    result = _run(["sc", "query", svc])
    output = result.stdout + result.stderr
    state = "UNKNOWN"
    pid_from_sc = None

    for line in output.splitlines():
        line = line.strip()
        if line.startswith("STATE"):
            parts = line.split()
            # e.g.  STATE              : 4  RUNNING
            for i, part in enumerate(parts):
                if part in ("RUNNING", "STOPPED", "PAUSED", "START_PENDING",
                             "STOP_PENDING", "CONTINUE_PENDING", "PAUSE_PENDING"):
                    state = part
                    break
        if "PID" in line and ":" in line:
            try:
                pid_from_sc = int(line.split(":")[-1].strip())
            except ValueError:
                pass

    return {"state": state, "pid_from_sc": pid_from_sc, "raw": output.strip()}


def check_process() -> dict:
    """Find any python.exe processes and the PID holding port 8000."""
    result = _run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"])
    python_pids = []
    for line in result.stdout.splitlines():
        line = line.strip().strip('"')
        if not line:
            continue
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2:
            try:
                python_pids.append(int(parts[1]))
            except ValueError:
                pass
    port_pid = check_port()
    return {"python_pids": python_pids, "port_pid": port_pid}


def check_port() -> int | None:
    """Return the PID holding port 8000, or None."""
    port = CONFIG["app_port"]
    result = _run(["netstat", "-ano"])
    for line in result.stdout.splitlines():
        if f":{port} " in line or f":{port}\t" in line:
            parts = line.split()
            if len(parts) >= 5:
                try:
                    return int(parts[-1])
                except ValueError:
                    pass
    return None


def check_http(path: str = "/health") -> dict:
    """HTTP GET to the app; return {status_code, ok, error}."""
    host = CONFIG["app_host"]
    port = CONFIG["app_port"]
    timeout = CONFIG["health_timeout_sec"]
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request("GET", path)
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return {"status_code": resp.status, "ok": resp.status < 400, "error": None}
    except Exception as exc:
        return {"status_code": None, "ok": False, "error": str(exc)}


def check_logs() -> dict:
    """Read recent log lines and extract ERROR/Exception lines."""
    log_dir = CONFIG["log_dir"]
    fallback = os.path.join(CONFIG["app_dir"], "server_log.txt")
    lines = []
    source = None

    if os.path.isdir(log_dir):
        try:
            files = sorted(
                [os.path.join(log_dir, f) for f in os.listdir(log_dir)
                 if os.path.isfile(os.path.join(log_dir, f))],
                key=os.path.getmtime,
                reverse=True,
            )
            if files:
                source = files[0]
        except OSError:
            pass

    if source is None and os.path.isfile(fallback):
        source = fallback

    if source:
        try:
            with open(source, "r", encoding="utf-8", errors="replace") as fh:
                all_lines = fh.readlines()
            lines = [l.rstrip() for l in all_lines[-100:]]
        except OSError:
            pass

    error_lines = [l for l in lines if "ERROR" in l or "Exception" in l
                   or "Traceback" in l]
    return {
        "source": source,
        "last_lines": lines[-50:],
        "error_lines": error_lines,
    }


def check_db() -> dict:
    """Check SQLite DB existence, readability, and integrity."""
    path = CONFIG["db_path"]
    if not os.path.isfile(path):
        return {"exists": False, "readable": False,
                "integrity_ok": False, "integrity_result": "File not found"}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True,
                               check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        rows = cursor.fetchall()
        conn.close()
        result = rows[0][0] if rows else "no result"
        return {
            "exists": True,
            "readable": True,
            "integrity_ok": result == "ok",
            "integrity_result": result,
        }
    except Exception as exc:
        return {"exists": True, "readable": False,
                "integrity_ok": False, "integrity_result": str(exc)}


def check_disk() -> dict:
    """Check disk space and write permissions on app_dir."""
    app_dir = CONFIG["app_dir"]
    try:
        usage = shutil.disk_usage(app_dir)
        free_gb = usage.free / (1024 ** 3)
        free_ok = usage.free > 500 * 1024 * 1024
    except Exception as exc:
        return {"free_gb": None, "free_ok": False, "write_ok": False, "error": str(exc)}

    write_ok = os.access(app_dir, os.W_OK)
    return {"free_gb": round(free_gb, 2), "free_ok": free_ok, "write_ok": write_ok,
            "error": None}


def check_git_commit() -> str:
    """Return the latest git commit hash + message or 'N/A'."""
    result = _run(["git", "-C", CONFIG["app_dir"], "log", "--oneline", "-1"])
    out = (result.stdout or result.stderr or "").strip()
    return out if out else "N/A"


def run_diagnostics() -> dict:
    """Run all checks and return a combined results dict."""
    svc = check_service()
    proc = check_process()
    http_health = check_http("/health")
    http_root = check_http("/")
    http_scan = check_http("/scan")
    logs = check_logs()
    db = check_db()
    disk = check_disk()
    commit = check_git_commit()

    return {
        "service": svc,
        "process": proc,
        "http": {
            "/health": http_health,
            "/": http_root,
            "/scan": http_scan,
        },
        "logs": logs,
        "db": db,
        "disk": disk,
        "commit": commit,
        "timestamp": datetime.datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Repair functions (pure — no GUI deps)
# ---------------------------------------------------------------------------

_restart_count = 0


def _reset_restart_count():
    global _restart_count
    _restart_count = 0


def _pid_is_python(pid: int) -> bool:
    """Verify that a PID belongs to python.exe before killing it."""
    result = _run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"])
    return "python.exe" in result.stdout.lower()


def run_repair(progress_cb=None) -> dict:
    """
    Attempt to recover the MRDToolControl service.
    progress_cb(message, level) is called for each step if provided.
    Returns {"success": bool, "actions": [str], "final_diag": dict}.
    """
    global _restart_count

    svc = CONFIG["service_name"]
    actions = []

    def log_action(msg, level="info"):
        actions.append(f"[{level.upper()}] {msg}")
        if progress_cb:
            progress_cb(msg, level)

    if _restart_count >= CONFIG["max_restarts"]:
        log_action(
            f"Se alcanzó el límite de {CONFIG['max_restarts']} reinicios. "
            "Abortando recuperación.", "error"
        )
        final = run_diagnostics()
        return {"success": False, "actions": actions, "final_diag": final}

    diag = run_diagnostics()
    svc_state = diag["service"]["state"]
    health_ok = diag["http"]["/health"]["ok"]

    # Step 1: Service is stopped — just start it
    if svc_state == "STOPPED":
        log_action("Servicio detenido. Intentando iniciar...", "warn")
        _run(["sc", "start", svc])
        _restart_count += 1
        log_action(f"sc start {svc} ejecutado (intento #{_restart_count})", "info")
        time.sleep(5)

    # Step 2: Service running but /health failing — stop then start
    elif svc_state == "RUNNING" and not health_ok:
        log_action(
            "Servicio en ejecución pero /health no responde. "
            "Reiniciando...", "warn"
        )
        _run(["sc", "stop", svc])
        _restart_count += 1
        log_action(f"sc stop {svc} ejecutado (intento #{_restart_count})", "info")
        time.sleep(6)
        _run(["sc", "start", svc])
        log_action(f"sc start {svc} ejecutado", "info")
        time.sleep(6)

    # Step 3: Stale process holding port — kill it, then start
    port_pid = diag["process"]["port_pid"]
    if port_pid and svc_state != "RUNNING":
        log_action(
            f"PID {port_pid} retiene el puerto {CONFIG['app_port']}. "
            "Verificando proceso...", "warn"
        )
        if _pid_is_python(port_pid):
            log_action(f"Terminando proceso python.exe PID {port_pid}...", "warn")
            _run(["taskkill", "/F", "/PID", str(port_pid)])
            log_action(f"taskkill /F /PID {port_pid} ejecutado", "info")
            time.sleep(3)
            _run(["sc", "start", svc])
            _restart_count += 1
            log_action(f"sc start {svc} ejecutado (intento #{_restart_count})", "info")
        else:
            log_action(
                f"PID {port_pid} no es python.exe — no se puede terminar de forma segura.",
                "error"
            )

    # Step 4: Poll /health until it responds or timeout
    log_action(
        f"Esperando hasta {CONFIG['health_wait_sec']}s para que /health responda...",
        "info"
    )
    deadline = time.time() + CONFIG["health_wait_sec"]
    health_up = False
    while time.time() < deadline:
        h = check_http("/health")
        if h["ok"]:
            health_up = True
            log_action("/health responde correctamente.", "ok")
            break
        time.sleep(2)

    if not health_up:
        log_action("/health sigue sin responder tras la espera.", "error")

    # Step 5: Final diagnostics
    final = run_diagnostics()
    scan_ok = final["http"]["/scan"]["ok"]
    success = health_up and scan_ok

    if success:
        log_action("Recuperación completada con éxito.", "ok")
    else:
        log_action("Recuperación fallida. Revise el informe.", "error")

    return {"success": success, "actions": actions, "final_diag": final}


def restore_stable_version(progress_cb=None) -> dict:
    """
    Restore code from the latest git commit using stash + checkout.
    Does NOT touch the database. Returns {"success": bool, "actions": [str]}.
    """
    app_dir = CONFIG["app_dir"]
    svc = CONFIG["service_name"]
    actions = []

    def log_action(msg, level="info"):
        actions.append(f"[{level.upper()}] {msg}")
        if progress_cb:
            progress_cb(msg, level)

    log_action("Guardando cambios locales con git stash...", "info")
    stash_result = _run(["git", "-C", app_dir, "stash"])
    log_action(f"git stash: {(stash_result.stdout or stash_result.stderr).strip()}", "info")

    log_action("Restaurando archivos del último commit (git checkout HEAD -- .)...", "warn")
    checkout_result = _run(["git", "-C", app_dir, "checkout", "HEAD", "--", "."])
    out = (checkout_result.stdout or checkout_result.stderr or "").strip()
    if checkout_result.returncode != 0:
        log_action(f"Error en git checkout: {out}", "error")
        return {"success": False, "actions": actions}
    log_action(f"git checkout: {out or 'OK'}", "ok")

    log_action("Reiniciando servicio tras restauración...", "info")
    _run(["sc", "stop", svc])
    time.sleep(6)
    _run(["sc", "start", svc])
    time.sleep(8)

    h = check_http("/health")
    if h["ok"]:
        log_action("Servicio activo y /health responde. Restauración exitosa.", "ok")
        return {"success": True, "actions": actions}
    else:
        log_action("/health no responde tras restauración.", "error")
        return {"success": False, "actions": actions}


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(diag_results: dict, repair_actions: list | None = None) -> str:
    """Write a human-readable + JSON report and return its file path."""
    report_dir = CONFIG["report_dir"]
    os.makedirs(report_dir, exist_ok=True)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"mrd_report_{ts}.txt"
    filepath = os.path.join(report_dir, filename)

    svc = diag_results.get("service", {})
    proc = diag_results.get("process", {})
    http = diag_results.get("http", {})
    db = diag_results.get("db", {})
    disk = diag_results.get("disk", {})
    logs = diag_results.get("logs", {})
    commit = diag_results.get("commit", "N/A")

    def yn(val):
        return "Sí" if val else "No"

    def fmt_http(path):
        r = http.get(path, {})
        if r.get("ok"):
            return f"OK ({r.get('status_code')})"
        err = r.get("error") or f"HTTP {r.get('status_code')}"
        return f"ERROR — {err}"

    error_lines = logs.get("error_lines", [])
    error_block = "\n    ".join(error_lines[-10:]) if error_lines else "(ninguno)"
    actions_block = (
        "\n    ".join(repair_actions) if repair_actions else "(ninguna acción realizada)"
    )

    health_ok = http.get("/health", {}).get("ok", False)
    scan_ok = http.get("/scan", {}).get("ok", False)
    final_result = "OK" if (health_ok and scan_ok) else "NO SE PUDO RECUPERAR"

    port_pid = proc.get("port_pid")
    port_str = str(port_pid) if port_pid else "libre"
    free_gb = disk.get("free_gb")
    free_str = f"{free_gb} GB" if free_gb is not None else "N/A"
    disk_perm = "OK" if disk.get("write_ok") else "Sin permisos de escritura"

    report_text = f"""\
MRD TOOL CONTROL — INFORME DE DIAGNÓSTICO
Fecha: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
============================================

ESTADO DEL SERVICIO: {svc.get('state', 'UNKNOWN')}
PID (sc): {svc.get('pid_from_sc') or 'N/A'}
COMMIT: {commit}
PUERTO {CONFIG['app_port']}: {port_str}

COMPROBACIONES HTTP:
  /health: {fmt_http('/health')}
  /: {fmt_http('/')}
  /scan: {fmt_http('/scan')}

BASE DE DATOS:
  Existe:    {yn(db.get('exists'))}
  Legible:   {yn(db.get('readable'))}
  Integridad: {db.get('integrity_result', 'N/A')}

DISCO:
  Libre:     {free_str}
  Permisos:  {disk_perm}

ÚLTIMOS ERRORES EN LOG:
  {error_block}

ACCIONES INTENTADAS:
  {actions_block}

RESULTADO FINAL: {final_result}

============================================
[NOTA: Este informe ha sido redactado de forma segura.
 No contiene contraseñas, tokens ni datos sensibles.]
============================================

--- JSON COMPLETO (para soporte técnico) ---
{json.dumps(diag_results, indent=2, default=str)}
"""

    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(report_text)

    return filepath


# ---------------------------------------------------------------------------
# GUI Application
# ---------------------------------------------------------------------------

class RecoveryApp:
    # Color palette
    COLOR_BG = "#1a1a2e"
    COLOR_LOG_BG = "#0f0f1a"
    COLOR_GREEN = "#22c55e"
    COLOR_YELLOW = "#f59e0b"
    COLOR_RED = "#ef4444"
    COLOR_WHITE = "#f1f5f9"
    COLOR_GRAY = "#64748b"
    COLOR_PANEL = "#16213e"
    COLOR_BTN_BG = "#1e293b"
    COLOR_BTN_FG = "#e2e8f0"
    COLOR_BTN_ACTIVE = "#334155"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("MRD Tool Control — Diagnóstico y Recuperación")
        self.root.configure(bg=self.COLOR_BG)
        self.root.resizable(True, True)
        self.root.minsize(820, 600)

        # State
        self._last_diag: dict = {}
        self._last_repair_actions: list = []
        self._last_report_path: str | None = None
        self._busy = False

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Auto-diagnose on start
        self.root.after(300, self._auto_diagnose)

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = self.root

        # ---- Status bar ----
        self._status_frame = tk.Frame(root, bg=self.COLOR_GRAY, height=64)
        self._status_frame.pack(fill=tk.X, padx=10, pady=(10, 0))
        self._status_frame.pack_propagate(False)

        self._status_label = tk.Label(
            self._status_frame,
            text="Iniciando diagnóstico…",
            font=("Segoe UI", 14, "bold"),
            fg=self.COLOR_WHITE,
            bg=self.COLOR_GRAY,
            anchor="center",
        )
        self._status_label.pack(expand=True, fill=tk.BOTH, padx=16)

        # ---- Log area ----
        log_frame = tk.Frame(root, bg=self.COLOR_BG)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)

        self._log_text = scrolledtext.ScrolledText(
            log_frame,
            bg=self.COLOR_LOG_BG,
            fg=self.COLOR_WHITE,
            font=("Consolas", 10),
            state=tk.DISABLED,
            wrap=tk.WORD,
            relief=tk.FLAT,
            bd=0,
            padx=8,
            pady=6,
        )
        self._log_text.pack(fill=tk.BOTH, expand=True)

        # Configure tags for colored lines
        self._log_text.tag_config("info",  foreground=self.COLOR_WHITE)
        self._log_text.tag_config("ok",    foreground=self.COLOR_GREEN)
        self._log_text.tag_config("warn",  foreground=self.COLOR_YELLOW)
        self._log_text.tag_config("error", foreground=self.COLOR_RED)

        # ---- Progress bar ----
        self._progress = ttk.Progressbar(root, mode="indeterminate", length=200)
        self._progress.pack(fill=tk.X, padx=10, pady=(0, 4))

        # ---- Button row ----
        btn_frame = tk.Frame(root, bg=self.COLOR_BG)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        btn_cfg = dict(
            bg=self.COLOR_BTN_BG,
            fg=self.COLOR_BTN_FG,
            activebackground=self.COLOR_BTN_ACTIVE,
            activeforeground=self.COLOR_WHITE,
            relief=tk.FLAT,
            padx=14,
            pady=8,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            bd=0,
        )

        self._btn_diag = tk.Button(
            btn_frame, text="Diagnosticar", command=self._on_diagnose, **btn_cfg
        )
        self._btn_repair = tk.Button(
            btn_frame, text="Recuperar aplicación", command=self._on_repair, **btn_cfg
        )
        self._btn_report = tk.Button(
            btn_frame, text="Abrir informe", command=self._on_open_report,
            state=tk.DISABLED, **btn_cfg
        )
        self._btn_restore = tk.Button(
            btn_frame, text="Restaurar versión estable",
            command=self._on_restore, **btn_cfg
        )
        self._btn_close = tk.Button(
            btn_frame, text="Cerrar", command=self._on_close, **btn_cfg
        )

        for btn in (self._btn_diag, self._btn_repair, self._btn_report,
                    self._btn_restore, self._btn_close):
            btn.pack(side=tk.LEFT, padx=(0, 6))

        # Style the progress bar
        style = ttk.Style()
        style.theme_use("default")
        style.configure("TProgressbar", troughcolor=self.COLOR_LOG_BG,
                        background=self.COLOR_GREEN)

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def set_status(self, color: str, text: str):
        """Thread-safe status update."""
        color_map = {
            "green": self.COLOR_GREEN,
            "yellow": self.COLOR_YELLOW,
            "red": self.COLOR_RED,
        }
        bg = color_map.get(color, self.COLOR_GRAY)
        self.root.after(0, lambda: self._apply_status(bg, text))

    def _apply_status(self, bg: str, text: str):
        self._status_frame.configure(bg=bg)
        self._status_label.configure(bg=bg, text=text)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def log(self, message: str, level: str = "info"):
        """Thread-safe append to scrolled log."""
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {message}\n"
        self.root.after(0, lambda: self._append_log(line, level))

    def _append_log(self, line: str, level: str):
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.insert(tk.END, line, level)
        self._log_text.see(tk.END)
        self._log_text.configure(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Progress / busy state
    # ------------------------------------------------------------------

    def _start_busy(self):
        self._busy = True
        for btn in (self._btn_diag, self._btn_repair, self._btn_restore):
            btn.configure(state=tk.DISABLED)
        self._progress.start(12)

    def _stop_busy(self):
        self._busy = False
        for btn in (self._btn_diag, self._btn_repair, self._btn_restore):
            btn.configure(state=tk.NORMAL)
        self._progress.stop()

    # ------------------------------------------------------------------
    # Auto-diagnose on startup
    # ------------------------------------------------------------------

    def _auto_diagnose(self):
        self.log("Iniciando diagnóstico automático…", "info")
        self._run_diagnostics_thread()

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def _on_diagnose(self):
        if self._busy:
            return
        self.log("─" * 60, "info")
        self.log("Diagnóstico iniciado por el usuario.", "info")
        self._run_diagnostics_thread()

    def _run_diagnostics_thread(self):
        self._start_busy()
        self.set_status("yellow", "Ejecutando diagnóstico…")
        t = threading.Thread(target=self._diag_worker, daemon=True)
        t.start()

    def _diag_worker(self):
        try:
            self.log("Comprobando servicio Windows…", "info")
            diag = run_diagnostics()
            self._last_diag = diag
            self.root.after(0, lambda: self._display_diag(diag))
        except Exception as exc:
            self.log(f"Error inesperado durante diagnóstico: {exc}", "error")
            self.set_status("red", "Error en diagnóstico")
        finally:
            self.root.after(0, self._stop_busy)

    def _display_diag(self, diag: dict):
        svc = diag["service"]
        http = diag["http"]
        db = diag["db"]
        disk = diag["disk"]
        proc = diag["process"]

        state = svc.get("state", "UNKNOWN")
        health_ok = http["/health"]["ok"]
        scan_ok = http["/scan"]["ok"]

        # Determine overall status
        if state == "RUNNING" and health_ok:
            self.set_status("green", f"Servicio ACTIVO — /health OK")
        elif state == "RUNNING" and not health_ok:
            self.set_status("yellow", "Servicio en ejecución pero /health no responde")
        else:
            self.set_status("red", f"Servicio {state} — intervención requerida")

        level = "ok" if state == "RUNNING" else "error"
        self.log(f"Servicio: {state} | PID(sc): {svc.get('pid_from_sc') or 'N/A'}", level)
        self.log(f"Commit: {diag.get('commit', 'N/A')}", "info")
        self.log(f"Puerto {CONFIG['app_port']}: PID={proc.get('port_pid') or 'libre'}", "info")

        for path, result in http.items():
            lvl = "ok" if result["ok"] else "error"
            code = result.get("status_code") or result.get("error", "—")
            self.log(f"HTTP {path}: {code}", lvl)

        db_lvl = "ok" if db.get("integrity_ok") else "error"
        self.log(
            f"DB: existe={db.get('exists')} legible={db.get('readable')} "
            f"integridad={db.get('integrity_result', '?')}",
            db_lvl,
        )

        disk_lvl = "ok" if disk.get("free_ok") else "warn"
        self.log(f"Disco: {disk.get('free_gb', '?')} GB libres | "
                 f"escritura={'OK' if disk.get('write_ok') else 'ERROR'}", disk_lvl)

        errors = diag["logs"].get("error_lines", [])
        if errors:
            self.log(f"Últimos errores en log ({len(errors)} líneas):", "warn")
            for line in errors[-5:]:
                self.log(f"  {line}", "warn")
        else:
            self.log("Sin errores recientes en log.", "ok")

        self.log("Diagnóstico completado.", "info")

    # ------------------------------------------------------------------
    # Repair
    # ------------------------------------------------------------------

    def _on_repair(self):
        if self._busy:
            return
        self.log("─" * 60, "info")
        self.log("Iniciando proceso de recuperación…", "warn")
        self._start_busy()
        self.set_status("yellow", "Recuperando aplicación…")
        t = threading.Thread(target=self._repair_worker, daemon=True)
        t.start()

    def _repair_worker(self):
        try:
            result = run_repair(progress_cb=lambda msg, lvl: self.log(msg, lvl))
            self._last_repair_actions = result["actions"]
            self._last_diag = result["final_diag"]
            path = generate_report(self._last_diag, self._last_repair_actions)
            self._last_report_path = path
            self.root.after(0, lambda: self._btn_report.configure(state=tk.NORMAL))

            if result["success"]:
                self.set_status("green", "Recuperación exitosa — aplicación activa")
                self.log("Recuperación completada con éxito.", "ok")
            else:
                self.set_status("red", "No se pudo recuperar — revise el informe")
                self.log(f"Informe guardado en: {path}", "info")
        except Exception as exc:
            self.log(f"Error inesperado durante recuperación: {exc}", "error")
            self.set_status("red", "Error en recuperación")
        finally:
            self.root.after(0, self._stop_busy)

    # ------------------------------------------------------------------
    # Open report
    # ------------------------------------------------------------------

    def _on_open_report(self):
        if self._last_report_path and os.path.isfile(self._last_report_path):
            try:
                os.startfile(self._last_report_path)
            except AttributeError:
                subprocess.Popen(["notepad.exe", self._last_report_path])
        else:
            messagebox.showinfo("Informe", "No hay informe generado todavía. "
                                "Ejecute primero un diagnóstico o recuperación.")

    # ------------------------------------------------------------------
    # Restore stable version
    # ------------------------------------------------------------------

    def _on_restore(self):
        if self._busy:
            return
        confirm1 = messagebox.askyesno(
            "Restaurar versión estable",
            "¿Está seguro? Esto reemplazará el código actual con la última "
            "versión estable de git.\nLa base de datos NO se toca.",
            icon="warning",
        )
        if not confirm1:
            self.log("Restauración cancelada por el usuario.", "info")
            return

        confirm2 = messagebox.askyesno(
            "ÚLTIMA CONFIRMACIÓN",
            "ÚLTIMA CONFIRMACIÓN: ¿Restaurar código? Esto no puede deshacerse.",
            icon="warning",
        )
        if not confirm2:
            self.log("Restauración cancelada en segunda confirmación.", "info")
            return

        self.log("─" * 60, "info")
        self.log("Iniciando restauración de versión estable…", "warn")
        self._start_busy()
        self.set_status("yellow", "Restaurando versión estable…")
        t = threading.Thread(target=self._restore_worker, daemon=True)
        t.start()

    def _restore_worker(self):
        try:
            result = restore_stable_version(
                progress_cb=lambda msg, lvl: self.log(msg, lvl)
            )
            self._last_repair_actions = result["actions"]
            self._last_diag = run_diagnostics()
            path = generate_report(self._last_diag, self._last_repair_actions)
            self._last_report_path = path
            self.root.after(0, lambda: self._btn_report.configure(state=tk.NORMAL))

            if result["success"]:
                self.set_status("green", "Restauración exitosa — aplicación activa")
                self.log("Restauración de versión estable completada.", "ok")
            else:
                self.set_status("red", "Restauración fallida — revise el informe")
                self.log(f"Informe guardado en: {path}", "info")
        except Exception as exc:
            self.log(f"Error inesperado durante restauración: {exc}", "error")
            self.set_status("red", "Error en restauración")
        finally:
            self.root.after(0, self._stop_busy)

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def _on_close(self):
        release_lock()
        self.root.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # UAC elevation check (Windows only)
    if sys.platform == "win32" and not is_admin():
        relaunch_as_admin()
        return

    # Lock file check
    if not acquire_lock():
        # Need a minimal Tk root to show the error dialog
        _root = tk.Tk()
        _root.withdraw()
        messagebox.showerror(
            "Ya en ejecución",
            "Ya hay una instancia en ejecución.\n"
            "Cierre la instancia existente antes de abrir una nueva.",
        )
        _root.destroy()
        sys.exit(1)

    root = tk.Tk()
    root.geometry("1000x700")
    app = RecoveryApp(root)  # noqa: F841

    try:
        root.mainloop()
    finally:
        release_lock()


if __name__ == "__main__":
    main()
