"""
MRD Tool Control — Diagnóstico y Recuperación
Standalone GUI recovery tool for the MRDToolControl Windows service.
"""

import os
import sys
import re as _re
import ctypes
import base64
import subprocess
import threading
import http.client
import sqlite3
import shutil
import json
import time
import datetime
import html
import hashlib
import secrets
import socket
import tempfile
import zipfile
import webbrowser
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from typing import Optional, Tuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Configuration — edit here for your environment
# ---------------------------------------------------------------------------
CONFIG = {
    "service_name": "MRDToolControl",
    # Durante la migración llegaron a existir dos nombres. La consola detecta
    # ambos sin asumir cuál está instalado y nunca muestra sus credenciales.
    "cloudflare_services": ("cloudflared", "CloudflaredMRD"),
    "app_port": 8000,
    "app_host": "localhost",
    "app_dir": r"C:\mrd_tool_control",
    # db_path se resuelve en run_diagnostics() via _resolve_db_path()
    "db_path": r"C:\mrd_tool_control\data\mrd_tool.db",
    "log_dir": r"C:\mrd_tool_control\logs",
    "lock_file": r"C:\mrd_tool_control\recovery_tool\.recovery.lock",
    "report_dir": r"C:\mrd_tool_control\recovery_tool\reports",
    "maintenance_marker": r"C:\mrd_tool_control\.maintenance_mode",
    "ollama_host": "127.0.0.1",
    "ollama_port": 11434,
    "ollama_rescue_port": 11435,
    "ollama_rescue_exe": r"C:\Users\IAS MRD\AppData\Local\MRDRescue\ollama\ollama.exe",
    "ollama_models": r"C:\Users\IAS MRD\.ollama\models",
    # Modelo ligero para que el diagnóstico sea ágil en el Intel N150.
    "ollama_model": "qwen2.5:1.5b",
    "ollama_timeout_sec": 90,
    "public_app_url": "https://app.iasmrd.com/",
    "public_health_url": "https://app.iasmrd.com/health",
    "mobile_public_url": "https://rescue.iasmrd.com",
    "mobile_identity_file": r"C:\mrd_tool_control\recovery_tool\.mobile_identity.dat",
    "stable_snapshot_path": r"C:\mrd_tool_control\recovery_tool\stable\mrd_stable_code.zip",
    "safety_backup_dir": r"C:\mrd_tool_control\backups",
    "mobile_port": 8765,
    "max_restarts": 3,
    "health_timeout_sec": 3,
    "health_wait_sec": 25,
}

# ---------------------------------------------------------------------------
# Fix 6 — Restart count persisted across executions with expiry
# ---------------------------------------------------------------------------
RESTART_LOG_PATH = os.path.join(
    os.path.dirname(CONFIG["lock_file"]), ".restart_count.json"
)
RESTART_WINDOW_SEC = 300  # 5 minutes


def _get_restart_count() -> int:
    try:
        with open(RESTART_LOG_PATH) as f:
            data = json.load(f)
        if time.time() - data.get("ts", 0) > RESTART_WINDOW_SEC:
            return 0  # Window expired
        return data.get("count", 0)
    except Exception:
        return 0


def _increment_restart_count():
    count = _get_restart_count() + 1
    try:
        os.makedirs(os.path.dirname(RESTART_LOG_PATH), exist_ok=True)
        with open(RESTART_LOG_PATH, "w") as f:
            json.dump({"count": count, "ts": time.time()}, f)
    except Exception:
        pass


def _reset_restart_count():
    try:
        os.remove(RESTART_LOG_PATH)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Fix 9 — Secret sanitization (eliminación completa del valor)
# ---------------------------------------------------------------------------
_SECRET_PATTERNS = [
    # Authorization header — captura todo el valor incluyendo Bearer + token
    (_re.compile(r'(Authorization\s*[:=]\s*)\S.*', _re.I), r'\1[REDACTED]'),
    # Bearer tokens standalone (cuando no van precedidos por Authorization:)
    (_re.compile(r'(Bearer\s+)[A-Za-z0-9\-._~+/]+=*', _re.I), r'\1[REDACTED]'),
    # JSON key-value: "password": "valor" / "token": "valor" etc.
    (_re.compile(
        r'("(?:password|passwd|pwd|secret|token|api_key|apikey|access_key|private_key|auth)"\s*:\s*)"[^"]*"',
        _re.I),
     r'\1"[REDACTED]"'),
    # key=value o key:value en logs/URLs (text plano)
    (_re.compile(
        r'((?:password|passwd|pwd|secret|token|api_key|apikey|access_key|private_key)\s*[=:]\s*)\S+',
        _re.I),
     r'\1[REDACTED]'),
    # JWT-shaped strings (3 segmentos base64 separados por puntos)
    (_re.compile(r'eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]*'),
     '[REDACTED-JWT]'),
    # Cookie headers — elimina todos los valores de la línea
    (_re.compile(r'(Cookie\s*:\s*).*', _re.I), r'\1[REDACTED]'),
    # Set-Cookie
    (_re.compile(r'(Set-Cookie\s*:\s*).*', _re.I), r'\1[REDACTED]'),
    # Connection strings con credenciales
    (_re.compile(r'://[^:]+:[^@]+@'), '://[REDACTED]@'),
]


def sanitize_for_report(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ---------------------------------------------------------------------------
# Fix 1, 3, 4, 5, 10 — DB path desde config real (con open() como context manager)
# ---------------------------------------------------------------------------

_DB_INDETERMINATE = "base indeterminada"


def _resolve_db_path(app_dir: str) -> str:
    """
    Resuelve la ruta de la BD comparando dos fuentes independientes:
      1) config/local.env o .env  — busca MRD_DATABASE_URL (primera coincidencia)
      2) config.py                — busca MRD_DATABASE_URL

    Prioridad de configuración documentada:
      • Si solo una fuente tiene valor → usa esa ruta.
      • Si ambas tienen el MISMO valor → usa esa ruta.
      • Si ambas tienen VALORES DISTINTOS → devuelve 'base indeterminada'.
      • Si ninguna tiene valor → usa el predeterminado data/mrd_tool.db.

    Nunca adivina buscando archivos .db en el directorio.
    Todas las rutas se normalizan con os.path.normpath.
    """
    default = os.path.normpath(os.path.join(app_dir, "data", "mrd_tool.db"))
    found: list = []

    def _norm(p: str, base: str) -> str:
        if not os.path.isabs(p):
            p = os.path.join(base, p)
        return os.path.normpath(p)

    # Fuente 1: config/local.env → .env (primera que tenga MRD_DATABASE_URL)
    for env_file in [
        os.path.join(app_dir, "config", "local.env"),
        os.path.join(app_dir, ".env"),
    ]:
        try:
            with open(env_file, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
            m = _re.search(r'^MRD_DATABASE_URL\s*=\s*sqlite:///([^\s\'"]+)', text, _re.M)
            if m:
                found.append(_norm(m.group(1), app_dir))
                break  # una sola fuente env es suficiente
        except Exception:
            pass

    # Fuente 2: config.py (siempre se comprueba para detectar conflictos)
    config_py = os.path.join(app_dir, "config.py")
    try:
        with open(config_py, encoding="utf-8", errors="ignore") as fh:
            text = fh.read()
        m = _re.search(
            r'MRD_DATABASE_URL[^=\n]*=\s*["\']?sqlite:///([^\s\'"]+)', text
        )
        if m:
            found.append(_norm(m.group(1), app_dir))
    except Exception:
        pass

    if not found:
        return default

    unique = list(dict.fromkeys(found))
    if len(unique) > 1:
        return _DB_INDETERMINATE   # Fuentes en conflicto — no elige
    return unique[0]


# ---------------------------------------------------------------------------
# Fix 5 — Atomic lock file
# ---------------------------------------------------------------------------

def _lock_pid_running(pid: int) -> bool:
    """Return True if PID is currently alive (Windows tasklist check)."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def _acquire_lock(lock_path: str) -> bool:
    """Atomically create lock file. Returns True if lock acquired."""
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, 'w') as f:
            f.write(str(os.getpid()))
        return True
    except FileExistsError:
        # Check if PID inside is still alive
        try:
            with open(lock_path) as f:
                pid = int(f.read().strip())
            if _lock_pid_running(pid):
                return False  # Genuinely running
            # Stale lock — remove and retry once
            os.remove(lock_path)
            return _acquire_lock(lock_path)
        except Exception:
            return False


def acquire_lock() -> bool:
    """
    Check the lock file. Return True if we acquired it, False if another
    instance is already running. Writes own PID on success.
    """
    return _acquire_lock(CONFIG["lock_file"])


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
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
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
# Fix 8 — sc start/stop with return code verification
# ---------------------------------------------------------------------------

def sc_start(service_name: str) -> Tuple[bool, str]:
    r = _run(["sc", "start", service_name])
    # rc 0 = started, 1056 = already running
    if r.returncode in (0, 1056):
        return True, r.stdout.strip() or "OK"
    return False, f"sc start rc={r.returncode}: {r.stderr.strip() or r.stdout.strip()}"


def sc_stop(service_name: str) -> Tuple[bool, str]:
    r = _run(["sc", "stop", service_name])
    if r.returncode in (0, 1062):  # 1062 = not started
        return True, r.stdout.strip() or "OK"
    return False, f"sc stop rc={r.returncode}: {r.stderr.strip() or r.stdout.strip()}"


# ---------------------------------------------------------------------------
# Fix 2 — LISTENING sockets only, exact port
# ---------------------------------------------------------------------------

def check_port(port: int) -> Optional[int]:
    """Return PID holding LISTENING socket on exact port, or None."""
    result = _run(["netstat", "-ano"])
    for line in result.stdout.splitlines():
        parts = line.split()
        # Format: Proto  Local Address  Foreign Address  State  PID
        if len(parts) < 5:
            continue
        if parts[3].upper() != "LISTENING":
            continue
        local = parts[1]
        # Must be exact port match: ends with :PORT
        if not (local.endswith(f":{port}") or local == f"0.0.0.0:{port}"
                or local == f"[::]:{port}"):
            continue
        try:
            return int(parts[4])
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Fix 3 — PID verification: only kill confirmed service PID
# ---------------------------------------------------------------------------

def _get_service_pid(service_name: str) -> Optional[int]:
    """Get PID of service via sc queryex. Never guess."""
    result = _run(["sc", "queryex", service_name])
    for line in result.stdout.splitlines():
        if "PID" in line.upper():
            parts = line.split(":")
            if len(parts) >= 2:
                try:
                    return int(parts[1].strip())
                except ValueError:
                    pass
    return None


def _verify_pid_is_service(pid: int, service_name: str, app_dir: str) -> bool:
    """
    Confirma que el PID pertenece inequívocamente al servicio MRD.
    Rechaza rutas vacías y exige que el ejecutable esté bajo app_dir.
    Que el nombre contenga 'python' NO es condición suficiente.
    """
    # Paso 1: el PID existe en tasklist
    r1 = _run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"])
    if str(pid) not in r1.stdout:
        return False
    # Paso 2: ruta del ejecutable obtenida por wmic
    r2 = _run(["wmic", "process", "where", f"ProcessId={pid}",
                "get", "ExecutablePath", "/FORMAT:LIST"])
    path_line = next((l for l in r2.stdout.splitlines() if "ExecutablePath" in l), "")
    exe_path = path_line.split("=", 1)[-1].strip().lower() if "=" in path_line else ""
    # Ruta vacía → identidad no demostrable → rechaza
    if not exe_path:
        return False
    # El ejecutable debe residir bajo app_dir — "python" solo no basta
    if app_dir.lower() not in exe_path:
        return False
    return True


def safe_kill_port_holder(port: int, service_name: str, app_dir: str) -> Tuple[bool, str]:
    """Kill process on port ONLY if verified to be the MRD service PID."""
    port_pid = check_port(port)
    if port_pid is None:
        return False, "No hay proceso en el puerto"
    svc_pid = _get_service_pid(service_name)
    if svc_pid is None or svc_pid != port_pid:
        return False, (
            f"PID {port_pid} en puerto no coincide con servicio "
            f"(PID servicio: {svc_pid}). No se termina."
        )
    if not _verify_pid_is_service(port_pid, service_name, app_dir):
        return False, (
            f"PID {port_pid} no pasa verificación de ejecutable. No se termina."
        )
    result = _run(["taskkill", "/F", "/PID", str(port_pid)])
    if result.returncode != 0:
        return False, f"taskkill falló (rc={result.returncode}): {result.stderr.strip()}"
    return True, f"Proceso {port_pid} terminado correctamente"


# ---------------------------------------------------------------------------
# Diagnostic functions (pure — no GUI dependencies)
# ---------------------------------------------------------------------------

def check_service_named(svc: str) -> dict:
    """Consulta un servicio sin depender del idioma de Windows."""
    result = _run(["sc", "queryex", svc])
    output = result.stdout + result.stderr
    state = "UNKNOWN"
    pid_from_sc = None

    for line in output.splitlines():
        line = line.strip()
        # sc.exe traduce la etiqueta (STATE/ESTADO), pero mantiene estos
        # valores estables. Buscar el valor evita falsos "UNKNOWN".
        for candidate in ("RUNNING", "STOPPED", "PAUSED", "START_PENDING",
                          "STOP_PENDING", "CONTINUE_PENDING", "PAUSE_PENDING"):
            if _re.search(rf"\b{candidate}\b", line.upper()):
                state = candidate
                break
        if "PID" in line and ":" in line:
            try:
                pid_from_sc = int(line.split(":")[-1].strip())
            except ValueError:
                pass

    exists = result.returncode == 0 or state != "UNKNOWN"
    return {"name": svc, "exists": exists, "state": state,
            "pid_from_sc": pid_from_sc, "raw": output.strip()}


def check_service() -> dict:
    """Consulta el servicio principal de MRD."""
    return check_service_named(CONFIG["service_name"])


def check_tunnels() -> list:
    """Devuelve todos los servicios de túnel conocidos, sin secretos."""
    return [check_service_named(name) for name in CONFIG["cloudflare_services"]]


def check_process() -> dict:
    """Find any python.exe processes and the PID holding the app port."""
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
    port_pid = check_port(CONFIG["app_port"])
    return {"python_pids": python_pids, "port_pid": port_pid}


# Fix 4-6 — /health válido solo con JSON {"status": "ok"} exacto
def check_http(host: str, port: int, path: str, timeout: int = 8) -> dict:
    result = {"status_code": None, "ok": False, "content_ok": False, "error": None}
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        conn.request("GET", path)
        resp = conn.getresponse()
        result["status_code"] = resp.status
        raw = resp.read(4096)
        result["ok"] = resp.status < 400
        if path == "/health":
            # content_ok solo si el cuerpo es JSON con {"status": "ok"} exacto.
            # JSON inválido, status distinto de "ok", HTML o cuerpo vacío → False.
            try:
                if not raw:
                    raise ValueError("empty body")
                data = json.loads(raw.decode("utf-8", errors="replace"))
                result["content_ok"] = (
                    isinstance(data, dict) and data.get("status") == "ok"
                )
            except Exception:
                result["content_ok"] = False
        else:
            result["content_ok"] = result["ok"]
        conn.close()
    except Exception as e:
        result["error"] = str(e)
    return result


def check_public_access(url: str, timeout: int = 5) -> dict:
    """Comprueba la ruta pública desde este PC, separada de la salud local."""
    result = {"ok": False, "status_code": None, "content_ok": False, "error": None}
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("La URL pública debe usar HTTPS")
        conn = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=timeout)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        conn.request("GET", path)
        response = conn.getresponse()
        raw = response.read(4096)
        conn.close()
        result["status_code"] = response.status
        result["ok"] = response.status == 200
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
            result["content_ok"] = payload.get("status") == "ok"
        except Exception:
            result["content_ok"] = result["ok"]
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _query_ollama_tags(port: int) -> dict:
    result = {"ok": False, "models": [], "port": port, "error": None}
    try:
        conn = http.client.HTTPConnection(
            CONFIG["ollama_host"], port, timeout=3
        )
        conn.request("GET", "/api/tags")
        response = conn.getresponse()
        raw = response.read(1024 * 1024)
        conn.close()
        if response.status != 200:
            result["error"] = f"HTTP {response.status}"
            return result
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        result["models"] = [
            str(item.get("name")) for item in payload.get("models", [])
            if item.get("name")
        ]
        result["ok"] = bool(result["models"])
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _start_rescue_ollama() -> bool:
    """Inicia el motor IA autónomo sin consola y sin permisos administrativos."""
    exe = CONFIG["ollama_rescue_exe"]
    if not os.path.isfile(exe):
        return False
    env = os.environ.copy()
    env["OLLAMA_HOST"] = f"{CONFIG['ollama_host']}:{CONFIG['ollama_rescue_port']}"
    env["OLLAMA_MODELS"] = CONFIG["ollama_models"]
    flags = 0
    if sys.platform == "win32":
        flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                 | getattr(subprocess, "DETACHED_PROCESS", 0)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        subprocess.Popen(
            [exe, "serve"], cwd=os.path.dirname(exe), env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=flags,
            close_fds=True,
        )
        return True
    except Exception:
        return False


def check_ollama() -> dict:
    """Prefiere la IA autónoma de Rescue y usa el servicio general como respaldo."""
    rescue_port = CONFIG["ollama_rescue_port"]
    result = _query_ollama_tags(rescue_port)
    if not result["ok"] and _start_rescue_ollama():
        for _ in range(8):
            time.sleep(0.5)
            result = _query_ollama_tags(rescue_port)
            if result["ok"]:
                break
    if not result["ok"]:
        result = _query_ollama_tags(CONFIG["ollama_port"])

    result["selected"] = CONFIG["ollama_model"]
    result["mode"] = "rescue" if result.get("port") == rescue_port else "servicio"
    if CONFIG["ollama_model"] not in result.get("models", []) and result.get("models"):
        result["selected"] = result["models"][0]
    return result


def _ai_safe_snapshot(diag: dict) -> dict:
    """Datos mínimos permitidos para Ollama; nunca incluye credenciales."""
    http_results = {}
    for path, value in diag.get("http", {}).items():
        http_results[path] = {
            "ok": bool(value.get("ok")),
            "content_ok": bool(value.get("content_ok")),
            "status_code": value.get("status_code"),
            "error": sanitize_for_report(str(value.get("error") or ""))[:300],
        }
    return {
        "service": diag.get("service", {}).get("state"),
        "tunnels": [
            {"name": t.get("name"), "state": t.get("state")}
            for t in diag.get("tunnels", [])
        ],
        "http": http_results,
        "public_access_from_this_pc": {
            "ok": diag.get("public", {}).get("ok"),
            "content_ok": diag.get("public", {}).get("content_ok"),
            "status_code": diag.get("public", {}).get("status_code"),
            "error": sanitize_for_report(str(diag.get("public", {}).get("error") or ""))[:300],
        },
        "database": {
            "exists": diag.get("db", {}).get("exists"),
            "readable": diag.get("db", {}).get("readable"),
            "integrity_ok": diag.get("db", {}).get("integrity_ok"),
            "integrity": sanitize_for_report(
                str(diag.get("db", {}).get("integrity_result", ""))
            )[:300],
        },
        "disk": diag.get("disk", {}),
        "capacity": diag.get("capacity", {}),
        "recent_errors": [
            sanitize_for_report(str(line))[:500]
            for line in diag.get("logs", {}).get("error_lines", [])[-8:]
        ],
    }


def ask_ollama(diag: dict, phase: str = "diagnóstico") -> dict:
    """Solicita análisis local. La respuesta solo se muestra; jamás se ejecuta."""
    ollama = check_ollama()
    if not ollama["ok"]:
        return {"ok": False, "text": "", "error": ollama.get("error") or "Ollama no disponible"}

    system_prompt = (
        "Eres el técnico local de MRD Tool Control. Analiza únicamente el estado "
        "recibido. Responde en español, máximo 8 líneas, con: causa probable, "
        "comprobaciones y resultado. No generes comandos, código, SQL, credenciales "
        "ni instrucciones destructivas. Las acciones reales las ejecuta un motor "
        "determinista y seguro; tú solo diagnosticas y explicas."
    )
    user_prompt = json.dumps(
        {"phase": phase, "snapshot": _ai_safe_snapshot(diag)},
        ensure_ascii=False, separators=(",", ":"), default=str,
    )
    body = json.dumps({
        "model": ollama["selected"],
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {"temperature": 0.1, "num_predict": 350},
    }, ensure_ascii=False).encode("utf-8")
    try:
        conn = http.client.HTTPConnection(
            CONFIG["ollama_host"], ollama["port"],
            timeout=CONFIG["ollama_timeout_sec"],
        )
        conn.request("POST", "/api/chat", body=body,
                     headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        raw = response.read(2 * 1024 * 1024)
        conn.close()
        if response.status != 200:
            return {"ok": False, "text": "", "error": f"Ollama HTTP {response.status}"}
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        text = sanitize_for_report(
            str(payload.get("message", {}).get("content", "")).strip()
        )[:5000]
        return {"ok": bool(text), "text": text, "error": None,
                "model": ollama["selected"]}
    except Exception as exc:
        return {"ok": False, "text": "", "error": str(exc)}


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
    if path == _DB_INDETERMINATE:
        return {"exists": False, "readable": False,
                "integrity_ok": False, "integrity_result": _DB_INDETERMINATE}
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
        total_gb = usage.total / (1024 ** 3)
        used_gb = usage.used / (1024 ** 3)
        used_percent = (usage.used / usage.total * 100) if usage.total else 0
        free_ok = usage.free > 500 * 1024 * 1024
    except Exception as exc:
        return {"free_gb": None, "free_ok": False, "write_ok": False, "error": str(exc)}

    write_ok = os.access(app_dir, os.W_OK)
    return {"free_gb": round(free_gb, 2), "total_gb": round(total_gb, 2),
            "used_gb": round(used_gb, 2), "used_percent": round(used_percent, 1),
            "free_ok": free_ok, "write_ok": write_ok, "error": None}


def _directory_size(path: str) -> int:
    total = 0
    if not os.path.isdir(path):
        return 0
    for root, _dirs, files in os.walk(path):
        for filename in files:
            try:
                total += os.path.getsize(os.path.join(root, filename))
            except OSError:
                pass
    return total


def check_capacity() -> dict:
    """Capacidad útil para el encargado: RAM, BD, adjuntos y copias."""
    memory = {"total_gb": None, "used_gb": None, "used_percent": None}
    if sys.platform == "win32":
        try:
            class _MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                total = status.ullTotalPhys
                used = total - status.ullAvailPhys
                memory = {
                    "total_gb": round(total / (1024 ** 3), 1),
                    "used_gb": round(used / (1024 ** 3), 1),
                    "used_percent": int(status.dwMemoryLoad),
                }
        except Exception:
            pass

    db_path = CONFIG.get("db_path", "")
    db_bytes = os.path.getsize(db_path) if db_path and os.path.isfile(db_path) else 0
    backups_dir = os.path.join(CONFIG["app_dir"], "backups")
    try:
        backup_count = sum(
            1 for name in os.listdir(backups_dir)
            if os.path.isfile(os.path.join(backups_dir, name))
            and name.lower().endswith((".db", ".zip"))
        )
    except OSError:
        backup_count = 0
    return {
        "memory": memory,
        "database_mb": round(db_bytes / (1024 ** 2), 1),
        "uploads_mb": round(_directory_size(os.path.join(CONFIG["app_dir"], "uploads")) / (1024 ** 2), 1),
        "backups_mb": round(_directory_size(backups_dir) / (1024 ** 2), 1),
        "backup_count": backup_count,
    }


def check_git_commit() -> str:
    """Return the latest git commit hash + message or 'N/A'."""
    candidates = [
        "git",
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files\Git\bin\git.exe",
    ]
    for executable in candidates:
        if executable != "git" and not os.path.isfile(executable):
            continue
        result = _run([executable, "-C", CONFIG["app_dir"], "log", "--oneline", "-1"])
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    try:
        with open(os.path.join(CONFIG["app_dir"], "version.json"), encoding="utf-8") as fh:
            version = json.load(fh).get("version_actual")
        if version:
            return f"Versión {version}"
    except Exception:
        pass
    return "Versión no disponible"


def run_diagnostics() -> dict:
    """Run all checks and return a combined results dict."""
    # Fix 1: Resolve real DB path at runtime, not at module import
    CONFIG["db_path"] = _resolve_db_path(CONFIG["app_dir"])

    svc = check_service()
    tunnels = check_tunnels()
    proc = check_process()
    host = CONFIG["app_host"]
    port = CONFIG["app_port"]
    timeout = CONFIG["health_timeout_sec"]
    http_health = check_http(host, port, "/health", timeout)
    http_root = check_http(host, port, "/", timeout)
    http_scan = check_http(host, port, "/scan", timeout)
    public = check_public_access(CONFIG["public_health_url"])
    logs = check_logs()
    db = check_db()
    disk = check_disk()
    capacity = check_capacity()
    ollama = check_ollama()
    commit = check_git_commit()

    return {
        "service": svc,
        "tunnels": tunnels,
        "process": proc,
        "http": {
            "/health": http_health,
            "/": http_root,
            "/scan": http_scan,
        },
        "public": public,
        "logs": logs,
        "db": db,
        "disk": disk,
        "capacity": capacity,
        "ollama": ollama,
        "commit": commit,
        "timestamp": datetime.datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Repair functions (pure — no GUI deps)
# ---------------------------------------------------------------------------

CODE_SNAPSHOT_DIRS = ("templates", "static", "mobile", "migrations", "services")
CODE_ROOT_NAMES = {
    "alembic.ini", "requirements.txt", "requirements-dev.txt", "version.json",
}
CODE_ROOT_SUFFIXES = (".py",)


def _iter_code_files(app_dir: str):
    """Devuelve únicamente código y recursos; nunca datos, secretos ni adjuntos."""
    app_dir = os.path.abspath(app_dir)
    for name in sorted(os.listdir(app_dir)):
        path = os.path.join(app_dir, name)
        if os.path.isfile(path) and (name in CODE_ROOT_NAMES or name.endswith(CODE_ROOT_SUFFIXES)):
            yield name.replace("\\", "/"), path
    for dirname in CODE_SNAPSHOT_DIRS:
        base = os.path.join(app_dir, dirname)
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in {"__pycache__", ".pytest_cache"})
            for name in sorted(files):
                if name.endswith((".pyc", ".pyo")):
                    continue
                path = os.path.join(root, name)
                rel = os.path.relpath(path, app_dir).replace("\\", "/")
                yield rel, path


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_code_snapshot(app_dir: str, snapshot_path: str) -> dict:
    """Crea un ZIP verificable del código, excluyendo siempre datos y secretos."""
    files = list(_iter_code_files(app_dir))
    if not files:
        raise RuntimeError("No se encontraron archivos de aplicación para guardar")
    os.makedirs(os.path.dirname(snapshot_path), exist_ok=True)
    manifest = {
        "created_at": datetime.datetime.now().isoformat(),
        "app_dir": os.path.abspath(app_dir),
        "files": {rel: _sha256_file(path) for rel, path in files},
    }
    tmp_path = snapshot_path + ".tmp"
    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for rel, path in files:
                archive.write(path, f"code/{rel}")
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        os.replace(tmp_path, snapshot_path)
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
    return manifest


def verify_code_snapshot(snapshot_path: str) -> dict:
    """Valida rutas y hashes antes de permitir cualquier restauración."""
    if not os.path.isfile(snapshot_path):
        raise FileNotFoundError("No existe una versión estable preparada")
    with zipfile.ZipFile(snapshot_path, "r") as archive:
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        files = manifest.get("files") or {}
        if not files:
            raise RuntimeError("El punto estable no contiene archivos")
        for rel, expected in files.items():
            normalized = rel.replace("\\", "/")
            if normalized.startswith("/") or ".." in normalized.split("/"):
                raise RuntimeError("El punto estable contiene una ruta no segura")
            data = archive.read(f"code/{normalized}")
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected:
                raise RuntimeError(f"Integridad incorrecta en {normalized}")
    return manifest


def _backup_database(db_path: str, destination: str):
    """Copia SQLite mediante su API de backup para obtener una copia coherente."""
    if not db_path or not os.path.isfile(db_path):
        return
    source = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def create_pre_restore_backup() -> dict:
    """Guarda código y una copia coherente de la BD antes de restaurar."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_dir = os.path.join(CONFIG["safety_backup_dir"], f"before_stable_restore_{timestamp}")
    os.makedirs(backup_dir, exist_ok=False)
    code_path = os.path.join(backup_dir, "code_before_restore.zip")
    create_code_snapshot(CONFIG["app_dir"], code_path)
    db_path = _resolve_db_path(CONFIG["app_dir"])
    db_copy = os.path.join(backup_dir, "database_before_restore.sqlite")
    _backup_database(db_path, db_copy)
    return {"dir": backup_dir, "code": code_path,
            "database": db_copy if os.path.isfile(db_copy) else None}


def _restore_code_snapshot(snapshot_path: str, app_dir: str):
    """Restaura solo los archivos declarados, con el servicio ya detenido."""
    manifest = verify_code_snapshot(snapshot_path)
    with tempfile.TemporaryDirectory(prefix="mrd_restore_") as staging:
        with zipfile.ZipFile(snapshot_path, "r") as archive:
            for rel in manifest["files"]:
                source = archive.extract(f"code/{rel}", staging)
                destination = os.path.abspath(os.path.join(app_dir, rel))
                app_root = os.path.abspath(app_dir) + os.sep
                if not destination.startswith(app_root):
                    raise RuntimeError("Destino de restauración no seguro")
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.copy2(source, destination)
    return manifest


def _wait_healthy(timeout_sec: int = None) -> bool:
    deadline = time.time() + (timeout_sec or CONFIG["health_wait_sec"])
    while time.time() < deadline:
        health = check_http(CONFIG["app_host"], CONFIG["app_port"], "/health", 2)
        if health.get("ok") and health.get("content_ok"):
            return True
        time.sleep(1)
    return False


def restore_stable_version(progress_cb=None) -> dict:
    """Restaura código conocido, con backup previo y reversión automática."""
    actions = []

    def emit(message, level="info"):
        actions.append(f"[{level.upper()}] {message}")
        if progress_cb:
            progress_cb(message, level)

    stable_path = CONFIG["stable_snapshot_path"]
    verify_code_snapshot(stable_path)
    emit("Versión estable verificada.", "ok")
    backup = create_pre_restore_backup()
    emit(f"Copia previa creada en {backup['dir']}", "ok")
    _set_manual_shutdown(True)
    code_applied = False
    try:
        stopped, message = sc_stop(CONFIG["service_name"])
        if not stopped and check_service().get("state") != "STOPPED":
            raise RuntimeError(f"No se pudo detener MRD: {message}")
        emit("Servicio detenido de forma controlada.", "info")
        # Desde este punto cualquier excepción exige recuperar el código previo,
        # incluso si la copia se interrumpe a mitad de un archivo.
        code_applied = True
        _restore_code_snapshot(stable_path, CONFIG["app_dir"])
        emit("Código estable restaurado; datos y adjuntos no se tocaron.", "ok")
        _set_manual_shutdown(False)
        started, message = sc_start(CONFIG["service_name"])
        if not started and check_service().get("state") != "RUNNING":
            raise RuntimeError(f"No se pudo iniciar MRD: {message}")
        if _wait_healthy():
            _reset_restart_count()
            emit("MRD responde correctamente con la versión estable.", "ok")
            return {"success": True, "rolled_back": False, "backup": backup,
                    "actions": actions, "final_diag": run_diagnostics()}
        raise RuntimeError("La versión estable no superó la comprobación /health")
    except Exception as exc:
        emit(f"La restauración no fue válida: {exc}", "error")
        rolled_back = False
        if code_applied:
            emit("Recuperando automáticamente el código anterior…", "warn")
            try:
                sc_stop(CONFIG["service_name"])
                _restore_code_snapshot(backup["code"], CONFIG["app_dir"])
                rolled_back = True
                _set_manual_shutdown(False)
                sc_start(CONFIG["service_name"])
                recovered = _wait_healthy()
                emit("Código anterior recuperado." if recovered else
                     "Código anterior copiado, pero /health no responde.",
                     "ok" if recovered else "error")
            finally:
                _set_manual_shutdown(False)
        else:
            _set_manual_shutdown(False)
            emit("No se modificó ningún archivo de la aplicación.", "ok")
        return {"success": False, "rolled_back": rolled_back, "backup": backup,
                "actions": actions, "final_diag": run_diagnostics()}

def _set_manual_shutdown(enabled: bool):
    """Pausa/reanuda el vigilante mediante su marcador de mantenimiento."""
    marker = CONFIG["maintenance_marker"]
    if enabled:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        tmp = marker + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(datetime.datetime.now().isoformat())
        os.replace(tmp, marker)
    else:
        try:
            os.remove(marker)
        except FileNotFoundError:
            pass


def _start_known_tunnels(progress_cb=None) -> list:
    actions = []
    for tunnel in check_tunnels():
        if not tunnel.get("exists"):
            continue
        name = tunnel["name"]
        if tunnel.get("state") == "RUNNING":
            actions.append(f"Túnel {name}: ya estaba activo")
            continue
        ok, msg = sc_start(name)
        actions.append(f"Túnel {name}: {'iniciado' if ok else msg}")
        if progress_cb:
            progress_cb(actions[-1], "ok" if ok else "error")
    return actions


def power_on(progress_cb=None) -> dict:
    """Enciende túnel y aplicación y reactiva el vigilante 24/7."""
    _set_manual_shutdown(False)
    actions = _start_known_tunnels(progress_cb)
    svc = check_service()
    if svc.get("state") != "RUNNING":
        ok, msg = sc_start(CONFIG["service_name"])
        text = f"Aplicación: {'encendida' if ok else msg}"
        actions.append(text)
        if progress_cb:
            progress_cb(text, "ok" if ok else "error")
    deadline = time.time() + CONFIG["health_wait_sec"]
    while time.time() < deadline:
        health = check_http(CONFIG["app_host"], CONFIG["app_port"], "/health", 2)
        if health.get("ok") and health.get("content_ok"):
            _reset_restart_count()
            return {"success": True, "actions": actions, "final_diag": run_diagnostics()}
        time.sleep(1)
    return {"success": False, "actions": actions, "final_diag": run_diagnostics()}


def power_off(progress_cb=None) -> dict:
    """Apagado manual seguro: no altera ni abre la base de datos."""
    _set_manual_shutdown(True)
    actions = []
    ok, msg = sc_stop(CONFIG["service_name"])
    actions.append(f"Aplicación: {'apagada' if ok else msg}")
    if progress_cb:
        progress_cb(actions[-1], "ok" if ok else "error")
    # Los túneles pueden servir otros accesos del mismo PC. Se dejan activos;
    # con MRD apagado no exponen la aplicación y evitamos afectar otros sistemas.
    actions.append("Acceso público: queda preparado para el próximo encendido")
    return {"success": ok, "actions": actions,
            "service": check_service(), "tunnels": check_tunnels()}

def run_repair(progress_cb=None) -> dict:
    """
    Attempt to recover the MRDToolControl service.
    progress_cb(message, level) is called for each step if provided.
    Returns {"success": bool, "actions": [str], "final_diag": dict}.
    """
    svc = CONFIG["service_name"]
    app_dir = CONFIG["app_dir"]
    actions = []

    # Una recuperación solicitada expresamente equivale a encender el sistema.
    _set_manual_shutdown(False)

    def log_action(msg, level="info"):
        actions.append(f"[{level.upper()}] {msg}")
        if progress_cb:
            progress_cb(msg, level)

    # Fix 6: use persisted restart count
    current_count = _get_restart_count()
    if current_count >= CONFIG["max_restarts"]:
        log_action(
            f"Se alcanzó el límite de {CONFIG['max_restarts']} reinicios. "
            "Abortando recuperación.", "error"
        )
        final = run_diagnostics()
        return {"success": False, "actions": actions, "final_diag": final}

    diag = run_diagnostics()
    svc_state = diag["service"]["state"]
    # Fix 6: /health válido solo si ok Y content_ok ambos True
    health_ok = (diag["http"]["/health"]["ok"]
                 and diag["http"]["/health"]["content_ok"])

    for tunnel_action in _start_known_tunnels(progress_cb):
        actions.append(f"[INFO] {tunnel_action}")

    # Step 1: Service is stopped — just start it
    if svc_state == "STOPPED":
        log_action("Servicio detenido. Intentando iniciar...", "warn")
        _increment_restart_count()
        ok, msg = sc_start(svc)
        log_action(
            f"sc start {svc}: {msg} (intento #{_get_restart_count()})",
            "info" if ok else "error"
        )
        time.sleep(5)

    # Step 2: Service running but /health failing — stop then start
    elif svc_state == "RUNNING" and not health_ok:
        log_action(
            "Servicio en ejecución pero /health no responde. Reiniciando...", "warn"
        )
        _increment_restart_count()
        ok_stop, msg_stop = sc_stop(svc)
        log_action(
            f"sc stop {svc}: {msg_stop} (intento #{_get_restart_count()})",
            "info" if ok_stop else "error"
        )
        time.sleep(6)
        ok_start, msg_start = sc_start(svc)
        log_action(
            f"sc start {svc}: {msg_start}",
            "info" if ok_start else "error"
        )
        time.sleep(6)

    # Step 3: Stale process holding port — kill it strictly, then start
    port_pid = diag["process"]["port_pid"]
    if port_pid and svc_state != "RUNNING":
        log_action(
            f"PID {port_pid} retiene el puerto {CONFIG['app_port']}. "
            "Verificando proceso...", "warn"
        )
        kill_ok, kill_msg = safe_kill_port_holder(
            CONFIG["app_port"], svc, app_dir
        )
        log_action(kill_msg, "info" if kill_ok else "error")
        if kill_ok:
            time.sleep(3)
            _increment_restart_count()
            ok, msg = sc_start(svc)
            log_action(
                f"sc start {svc}: {msg} (intento #{_get_restart_count()})",
                "info" if ok else "error"
            )

    # Step 4: Poll /health until it responds or timeout
    log_action(
        f"Esperando hasta {CONFIG['health_wait_sec']}s para que /health responda...",
        "info"
    )
    deadline = time.time() + CONFIG["health_wait_sec"]
    health_up = False
    while time.time() < deadline:
        h = check_http(CONFIG["app_host"], CONFIG["app_port"], "/health",
                       CONFIG["health_timeout_sec"])
        # Fix 6: exige ok Y content_ok simultáneamente
        if h["ok"] and h["content_ok"]:
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


def run_ai_repair(progress_cb=None) -> dict:
    """
    Diagnóstico Ollama + reparación determinista + verificación Ollama.
    El texto del modelo nunca se convierte en comandos ni acciones.
    """
    actions = []

    def emit(message, level="info"):
        actions.append(f"[{level.upper()}] {message}")
        if progress_cb:
            progress_cb(message, level)

    emit("IA local: analizando el estado del sistema…", "info")
    initial = run_diagnostics()
    before = ask_ollama(initial, "antes de la reparación")
    if before.get("ok"):
        emit(f"Diagnóstico Ollama ({before.get('model')}):\n{before['text']}", "info")
    else:
        emit(f"Ollama no respondió; continúa el motor seguro: {before.get('error')}", "warn")

    db = initial.get("db", {})
    if db.get("exists") and not db.get("integrity_ok"):
        emit(
            "La base de datos no supera integridad. Se bloquea la reparación automática "
            "para no agravar el daño; los datos no se modificaron.", "error"
        )
        return {"success": False, "actions": actions, "initial_diag": initial,
                "final_diag": initial, "ai_before": before, "ai_after": None}

    emit("Motor seguro: aplicando procedimientos autorizados…", "warn")
    repair = run_repair(progress_cb=progress_cb)
    actions.extend(repair.get("actions", []))
    final = repair["final_diag"]

    emit("IA local: verificando el resultado final…", "info")
    after = ask_ollama(final, "después de la reparación")
    if after.get("ok"):
        emit(f"Verificación Ollama ({after.get('model')}):\n{after['text']}", "ok")
    else:
        emit(f"Verificación IA no disponible: {after.get('error')}", "warn")

    return {
        "success": bool(repair.get("success")), "actions": actions,
        "initial_diag": initial, "final_diag": final,
        "ai_before": before, "ai_after": after,
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(diag_results: dict, repair_actions=None) -> str:
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
    capacity = diag_results.get("capacity", {})
    tunnels = diag_results.get("tunnels", [])
    ollama = diag_results.get("ollama", {})
    public = diag_results.get("public", {})
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
    # Fix 9: sanitize log lines before writing
    sanitized_errors = [sanitize_for_report(l) for l in error_lines[-10:]]
    error_block = "\n    ".join(sanitized_errors) if sanitized_errors else "(ninguno)"

    if repair_actions:
        sanitized_actions = [sanitize_for_report(a) for a in repair_actions]
    else:
        sanitized_actions = []
    actions_block = (
        "\n    ".join(sanitized_actions) if sanitized_actions else "(ninguna acción realizada)"
    )

    # Fix 6: /health válido solo si ok Y content_ok
    _h = http.get("/health", {})
    health_ok = _h.get("ok", False) and _h.get("content_ok", False)
    scan_ok = http.get("/scan", {}).get("ok", False)
    final_result = "OK" if (health_ok and scan_ok) else "NO SE PUDO RECUPERAR"

    port_pid = proc.get("port_pid")
    port_str = str(port_pid) if port_pid else "libre"
    free_gb = disk.get("free_gb")
    free_str = f"{free_gb} GB" if free_gb is not None else "N/A"
    disk_perm = "OK" if disk.get("write_ok") else "Sin permisos de escritura"

    # Fix 9: sanitize commit field
    commit_safe = sanitize_for_report(str(commit))

    report_text = f"""\
MRD TOOL CONTROL — INFORME DE DIAGNÓSTICO
Fecha: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
============================================

ESTADO DEL SERVICIO: {svc.get('state', 'UNKNOWN')}
PID (sc): {svc.get('pid_from_sc') or 'N/A'}
COMMIT: {commit_safe}
PUERTO {CONFIG['app_port']}: {port_str}

COMPROBACIONES HTTP:
  /health: {fmt_http('/health')}
  /: {fmt_http('/')}
  /scan: {fmt_http('/scan')}
  Público desde este PC: {'OK' if public.get('ok') and public.get('content_ok') else 'NO DISPONIBLE'}

BASE DE DATOS:
  Existe:    {yn(db.get('exists'))}
  Legible:   {yn(db.get('readable'))}
  Integridad: {db.get('integrity_result', 'N/A')}

DISCO:
  Libre:     {free_str} de {disk.get('total_gb', 'N/A')} GB
  Ocupado:   {disk.get('used_percent', 'N/A')}%
  Permisos:  {disk_perm}

CAPACIDAD:
  Memoria:   {capacity.get('memory', {}).get('used_percent', 'N/A')}% usada
  Base datos:{capacity.get('database_mb', 'N/A')} MB
  Adjuntos:  {capacity.get('uploads_mb', 'N/A')} MB
  Copias:    {capacity.get('backup_count', 0)} ({capacity.get('backups_mb', 0)} MB)

TÚNEL:
  {', '.join(f"{t.get('name')}: {t.get('state')}" for t in tunnels) or 'No detectado'}

OLLAMA IA:
  Estado:    {'ACTIVO' if ollama.get('ok') else 'NO DISPONIBLE'}
  Modelo:    {ollama.get('selected', 'N/A')}
  Motor:     {ollama.get('mode', 'N/A')}

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
{sanitize_for_report(json.dumps(diag_results, indent=2, default=str))}
"""

    # Fix 9: final sanitization pass on the entire report
    report_text = sanitize_for_report(report_text)

    with open(filepath, "w", encoding="utf-8") as fh:
        fh.write(report_text)

    return filepath


# ---------------------------------------------------------------------------
# GUI Application
# ---------------------------------------------------------------------------

def _open_mrd_url(url: str) -> Tuple[bool, str]:
    """Abre MRD como aplicación independiente en el navegador instalado."""
    browsers = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    try:
        browser = next((path for path in browsers if os.path.isfile(path)), None)
        if browser:
            subprocess.Popen([browser, f"--app={url}", "--start-maximized"],
                             close_fds=True)
        else:
            webbrowser.open(url)
        return True, url
    except Exception as exc:
        return False, str(exc)


def open_public_mrd() -> Tuple[bool, str]:
    """Abre siempre el acceso oficial y público de MRD."""
    return _open_mrd_url(CONFIG["public_app_url"])


def open_local_mrd() -> Tuple[bool, str]:
    """Abre el acceso local de emergencia cuando Internet no está disponible."""
    return _open_mrd_url(f"http://127.0.0.1:{CONFIG['app_port']}/")


def configure_windows_app_identity():
    """Evita que Windows agrupe MRD Rescue bajo el icono de Python."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "IASMRD.MRDRescue.ControlCenter.1"
        )
    except Exception:
        pass


def _local_network_ip() -> str:
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("1.1.1.1", 80))
        address = probe.getsockname()[0]
        probe.close()
        return address
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def _dpapi_transform(data: bytes, protect: bool) -> bytes:
    """Protege la identidad móvil con DPAPI de todo este ordenador."""
    if sys.platform != "win32":
        return data

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong),
                    ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    source_buffer = ctypes.create_string_buffer(data)
    source = DataBlob(len(data), ctypes.cast(source_buffer,
                                             ctypes.POINTER(ctypes.c_ubyte)))
    destination = DataBlob()
    flags = 0x4  # CRYPTPROTECT_LOCAL_MACHINE: GUI y servicio comparten identidad.
    if protect:
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(source), "MRD Rescue", None, None, None, flags,
            ctypes.byref(destination)
        )
    else:
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, flags,
            ctypes.byref(destination)
        )
    if not ok:
        raise OSError("Windows no pudo proteger la identidad móvil")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(destination.pbData)


def load_or_create_mobile_token() -> str:
    """Mantiene el mismo móvil autorizado sin guardar su llave en texto claro."""
    path = CONFIG["mobile_identity_file"]
    try:
        with open(path, "rb") as fh:
            protected = base64.b64decode(fh.read(), validate=True)
        token = _dpapi_transform(protected, False).decode("ascii")
        if len(token) >= 32:
            return token
    except (FileNotFoundError, ValueError, OSError, UnicodeError):
        pass
    token = secrets.token_urlsafe(32)
    protected = _dpapi_transform(token.encode("ascii"), True)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "wb") as fh:
        fh.write(base64.b64encode(protected))
    os.replace(temporary, path)
    if sys.platform == "win32":
        _run(["attrib", "+H", path])
    return token


class MobileControlServer:
    """Panel remoto publicado por Cloudflare con una única acción segura."""

    def __init__(self, app):
        self.app = app
        self.token = load_or_create_mobile_token()
        self.port = CONFIG["mobile_port"]
        self.public_origin = CONFIG["mobile_public_url"].rstrip("/")
        # El fragmento no se envía a Cloudflare ni aparece en sus registros.
        self.url = f"{self.public_origin}/#token={self.token}"
        self.httpd = None
        self.thread = None
        self.last_action_at = 0.0
        self._status_cache = None
        self._status_cache_at = 0.0
        self._status_lock = threading.Lock()

    def mobile_status(self) -> dict:
        """Resumen completo con caché para no castigar al Intel N150."""
        with self._status_lock:
            if self._status_cache and time.time() - self._status_cache_at < 15:
                payload = dict(self._status_cache)
            else:
                diag = run_diagnostics()
                http = diag.get("http", {})
                health = http.get("/health", {})
                capacity = diag.get("capacity", {})
                memory = capacity.get("memory", {})
                db = diag.get("db", {})
                public = diag.get("public", {})
                ollama = diag.get("ollama", {})
                payload = {
                    "ok": True,
                    "active": (diag.get("service", {}).get("state") == "RUNNING"
                               and health.get("content_ok")),
                    "service": diag.get("service", {}).get("state", "UNKNOWN"),
                    "health": health.get("status_code"),
                    "public_ok": bool(public.get("ok") and public.get("content_ok")),
                    "db_ok": bool(db.get("integrity_ok")),
                    "database_mb": capacity.get("database_mb", 0),
                    "disk_percent": diag.get("disk", {}).get("used_percent"),
                    "ram_percent": memory.get("used_percent"),
                    "ai_ok": bool(ollama.get("ok")),
                    "ai_mode": ollama.get("mode", "rescue"),
                    "stable_available": os.path.isfile(CONFIG["stable_snapshot_path"]),
                    "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                }
                self._status_cache = dict(payload)
                self._status_cache_at = time.time()
        payload["busy"] = bool(self.app._busy)
        activity = getattr(self.app, "mobile_activity", None)
        recent = activity() if callable(activity) else []
        payload["activity"] = recent if isinstance(recent, list) else []
        return payload

    def start(self) -> Tuple[bool, str]:
        controller = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def _authorized(self):
                supplied = self.headers.get("X-MRD-Rescue-Token", "")
                if not supplied:
                    cookie = SimpleCookie(self.headers.get("Cookie", ""))
                    saved = cookie.get("mrd_rescue")
                    supplied = saved.value if saved else ""
                return secrets.compare_digest(supplied, controller.token)

            def _origin_allowed(self):
                origin = self.headers.get("Origin", "")
                return not origin or origin.rstrip("/") == controller.public_origin

            def _security_headers(self):
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

            def _send(self, status, body, content_type="text/html; charset=utf-8"):
                encoded = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(encoded)))
                self._security_headers()
                self.end_headers()
                try:
                    self.wfile.write(encoded)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    # El móvil cerró o puso en segundo plano la PWA mientras
                    # llegaba la respuesta. No es una avería del servicio.
                    return

            def _send_json(self, status, payload):
                self._send(status, json.dumps(payload, ensure_ascii=False),
                           "application/json; charset=utf-8")

            def _send_bytes(self, status, payload, content_type):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self._security_headers()
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    return

            def do_GET(self):
                path = urlparse(self.path).path
                if path == "/manifest.webmanifest":
                    self._send_json(200, {
                        "name": "MRD Rescue", "short_name": "MRD Rescue",
                        "id": "/", "start_url": "/", "scope": "/",
                        "display": "standalone", "background_color": "#071225",
                        "theme_color": "#13213d",
                        "icons": [{"src": "/icon.png", "sizes": "any",
                                   "type": "image/png"}],
                    })
                    return
                if path == "/sw.js":
                    script = ("self.addEventListener('install',e=>self.skipWaiting());"
                              "self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));")
                    self._send(200, script, "application/javascript; charset=utf-8")
                    return
                if path == "/icon.png":
                    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             "assets", "mrd_rescue.png")
                    try:
                        with open(icon_path, "rb") as fh:
                            self._send_bytes(200, fh.read(), "image/png")
                    except OSError:
                        self._send(404, "")
                    return
                if path == "/status":
                    if not self._authorized():
                        self._send_json(403, {"ok": False, "error": "Acceso no autorizado"})
                        return
                    self._send_json(200, controller.mobile_status())
                    return
                if path != "/":
                    self._send(404, "<h1>No encontrado</h1>")
                    return
                body = """<!doctype html><html lang='es'><head>
<meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'>
<meta name='robots' content='noindex,nofollow'><meta name='theme-color' content='#071225'>
<link rel='manifest' href='/manifest.webmanifest'><link rel='apple-touch-icon' href='/icon.png'>
<title>MRD Rescue</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(160deg,#071225,#111b34);color:#eef6ff;font-family:Arial,sans-serif;min-height:100vh}}
.wrap{{max-width:760px;margin:auto;padding:18px 16px 34px}}header{{display:flex;align-items:center;gap:14px;margin:6px 0 18px}}
.logo{{width:62px;height:62px;border-radius:18px;background:#172747;padding:8px;box-shadow:0 10px 28px #0007}}h1{{font-size:25px;margin:0}}.muted{{color:#91a4c2;margin:5px 0}}
.hero,.card,.panel{{background:#13213d;border:1px solid #29436b;border-radius:20px;box-shadow:0 14px 35px #0005}}
.hero{{padding:20px;margin-bottom:13px;display:flex;justify-content:space-between;align-items:center;gap:12px}}.state{{font-size:23px;font-weight:900}}
.ok{{color:#22c55e}}.bad{{color:#ef4444}}.warn{{color:#f59e0b}}.pulse{{width:13px;height:13px;border-radius:50%;background:#22c55e;box-shadow:0 0 16px #22c55e}}
.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}}.card{{padding:15px;min-height:94px}}.label{{font-size:11px;color:#7f94b5;font-weight:800;letter-spacing:.5px}}
.value{{font-size:18px;font-weight:900;margin-top:9px}}.actions{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:14px 0}}
button,.link{{border:0;border-radius:15px;padding:16px 10px;color:white;font-size:14px;font-weight:900;text-align:center;text-decoration:none;background:#1d4ed8}}
button:disabled{{opacity:.45}}.ai{{background:#6d28d9}}.restore{{background:#9a3412}}.green{{background:#166534}}.teal{{background:#0f766e}}.slate{{background:#334155}}
.panel{{padding:17px;margin-top:13px}}#activity{{font:12px/1.55 Consolas,monospace;white-space:pre-wrap;color:#bcd0eb;max-height:170px;overflow:auto;background:#091329;border-radius:13px;padding:12px}}
#install-help{{display:none;background:#0d2a2c;border:1px solid #1e6465;border-radius:13px;padding:12px;margin-top:10px;color:#b7ece8}}
@media(min-width:650px){{.grid{{grid-template-columns:repeat(3,1fr)}}.actions{{grid-template-columns:repeat(3,1fr)}}}}
</style></head><body><main class='wrap'>
<header><img class='logo' src='/icon.png' alt='MRD'><div><h1>MRD RESCUE</h1><p class='muted'>Centro seguro de recuperación</p></div></header>
<section class='hero'><div><div id='state' class='state'>COMPROBANDO…</div><p id='detail' class='muted'>Validando este móvil</p></div><div id='pulse' class='pulse'></div></section>
<section class='grid'>
<div class='card'><div class='label'>APLICACIÓN</div><div id='app' class='value'>—</div></div>
<div class='card'><div class='label'>ACCESO PÚBLICO</div><div id='public' class='value'>—</div></div>
<div class='card'><div class='label'>DATOS</div><div id='db' class='value'>—</div></div>
<div class='card'><div class='label'>DISCO</div><div id='disk' class='value'>—</div></div>
<div class='card'><div class='label'>MEMORIA</div><div id='ram' class='value'>—</div></div>
<div class='card'><div class='label'>OLLAMA IA</div><div id='ai' class='value'>—</div></div>
</section>
<section class='actions'>
<button id='power' class='green' disabled>ENCENDER</button><button id='basic' disabled>REINICIAR Y REPARAR</button>
<button id='repair' class='ai' disabled>REPARACIÓN IA SEGURA</button><button id='restore' class='restore' disabled>RECUPERAR VERSIÓN ESTABLE</button>
<button id='diagnose' class='slate' disabled>DIAGNOSTICAR</button><a class='link teal' href='https://app.iasmrd.com/'>ABRIR MRD</a>
</section>
<section class='panel'><b>Actividad reciente</b><pre id='activity'>Esperando datos…</pre></section>
<section class='panel'><button id='install' class='teal'>INSTALAR MRD RESCUE</button><div id='install-help'>Android: menú de Chrome → Instalar aplicación. iPhone: Safari → Compartir → Añadir a pantalla de inicio.</div></section>
</main><script>
const token=new URLSearchParams(location.hash.slice(1)).get('token')||'';const headers={{'X-MRD-Rescue-Token':token}};
const ids=['power','basic','repair','restore','diagnose'];const byId=id=>document.getElementById(id);
async function enroll(){{if(!token)return;const r=await fetch('/enroll',{{method:'POST',headers}});if(r.ok)history.replaceState(null,'',location.pathname);}}
function val(id,text,good){{const e=byId(id);e.textContent=text;e.className='value '+(good===true?'ok':good===false?'bad':'warn');}}
async function refresh(){{try{{const r=await fetch('/status',{{headers,cache:'no-store'}}),d=await r.json();if(!r.ok)throw new Error(d.error||'Móvil no identificado');
byId('state').textContent=d.active?'SISTEMA FUNCIONANDO':'NECESITA ATENCIÓN';byId('state').className='state '+(d.active?'ok':'bad');byId('detail').textContent='Servicio '+d.service+' · salud '+(d.health||'sin respuesta')+' · '+d.timestamp;
byId('pulse').style.background=d.active?'#22c55e':'#ef4444';val('app',d.active?'ACTIVA':'DETENIDA',d.active);val('public',d.public_ok?'ACTIVO':'REVISAR',d.public_ok);val('db',(d.db_ok?'OK · ':'REVISAR · ')+d.database_mb+' MB',d.db_ok);val('disk',d.disk_percent+'% usado',d.disk_percent<85);val('ram',d.ram_percent+'% usada',d.ram_percent<85);val('ai',d.ai_ok?'LISTA · '+String(d.ai_mode).toUpperCase():'NO DISPONIBLE',d.ai_ok);
ids.forEach(id=>byId(id).disabled=d.busy);byId('restore').disabled=d.busy||!d.stable_available;byId('activity').textContent=(d.activity||[]).join('\\n')||'Sin incidencias recientes.';}}
catch(e){{byId('state').textContent='MÓVIL NO IDENTIFICADO';byId('state').className='state bad';byId('detail').textContent=e.message;ids.forEach(id=>byId(id).disabled=true);}}}}
async function action(path,confirmText){{if(confirmText&&!confirm(confirmText))return;ids.forEach(id=>byId(id).disabled=true);const r=await fetch(path,{{method:'POST',headers}}),d=await r.json();byId('detail').textContent=d.message||d.error||'Solicitud enviada';setTimeout(refresh,1200);}}
byId('power').onclick=()=>action('/power-on');byId('basic').onclick=()=>action('/repair-basic');byId('repair').onclick=()=>action('/repair');byId('diagnose').onclick=()=>action('/diagnose');byId('restore').onclick=()=>action('/restore','Se creará un backup antes. ¿Recuperar la versión estable?');
let prompt=null;addEventListener('beforeinstallprompt',e=>{{e.preventDefault();prompt=e;}});byId('install').onclick=async()=>{{if(prompt){{await prompt.prompt();prompt=null}}else byId('install-help').style.display='block';}};
if(matchMedia('(display-mode: standalone)').matches)byId('install').closest('.panel').style.display='none';if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js');enroll().then(refresh);setInterval(refresh,15000);
</script></body></html>""".replace("{{", "{").replace("}}", "}")
                self._send(200, body)

            def do_POST(self):
                path = urlparse(self.path).path
                if path == "/enroll":
                    if not self._authorized() or not self._origin_allowed():
                        self._send_json(403, {"ok": False, "error": "Acceso no autorizado"})
                        return
                    payload = json.dumps(
                        {"ok": True, "message": "Móvil autorizado"},
                        ensure_ascii=False
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header(
                        "Set-Cookie", "mrd_rescue=" + controller.token +
                        "; Path=/; Max-Age=31536000; Secure; HttpOnly; SameSite=Strict"
                    )
                    self._security_headers()
                    self.end_headers()
                    try:
                        self.wfile.write(payload)
                    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                        return
                    return
                actions = {
                    "/power-on": ("_on_power_on", "Encendido iniciado"),
                    "/repair-basic": ("_on_repair", "Reinicio y reparación iniciados"),
                    "/repair": ("_on_ai_repair", "Reparación IA iniciada"),
                    "/restore": ("_on_remote_restore",
                                 "Recuperación estable iniciada con backup previo"),
                    "/diagnose": ("_on_diagnose", "Diagnóstico iniciado"),
                }
                if path not in actions or not self._authorized():
                    self._send_json(403, {"ok": False, "error": "Acceso no autorizado"})
                    return
                if not self._origin_allowed():
                    self._send_json(403, {"ok": False, "error": "Origen no autorizado"})
                    return
                if controller.app._busy:
                    self._send_json(409, {"ok": False, "error": "Ya hay una reparación en curso"})
                    return
                if time.time() - controller.last_action_at < 30:
                    self._send_json(429, {"ok": False, "error": "Espera antes de repetir la acción"})
                    return
                controller.last_action_at = time.time()
                method_name, message = actions[path]
                action = getattr(controller.app, method_name, None)
                if not callable(action):
                    self._send_json(503, {"ok": False, "error": "Acción no disponible"})
                    return
                controller.app.root.after(0, action)
                self._send_json(202, {"ok": True, "message": message})

        try:
            # Solo escucha en este PC; Cloudflare es la única entrada exterior.
            self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
            self.port = self.httpd.server_port
            self.url = f"{self.public_origin}/#token={self.token}"
            self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True,
                                           name="mrd-rescue-mobile")
            self.thread.start()
            return True, self.url
        except Exception as exc:
            return False, str(exc)

    def _ensure_private_firewall_rule(self):
        if sys.platform != "win32":
            return
        name = "MRD Rescue Movil"
        shown = _run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"])
        if shown.returncode == 0:
            return
        _run([
            "netsh", "advfirewall", "firewall", "add", "rule", f"name={name}",
            "dir=in", "action=allow", "protocol=TCP", f"localport={self.port}",
            "profile=private", "remoteip=localsubnet",
        ])

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()

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
        self.root.title("MRD RESCUE — Centro Seguro de Recuperación")
        self.root.configure(bg=self.COLOR_BG)
        self.root.resizable(True, True)
        self.root.minsize(1100, 680)

        # State
        self._last_diag: dict = {}
        self._last_repair_actions: list = []
        self._last_report_path = None
        self._busy = False

        asset_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        self._icon_path = os.path.join(asset_dir, "mrd_rescue.ico")
        self._logo_path = os.path.join(asset_dir, "mrd_rescue.png")
        try:
            self.root.iconbitmap(self._icon_path)
        except Exception:
            try:
                self._window_icon = tk.PhotoImage(file=self._logo_path)
                self.root.iconphoto(True, self._window_icon)
            except Exception:
                self._window_icon = None

        self._build_ui()
        self._mobile = MobileControlServer(self)
        mobile_ok, mobile_message = self._mobile.start()
        if mobile_ok:
            self.log(f"Panel móvil seguro preparado: {self._mobile.public_origin}", "ok")
        else:
            self.log(f"Panel móvil no disponible: {mobile_message}", "warn")
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

        # ---- Resumen visual independiente de MRD ----
        summary = tk.Frame(root, bg=self.COLOR_BG)
        summary.pack(fill=tk.X, padx=10, pady=8)
        self._summary_labels = {}
        for key, title in (("app", "APLICACIÓN"), ("tunnel", "ACCESO PÚBLICO"),
                           ("db", "DATOS"), ("disk", "DISCO"), ("ram", "MEMORIA"),
                           ("ai", "OLLAMA IA")):
            card = tk.Frame(summary, bg=self.COLOR_PANEL, bd=0, padx=12, pady=8)
            card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=3)
            tk.Label(card, text=title, bg=self.COLOR_PANEL, fg=self.COLOR_GRAY,
                     font=("Segoe UI", 8, "bold")).pack(anchor="w")
            value = tk.Label(card, text="Comprobando…", bg=self.COLOR_PANEL,
                             fg=self.COLOR_WHITE, font=("Segoe UI", 11, "bold"))
            value.pack(anchor="w", pady=(3, 0))
            self._summary_labels[key] = value

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
        primary_frame = tk.Frame(btn_frame, bg=self.COLOR_BG)
        primary_frame.pack(fill=tk.X, pady=(0, 6))
        secondary_frame = tk.Frame(btn_frame, bg=self.COLOR_BG)
        secondary_frame.pack(fill=tk.X)
        restore_frame = tk.Frame(btn_frame, bg=self.COLOR_BG)
        restore_frame.pack(fill=tk.X, pady=(6, 0))

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
            secondary_frame, text="Diagnosticar", command=self._on_diagnose, **btn_cfg
        )
        self._btn_repair = tk.Button(
            primary_frame, text="REINICIAR Y REPARAR", command=self._on_repair, **btn_cfg
        )
        self._btn_ai = tk.Button(
            primary_frame, text="REPARACIÓN IA SEGURA", command=self._on_ai_repair, **btn_cfg
        )
        self._btn_on = tk.Button(
            primary_frame, text="ENCENDER", command=self._on_power_on, **btn_cfg
        )
        self._btn_off = tk.Button(
            primary_frame, text="APAGAR", command=self._on_power_off, **btn_cfg
        )
        self._btn_open = tk.Button(
            primary_frame, text="ABRIR MRD PÚBLICO", command=self._on_open_public, **btn_cfg
        )
        self._btn_mobile = tk.Button(
            secondary_frame, text="CONTROL DESDE MÓVIL", command=self._on_mobile, **btn_cfg
        )
        self._btn_on.configure(bg="#166534", activebackground="#15803d")
        self._btn_repair.configure(bg="#1d4ed8", activebackground="#2563eb")
        self._btn_ai.configure(bg="#6d28d9", activebackground="#7c3aed")
        self._btn_off.configure(bg="#991b1b", activebackground="#b91c1c")
        self._btn_open.configure(bg="#0f766e", activebackground="#0d9488")
        self._btn_mobile.configure(bg="#334155", activebackground="#475569")
        self._btn_report = tk.Button(
            secondary_frame, text="Abrir informe", command=self._on_open_report,
            state=tk.DISABLED, **btn_cfg
        )
        # Fix 4: button now calls _restore_stable directly
        self._btn_restore = tk.Button(
            restore_frame, text="RECUPERAR ÚLTIMA VERSIÓN ESTABLE (CREA BACKUP ANTES)",
            command=self._restore_stable, **btn_cfg
        )
        self._btn_close = tk.Button(
            secondary_frame, text="Cerrar", command=self._on_close, **btn_cfg
        )

        for btn in (self._btn_on, self._btn_repair, self._btn_ai,
                    self._btn_open, self._btn_off):
            btn.pack(side=tk.LEFT, padx=(0, 6), fill=tk.X, expand=True)
        for btn in (self._btn_mobile, self._btn_diag, self._btn_report, self._btn_close):
            btn.pack(side=tk.LEFT, padx=(0, 6))
        self._btn_restore.configure(bg="#9a3412", activebackground="#c2410c")
        self._btn_restore.pack(fill=tk.X)

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
        for btn in (self._btn_diag, self._btn_repair, self._btn_restore,
                    self._btn_on, self._btn_ai, self._btn_off):
            btn.configure(state=tk.DISABLED)
        self._progress.start(12)

    def _stop_busy(self):
        self._busy = False
        for btn in (self._btn_diag, self._btn_repair, self._btn_restore,
                    self._btn_on, self._btn_ai, self._btn_off):
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
        capacity = diag.get("capacity", {})
        tunnels = diag.get("tunnels", [])
        public = diag.get("public", {})
        proc = diag["process"]

        state = svc.get("state", "UNKNOWN")
        # Fix 6: /health válido solo si ok Y content_ok
        health_ok = http["/health"]["ok"] and http["/health"]["content_ok"]
        scan_ok = http["/scan"]["ok"]

        # Determine overall status
        # Fix 6: /health válido solo si ok Y content_ok
        health_ok = http["/health"]["ok"] and http["/health"]["content_ok"]
        public_ok = bool(public.get("ok") and public.get("content_ok"))
        if state == "RUNNING" and health_ok and public_ok:
            self.set_status("green", "Servicio ACTIVO — /health OK")
        elif state == "RUNNING" and health_ok:
            self.set_status(
                "yellow",
                "Servidor activo — acceso público sin confirmar; disponible el respaldo local"
            )
        elif state == "RUNNING" and not health_ok:
            self.set_status("yellow", "Servicio en ejecución pero /health no responde")
        else:
            self.set_status("red", f"Servicio {state} — intervención requerida")

        def card(key, text, color):
            self._summary_labels[key].configure(text=text, fg=color)

        card("app", "ACTIVA" if state == "RUNNING" and health_ok else "DETENIDA",
             self.COLOR_GREEN if state == "RUNNING" and health_ok else self.COLOR_RED)
        tunnel_running = any(t.get("state") == "RUNNING" for t in tunnels)
        tunnel_text = ("ACTIVO" if tunnel_running and public_ok else
                       "RUTA PC BLOQUEADA" if tunnel_running else "DETENIDO")
        tunnel_color = (self.COLOR_GREEN if tunnel_running and public_ok else
                        self.COLOR_YELLOW if tunnel_running else self.COLOR_RED)
        card("tunnel", tunnel_text, tunnel_color)
        card("db", f"OK · {capacity.get('database_mb', 0)} MB" if db.get("integrity_ok") else "REVISAR",
             self.COLOR_GREEN if db.get("integrity_ok") else self.COLOR_RED)
        disk_used = disk.get("used_percent")
        card("disk", f"{disk_used}% usado" if disk_used is not None else "N/D",
             self.COLOR_GREEN if disk.get("free_ok") else self.COLOR_YELLOW)
        memory = capacity.get("memory", {})
        ram_used = memory.get("used_percent")
        card("ram", f"{ram_used}% usado" if ram_used is not None else "N/D",
             self.COLOR_YELLOW if ram_used is not None and ram_used >= 85 else self.COLOR_GREEN)
        ollama = diag.get("ollama", {})
        card("ai", (f"LISTA · {str(ollama.get('mode', '')).upper()}"
                    if ollama.get("ok") else "NO DISPONIBLE"),
             self.COLOR_GREEN if ollama.get("ok") else self.COLOR_YELLOW)

        level = "ok" if state == "RUNNING" else "error"
        self.log(f"Servicio: {state} | PID(sc): {svc.get('pid_from_sc') or 'N/A'}", level)
        self.log(f"Commit: {diag.get('commit', 'N/A')}", "info")
        self.log(f"Puerto {CONFIG['app_port']}: PID={proc.get('port_pid') or 'libre'}", "info")

        for path, result in http.items():
            lvl = "ok" if result["ok"] else "error"
            code = result.get("status_code") or result.get("error", "—")
            self.log(f"HTTP {path}: {code}", lvl)
        if public_ok:
            self.log(f"Acceso público desde este PC: OK ({public.get('status_code')})", "ok")
        else:
            self.log(
                "Acceso público desde este PC: NO DISPONIBLE. "
                "El servidor local sigue activo y conserva el respaldo de emergencia.", "warn"
            )

        db_lvl = "ok" if db.get("integrity_ok") else "error"
        self.log(
            f"DB: existe={db.get('exists')} legible={db.get('readable')} "
            f"integridad={db.get('integrity_result', '?')}",
            db_lvl,
        )
        if ollama.get("ok"):
            self.log(
                f"Ollama: activo · motor {ollama.get('mode')} · modelo {ollama.get('selected')}",
                "ok"
            )
        else:
            self.log(f"Ollama: no disponible · {ollama.get('error') or 'sin modelo'}", "warn")

        disk_lvl = "ok" if disk.get("free_ok") else "warn"
        self.log(f"Disco: {disk.get('free_gb', '?')} GB libres | "
                 f"escritura={'OK' if disk.get('write_ok') else 'ERROR'}", disk_lvl)
        self.log(
            f"Capacidad: RAM {memory.get('used_gb', '?')}/{memory.get('total_gb', '?')} GB | "
            f"BD {capacity.get('database_mb', '?')} MB | adjuntos {capacity.get('uploads_mb', '?')} MB | "
            f"{capacity.get('backup_count', 0)} copias ({capacity.get('backups_mb', 0)} MB)", "info"
        )

        errors = diag["logs"].get("error_lines", [])
        if errors:
            self.log(f"Últimos errores en log ({len(errors)} líneas):", "warn")
            for line in errors[-5:]:
                self.log(f"  {line}", "warn")
        else:
            self.log("Sin errores recientes en log.", "ok")

        self.log("Diagnóstico completado.", "info")

    # ------------------------------------------------------------------
    # Accesos directos
    # ------------------------------------------------------------------

    def _on_open_public(self):
        ok, detail = open_public_mrd()
        if ok:
            self.log("MRD abierta por el acceso público oficial.", "ok")
        else:
            self.log(f"No se pudo abrir el acceso público de MRD: {detail}", "error")

    def _on_open_local(self):
        ok, detail = open_local_mrd()
        if ok:
            self.log("MRD abierta por acceso local seguro.", "ok")
        else:
            self.log(f"No se pudo abrir MRD: {detail}", "error")

    def _on_mobile(self):
        if not getattr(self, "_mobile", None):
            messagebox.showerror("Control móvil", "El panel móvil no está disponible.")
            return
        try:
            import qrcode
            os.makedirs(CONFIG["report_dir"], exist_ok=True)
            qr_path = os.path.join(CONFIG["report_dir"], "mrd_rescue_mobile.png")
            qrcode.make(self._mobile.url).save(qr_path)
            dialog = tk.Toplevel(self.root)
            dialog.title("MRD Rescue — Control desde móvil")
            dialog.configure(bg=self.COLOR_BG)
            dialog.resizable(False, False)
            try:
                dialog.iconbitmap(self._icon_path)
            except Exception:
                pass
            tk.Label(dialog, text="Escanea con el móvil", bg=self.COLOR_BG,
                     fg=self.COLOR_WHITE, font=("Segoe UI", 18, "bold")).pack(pady=(18, 4))
            tk.Label(dialog, text="Funciona desde cualquier lugar con conexión a Internet",
                     bg=self.COLOR_BG, fg=self.COLOR_GRAY,
                     font=("Segoe UI", 11)).pack(pady=(0, 10))
            qr_image = tk.PhotoImage(file=qr_path)
            qr_label = tk.Label(dialog, image=qr_image, bg="white", padx=10, pady=10)
            qr_label.image = qr_image
            qr_label.pack(padx=24, pady=8)
            tk.Label(dialog, text=self._mobile.public_origin,
                     bg=self.COLOR_BG, fg=self.COLOR_GREEN,
                     font=("Segoe UI", 11, "bold")).pack(pady=(6, 2))
            tk.Label(dialog, text="Escanéalo una sola vez: este móvil quedará autorizado.",
                     bg=self.COLOR_BG, fg=self.COLOR_GRAY,
                     font=("Segoe UI", 9)).pack(pady=(0, 18))
        except Exception as exc:
            messagebox.showerror("Control móvil", f"No se pudo generar el QR:\n{exc}")

    # ------------------------------------------------------------------
    # Encendido / apagado independiente
    # ------------------------------------------------------------------

    def _show_success_or_local_fallback(self, diag, success_text):
        public = diag.get("public", {})
        if public.get("ok") and public.get("content_ok"):
            self.set_status("green", success_text)
            return
        self.set_status(
            "yellow",
            "Servidor reparado — Cloudflare no abre en este PC; abriendo acceso local"
        )
        self.log(
            "El servidor está reparado, pero la ruta pública de este PC sigue bloqueada. "
            "Se abre temporalmente MRD por la conexión local de emergencia.", "warn"
        )
        self.root.after(0, self._on_open_local)

    def _on_power_on(self):
        if self._busy:
            return
        self.log("Encendiendo MRD y reactivando el vigilante 24/7…", "info")
        self._start_busy()
        self.set_status("yellow", "Encendiendo sistema…")
        threading.Thread(target=self._power_on_worker, daemon=True).start()

    def _power_on_worker(self):
        try:
            result = power_on(progress_cb=lambda msg, lvl: self.log(msg, lvl))
            self._last_diag = result["final_diag"]
            self.root.after(0, lambda: self._display_diag(self._last_diag))
            if result["success"]:
                self._show_success_or_local_fallback(
                    self._last_diag, "Sistema encendido y protegido"
                )
            else:
                self.set_status("red", "No se pudo encender — use Reiniciar y reparar")
        except Exception as exc:
            self.log(f"Error al encender: {exc}", "error")
            self.set_status("red", "Error al encender")
        finally:
            self.root.after(0, self._stop_busy)

    def _on_power_off(self):
        if self._busy:
            return
        if not messagebox.askyesno(
            "Apagar MRD Tool Control",
            "Se cerrará el acceso al programa hasta que pulses ENCENDER.\n\n"
            "Los datos no se borrarán. ¿Quieres apagarlo?"
        ):
            return
        self._start_busy()
        self.set_status("yellow", "Apagando de forma segura…")
        threading.Thread(target=self._power_off_worker, daemon=True).start()

    def _power_off_worker(self):
        try:
            result = power_off(progress_cb=lambda msg, lvl: self.log(msg, lvl))
            if result["success"]:
                self.set_status("red", "Sistema apagado manualmente — datos protegidos")
                self.root.after(0, lambda: self._summary_labels["app"].configure(
                    text="APAGADA", fg=self.COLOR_RED))
                self.root.after(0, lambda: self._summary_labels["tunnel"].configure(
                    text="EN ESPERA", fg=self.COLOR_YELLOW))
            else:
                self.set_status("red", "Apagado incompleto — revise el informe")
        except Exception as exc:
            self.log(f"Error al apagar: {exc}", "error")
            self.set_status("red", "Error al apagar")
        finally:
            self.root.after(0, self._stop_busy)

    # ------------------------------------------------------------------
    # Reparación asistida por Ollama
    # ------------------------------------------------------------------

    def _on_ai_repair(self):
        if self._busy:
            return
        self.log("═" * 60, "info")
        self.log("Iniciando reparación asistida por Ollama…", "warn")
        self._start_busy()
        self.set_status("yellow", "Ollama analiza y el motor seguro repara…")
        threading.Thread(target=self._ai_repair_worker, daemon=True).start()

    def _ai_repair_worker(self):
        try:
            result = run_ai_repair(progress_cb=lambda msg, lvl: self.log(msg, lvl))
            self._last_repair_actions = result["actions"]
            self._last_diag = result["final_diag"]
            path = generate_report(self._last_diag, self._last_repair_actions)
            self._last_report_path = path
            self.root.after(0, lambda: self._btn_report.configure(state=tk.NORMAL))
            self.root.after(0, lambda: self._display_diag(self._last_diag))
            if result["success"]:
                self._show_success_or_local_fallback(
                    self._last_diag, "Reparación IA completada — sistema verificado"
                )
                self.log("MRD RESCUE confirma que el servidor vuelve a estar operativo.", "ok")
            else:
                self.set_status("red", "Protección activada — no se aplicaron acciones inseguras")
                self.log(f"Informe seguro guardado en: {path}", "warn")
        except Exception as exc:
            self.log(f"Error en reparación IA: {exc}", "error")
            self.set_status("red", "La reparación IA no pudo completarse")
        finally:
            self.root.after(0, self._stop_busy)

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
            self.root.after(0, lambda: self._display_diag(self._last_diag))

            if result["success"]:
                self._show_success_or_local_fallback(
                    self._last_diag, "Recuperación exitosa — aplicación activa"
                )
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
    # Restauración segura de la última versión estable
    # ------------------------------------------------------------------

    def _restore_stable(self):
        if self._busy:
            return
        if not os.path.isfile(CONFIG["stable_snapshot_path"]):
            messagebox.showerror(
                "No existe un punto estable",
                "Todavía no hay una versión estable preparada para recuperar."
            )
            return
        if not messagebox.askyesno(
            "Recuperar MRD",
            "Se creará primero un backup completo de seguridad.\n\n"
            "Después se restaurará únicamente el código estable. El inventario, "
            "la base de datos, los documentos y las fotografías no se sustituirán.\n\n"
            "Si la restauración falla, el código anterior volverá automáticamente.\n\n"
            "¿Quieres continuar?"
        ):
            return
        self.log("═" * 60, "info")
        self.log("Creando backup y preparando recuperación estable…", "warn")
        self._start_busy()
        self.set_status("yellow", "Protegiendo datos antes de recuperar…")
        threading.Thread(target=self._restore_stable_worker, daemon=True).start()

    def _on_remote_restore(self):
        """La PWA ya exige confirmación, credencial y origen válido."""
        if self._busy:
            return
        self.log("═" * 60, "info")
        self.log("Recuperación estable solicitada desde el móvil autorizado…", "warn")
        self._start_busy()
        self.set_status("yellow", "Protegiendo datos antes de recuperar…")
        threading.Thread(target=self._restore_stable_worker, daemon=True).start()

    def _restore_stable_worker(self):
        try:
            result = restore_stable_version(
                progress_cb=lambda msg, lvl: self.log(msg, lvl)
            )
            self._last_repair_actions = result["actions"]
            self._last_diag = result["final_diag"]
            path = generate_report(self._last_diag, self._last_repair_actions)
            self._last_report_path = path
            self.root.after(0, lambda: self._btn_report.configure(state=tk.NORMAL))
            self.root.after(0, lambda: self._display_diag(self._last_diag))
            if result["success"]:
                self._show_success_or_local_fallback(
                    self._last_diag, "Versión estable recuperada — datos intactos"
                )
                self.log(f"Backup previo conservado en: {result['backup']['dir']}", "ok")
            else:
                self.set_status("red", "Restauración cancelada — código anterior recuperado")
                self.log(
                    f"Se volvió al código anterior. Backup: {result['backup']['dir']}",
                    "warn"
                )
        except Exception as exc:
            self.log(f"No se pudo iniciar la recuperación estable: {exc}", "error")
            self.set_status("red", "Recuperación estable no ejecutada")
        finally:
            self.root.after(0, self._stop_busy)

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def _on_close(self):
        try:
            if getattr(self, "_mobile", None):
                self._mobile.stop()
        except Exception:
            pass
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

    configure_windows_app_identity()
    root = tk.Tk()
    root.geometry("1220x780")
    app = RecoveryApp(root)  # noqa: F841

    try:
        root.mainloop()
    finally:
        release_lock()


if __name__ == "__main__":
    main()
