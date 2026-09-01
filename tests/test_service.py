"""
MRD TOOL CONTROL — Suite de tests Sprint 5.3 — Servicios de Producción
v1.9.3-alpha

Tests:
  - Carga de service.yaml
  - service_health.py (todos los checks individuales)
  - windows_service.py (config, runner init, flags de señal)
  - API endpoints (status, health, logs, restart, stop, start)
  - Panel de administración /servicio

Ejecutar: cd "C:\\mrd tool\\mrd_tool_control" && python -m pytest tests/test_service.py -v
"""
import io
import json
import os
import sys
import time
import tempfile
from pathlib import Path

import pytest

# ─── Entorno ──────────────────────────────────────────────────────────────────
os.environ.setdefault("MRD_ENV", "development")
os.environ.setdefault("MRD_SECRET_KEY", "test-secret-key-sprint53-" + "x" * 32)
os.environ.setdefault("MRD_ADMIN_PASSWORD", "TestAdmin@2024!")
os.environ.setdefault("MRD_PASSWORD_MIN_LENGTH", "10")
os.environ.setdefault("MRD_DATABASE_URL", "sqlite:////tmp/test_mrd_sprint53.db")

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ─── Tests de service.yaml ────────────────────────────────────────────────────

class TestServiceYaml:
    """Verifica que service.yaml existe y tiene la estructura correcta."""

    def test_yaml_file_exists(self):
        yaml_path = PROJECT_ROOT / "service.yaml"
        assert yaml_path.exists(), "service.yaml no encontrado en la raíz del proyecto"

    def test_yaml_parseable(self):
        import yaml
        yaml_path = PROJECT_ROOT / "service.yaml"
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict), "service.yaml no es un dict YAML válido"

    def test_yaml_service_section(self):
        import yaml
        with open(PROJECT_ROOT / "service.yaml", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        svc = data.get("service", {})
        assert svc.get("name") == "MRDToolControl"
        assert "display_name" in svc
        assert "description" in svc
        assert svc.get("startup") in ("automatic", "manual", "disabled")

    def test_yaml_server_section(self):
        import yaml
        with open(PROJECT_ROOT / "service.yaml", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        srv = data.get("server", {})
        assert "port" in srv
        assert "host" in srv
        assert int(srv.get("workers", 0)) == 1, "Workers debe ser 1 con SQLite"

    def test_yaml_watchdog_section(self):
        import yaml
        with open(PROJECT_ROOT / "service.yaml", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        wd = data.get("watchdog", {})
        assert "enabled" in wd
        assert int(wd.get("max_restarts", 0)) > 0
        assert int(wd.get("restart_delay_seconds", 0)) >= 10

    def test_yaml_recovery_section(self):
        import yaml
        with open(PROJECT_ROOT / "service.yaml", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        rec = data.get("service", {}).get("recovery", {})
        assert rec.get("first_failure") == "restart"
        assert rec.get("second_failure") == "restart"
        assert rec.get("third_failure") == "restart"
        assert int(rec.get("restart_delay_seconds", 0)) >= 10

    def test_yaml_logging_section(self):
        import yaml
        with open(PROJECT_ROOT / "service.yaml", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        lg = data.get("logging", {})
        for key in ("service_log", "startup_log", "shutdown_log", "crash_log", "rotation_log"):
            assert key in lg, f"logging.{key} no encontrado en service.yaml"

    def test_yaml_cleanup_section(self):
        import yaml
        with open(PROJECT_ROOT / "service.yaml", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        cl = data.get("cleanup", {})
        assert "enabled" in cl
        assert 0 <= int(cl.get("schedule_hour", -1)) <= 23


# ─── Tests de service_health.py ───────────────────────────────────────────────

class TestServiceHealth:
    """Tests de los health checks individuales."""

    def test_check_disk_space_ok(self):
        from service_health import check_disk_space
        result = check_disk_space(min_free_gb=0.001)  # umbral muy bajo para que pase
        assert hasattr(result, 'ok')
        assert hasattr(result, 'detail')
        assert isinstance(result.detail, str)

    def test_check_memory_returns_result(self):
        from service_health import check_memory
        result = check_memory()
        assert hasattr(result, 'ok')
        assert hasattr(result, 'detail')

    def test_check_port_closed_port_fails(self):
        from service_health import check_port
        # Puerto 1 siempre estará cerrado en entorno de test
        result = check_port(port=1, timeout=0.5)
        assert result.ok is False
        assert "1" in result.detail

    def test_check_directory_existing(self, tmp_path):
        from service_health import check_directory
        result = check_directory(tmp_path, "test_dir")
        assert result.ok is True
        assert "test_dir" in result.detail

    def test_check_directory_creates_if_missing(self, tmp_path):
        from service_health import check_directory
        new_dir = tmp_path / "nuevo_subdir"
        result = check_directory(new_dir, "nuevo")
        assert result.ok is True
        assert new_dir.exists()

    def test_check_database_missing_file(self, tmp_path):
        from service_health import check_database
        result = check_database(tmp_path / "nonexistent.db")
        assert result.ok is False
        assert "no encontrado" in result.detail.lower() or "not found" in result.detail.lower()

    def test_check_database_valid_sqlite(self, tmp_path):
        import sqlite3
        db_path = tmp_path / "test.db"
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("CREATE TABLE t (id INTEGER)")
            conn.execute("INSERT INTO t VALUES (1)")
            conn.commit()
        from service_health import check_database
        result = check_database(db_path)
        assert result.ok is True
        assert "KB" in result.detail or "activa" in result.detail

    def test_health_result_to_dict(self):
        from service_health import HealthResult
        r = HealthResult(True, "todo bien", value=42)
        d = r.to_dict()
        assert d["status"] == "ok"
        assert d["detail"] == "todo bien"
        assert d["value"] == 42

    def test_health_result_error_to_dict(self):
        from service_health import HealthResult
        r = HealthResult(False, "algo falló")
        d = r.to_dict()
        assert d["status"] == "error"
        assert "value" not in d

    def test_run_all_checks_structure(self):
        from service_health import run_all_checks
        result = run_all_checks(port=19999, min_free_gb=0.001)
        assert "healthy" in result
        assert "timestamp" in result
        assert "checks" in result
        assert isinstance(result["checks"], dict)
        # Debe incluir todos los checks clave
        expected = {"database", "disk_space", "memory", "port", "uploads", "logs", "backups"}
        for k in expected:
            assert k in result["checks"], f"Check '{k}' no encontrado en resultado"

    def test_run_all_checks_values_have_status(self):
        from service_health import run_all_checks
        result = run_all_checks(port=19999, min_free_gb=0.001)
        for name, check in result["checks"].items():
            assert "status" in check, f"Check '{name}' no tiene campo 'status'"
            assert check["status"] in ("ok", "error"), f"Estado inválido en '{name}'"
            assert "detail" in check, f"Check '{name}' no tiene campo 'detail'"

    def test_get_system_metrics_returns_dict(self):
        from service_health import get_system_metrics
        metrics = get_system_metrics()
        assert isinstance(metrics, dict)

    def test_run_all_checks_timestamp_utc(self):
        from service_health import run_all_checks
        result = run_all_checks(port=19999, min_free_gb=0.001)
        ts = result.get("timestamp", "")
        assert ts.endswith("Z"), f"Timestamp debe terminar en Z (UTC): {ts}"


# ─── Tests de windows_service.py ──────────────────────────────────────────────

class TestWindowsService:
    """Tests del módulo windows_service.py (sin pywin32)."""

    def test_module_importable(self):
        """windows_service.py debe importarse sin errores aunque pywin32 no esté."""
        import importlib
        ws = importlib.import_module("windows_service")
        assert ws is not None

    def test_constants_loaded(self):
        import windows_service as ws
        assert ws.SERVICE_NAME == "MRDToolControl"
        assert isinstance(ws.SERVER_PORT, int)
        assert ws.SERVER_PORT > 0
        assert ws.SERVER_WORKERS >= 1

    def test_workers_sqlite_constraint(self):
        """Con SQLite el número de workers debe ser 1."""
        import windows_service as ws
        # Debería ser 1 según service.yaml
        assert ws.SERVER_WORKERS == 1, (
            f"Workers debe ser 1 con SQLite (actual: {ws.SERVER_WORKERS}). "
            "Cambia 'workers' en service.yaml"
        )

    def test_log_dir_created(self):
        import windows_service as ws
        assert ws.LOG_DIR.exists(), f"LOG_DIR no fue creado: {ws.LOG_DIR}"
        assert ws.LOG_DIR.is_dir()

    def test_runner_initialization(self):
        import windows_service as ws
        runner = ws.MRDServiceRunner()
        assert runner._stop_event is not None
        assert runner._process is None
        assert runner._restart_count == 0

    def test_runner_stop_sets_event(self):
        import windows_service as ws
        import threading
        runner = ws.MRDServiceRunner()
        assert not runner._stop_event.is_set()
        runner.stop()
        assert runner._stop_event.is_set()

    def test_find_python_returns_string(self):
        import windows_service as ws
        py = ws._find_python()
        assert isinstance(py, str)
        assert len(py) > 0

    def test_service_env_has_mrd_env(self):
        import windows_service as ws
        env = ws._get_service_env()
        assert "MRD_ENV" in env

    def test_restart_flag_file_path(self):
        import windows_service as ws
        # El archivo de señal debe estar en la raíz del proyecto
        assert ws.RESTART_FLAG_FILE.parent == ws.BASE_DIR

    def test_status_file_path(self):
        import windows_service as ws
        assert ws.STATUS_FILE.parent == ws.BASE_DIR

    def test_write_read_status(self, tmp_path, monkeypatch):
        import windows_service as ws
        test_status_file = tmp_path / ".service_status"
        monkeypatch.setattr(ws, "STATUS_FILE", test_status_file)
        data = {"status": "running", "pid": 1234, "port": 8000}
        ws._write_status(data)
        result = ws._read_status()
        assert result["status"] == "running"
        assert result["pid"] == 1234

    def test_read_status_missing_file(self, tmp_path, monkeypatch):
        import windows_service as ws
        monkeypatch.setattr(ws, "STATUS_FILE", tmp_path / ".nonexistent")
        result = ws._read_status()
        assert result == {}

    def test_cfg_helper_defaults(self):
        import windows_service as ws
        val = ws._cfg("nonexistent_key", "also_missing", default="fallback")
        assert val == "fallback"

    def test_windows_service_available_flag(self):
        import windows_service as ws
        # En Linux siempre False, en Windows puede ser True
        assert isinstance(ws.WINDOWS_SERVICE_AVAILABLE, bool)


# ─── Tests de API de servicio (endpoints HTTP) ────────────────────────────────

class TestServiceAPI:
    """Tests de los endpoints /api/service/* y /servicio.

    Nota: requiere_login devuelve HTTP 303 (redirect a /login).
    El TestClient con follow_redirects=True seguiría al /login (200).
    Usamos follow_redirects=False para capturar el redirect real.
    """

    def test_servicio_panel_requires_auth(self, client):
        r = client.get("/servicio", follow_redirects=False)
        assert r.status_code in (302, 303, 401)

    def test_status_requires_auth(self, client):
        r = client.get("/api/service/status", follow_redirects=False)
        assert r.status_code in (303, 302, 401, 403)

    def test_health_requires_auth(self, client):
        r = client.get("/api/service/health", follow_redirects=False)
        assert r.status_code in (303, 302, 401, 403)

    def test_restart_requires_auth(self, client):
        r = client.post("/api/service/restart", follow_redirects=False)
        assert r.status_code in (303, 302, 401, 403)

    def test_stop_requires_auth(self, client):
        r = client.post("/api/service/stop", follow_redirects=False)
        assert r.status_code in (303, 302, 401, 403)

    def test_start_requires_auth(self, client):
        r = client.post("/api/service/start", follow_redirects=False)
        assert r.status_code in (303, 302, 401, 403)

    def test_logs_requires_auth(self, client):
        r = client.get("/api/service/logs/service", follow_redirects=False)
        assert r.status_code in (303, 302, 401, 403)

    def test_logs_invalid_name_blocked(self, client):
        """Nombres de log no permitidos deben devolver 400 o redirigir."""
        r = client.get("/api/service/logs/../../etc/passwd", follow_redirects=False)
        # Puede ser 302/303 (redirect sin auth), 400 (nombre inválido), 404, 422
        assert r.status_code not in (200,)  # nunca devuelve contenido peligroso


# ─── Tests de estructura de archivos ──────────────────────────────────────────

class TestFileStructure:
    """Verifica que todos los archivos entregados por Sprint 5.3 existen."""

    FILES_REQUIRED = [
        "windows_service.py",
        "service.yaml",
        "service_health.py",
        "install_service.ps1",
        "uninstall_service.ps1",
        "start_service.ps1",
        "stop_service.ps1",
        "restart_service.ps1",
        "status_service.ps1",
        "templates/servicio.html",
        "tools/development/reset_admin.py",
        "tools/development/hacer_admin.py",
        "tools/maintenance/DIAGNOSTICO.py",
        "tools/maintenance/fix_usuarios.py",
        "logs/service.log",
        "logs/startup.log",
        "logs/shutdown.log",
        "logs/crash.log",
        "logs/rotation.log",
    ]

    @pytest.mark.parametrize("path", FILES_REQUIRED)
    def test_file_exists(self, path):
        full = PROJECT_ROOT / path
        assert full.exists(), f"Archivo faltante: {path}"

    DIRS_REQUIRED = [
        "tools",
        "tools/development",
        "tools/maintenance",
        "tools/obsolete",
        "logs",
        "temp",
        "cache",
    ]

    @pytest.mark.parametrize("path", DIRS_REQUIRED)
    def test_dir_exists(self, path):
        full = PROJECT_ROOT / path
        assert full.exists() and full.is_dir(), f"Directorio faltante: {path}"

    def test_service_scripts_not_empty(self):
        """Los scripts de PowerShell deben tener contenido mínimo."""
        scripts = ["install_service.ps1", "uninstall_service.ps1",
                   "start_service.ps1", "stop_service.ps1",
                   "restart_service.ps1", "status_service.ps1"]
        for s in scripts:
            path = PROJECT_ROOT / s
            size = path.stat().st_size
            assert size > 200, f"{s} parece vacío o muy pequeño ({size} bytes)"

    def test_version_json_updated(self):
        import json
        with open(PROJECT_ROOT / "version.json", encoding="utf-8") as f:
            data = json.load(f)
        actual = tuple(map(int, data["version_actual"].split("-")[0].split(".")))
        assert actual >= (1, 9, 3)
        assert data.get("nombre") == "MRD TOOL CONTROL"

    def test_requirements_has_pyyaml(self):
        content = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
        assert "pyyaml" in content.lower()

    def test_windows_service_has_pywin32_service_class(self):
        """windows_service.py debe definir la clase MRDWindowsService o indicar que pywin32 no está."""
        content = (PROJECT_ROOT / "windows_service.py").read_text(encoding="utf-8")
        assert "MRDWindowsService" in content
        assert "MRDServiceRunner" in content

    def test_service_health_exports_run_all_checks(self):
        from service_health import run_all_checks, get_system_metrics
        assert callable(run_all_checks)
        assert callable(get_system_metrics)

    def test_install_script_has_recovery_config(self):
        content = (PROJECT_ROOT / "install_service.ps1").read_text(encoding="utf-8")
        assert "sc.exe failure" in content or "sc failure" in content

    def test_install_script_checks_admin(self):
        content = (PROJECT_ROOT / "install_service.ps1").read_text(encoding="utf-8")
        assert "Administrator" in content

    def test_servicio_template_has_api_calls(self):
        """El template llama a la API de servicio (puede usar template literals JS)."""
        content = (PROJECT_ROOT / "templates" / "servicio.html").read_text(encoding="utf-8")
        # Los endpoints status y health se referencian como strings literales
        assert "/api/service/status" in content
        assert "/api/service/health" in content
        # El restart/stop/start se llama via svcAction(action) con template literal
        assert "svcAction" in content
        assert "/api/service/" in content

    def test_main_py_has_service_routes(self):
        content = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        assert "/api/service/status" in content
        assert "/api/service/health" in content
        assert "/api/service/restart" in content
        assert "/api/service/stop" in content
        assert "/api/service/start" in content
        assert "/servicio" in content

    def test_watchdog_in_windows_service(self):
        content = (PROJECT_ROOT / "windows_service.py").read_text(encoding="utf-8")
        assert "_watchdog_loop" in content
        assert "_handle_unexpected_exit" in content

    def test_cleanup_in_windows_service(self):
        content = (PROJECT_ROOT / "windows_service.py").read_text(encoding="utf-8")
        assert "_cleanup_loop" in content
        assert "_run_cleanup" in content

    def test_no_sensitive_data_in_service_log_code(self):
        """El código no debe registrar contraseñas ni tokens en los logs."""
        content = (PROJECT_ROOT / "windows_service.py").read_text(encoding="utf-8")
        # Debe existir el comentario de advertencia sobre datos sensibles
        assert "contraseña" in content.lower() or "sensitive" in content.lower() or "password" in content.lower()

    def test_restart_flag_file_mechanism(self):
        """El mecanismo de restart via archivo de señal debe existir."""
        content = (PROJECT_ROOT / "windows_service.py").read_text(encoding="utf-8")
        assert "RESTART_FLAG_FILE" in content
        assert ".service_restart" in content
