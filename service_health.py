"""
MRD TOOL CONTROL — Módulo de Health Check del Servicio
Sprint 5.3 — Servicios de Producción
v1.9.3-alpha

Comprueba: DB, disco, RAM, puerto, uploads, backups, logs.
Nunca registra contraseñas, tokens ni datos sensibles.
"""
from __future__ import annotations

import os
import shutil
import socket
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent


# ─── Resultado de un check individual ─────────────────────────────────────────

class HealthResult:
    def __init__(self, ok: bool, detail: str, value: Any = None):
        self.ok = ok
        self.detail = detail
        self.value = value

    def to_dict(self) -> dict:
        return {
            "status": "ok" if self.ok else "error",
            "detail": self.detail,
            **({"value": self.value} if self.value is not None else {}),
        }


# ─── Checks individuales ──────────────────────────────────────────────────────

def check_database(db_path: Path | None = None) -> HealthResult:
    """Verifica que la base de datos SQLite sea accesible y responda."""
    try:
        import sqlite3
        if db_path is None:
            from config import DATA_DIR
            db_path = DATA_DIR / "mrd_tool.db"

        if not db_path.exists():
            return HealthResult(False, f"Archivo DB no encontrado: {db_path.name}")

        with sqlite3.connect(str(db_path), timeout=5) as conn:
            conn.execute("SELECT 1").fetchone()
            conn.execute("PRAGMA integrity_check").fetchone()

        size_kb = db_path.stat().st_size // 1024
        return HealthResult(True, f"Conexión activa — {size_kb} KB", value=size_kb)
    except Exception as exc:
        return HealthResult(False, f"Error DB: {exc}")


def check_disk_space(path: Path | None = None, min_free_gb: float = 1.0) -> HealthResult:
    """Verifica espacio libre en disco."""
    try:
        if path is None:
            path = BASE_DIR
        usage = shutil.disk_usage(str(path))
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        used_pct = (usage.used / usage.total) * 100
        detail = f"{free_gb:.1f} GB libres de {total_gb:.1f} GB ({used_pct:.0f}% usado)"
        ok = free_gb >= min_free_gb
        if not ok:
            detail = f"ALERTA: solo {free_gb:.1f} GB libres (mínimo {min_free_gb} GB)"
        return HealthResult(ok, detail, value=round(free_gb, 2))
    except Exception as exc:
        return HealthResult(False, f"Error disco: {exc}")


def check_memory() -> HealthResult:
    """Verifica uso de RAM del sistema."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        used_mb = vm.used / (1024 ** 2)
        total_mb = vm.total / (1024 ** 2)
        pct = vm.percent
        detail = f"{used_mb:.0f} MB usados de {total_mb:.0f} MB ({pct:.0f}%)"
        ok = pct < 90  # alerta si >90%
        if not ok:
            detail = f"ALERTA: RAM al {pct:.0f}% ({used_mb:.0f}/{total_mb:.0f} MB)"
        return HealthResult(ok, detail, value=pct)
    except ImportError:
        return HealthResult(True, "psutil no disponible — check omitido")
    except Exception as exc:
        return HealthResult(False, f"Error RAM: {exc}")


def check_port(port: int = 8000, host: str = "127.0.0.1", timeout: float = 3.0) -> HealthResult:
    """Verifica que uvicorn esté escuchando en el puerto configurado."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return HealthResult(True, f"Puerto {port} activo en {host}")
    except (ConnectionRefusedError, socket.timeout, OSError) as exc:
        return HealthResult(False, f"Puerto {port} no disponible: {exc}")


def check_directory(path: Path, name: str, check_write: bool = True) -> HealthResult:
    """Verifica que un directorio exista y sea escribible."""
    try:
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            return HealthResult(True, f"{name}: creado automáticamente")
        if not path.is_dir():
            return HealthResult(False, f"{name}: existe pero no es un directorio")
        if check_write:
            test_file = path / ".write_test"
            test_file.touch()
            test_file.unlink()
        file_count = sum(1 for _ in path.iterdir())
        return HealthResult(True, f"{name}: OK ({file_count} archivos)", value=file_count)
    except PermissionError:
        return HealthResult(False, f"{name}: sin permisos de escritura")
    except Exception as exc:
        return HealthResult(False, f"{name}: {exc}")


def check_uploads() -> HealthResult:
    uploads = BASE_DIR / "uploads"
    return check_directory(uploads, "uploads")


def check_logs() -> HealthResult:
    logs = BASE_DIR / "logs"
    return check_directory(logs, "logs")


def check_backups() -> HealthResult:
    """Verifica directorio de backups y fecha del último backup."""
    backups = BASE_DIR / "backups"
    try:
        if not backups.exists():
            backups.mkdir(parents=True, exist_ok=True)
            return HealthResult(True, "backups: directorio creado")

        backup_files = sorted(
            [f for f in backups.iterdir() if f.is_file() and f.suffix in (".db", ".zip", ".bak")],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if not backup_files:
            return HealthResult(True, "backups: sin backups aún (OK en instalación nueva)")

        last = backup_files[0]
        age = datetime.now() - datetime.fromtimestamp(last.stat().st_mtime)
        ok = age.days < 7
        detail = f"Último backup: {last.name} — hace {age.days}d {age.seconds // 3600}h"
        if not ok:
            detail = f"ALERTA: backup antiguo ({age.days} días). {detail}"
        return HealthResult(ok, detail)
    except Exception as exc:
        return HealthResult(False, f"Error backups: {exc}")


def check_service_process() -> HealthResult:
    """Verifica si el proceso del servicio MRDToolControl está activo (Windows)."""
    try:
        import subprocess
        result = subprocess.run(
            ["sc.exe", "query", "MRDToolControl"],
            capture_output=True, text=True, timeout=5
        )
        if "RUNNING" in result.stdout:
            return HealthResult(True, "Servicio Windows activo (RUNNING)")
        elif "STOPPED" in result.stdout:
            return HealthResult(False, "Servicio Windows detenido (STOPPED)")
        else:
            return HealthResult(True, "Modo standalone (sin servicio Windows)")
    except FileNotFoundError:
        return HealthResult(True, "sc.exe no disponible — Linux/dev")
    except Exception as exc:
        return HealthResult(False, f"Error estado servicio: {exc}")


# ─── Comprobación global ──────────────────────────────────────────────────────

def run_all_checks(
    port: int = 8000,
    db_path: Path | None = None,
    min_free_gb: float = 1.0,
) -> dict:
    """
    Ejecuta todos los health checks y devuelve un dict consolidado.

    Returns:
        {
            "healthy": bool,
            "timestamp": ISO-8601,
            "checks": { nombre: {status, detail, ?value} }
        }
    """
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    results: dict[str, HealthResult] = {
        "database":   check_database(db_path),
        "disk_space": check_disk_space(min_free_gb=min_free_gb),
        "memory":     check_memory(),
        "port":       check_port(port),
        "uploads":    check_uploads(),
        "logs":       check_logs(),
        "backups":    check_backups(),
    }

    all_ok = all(r.ok for r in results.values())

    return {
        "healthy": all_ok,
        "timestamp": ts,
        "checks": {k: v.to_dict() for k, v in results.items()},
    }


def get_system_metrics() -> dict:
    """Devuelve métricas del sistema para el panel de servicio."""
    metrics: dict = {}
    try:
        import psutil
        metrics["cpu_percent"] = psutil.cpu_percent(interval=0.5)
        vm = psutil.virtual_memory()
        metrics["memory_used_mb"] = round(vm.used / (1024 ** 2), 1)
        metrics["memory_total_mb"] = round(vm.total / (1024 ** 2), 1)
        metrics["memory_percent"] = vm.percent
        metrics["disk_free_gb"] = round(shutil.disk_usage(str(BASE_DIR)).free / (1024 ** 3), 1)

        # Proceso uvicorn (buscar por nombre)
        for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_info", "create_time"]):
            try:
                if proc.info["name"] and "uvicorn" in proc.info["name"].lower():
                    metrics["uvicorn_pid"] = proc.info["pid"]
                    metrics["uvicorn_memory_mb"] = round(
                        proc.info["memory_info"].rss / (1024 ** 2), 1
                    )
                    metrics["uvicorn_started"] = datetime.fromtimestamp(
                        proc.info["create_time"]
                    ).isoformat(timespec="seconds")
                    break
                # También buscar por cmdline
                cmdline = proc.info.get("cmdline") or []
                if any("uvicorn" in c for c in cmdline):
                    metrics["uvicorn_pid"] = proc.info["pid"]
                    metrics["uvicorn_memory_mb"] = round(
                        proc.info["memory_info"].rss / (1024 ** 2), 1
                    )
                    metrics["uvicorn_started"] = datetime.fromtimestamp(
                        proc.info["create_time"]
                    ).isoformat(timespec="seconds")
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except ImportError:
        metrics["psutil_error"] = "psutil no instalado"
    except Exception as exc:
        metrics["error"] = str(exc)

    return metrics
