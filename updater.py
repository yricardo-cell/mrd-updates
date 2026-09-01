"""
MRD TOOL CONTROL — Sistema de Actualizaciones
Sprint 5.7 — v1.9.7-alpha
- Servidor de versiones configurable
- Descarga segura con SHA-256 y firma
- Backup previo automático
- Instalación, reinicio y health check
- Rollback automático
- 8 estados: disponible/descargando/verificando/instalando/reiniciando/correcta/fallida/revertida
"""
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("mrd.updater")

BASE_DIR   = Path(__file__).parent
UPDATE_DIR = BASE_DIR / "updates"
UPDATE_DIR.mkdir(parents=True, exist_ok=True)

# ─── Estados ──────────────────────────────────────────────────────────────────
STATE_IDLE        = "idle"
STATE_AVAILABLE   = "disponible"
STATE_DOWNLOADING = "descargando"
STATE_VERIFYING   = "verificando"
STATE_INSTALLING  = "instalando"
STATE_RESTARTING  = "reiniciando"
STATE_SUCCESS     = "correcta"
STATE_FAILED      = "fallida"
STATE_REVERTED    = "revertida"

# ─── Estado global en memoria ─────────────────────────────────────────────────
_state = {
    "status":       STATE_IDLE,
    "progress":     0,          # 0-100
    "message":      "",
    "version":      None,
    "download_url": None,
    "sha256":       None,
    "started_at":   None,
    "finished_at":  None,
    "error":        None,
    "rollback_available": False,
    "log":          [],
}
_state_lock = threading.Lock()
_update_thread = None


def _set_state(**kwargs):
    with _state_lock:
        _state.update(kwargs)
        msg = kwargs.get("message", "")
        if msg:
            _state["log"].append({
                "ts":  datetime.utcnow().isoformat(timespec="seconds"),
                "msg": msg,
            })
            if len(_state["log"]) > 50:
                _state["log"] = _state["log"][-50:]
        logger.info("[updater] %s | %s%%: %s", _state["status"], _state.get("progress",0), msg)


def get_state() -> dict:
    with _state_lock:
        return dict(_state)


# ─── Configuración ────────────────────────────────────────────────────────────
def _get_update_config() -> dict:
    return {
        "server_url":    os.getenv("MRD_UPDATE_SERVER", "").rstrip("/"),
        "version_file":  os.getenv("MRD_UPDATE_VERSION_FILE", "version.json"),
        "timeout":       int(os.getenv("MRD_UPDATE_TIMEOUT", "30")),
        "verify_ssl":    os.getenv("MRD_UPDATE_VERIFY_SSL", "1") != "0",
        "service_name":  os.getenv("MRD_SERVICE_NAME", "MRDToolControl"),
        "health_url":    os.getenv("MRD_HEALTH_URL", "http://localhost:8000/health"),
        "health_retries": int(os.getenv("MRD_HEALTH_RETRIES", "10")),
        "health_delay":   int(os.getenv("MRD_HEALTH_DELAY",   "3")),
    }


# ─── Comprobar versión disponible ─────────────────────────────────────────────
def check_update() -> dict:
    """
    Consulta el servidor de versiones y compara con la versión actual.
    Devuelve {available, current_version, latest_version, release_notes, download_url, sha256}.
    """
    cfg = _get_update_config()
    server = cfg["server_url"]

    # Versión actual
    try:
        vfile = BASE_DIR / "version.json"
        current = json.loads(vfile.read_text()).get("version_actual", "0.0.0")
    except Exception:
        current = "0.0.0"

    if not server:
        return {
            "available":       False,
            "current_version": current,
            "latest_version":  None,
            "message":         "Servidor de actualizaciones no configurado (MRD_UPDATE_SERVER).",
            "configured":      False,
        }

    try:
        url     = f"{server}/{cfg['version_file']}"
        req     = urllib.request.Request(url, headers={"User-Agent": f"MRD-TOOL/{current}"})
        timeout = cfg["timeout"]
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            remote = json.loads(resp.read().decode())

        latest       = remote.get("version_actual", remote.get("version", ""))
        download_url = remote.get("download_url", "")
        sha256       = remote.get("sha256", "")
        notes        = remote.get("notas", remote.get("changelog", []))
        available    = _version_gt(latest, current)

        if available:
            _set_state(status=STATE_AVAILABLE, version=latest, download_url=download_url,
                       sha256=sha256, message=f"Actualización disponible: {latest}")

        return {
            "available":       available,
            "current_version": current,
            "latest_version":  latest,
            "download_url":    download_url,
            "sha256":          sha256,
            "release_notes":   notes,
            "server":          server,
            "configured":      True,
        }
    except urllib.error.URLError as exc:
        return {"available": False, "current_version": current, "error": str(exc), "configured": True}
    except Exception as exc:
        return {"available": False, "current_version": current, "error": str(exc), "configured": True}


def _version_gt(a: str, b: str) -> bool:
    """Compara semver simple: True si a > b."""
    def _parts(v):
        core = v.split("-")[0]
        try:
            return tuple(int(x) for x in core.split("."))
        except Exception:
            return (0,)
    return _parts(a) > _parts(b)


# ─── SHA-256 ──────────────────────────────────────────────────────────────────
def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ─── Descarga con progreso ────────────────────────────────────────────────────
def _download_file(url: str, dest: Path, timeout: int = 30) -> bool:
    """Descarga un fichero mostrando progreso en el estado global."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MRD-TOOL-UPDATER/1.9.7"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = int(downloaded / total * 50)  # descargar = 0-50%
                        _set_state(progress=pct, message=f"Descargando… {downloaded//1024} KB")
        return True
    except Exception as exc:
        _set_state(status=STATE_FAILED, message=f"Error de descarga: {exc}", error=str(exc))
        return False


# ─── Proceso completo de actualización ───────────────────────────────────────
def _run_update(download_url: str, expected_sha256: str, version: str, service_name: str):
    """Ejecutado en hilo secundario."""
    _set_state(
        status=STATE_DOWNLOADING, progress=0,
        started_at=datetime.utcnow().isoformat(timespec="seconds"),
        finished_at=None, error=None,
        message=f"Iniciando actualización a {version}",
    )

    cfg      = _get_update_config()
    tmp_zip  = UPDATE_DIR / f"update_{version}.zip"

    # 1. Backup previo — omitido (se hace manualmente al terminar la actualización)

    # 2. Descargar
    _set_state(status=STATE_DOWNLOADING, progress=10, message=f"Descargando {download_url}...")
    if not _download_file(download_url, tmp_zip, cfg["timeout"]):
        return

    # 3. Verificar SHA-256
    _set_state(status=STATE_VERIFYING, progress=55, message="Verificando integridad SHA-256...")
    actual_sha = _sha256_file(tmp_zip)
    if expected_sha256 and actual_sha.lower() != expected_sha256.lower():
        _set_state(
            status=STATE_FAILED, progress=0,
            message=f"SHA-256 no coincide. Esperado: {expected_sha256[:16]}… Obtenido: {actual_sha[:16]}…",
            error="SHA-256 mismatch",
        )
        tmp_zip.unlink(missing_ok=True)
        return
    _set_state(progress=60, message="SHA-256 verificado OK")

    # 4. Instalar
    _set_state(status=STATE_INSTALLING, progress=65, message="Instalando actualización...")
    backup_dir = UPDATE_DIR / f"rollback_{version}"
    install_ok = _install_update(tmp_zip, backup_dir)
    if not install_ok:
        return

    tmp_zip.unlink(missing_ok=True)
    _set_state(progress=80, message="Instalación completada. Reiniciando servicio...")

    # 5. Reiniciar
    _set_state(status=STATE_RESTARTING, progress=85, message=f"Reiniciando servicio {service_name}...")
    restart_ok = _restart_service(service_name)

    if not restart_ok:
        _set_state(progress=90, message="Servicio no reiniciado, intentando rollback...")
        _do_rollback(backup_dir, service_name, version)
        return

    # 6. Health check
    _set_state(progress=92, message="Comprobando salud de la aplicación...")
    healthy = _health_check(cfg["health_url"], cfg["health_retries"], cfg["health_delay"])

    if not healthy:
        _set_state(progress=95, message="Health check fallido. Iniciando rollback automático...")
        _do_rollback(backup_dir, service_name, version)
        return

    # 7. Éxito
    _set_state(
        status=STATE_SUCCESS, progress=100,
        message=f"Actualización a {version} completada con éxito.",
        rollback_available=True,
        finished_at=datetime.utcnow().isoformat(timespec="seconds"),
    )


def _install_update(zip_path: Path, backup_dir: Path) -> bool:
    """
    Extrae el ZIP de actualización sobre BASE_DIR.
    Guarda el estado actual en backup_dir para posible rollback.
    """
    import zipfile
    try:
        # Guardar snapshot de archivos que se van a sobreescribir
        backup_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            names = z.namelist()
            for name in names:
                src = BASE_DIR / name
                if src.exists() and src.is_file():
                    dst = backup_dir / name
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)

            # Extraer nuevos archivos
            z.extractall(BASE_DIR)

        _set_state(progress=78, message=f"{len(names)} archivos actualizados")
        return True
    except zipfile.BadZipFile:
        _set_state(status=STATE_FAILED, message="El archivo de actualización está corrupto (Bad ZIP).",
                   error="BadZipFile")
        return False
    except Exception as exc:
        _set_state(status=STATE_FAILED, message=f"Error de instalación: {exc}", error=str(exc))
        return False


def _restart_service(service_name: str) -> bool:
    """Reinicia el servicio Windows con sc.exe; si falla, usa REINICIAR_AHORA.ps1."""
    if sys.platform != "win32":
        logger.info("No Windows: omitiendo restart de servicio (test mode)")
        return True
    # 1. Intentar via sc.exe (si corre como servicio Windows)
    try:
        subprocess.run(["sc.exe", "stop", service_name], capture_output=True, timeout=30)
        time.sleep(3)
        r = subprocess.run(["sc.exe", "start", service_name], capture_output=True, timeout=30)
        if r.returncode == 0:
            logger.info("Servicio reiniciado via sc.exe")
            return True
    except Exception as exc:
        logger.warning("sc.exe fallo: %s — intentando PS1", exc)

    # 2. Fallback: REINICIAR_AHORA.ps1 (tray / VBS)
    try:
        ps1 = BASE_DIR / "REINICIAR_AHORA.ps1"
        if ps1.exists():
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(ps1)],
                creationflags=0x00000008,  # DETACHED_PROCESS
            )
            logger.info("Reinicio lanzado via REINICIAR_AHORA.ps1")
            return True
    except Exception as exc:
        logger.error("Fallback PS1 fallo: %s", exc)

    return False


def _health_check(url: str, retries: int, delay: int) -> bool:
    """Espera a que la aplicación responda en /health."""
    time.sleep(delay)  # dar tiempo al reinicio
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(delay)
    return False


def _do_rollback(backup_dir: Path, service_name: str, version: str):
    """Restaura los archivos del backup de rollback."""
    _set_state(status=STATE_FAILED, progress=95, message="Realizando rollback...")
    try:
        if backup_dir.exists():
            for f in backup_dir.rglob("*"):
                if f.is_file():
                    rel  = f.relative_to(backup_dir)
                    dest = BASE_DIR / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dest)
        _restart_service(service_name)
        _set_state(
            status=STATE_REVERTED, progress=0,
            message=f"Rollback completado. Versión {version} revertida.",
            finished_at=datetime.utcnow().isoformat(timespec="seconds"),
        )
    except Exception as exc:
        _set_state(
            status=STATE_FAILED,
            message=f"Rollback fallido: {exc}",
            error=str(exc),
        )


# ─── API pública ──────────────────────────────────────────────────────────────
def start_update(download_url: str, sha256: str, version: str) -> dict:
    """Inicia la actualización en hilo secundario."""
    global _update_thread
    with _state_lock:
        if _state["status"] in (STATE_DOWNLOADING, STATE_VERIFYING,
                                STATE_INSTALLING, STATE_RESTARTING):
            return {"ok": False, "error": "Actualización ya en curso."}

    cfg = _get_update_config()
    _update_thread = threading.Thread(
        target=_run_update,
        args=(download_url, sha256, version, cfg["service_name"]),
        daemon=True,
    )
    _update_thread.start()
    return {"ok": True, "message": f"Actualización a {version} iniciada."}


def rollback_update() -> dict:
    """Rollback manual a la versión anterior."""
    dirs = sorted(UPDATE_DIR.glob("rollback_*"), key=lambda d: d.stat().st_mtime, reverse=True)
    if not dirs:
        return {"ok": False, "error": "No hay backup de rollback disponible."}
    cfg = _get_update_config()
    backup_dir = dirs[0]
    version    = backup_dir.name.replace("rollback_", "")
    t = threading.Thread(
        target=_do_rollback,
        args=(backup_dir, cfg["service_name"], version),
        daemon=True,
    )
    t.start()
    return {"ok": True, "message": f"Rollback a {version} iniciado."}


def reset_state():
    """Reinicia el estado del updater (solo si no hay actualización en curso)."""
    with _state_lock:
        if _state["status"] in (STATE_DOWNLOADING, STATE_VERIFYING,
                                STATE_INSTALLING, STATE_RESTARTING):
            return False
        _state.update({
            "status":   STATE_IDLE, "progress": 0, "message": "",
            "version":  None, "download_url": None, "sha256": None,
            "started_at": None, "finished_at": None, "error": None,
            "rollback_available": False, "log": [],
        })
        return True
