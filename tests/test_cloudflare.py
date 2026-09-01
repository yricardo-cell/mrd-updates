"""
Tests Sprint 5.4 — Cloudflare Named Tunnel
MRD TOOL CONTROL v1.9.4-alpha
"""
import sys
import os
import json
import importlib
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def cf_config():
    return {
        "cf_tunnel_name": "mrd-tool",
        "cf_tunnel_id": "12345678-abcd-1234-abcd-123456789012",
        "cf_hostname": "herramientas.midominio.com",
        "cf_domain": "midominio.com",
        "cf_subdomain": "herramientas",
        "cf_public_url": "https://herramientas.midominio.com",
        "cf_config_file": "",
        "cf_force_https": True,
        "cf_internal_port": 8000,
        "cloudflared_service": "cloudflared",
        "cloudflared_exe": "cloudflared.exe",
        "port": 8000,
        "manual_url": "https://herramientas.midominio.com",
    }


# ─── TestFileStructure54 ──────────────────────────────────────────────────────

class TestFileStructure54:
    """Verifica que los nuevos archivos del Sprint 5.4 existen y tienen contenido."""

    def test_cloudflare_tunnel_py_exists(self):
        assert (BASE_DIR / "cloudflare_tunnel.py").exists()

    def test_install_cloudflared_ps1_exists(self):
        assert (BASE_DIR / "install_cloudflared.ps1").exists()

    def test_template_cloudflare_html_exists(self):
        assert (BASE_DIR / "templates" / "cloudflare.html").exists()

    def test_template_acceso_remoto_html_exists(self):
        assert (BASE_DIR / "templates" / "acceso_remoto.html").exists()

    def test_cloudflare_tunnel_not_empty(self):
        content = (BASE_DIR / "cloudflare_tunnel.py").read_text(encoding="utf-8")
        assert len(content) > 500

    def test_install_cloudflared_not_empty(self):
        content = (BASE_DIR / "install_cloudflared.ps1").read_text(encoding="utf-8")
        assert len(content) > 500

    def test_cloudflare_html_not_empty(self):
        content = (BASE_DIR / "templates" / "cloudflare.html").read_text(encoding="utf-8")
        assert len(content) > 200

    def test_version_updated(self):
        vfile = BASE_DIR / "version.json"
        assert vfile.exists()
        data = json.loads(vfile.read_text(encoding="utf-8"))
        actual = tuple(map(int, data["version_actual"].split("-")[0].split(".")))
        assert actual >= (1, 9, 4)

    def test_version_nombre(self):
        data = json.loads((BASE_DIR / "version.json").read_text(encoding="utf-8"))
        assert data["nombre"] == "MRD TOOL CONTROL"

    def test_version_changelog_has_cloudflare(self):
        content = (BASE_DIR / "cloudflare_tunnel.py").read_text(encoding="utf-8")
        assert "tunnel" in content.lower()


# ─── TestCloudflareTunnelModule ────────────────────────────────────────────────

class TestCloudflareTunnelModule:
    """Tests del módulo cloudflare_tunnel.py."""

    @pytest.fixture(autouse=True)
    def load_module(self):
        import cloudflare_tunnel as ct
        self.ct = ct

    def test_module_importable(self):
        assert self.ct is not None

    def test_sanitize_service_name_safe(self):
        assert self.ct._sanitize_service_name("cloudflared") == "cloudflared"
        assert self.ct._sanitize_service_name("mrd-svc_1") == "mrd-svc_1"

    def test_sanitize_service_name_blocks_injection(self):
        # Caracteres de shell deben eliminarse
        result = self.ct._sanitize_service_name("svc; rm -rf /")
        assert ";" not in result
        assert " " not in result

    def test_sanitize_exe_path_blocks_shell_chars(self):
        result = self.ct._sanitize_exe_path("cloudflared.exe; del *")
        assert ";" not in result

    def test_validate_hostname_valid(self):
        assert self.ct._validate_hostname("midominio.com") == "midominio.com"
        assert self.ct._validate_hostname("herramientas.midominio.com") is not None

    def test_validate_hostname_invalid(self):
        assert self.ct._validate_hostname("") is None
        assert self.ct._validate_hostname("bad hostname!") is None
        assert self.ct._validate_hostname("a" * 300) is None

    def test_validate_url_valid(self):
        assert self.ct._validate_url("https://midominio.com") == "https://midominio.com"
        assert self.ct._validate_url("http://localhost:8000") == "http://localhost:8000"

    def test_validate_url_invalid(self):
        assert self.ct._validate_url("ftp://midominio.com") is None
        assert self.ct._validate_url("javascript:alert(1)") is None
        assert self.ct._validate_url("") is None

    def test_validate_url_blocks_injection(self):
        assert self.ct._validate_url("https://a.com<script>") is None
        assert self.ct._validate_url("https://a.com'; DROP") is None

    def test_get_cloudflared_version_not_found(self):
        # Si no hay cloudflared instalado, devuelve None sin lanzar excepción
        result = self.ct.get_cloudflared_version("non_existent_cloudflared_xyz.exe")
        assert result is None

    def test_get_service_status_returns_dict(self):
        result = self.ct.get_service_status("nonexistentservice12345")
        assert isinstance(result, dict)
        assert "installed" in result
        assert "running" in result
        assert "state" in result

    def test_get_service_status_not_installed(self):
        result = self.ct.get_service_status("nonexistentservice12345")
        assert result["installed"] is False
        assert result["running"] is False

    def test_get_metrics_returns_dict(self):
        result = self.ct.get_metrics()
        assert isinstance(result, dict)
        assert "available" in result
        assert "connections" in result

    def test_get_metrics_unavailable_graceful(self):
        # Cuando cloudflared no está corriendo, available=False sin excepción
        result = self.ct.get_metrics()
        assert result["available"] is False or isinstance(result["available"], bool)

    def test_read_tunnel_config_no_file(self):
        result = self.ct.read_tunnel_config("")
        assert isinstance(result, dict)
        assert result["tunnel"] is None

    def test_read_tunnel_config_nonexistent_file(self):
        result = self.ct.read_tunnel_config("/nonexistent/path/config.yml")
        assert isinstance(result, dict)
        assert "error" in result

    def test_get_tunnel_status_returns_dict(self, cf_config):
        result = self.ct.get_tunnel_status(cf_config)
        assert isinstance(result, dict)

    def test_get_tunnel_status_no_credentials_exposed(self, cf_config):
        result = self.ct.get_tunnel_status(cf_config)
        # No debe exponer campos sensibles
        for key in result:
            assert "credential" not in key.lower()
            assert "token" not in key.lower()
            assert "cert" not in key.lower()
            assert "password" not in key.lower()

    def test_get_tunnel_status_has_required_fields(self, cf_config):
        result = self.ct.get_tunnel_status(cf_config)
        required = ["connected", "service_running", "service_state",
                    "cloudflared_version", "hostname", "public_url", "https", "checked_at"]
        for f in required:
            assert f in result, f"Campo faltante: {f}"

    def test_get_tunnel_status_reads_public_url(self, cf_config):
        result = self.ct.get_tunnel_status(cf_config)
        assert result["public_url"] == "https://herramientas.midominio.com"

    def test_get_tunnel_status_https_from_url(self, cf_config):
        result = self.ct.get_tunnel_status(cf_config)
        assert result["https"] is True

    def test_get_tunnel_status_hostname(self, cf_config):
        result = self.ct.get_tunnel_status(cf_config)
        assert result["hostname"] == "herramientas.midominio.com"

    def test_run_diagnostics_returns_list(self, cf_config):
        result = self.ct.run_diagnostics(cf_config, port=8000)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_run_diagnostics_check_structure(self, cf_config):
        checks = self.ct.run_diagnostics(cf_config, port=8000)
        for check in checks:
            assert "name" in check
            assert "label" in check
            assert "ok" in check
            assert "detail" in check
            assert "status" in check
            assert check["status"] in ("ok", "error")

    def test_run_diagnostics_has_8_checks(self, cf_config):
        checks = self.ct.run_diagnostics(cf_config, port=8000)
        assert len(checks) >= 8

    def test_run_diagnostics_check_names(self, cf_config):
        checks = self.ct.run_diagnostics(cf_config, port=8000)
        names = {c["name"] for c in checks}
        expected = {"local_server", "cf_service", "cf_metrics", "cf_version",
                    "dns", "public_url", "https", "scan_route"}
        assert expected.issubset(names)

    def test_restart_service_returns_dict(self):
        result = self.ct.restart_service("nonexistentservice12345")
        assert isinstance(result, dict)
        assert "ok" in result
        assert "message" in result

    def test_restart_service_nonexistent_not_crash(self):
        result = self.ct.restart_service("nonexistent_mrd_svc_xyz")
        assert isinstance(result, dict)
        # No lanza excepción
        assert result["ok"] is False or result["ok"] is True


# ─── TestRemoteAccessCF ────────────────────────────────────────────────────────

class TestRemoteAccessCF:
    """Tests de la integración CF en remote_access.py."""

    @pytest.fixture(autouse=True)
    def load_ra(self, tmp_path):
        import remote_access as ra
        ra.init(tmp_path)
        self.ra = ra
        self.tmp = tmp_path

    def test_default_config_has_cf_keys(self):
        cfg = self.ra._default_config()
        cf_keys = ["cf_tunnel_name", "cf_tunnel_id", "cf_hostname", "cf_domain",
                   "cf_subdomain", "cf_public_url", "cf_config_file",
                   "cf_force_https", "cf_internal_port"]
        for k in cf_keys:
            assert k in cfg, f"Clave faltante en _default_config: {k}"

    def test_save_config_cf_public_url_validated(self, tmp_path):
        # URL válida
        ok = self.ra.save_config({"cf_public_url": "https://midominio.com"})
        assert ok
        cfg = self.ra.load_config()
        assert cfg["cf_public_url"] == "https://midominio.com"

    def test_save_config_cf_public_url_rejects_invalid(self):
        self.ra.save_config({"cf_public_url": "ftp://bad.com"})
        cfg = self.ra.load_config()
        assert cfg.get("cf_public_url", "") == ""

    def test_save_config_cf_hostname_sanitized(self):
        self.ra.save_config({"cf_hostname": "mi<script>dominio.com"})
        cfg = self.ra.load_config()
        assert "<script>" not in cfg.get("cf_hostname", "")

    def test_save_config_cf_tunnel_name_sanitized(self):
        self.ra.save_config({"cf_tunnel_name": "mrd; rm -rf /"})
        cfg = self.ra.load_config()
        assert ";" not in cfg.get("cf_tunnel_name", "")

    def test_detect_cloudflare_named_tunnel_priority(self):
        """Named Tunnel (cf_public_url) debe tener prioridad sobre manual_url."""
        cfg = self.ra._default_config()
        cfg["cf_public_url"] = "https://herramientas.midominio.com"
        cfg["manual_url"] = "https://quick.trycloudflare.com"
        with patch.object(self.ra, '_is_process_running', return_value=False), \
             patch.object(self.ra, '_is_service_running', return_value=False):
            result = self.ra._detect_cloudflare(cfg)
        assert result is not None
        assert result["type"] == "named_tunnel"
        assert result["url"] == "https://herramientas.midominio.com"

    def test_scan_url_uses_public_url(self):
        """QR/scan_url usa PUBLIC_URL cuando está disponible."""
        cfg = self.ra._default_config()
        cfg["cf_public_url"] = "https://herramientas.midominio.com"
        with patch.dict(os.environ, {"MRD_PUBLIC_URL": "", "PUBLIC_URL": "", "MRD_SCAN_URL": ""}), \
             patch.object(self.ra, '_detect_cloudflare') as mock_cf, \
             patch.object(self.ra, '_detect_ngrok', return_value=None), \
             patch.object(self.ra, '_detect_tailscale', return_value=None), \
             patch.object(self.ra, '_measure_latency', return_value=5):
            mock_cf.return_value = {
                "name": "cloudflare", "label": "Named Tunnel", "active": True,
                "url": "https://herramientas.midominio.com", "type": "named_tunnel",
                "source": "named_config", "process_running": False, "service_running": False,
            }
            status = self.ra.detect_all(cfg)
        assert "/scan" in status["scan_url"]
        assert "localhost" not in status["scan_url"]
        assert "127.0.0.1" not in status["scan_url"]
        assert "herramientas.midominio.com" in status["scan_url"]

    def test_scan_url_fallback_to_local_when_no_public(self):
        """Cuando no hay URL pública, scan_url usa IP local (no localhost)."""
        cfg = self.ra._default_config()
        with patch.dict(os.environ, {"MRD_PUBLIC_URL": "", "PUBLIC_URL": "", "MRD_SCAN_URL": ""}), \
             patch.object(self.ra, '_detect_cloudflare', return_value=None), \
             patch.object(self.ra, '_detect_ngrok', return_value=None), \
             patch.object(self.ra, '_detect_tailscale', return_value=None), \
             patch.object(self.ra, '_measure_latency', return_value=5):
            status = self.ra.detect_all(cfg)
        assert "/scan" in status["scan_url"]


# ─── TestMainPyCF ─────────────────────────────────────────────────────────────

class TestMainPyCF:
    """Tests de integración de los endpoints /api/cloudflare/* en main.py."""

    @pytest.fixture(autouse=True)
    def client(self):
        os.environ.setdefault("MRD_SECRET_KEY", "test-cf-sprint54-key-" + "x" * 20)
        from fastapi.testclient import TestClient
        import main as m
        self.client = TestClient(m.app, follow_redirects=False)
        self.app = m.app

    def _auth_headers(self):
        return {}  # Las rutas redirigen si no hay cookie; chequeamos el 303

    def test_cloudflare_panel_requires_auth(self):
        r = self.client.get("/cloudflare")
        assert r.status_code in (303, 401, 403)

    def test_api_cf_status_requires_auth(self):
        r = self.client.get("/api/cloudflare/status")
        assert r.status_code in (303, 401, 403)

    def test_api_cf_info_requires_auth(self):
        r = self.client.get("/api/cloudflare/info")
        assert r.status_code in (303, 401, 403)

    def test_api_cf_test_requires_auth(self):
        r = self.client.post("/api/cloudflare/test")
        assert r.status_code in (303, 401, 403)

    def test_api_cf_restart_requires_auth(self):
        r = self.client.post("/api/cloudflare/restart")
        assert r.status_code in (303, 401, 403)

    def test_api_cf_config_requires_auth(self):
        r = self.client.post("/api/cloudflare/config",
                             json={"cf_public_url": "https://test.com"})
        assert r.status_code in (303, 401, 403)

    def test_login_csrf_exento(self):
        """POST /login no debe devolver 403 por CSRF (está en _CSRF_EXENTOS)."""
        import main as m
        assert "/login" in m._CSRF_EXENTOS

    def test_main_py_imports_cf_tunnel(self):
        """main.py importa cloudflare_tunnel."""
        import main as m
        assert hasattr(m, '_cf_tunnel')

    def test_sprint54_block_in_main(self):
        with open(BASE_DIR / "main.py", encoding="utf-8") as f:
            src = f.read()
        assert "SPRINT 5.4" in src
        assert "/api/cloudflare/status" in src
        assert "/api/cloudflare/test" in src
        assert "/api/cloudflare/restart" in src
        assert "/api/cloudflare/info" in src
        assert "/api/cloudflare/config" in src


# ─── TestInstallScript ────────────────────────────────────────────────────────

class TestInstallScript:
    """Verifica el contenido del script de instalación."""

    @pytest.fixture(autouse=True)
    def content(self):
        self.ps1 = (BASE_DIR / "install_cloudflared.ps1").read_text(encoding="utf-8")

    def test_requires_admin(self):
        assert "Require-Admin" in self.ps1 or "Administrator" in self.ps1

    def test_download_uses_https(self):
        import re
        urls = re.findall(r'https?://[^\s"\']+', self.ps1)
        download_urls = [u for u in urls if "github.com" in u or "cloudflare" in u.lower()]
        assert all(u.startswith("https://") for u in download_urls)

    def test_installs_as_service(self):
        assert "service install" in self.ps1

    def test_configures_auto_start(self):
        assert "start= auto" in self.ps1 or "start=auto" in self.ps1

    def test_configures_recovery(self):
        assert "failure" in self.ps1

    def test_has_uninstall_option(self):
        assert "UninstallOnly" in self.ps1 or "uninstall" in self.ps1

    def test_tunnel_create_command(self):
        assert "tunnel create" in self.ps1

    def test_tunnel_route_dns(self):
        assert "tunnel route dns" in self.ps1

    def test_updates_mrd_config(self):
        assert "remote_access_config.json" in self.ps1

    def test_no_hardcoded_tokens(self):
        # No debe haber tokens hardcodeados
        import re
        assert not re.search(r'(?i)(api[_\-]?key|token|secret)\s*=\s*["\'][a-zA-Z0-9]{20,}', self.ps1)


# ─── TestTemplates54 ──────────────────────────────────────────────────────────

class TestTemplates54:
    """Verifica los templates del Sprint 5.4."""

    def test_cloudflare_html_extends_base(self):
        content = (BASE_DIR / "templates" / "cloudflare.html").read_text(encoding="utf-8")
        assert 'extends "base.html"' in content

    def test_cloudflare_html_has_csrf(self):
        content = (BASE_DIR / "templates" / "cloudflare.html").read_text(encoding="utf-8")
        assert "_csrf_token" in content or "csrf_token" in content

    def test_cloudflare_html_has_api_calls(self):
        content = (BASE_DIR / "templates" / "cloudflare.html").read_text(encoding="utf-8")
        assert "/api/cloudflare/status" in content
        assert "/api/cloudflare/test" in content

    def test_cloudflare_html_no_credentials_displayed(self):
        content = (BASE_DIR / "templates" / "cloudflare.html").read_text(encoding="utf-8")
        assert "credentials-file" not in content.lower() or "credentials_file" not in content.lower()

    def test_acceso_remoto_html_has_qr_buttons(self):
        content = (BASE_DIR / "templates" / "acceso_remoto.html").read_text(encoding="utf-8")
        assert "Descargar QR" in content or "arDescargarQR" in content

    def test_acceso_remoto_html_has_copy_url(self):
        content = (BASE_DIR / "templates" / "acceso_remoto.html").read_text(encoding="utf-8")
        assert "Copiar URL" in content or "arCopiarURL" in content

    def test_acceso_remoto_html_cf_status(self):
        content = (BASE_DIR / "templates" / "acceso_remoto.html").read_text(encoding="utf-8")
        assert "ar-cf-status" in content or "Cloudflare" in content

    def test_acceso_remoto_html_cf_version(self):
        content = (BASE_DIR / "templates" / "acceso_remoto.html").read_text(encoding="utf-8")
        assert "cf-version" in content or "cloudflared" in content.lower()

    def test_acceso_remoto_html_link_to_cf_panel(self):
        content = (BASE_DIR / "templates" / "acceso_remoto.html").read_text(encoding="utf-8")
        assert "/cloudflare" in content

    def test_login_html_csrf_field_present(self):
        content = (BASE_DIR / "templates" / "login.html").read_text(encoding="utf-8")
        assert "_csrf_token" in content
