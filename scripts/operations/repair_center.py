"""MRD Repair Center — reparación granular 24x7 y recuperación DR4.

Es deliberadamente independiente de FastAPI/SQLAlchemy para poder ejecutarse
cuando la aplicación no arranca. Los ficheros solo se restauran desde una
línea base sellada para la MISMA versión. DR4 diagnostica fallos de
integridad repetidos y busca una copia que pase PRAGMA quick_check y
contenga el esquema propio de MRD, dejando la base dañada en cuarentena,
pero la restauración automática está desactivada: nunca escribe sobre la
base de datos en vivo y siempre exige intervención manual.

El modo check (apply=False) es inocuo por construcción: diagnostica sin
mutar `database_failures` ni escribir state.json/status.json/historial.
Solo el modo repair (apply=True) persiste y actúa, y únicamente restaura
ficheros ante un fallo real (fichero ausente, o BD/health local caídos):
un hash distinto con la app sana puede ser una edición manual legítima aún
sin resellar y no se revierte en silencio.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


COMPONENT_FILES = {
    "nucleo": (
        "main.py", "auth.py", "config.py", "database.py", "models.py",
        "security.py",
    ),
    "inventario_almacen": (
        "warehouse_service.py", "mostrador_service.py", "stock_service.py",
        "inventario_service.py", "dotacion_service.py",
        "templates/herramientas.html", "templates/maquinaria.html",
        "templates/movimientos.html", "templates/mostrador.html",
    ),
    "escaner_qr": (
        "scanner_service.py", "codigos.py", "generador_codigos.py",
        "static/js/scanner_hid.js", "static/js/scanner.js", "static/js/mrd.js",
        "templates/scan.html",
        "templates/scanner_configurar.html",
    ),
    "portal_trabajador": (
        "worker_portal_service.py", "static/js/portal-worker.js",
        "static/css/portal-trabajador.css", "static/css/worker-login.css",
        "templates/portal_trabajador.html", "templates/portal_trabajador_login.html",
        "templates/portal_pin_inicial.html", "templates/solicitudes_trabajadores.html",
        "templates/operaciones_portal_trabajadores.html",
    ),
    "etiquetas_albaranes": (
        "albaran_service.py", "label_printer.py", "etiquetas_service.py",
        "templates/albaranes_salida.html", "templates/albaran_detalle.html",
        "templates/etiquetas.html", "templates/centro_etiquetas.html",
    ),
    "acceso_remoto": (
        "remote_access.py", "cloudflare_tunnel.py", "service_health.py",
        "windows_service.py",
    ),
    "continuidad": (
        "scripts/operations/watchdog_mrd.ps1",
        "scripts/operations/install_continuity_24x7.ps1",
        "scripts/operations/repair_center.py", "recovery_tool/mrd_recovery.py",
        "templates/servicio.html",
        "sentinel/__init__.py", "sentinel/service.py",
        "scripts/operations/install_sentinel.ps1",
        "scripts/operations/install_cloudflare_redundancy.ps1",
    ),
    "cache_pwa": ("static/js/sw.js", "version.json"),
}
REQUIRED_DIRS = ("data", "logs", "uploads", "backups", "cache", "temp")
MAX_HISTORY = 100

# Tablas mínimas que identifican una base de datos como propia de MRD Tool
# Control. DR4 las exige TODAS antes de restaurar un candidato: quick_check
# solo prueba que el fichero SQLite no está corrupto, no que sea una copia de
# la base de datos real (en backups/ conviven .db de pruebas y de otras
# tandas de trabajo con el mismo mtime reciente).
_MRD_SCHEMA_SIGNATURE = (
    "usuarios", "herramientas", "movimientos", "identificadores_globales",
    "config_sistema",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _inside(root: Path, candidate: Path) -> Path:
    root = root.resolve()
    candidate = candidate.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Ruta fuera del ámbito MRD: {candidate}")
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return default


def _write_json_atomic(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            Path(tmp_name).unlink(missing_ok=True)
        except OSError:
            pass


def _version(root: Path) -> str:
    value = _read_json(root / "version.json", {}).get("version_actual")
    return str(value or "").strip()


def _state_default() -> dict:
    return {
        "database_failures": 0,
        "last_run": None,
        "last_result": "sin_ejecutar",
        "last_repair": None,
        "last_dr4": None,
        "history": [],
    }


def _load_state(state_root: Path) -> dict:
    state = _state_default()
    loaded = _read_json(state_root / "state.json", {})
    if isinstance(loaded, dict):
        state.update({key: loaded[key] for key in state if key in loaded})
    if not isinstance(state.get("history"), list):
        state["history"] = []
    return state


def _record(state: dict, action: str, result: str, detail: str) -> None:
    state["history"] = (state.get("history") or [])[-(MAX_HISTORY - 1):] + [{
        "timestamp": _utc_now(), "action": action, "result": result,
        "detail": str(detail)[:500],
    }]


def seal_baseline(root: Path, state_root: Path) -> dict:
    version = _version(root)
    if not version:
        raise RuntimeError("version.json no contiene version_actual")
    baseline_dir = _inside(state_root, state_root / "baselines" / version)
    manifest_path = baseline_dir / "manifest.json"
    if manifest_path.exists():
        manifest = _read_json(manifest_path, {})
        if manifest.get("version") == version:
            return {"ok": True, "sealed": False, "reason": "ya_sellada", "manifest": manifest}

    files: dict[str, dict] = {}
    for component, relatives in COMPONENT_FILES.items():
        for relative in relatives:
            source = _inside(root, root / relative)
            if not source.is_file():
                raise RuntimeError(f"No se puede sellar: falta {relative}")
            target = _inside(baseline_dir, baseline_dir / "files" / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            files[relative] = {"sha256": _sha256(source), "component": component}

    manifest = {"version": version, "sealed_at": _utc_now(), "files": files}
    _write_json_atomic(manifest_path, manifest)
    _write_json_atomic(state_root / "current_baseline.json", {
        "version": version, "manifest": str(manifest_path), "sealed_at": manifest["sealed_at"],
    })
    return {"ok": True, "sealed": True, "manifest": manifest}


def _current_manifest(root: Path, state_root: Path) -> tuple[dict | None, str | None]:
    pointer = _read_json(state_root / "current_baseline.json", {})
    version = _version(root)
    if not pointer:
        return None, "sin_linea_base"
    if pointer.get("version") != version:
        return None, "linea_base_de_otra_version"
    raw_path = pointer.get("manifest")
    if not raw_path:
        return None, "manifiesto_no_indicado"
    try:
        manifest_path = _inside(state_root, Path(raw_path))
    except (ValueError, OSError):
        return None, "ruta_de_manifiesto_invalida"
    manifest = _read_json(manifest_path, {})
    if manifest.get("version") != version or not isinstance(manifest.get("files"), dict):
        return None, "manifiesto_invalido"
    manifest["_dir"] = str(manifest_path.parent)
    return manifest, None


def _check_files(root: Path, manifest: dict | None, manifest_error: str | None) -> dict:
    result: dict[str, dict] = {}
    for component, relatives in COMPONENT_FILES.items():
        problems = []
        for relative in relatives:
            current = _inside(root, root / relative)
            if not current.is_file():
                problems.append({"file": relative, "reason": "ausente"})
                continue
            if manifest:
                expected = manifest["files"].get(relative, {}).get("sha256")
                if not expected:
                    problems.append({"file": relative, "reason": "sin_hash_sellado"})
                elif _sha256(current) != expected:
                    problems.append({"file": relative, "reason": "hash_modificado"})
        missing = any(p.get("reason") == "ausente" for p in problems)
        if not problems and manifest:
            status, detail = "ok", "Íntegro"
        elif not manifest and not missing:
            # Sin línea base sellada (o sellada para otra versión) no se puede
            # verificar el hash, pero los ficheros existen: es un aviso, no un
            # fallo. Marcarlo como error obligaba al vigilante a entrar en
            # --mode repair cada ciclo sin poder reparar nada.
            status, detail = "warning", manifest_error or "Sin línea base sellada"
        else:
            status, detail = "error", manifest_error or "Cambios detectados"
        result[component] = {"status": status, "detail": detail, "problems": problems}
    return result


def _sqlite_integrity(path: Path) -> tuple[str, str]:
    if not path.is_file():
        return "error", "Base de datos ausente"
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=2)
        try:
            row = connection.execute("PRAGMA quick_check(1)").fetchone()
        finally:
            connection.close()
        if row and str(row[0]).lower() == "ok":
            return "ok", "Integridad SQLite correcta"
        return "error", f"SQLite informó: {row[0] if row else 'sin respuesta'}"
    except sqlite3.OperationalError as exc:
        text = str(exc).lower()
        if "locked" in text or "busy" in text:
            return "warning", "Base de datos ocupada; no se considera corrupción"
        return "error", f"Error de integridad SQLite: {exc}"
    except (OSError, sqlite3.DatabaseError) as exc:
        return "error", f"Error de integridad SQLite: {exc}"


def _http_health(url: str, timeout: float = 3.0) -> tuple[str, str]:
    try:
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "MRD-Repair-Center/1"})
        with urlopen(request, timeout=timeout) as response:
            body = response.read(4096)
            if response.status != 200:
                return "error", f"HTTP {response.status}"
            try:
                payload = json.loads(body.decode("utf-8-sig"))
                if payload.get("status") != "ok":
                    return "error", "Health respondió sin estado ok"
            except (ValueError, UnicodeError):
                pass
        return "ok", "Responde correctamente"
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return "error", f"No responde: {type(exc).__name__}"


def _check_storage(root: Path, apply: bool) -> tuple[dict, list[str]]:
    repaired = []
    problems = []
    for relative in REQUIRED_DIRS:
        path = _inside(root, root / relative)
        if path.is_dir():
            continue
        problems.append(relative)
        if apply:
            path.mkdir(parents=True, exist_ok=True)
            repaired.append(relative)
    free_gb = shutil.disk_usage(root).free / (1024 ** 3)
    status = "ok"
    detail = f"{free_gb:.1f} GB libres"
    if problems and not apply:
        status, detail = "error", "Faltan carpetas: " + ", ".join(problems)
    elif free_gb < 1:
        status, detail = "warning", f"Disco casi lleno: {free_gb:.1f} GB libres"
    return {"status": status, "detail": detail, "missing": problems}, repaired


def _restore_files(
    root: Path, state_root: Path, manifest: dict, components: dict, app_unhealthy: bool,
) -> list[str]:
    repaired = []
    baseline_dir = Path(manifest["_dir"])
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    quarantine = _inside(state_root, state_root / "quarantine" / stamp / "files")
    for component in COMPONENT_FILES:
        for problem in components[component].get("problems", []):
            if problem.get("reason") != "ausente" and not app_unhealthy:
                # Un hash distinto (fichero presente) puede ser una edición
                # manual legítima sin resellar todavía; sin otra señal real
                # de fallo (BD o health local caídos) no se revierte en
                # silencio. Un fichero ausente sí es un fallo inequívoco.
                continue
            relative = problem["file"]
            expected = manifest["files"].get(relative, {}).get("sha256")
            sealed = _inside(baseline_dir, baseline_dir / "files" / relative)
            if not expected or not sealed.is_file() or _sha256(sealed) != expected:
                continue
            current = _inside(root, root / relative)
            if current.exists():
                saved = _inside(quarantine, quarantine / relative)
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(current, saved)
            current.parent.mkdir(parents=True, exist_ok=True)
            temp = current.with_name(current.name + ".mrd-repair.tmp")
            shutil.copy2(sealed, temp)
            os.replace(temp, current)
            repaired.append(relative)
    return repaired


def _is_mrd_database(path: Path) -> bool:
    """True solo si el .db contiene las tablas propias de MRD Tool Control.

    Complementa a `_sqlite_integrity`: un fichero puede ser un SQLite sano
    (pasar quick_check) y no ser una copia de la base de datos de MRD.
    """
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=2)
        try:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return False
    tables = {row[0] for row in rows}
    return all(table in tables for table in _MRD_SCHEMA_SIGNATURE)


def _backup_candidates(root: Path, live_db: Path) -> list[Path]:
    candidates = []
    backup_root = root / "backups"
    if not backup_root.is_dir():
        return candidates
    for pattern in ("**/mrd_tool.db.bak", "**/mrd_tool.db", "**/*.sqlite", "**/*.db"):
        for path in backup_root.glob(pattern):
            try:
                resolved = path.resolve()
                if resolved != live_db.resolve() and resolved.is_file() and resolved not in candidates:
                    candidates.append(resolved)
            except OSError:
                continue
    return sorted(candidates, key=lambda value: value.stat().st_mtime, reverse=True)


def _restore_database_dr4(root: Path, state_root: Path, live_db: Path) -> dict:
    """Diagnostica y deja constancia del fallo de integridad, pero nunca
    escribe sobre la base de datos en vivo: la restauración automática de
    DR4 está desactivada y exige intervención manual (ver CLAUDE.md, "no
    perder datos en reparaciones/rollback")."""
    backup = None
    for candidate in _backup_candidates(root, live_db):
        if _sqlite_integrity(candidate)[0] == "ok" and _is_mrd_database(candidate):
            backup = candidate
            break
    if backup is None:
        return {
            "ok": False,
            "manual_intervention_required": True,
            "detail": "No existe una copia SQLite válida para DR4. Requiere intervención manual.",
        }

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    quarantine = _inside(state_root, state_root / "quarantine" / stamp / "database")
    quarantine.mkdir(parents=True, exist_ok=True)
    if live_db.exists():
        shutil.copy2(live_db, quarantine / "mrd_tool.corrupt.db")
    return {
        "ok": False,
        "manual_intervention_required": True,
        "detail": (
            f"DR4 localizó una copia válida ({backup}) pero la restauración "
            "automática está desactivada. La base dañada quedó en cuarentena; "
            "requiere intervención manual."
        ),
        "backup": str(backup),
    }


def run_once(
    root: Path,
    state_root: Path,
    *,
    apply: bool = False,
    allow_dr4: bool = False,
    service_confirmed_stopped: bool = False,
    database_failure_threshold: int = 3,
    local_health_url: str = "http://127.0.0.1:8000/health",
    public_health_url: str = "https://app.iasmrd.com/health",
) -> dict:
    root = root.resolve()
    state_root = state_root.resolve()
    state_root.mkdir(parents=True, exist_ok=True)
    state = _load_state(state_root)
    manifest, manifest_error = _current_manifest(root, state_root)
    components = _check_files(root, manifest, manifest_error)
    storage, created_dirs = _check_storage(root, apply)
    components["almacenamiento"] = storage

    live_db = _inside(root, root / "data" / "mrd_tool.db")
    db_status, db_detail = _sqlite_integrity(live_db)
    # El modo check (apply=False) es solo diagnóstico: nunca debe mutar el
    # contador persistido, o un ciclo del vigilante que llama primero a check
    # y luego a repair lo incrementaría dos veces por cada fallo real. Se
    # calcula un valor "a falta de aplicar" solo para informar (dr4_ready,
    # consecutive_failures) y se confirma en disco únicamente si apply=True.
    persisted_failures = int(state.get("database_failures") or 0)
    if db_status == "error":
        tentative_failures = persisted_failures + 1
    elif db_status == "ok":
        tentative_failures = 0
    else:
        tentative_failures = persisted_failures
    if apply:
        state["database_failures"] = tentative_failures
    components["base_datos"] = {
        "status": db_status, "detail": db_detail,
        "consecutive_failures": tentative_failures,
    }

    local_status, local_detail = _http_health(local_health_url)
    public_status, public_detail = _http_health(public_health_url)
    components["aplicacion_local"] = {"status": local_status, "detail": local_detail}
    # Clave distinta de "acceso_remoto" (que es la comprobación de ficheros
    # de ese componente): antes la sobrescribía y ocultaba ficheros alterados.
    components["acceso_remoto_publico"] = {"status": public_status, "detail": public_detail}

    # Una app "sana" (BD y health local respondiendo bien) no debe ver
    # revertidos ficheros cuyo hash simplemente difiere: puede ser una
    # edición manual legítima aún sin resellar. Sin esta señal de fallo real,
    # solo se restauran ficheros literalmente ausentes.
    app_unhealthy = db_status == "error" or local_status == "error"

    repaired_files = []
    if apply and manifest:
        repaired_files = _restore_files(root, state_root, manifest, components, app_unhealthy)
        if repaired_files:
            # El informe visible debe describir el estado DESPUÉS del arreglo,
            # no mantener en rojo los archivos que ya se restauraron.
            components.update(_check_files(root, manifest, manifest_error))

    # Si un DR4 anterior ya concluyó que hace falta intervención humana, no
    # tiene sentido volver a parar MRD cada ciclo para repetir el mismo
    # diagnóstico: dr4_ready queda desarmado hasta que la BD vuelva a estar
    # sana (o alguien restaure a mano). El aviso se expone en el informe.
    if db_status == "ok" and state.get("dr4_manual_required"):
        if apply:
            state["dr4_manual_required"] = None
        dr4_manual_required = None
    else:
        dr4_manual_required = state.get("dr4_manual_required")
    dr4_ready = (
        db_status == "error"
        and tentative_failures >= max(2, database_failure_threshold)
        and not dr4_manual_required
    )
    dr4_result = None
    if apply and allow_dr4 and dr4_ready:
        if not service_confirmed_stopped:
            dr4_result = {"ok": False, "detail": "DR4 exige confirmar que MRD está detenido"}
        else:
            dr4_result = _restore_database_dr4(root, state_root, live_db)
            if dr4_result["ok"]:
                state["database_failures"] = 0
                state["last_dr4"] = _utc_now()
            elif dr4_result.get("manual_intervention_required"):
                dr4_manual_required = _utc_now()
                state["dr4_manual_required"] = dr4_manual_required

    remaining_errors = [name for name, value in components.items() if value["status"] == "error"]
    if dr4_result and dr4_result.get("ok"):
        remaining_errors = [name for name in remaining_errors if name != "base_datos"]

    changed = bool(repaired_files or created_dirs or (dr4_result and dr4_result.get("ok")))
    result = "reparado" if changed and not remaining_errors else ("problemas" if remaining_errors else "ok")
    report = {
        "ok": not remaining_errors,
        "result": result,
        "timestamp": _utc_now(),
        "version": _version(root),
        "baseline": manifest.get("version") if manifest else None,
        "baseline_error": manifest_error,
        "components": components,
        "repaired_files": repaired_files,
        "created_dirs": created_dirs,
        "restart_required": bool(repaired_files),
        "dr4_ready": dr4_ready,
        "dr4": dr4_result,
        "dr4_manual_required": dr4_manual_required,
        "remaining_errors": remaining_errors,
    }
    if apply:
        # El modo check es inocuo para el estado: no escribe state.json ni
        # añade historial. Solo el modo repair (apply=True), que ya es el
        # único que puede restaurar ficheros o BD, persiste el estado.
        state["last_run"] = report["timestamp"]
        state["last_result"] = result
        if changed:
            state["last_repair"] = report["timestamp"]
        _record(state, "repair", result, ", ".join(remaining_errors) or "sin incidencias")
        _write_json_atomic(state_root / "state.json", state)
    # El informe (status.json) sí se publica en ambos modos: es lo que lee
    # /servicio, y en una máquina sana el vigilante solo ejecuta check. En
    # modo check es best-effort: un fichero bloqueado por otro lector o con
    # permisos de otra cuenta no debe convertir un diagnóstico sano en
    # error_interno (el modo repair sí propaga el fallo, como siempre).
    try:
        _write_json_atomic(state_root / "status.json", report)
    except OSError:
        if apply:
            raise
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--state-root", type=Path,
        default=Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "MRDToolControl" / "repair-center",
    )
    parser.add_argument("--mode", choices=("check", "repair", "seal", "status"), default="check")
    parser.add_argument("--allow-dr4", action="store_true")
    parser.add_argument("--service-confirmed-stopped", action="store_true")
    parser.add_argument("--database-failure-threshold", type=int, default=3)
    parser.add_argument("--local-health-url", default="http://127.0.0.1:8000/health")
    parser.add_argument("--public-health-url", default="https://app.iasmrd.com/health")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.mode == "seal":
            result = seal_baseline(args.root, args.state_root)
        elif args.mode == "status":
            result = _read_json(args.state_root / "status.json", {"ok": False, "result": "sin_estado"})
        else:
            result = run_once(
                args.root, args.state_root, apply=args.mode == "repair",
                allow_dr4=args.allow_dr4,
                service_confirmed_stopped=args.service_confirmed_stopped,
                database_failure_threshold=args.database_failure_threshold,
                local_health_url=args.local_health_url,
                public_health_url=args.public_health_url,
            )
    except Exception as exc:
        result = {"ok": False, "result": "error_interno", "detail": str(exc)[:500], "timestamp": _utc_now()}
    print(json.dumps(result, ensure_ascii=False) if args.json else json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
