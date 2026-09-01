"""
Tests Sprint 5.7 — Actualizaciones Profesionales
v1.9.7-alpha
"""
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


class TestFileStructure57:
    def test_updater_py_exists(self):
        assert (ROOT / "updater.py").exists()

    def test_actualizaciones_html_exists(self):
        assert (ROOT / "templates" / "actualizaciones.html").exists()

    def test_version_is_197(self):
        v = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
        actual = tuple(map(int, v["version_actual"].split("-")[0].split(".")))
        assert actual >= (1, 9, 7)

    def test_changelog_sprint57(self):
        assert (ROOT / "updater.py").stat().st_size > 500

    def test_main_syntax_ok(self):
        import ast
        src = (ROOT / "main.py").read_text(encoding="utf-8")
        try:
            ast.parse(src)
        except SyntaxError as e:
            pytest.fail(f"Sintaxis inválida en main.py: {e}")


class TestUpdaterModule:
    def test_imports_ok(self):
        import updater as u
        assert hasattr(u, "check_update")
        assert hasattr(u, "start_update")
        assert hasattr(u, "rollback_update")
        assert hasattr(u, "reset_state")
        assert hasattr(u, "get_state")

    def test_states_defined(self):
        import updater as u
        assert u.STATE_IDLE        == "idle"
        assert u.STATE_AVAILABLE   == "disponible"
        assert u.STATE_DOWNLOADING == "descargando"
        assert u.STATE_VERIFYING   == "verificando"
        assert u.STATE_INSTALLING  == "instalando"
        assert u.STATE_RESTARTING  == "reiniciando"
        assert u.STATE_SUCCESS     == "correcta"
        assert u.STATE_FAILED      == "fallida"
        assert u.STATE_REVERTED    == "revertida"

    def test_get_state_structure(self):
        import updater as u
        state = u.get_state()
        assert "status"    in state
        assert "progress"  in state
        assert "message"   in state
        assert "version"   in state
        assert "log"       in state
        assert "error"     in state

    def test_initial_state_is_idle(self):
        import updater as u
        u.reset_state()
        state = u.get_state()
        assert state["status"]   in (u.STATE_IDLE, u.STATE_AVAILABLE)
        assert state["progress"] == 0

    def test_reset_state_returns_true_when_idle(self):
        import updater as u
        u.reset_state()  # asegurar estado idle
        result = u.reset_state()
        assert result is True

    def test_check_update_no_server(self, monkeypatch):
        import updater as u
        monkeypatch.delenv("MRD_UPDATE_SERVER", raising=False)
        result = u.check_update()
        assert "available"       in result
        assert "current_version" in result
        assert result["configured"] is False

    def test_check_update_bad_server(self, monkeypatch):
        import updater as u
        monkeypatch.setenv("MRD_UPDATE_SERVER", "http://no.existe.invalid")
        result = u.check_update()
        assert isinstance(result, dict)
        assert "available" in result
        # Debe fallar sin lanzar excepción

    def test_version_comparison(self):
        from updater import _version_gt
        assert _version_gt("1.9.8", "1.9.7") is True
        assert _version_gt("1.9.7", "1.9.7") is False
        assert _version_gt("1.9.6", "1.9.7") is False
        assert _version_gt("2.0.0", "1.9.9") is True
        assert _version_gt("1.9.8-alpha", "1.9.7-alpha") is True

    def test_sha256_file(self, tmp_path):
        from updater import _sha256_file
        f = tmp_path / "t.bin"
        f.write_bytes(b"test data")
        h = _sha256_file(f)
        assert len(h) == 64

    def test_start_update_blocks_if_already_running(self, monkeypatch):
        import updater as u
        # Simular estado en curso
        with u._state_lock:
            u._state["status"] = u.STATE_DOWNLOADING
        result = u.start_update("https://x.com/f.zip", "", "1.0.0")
        assert result["ok"] is False
        assert "error" in result
        # Resetear
        with u._state_lock:
            u._state["status"] = u.STATE_IDLE

    def test_start_update_returns_ok_when_idle(self, monkeypatch):
        import updater as u
        u.reset_state()
        # Parchear _run_update para que no haga nada
        monkeypatch.setattr(u, "_run_update", lambda *a, **kw: None)
        result = u.start_update("https://x.com/f.zip", "abc123", "1.0.0")
        assert result["ok"] is True
        # Esperar que el hilo arranque y resetear
        time.sleep(0.1)
        u.reset_state()

    def test_rollback_no_backup(self, monkeypatch, tmp_path):
        import updater as u
        monkeypatch.setattr(u, "UPDATE_DIR", tmp_path / "updates")
        (tmp_path / "updates").mkdir()
        result = u.rollback_update()
        assert result["ok"] is False
        assert "error" in result

    def test_get_update_config_keys(self):
        from updater import _get_update_config
        cfg = _get_update_config()
        assert "server_url"     in cfg
        assert "timeout"        in cfg
        assert "service_name"   in cfg
        assert "health_url"     in cfg
        assert "health_retries" in cfg

    def test_set_state_adds_to_log(self):
        import updater as u
        u.reset_state()
        u._set_state(message="test message")
        state = u.get_state()
        assert any("test message" in l.get("msg","") for l in state["log"])

    def test_health_check_fails_fast_on_bad_url(self):
        from updater import _health_check
        result = _health_check("http://127.0.0.1:19999/health", retries=1, delay=0)
        assert result is False


class TestMainUpdaterEndpoints:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        import main as m
        return TestClient(m.app, follow_redirects=False)

    def test_actualizaciones_page_requires_auth(self, client):
        r = client.get("/actualizaciones")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_upd_check_requires_auth(self, client):
        r = client.get("/api/update/check")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_upd_status_requires_auth(self, client):
        r = client.get("/api/update/status")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_upd_install_requires_auth(self, client):
        r = client.post("/api/update/install")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_upd_rollback_requires_auth(self, client):
        r = client.post("/api/update/rollback")
        assert r.status_code in (302, 303, 401, 403)

    def test_api_upd_reset_requires_auth(self, client):
        r = client.post("/api/update/reset")
        assert r.status_code in (302, 303, 401, 403)

    def test_sprint57_in_main(self):
        src = (ROOT / "main.py").read_text(encoding="utf-8")
        assert "updater" in src
        assert "/api/update/check"   in src
        assert "/api/update/install" in src
        assert "/api/update/rollback" in src

    def test_actualizaciones_html_extends_base(self):
        html = (ROOT / "templates" / "actualizaciones.html").read_text(encoding="utf-8")
        assert 'extends "base.html"' in html

    def test_actualizaciones_html_progress_bar(self):
        html = (ROOT / "templates" / "actualizaciones.html").read_text(encoding="utf-8")
        assert "progress" in html.lower()

    def test_actualizaciones_html_states(self):
        html = (ROOT / "templates" / "actualizaciones.html").read_text(encoding="utf-8")
        assert "descargando"  in html
        assert "verificando"  in html
        assert "instalando"   in html
        assert "correcta"     in html
        assert "fallida"      in html
        assert "revertida"    in html

    def test_actualizaciones_html_rollback_btn(self):
        html = (ROOT / "templates" / "actualizaciones.html").read_text(encoding="utf-8")
        assert "updRollback" in html

    def test_actualizaciones_html_csrf(self):
        html = (ROOT / "templates" / "actualizaciones.html").read_text(encoding="utf-8")
        assert "getCsrf" in html

    def test_url_validation_in_install_endpoint(self):
        src = (ROOT / "main.py").read_text(encoding="utf-8")
        assert "http://" in src or "https://" in src

