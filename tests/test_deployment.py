"""
tests/test_deployment.py — Suite de tests Sprint 5.8 IASMRD Cloudflare Deployment
Verifica configuración, middleware, variables de entorno y ficheros de documentación.
"""
import os
import sys
import json
from pathlib import Path

# ─── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
DOCS_DIR = BASE_DIR / "docs"
SCRIPTS_DIR = BASE_DIR / "scripts"
CONFIG_DIR = BASE_DIR / "config"


# ══════════════════════════════════════════════════════════════════════════════
# TestFileStructure58 — Estructura de ficheros del sprint
# ══════════════════════════════════════════════════════════════════════════════

class TestFileStructure58:
    """Verifica que todos los ficheros del Sprint 5.8 existen."""

    def test_config_local_env_exists(self):
        assert (CONFIG_DIR / "local.env").exists()

    def test_env_example_exists(self):
        assert (BASE_DIR / ".env.example").exists()

    def test_cloudflare_config_example_exists(self):
        assert (CONFIG_DIR / "cloudflare" / "config.example.yml").exists()

    def test_cloudflare_status_ps1_exists(self):
        assert (SCRIPTS_DIR / "cloudflare_status.ps1").exists()

    def test_cloudflare_restart_ps1_exists(self):
        assert (SCRIPTS_DIR / "cloudflare_restart.ps1").exists()

    def test_cloudflare_logs_ps1_exists(self):
        assert (SCRIPTS_DIR / "cloudflare_logs.ps1").exists()

    def test_cloudflare_test_ps1_exists(self):
        assert (SCRIPTS_DIR / "cloudflare_test.ps1").exists()

    def test_doc_cloudflare_iasmrd_exists(self):
        assert (DOCS_DIR / "CLOUDFLARE_IASMRD.md").exists()

    def test_doc_dominios_exists(self):
        assert (DOCS_DIR / "DOMINIOS_IASMRD.md").exists()

    def test_doc_acceso_remoto_exists(self):
        assert (DOCS_DIR / "ACCESO_REMOTO.md").exists()

    def test_doc_recuperar_tunel_exists(self):
        assert (DOCS_DIR / "RECUPERAR_TUNEL.md").exists()

    def test_doc_probar_movil_exists(self):
        assert (DOCS_DIR / "PROBAR_DESDE_MOVIL.md").exists()

    def test_doc_cloudflare_access_exists(self):
        assert (DOCS_DIR / "CLOUDFLARE_ACCESS.md").exists()

    def test_doc_cloudflare_security_exists(self):
        assert (DOCS_DIR / "CLOUDFLARE_SECURITY.md").exists()


# ══════════════════════════════════════════════════════════════════════════════
# TestConfigModule58 — Variables en config.py
# ══════════════════════════════════════════════════════════════════════════════

class TestConfigModule58:
    """Verifica que config.py exporta las nuevas variables del Sprint 5.8."""

    def _load_config(self):
        sys.path.insert(0, str(BASE_DIR))
        import importlib
        import config as cfg
        importlib.reload(cfg)
        return cfg

    def test_mrd_public_url_exported(self):
        cfg = self._load_config()
        assert hasattr(cfg, "MRD_PUBLIC_URL")

    def test_mrd_scan_url_exported(self):
        cfg = self._load_config()
        assert hasattr(cfg, "MRD_SCAN_URL")

    def test_mrd_trust_proxy_headers_exported(self):
        cfg = self._load_config()
        assert hasattr(cfg, "MRD_TRUST_PROXY_HEADERS")
        assert isinstance(cfg.MRD_TRUST_PROXY_HEADERS, bool)

    def test_mrd_https_only_exported(self):
        cfg = self._load_config()
        assert hasattr(cfg, "MRD_HTTPS_ONLY")
        assert isinstance(cfg.MRD_HTTPS_ONLY, bool)

    def test_mrd_allowed_hosts_exported(self):
        cfg = self._load_config()
        assert hasattr(cfg, "MRD_ALLOWED_HOSTS")
        assert isinstance(cfg.MRD_ALLOWED_HOSTS, list)

    def test_mrd_public_url_strips_trailing_slash(self):
        """MRD_PUBLIC_URL no debe tener barra final."""
        cfg = self._load_config()
        assert not cfg.MRD_PUBLIC_URL.endswith("/")

    def test_scan_url_derived_from_public_url(self):
        """Si MRD_PUBLIC_URL está definida, MRD_SCAN_URL debe terminar en /scan."""
        cfg = self._load_config()
        if cfg.MRD_PUBLIC_URL and not os.getenv("MRD_SCAN_URL"):
            assert cfg.MRD_SCAN_URL.endswith("/scan")


# ══════════════════════════════════════════════════════════════════════════════
# TestLocalEnv58 — Contenido de config/local.env
# ══════════════════════════════════════════════════════════════════════════════

class TestLocalEnv58:
    """Verifica que config/local.env tiene las variables IASMRD correctas."""

    def _read_env(self):
        env_file = CONFIG_DIR / "local.env"
        lines = env_file.read_text(encoding="utf-8").splitlines()
        env = {}
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
        return env

    def test_mrd_env_is_production(self):
        env = self._read_env()
        assert env.get("MRD_ENV") == "production"

    def test_mrd_public_url_set(self):
        env = self._read_env()
        assert "MRD_PUBLIC_URL" in env
        assert env["MRD_PUBLIC_URL"].startswith("https://")

    def test_mrd_public_url_no_trailing_slash(self):
        env = self._read_env()
        assert not env.get("MRD_PUBLIC_URL", "").endswith("/")

    def test_mrd_https_only_true(self):
        env = self._read_env()
        assert env.get("MRD_HTTPS_ONLY") == "true"

    def test_mrd_trust_proxy_headers_true(self):
        env = self._read_env()
        assert env.get("MRD_TRUST_PROXY_HEADERS") == "true"

    def test_mrd_allowed_hosts_set(self):
        env = self._read_env()
        assert "MRD_ALLOWED_HOSTS" in env
        assert len(env["MRD_ALLOWED_HOSTS"]) > 0

    def test_mrd_scan_url_set(self):
        env = self._read_env()
        assert "MRD_SCAN_URL" in env
        assert env["MRD_SCAN_URL"].endswith("/scan")

    def test_mrd_scan_url_https(self):
        env = self._read_env()
        assert env.get("MRD_SCAN_URL", "").startswith("https://")

    def test_mrd_cloudflare_tunnel_type(self):
        env = self._read_env()
        assert env.get("MRD_CLOUDFLARE_TUNNEL_TYPE") == "named"

    def test_mrd_remote_provider(self):
        env = self._read_env()
        assert env.get("MRD_REMOTE_PROVIDER") == "cloudflare"


# ══════════════════════════════════════════════════════════════════════════════
# TestDotEnvExample58 — Contenido de .env.example
# ══════════════════════════════════════════════════════════════════════════════

class TestDotEnvExample58:
    """Verifica que .env.example no tiene credenciales reales."""

    def _read_text(self):
        return (BASE_DIR / ".env.example").read_text(encoding="utf-8")

    def test_no_real_secret_key(self):
        txt = self._read_text()
        # La línea MRD_SECRET_KEY= debe estar vacía o con placeholder
        for line in txt.splitlines():
            if line.startswith("MRD_SECRET_KEY="):
                val = line.split("=", 1)[1].strip()
                assert len(val) == 0 or "TU" in val.upper() or "PLACEHOLDER" in val.upper() or len(val) < 10

    def test_no_real_uuid(self):
        """No debe contener UUIDs reales (longitud 36 con guiones)."""
        import re
        txt = self._read_text()
        uuids = re.findall(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            txt, re.IGNORECASE
        )
        assert len(uuids) == 0, f"UUID encontrado: {uuids}"

    def test_placeholder_domain(self):
        """Usa 'tudominio.com' como placeholder, no 'iasmrd.com'."""
        txt = self._read_text()
        assert "tudominio" in txt.lower()

    def test_new_iasmrd_vars_present(self):
        txt = self._read_text()
        assert "MRD_PUBLIC_URL" in txt
        assert "MRD_TRUST_PROXY_HEADERS" in txt
        assert "MRD_ALLOWED_HOSTS" in txt
        assert "MRD_SCAN_URL" in txt


# ══════════════════════════════════════════════════════════════════════════════
# TestMainPy58 — Verificación de main.py (sin importar)
# ══════════════════════════════════════════════════════════════════════════════

class TestMainPy58:
    """Verifica el contenido de main.py sin importarlo (evita dependencias)."""

    def _read_main(self):
        return (BASE_DIR / "main.py").read_text(encoding="utf-8")

    def test_main_syntax_valid(self):
        import ast
        src = self._read_main()
        ast.parse(src)  # lanza SyntaxError si hay error

    def test_proxy_headers_middleware_present(self):
        src = self._read_main()
        assert "_proxy_headers_mw" in src

    def test_trusted_host_middleware_import(self):
        src = self._read_main()
        assert "TrustedHostMiddleware" in src

    def test_mrd_public_url_imported(self):
        src = self._read_main()
        assert "MRD_PUBLIC_URL" in src

    def test_mrd_scan_url_imported(self):
        src = self._read_main()
        assert "MRD_SCAN_URL" in src

    def test_trust_proxy_headers_imported(self):
        src = self._read_main()
        assert "MRD_TRUST_PROXY_HEADERS" in src

    def test_diagnostics_endpoint_present(self):
        src = self._read_main()
        assert "api_deployment_diagnostics" in src
        assert "/api/deployment/diagnostics" in src

    def test_https_only_in_is_https(self):
        src = self._read_main()
        assert "_MRD_HTTPS_ONLY" in src

    def test_cf_visitor_header_checked(self):
        src = self._read_main()
        assert "cf-visitor" in src


# ══════════════════════════════════════════════════════════════════════════════
# TestRemoteAccess58 — remote_access.py actualizado
# ══════════════════════════════════════════════════════════════════════════════

class TestRemoteAccess58:
    """Verifica que remote_access.py usa MRD_PUBLIC_URL y MRD_SCAN_URL."""

    def _read_ra(self):
        return (BASE_DIR / "remote_access.py").read_text(encoding="utf-8")

    def test_env_public_url_override(self):
        src = self._read_ra()
        assert "MRD_PUBLIC_URL" in src
        assert "_env_public_url" in src

    def test_env_scan_url_override(self):
        src = self._read_ra()
        assert "MRD_SCAN_URL" in src
        assert "_env_scan_url" in src

    def test_sprint58_comment(self):
        src = self._read_ra()
        assert "Sprint 5.8" in src


# ══════════════════════════════════════════════════════════════════════════════
# TestDocumentation58 — Contenido mínimo de los docs
# ══════════════════════════════════════════════════════════════════════════════

class TestDocumentation58:
    """Verifica que los documentos contienen secciones clave."""

    def test_cloudflare_doc_has_install_section(self):
        txt = (DOCS_DIR / "CLOUDFLARE_IASMRD.md").read_text(encoding="utf-8")
        assert "Instalación" in txt or "instalación" in txt
        assert "app.iasmrd.com" in txt

    def test_security_doc_has_no_real_tokens(self):
        txt = (DOCS_DIR / "CLOUDFLARE_SECURITY.md").read_text(encoding="utf-8")
        # No debe haber tokens reales (secuencias largas de hex que no sean ejemplos)
        import re
        hex40 = re.findall(r"[0-9a-f]{40,}", txt, re.IGNORECASE)
        assert len(hex40) == 0, f"Posible token real: {hex40}"

    def test_recovery_doc_has_cases(self):
        txt = (DOCS_DIR / "RECUPERAR_TUNEL.md").read_text(encoding="utf-8")
        assert "Caso 1" in txt
        assert "Caso 2" in txt

    def test_ps1_no_hardcoded_tokens(self):
        """Los scripts PS1 no deben contener tokens hardcoded."""
        import re
        for ps1 in SCRIPTS_DIR.glob("cloudflare_*.ps1"):
            txt = ps1.read_text(encoding="utf-8", errors="ignore")
            hex40 = re.findall(r"[0-9a-f]{40,}", txt, re.IGNORECASE)
            assert len(hex40) == 0, f"{ps1.name}: posible token: {hex40}"


# ══════════════════════════════════════════════════════════════════════════════
# Runner independiente
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import traceback

    suites = [
        TestFileStructure58,
        TestConfigModule58,
        TestLocalEnv58,
        TestDotEnvExample58,
        TestMainPy58,
        TestRemoteAccess58,
        TestDocumentation58,
    ]

    total = passed = failed = 0
    for suite_cls in suites:
        suite = suite_cls()
        methods = [m for m in dir(suite) if m.startswith("test_")]
        print(f"\n{'─'*50}")
        print(f"  {suite_cls.__name__} ({len(methods)} tests)")
        print(f"{'─'*50}")
        for m in methods:
            total += 1
            try:
                getattr(suite, m)()
                print(f"  ✓ {m}")
                passed += 1
            except Exception as e:
                print(f"  ✗ {m}: {e}")
                failed += 1

    print(f"\n{'═'*50}")
    status = "PASS" if failed == 0 else "FAIL"
    print(f"  {status}: {passed}/{total} tests correctos ({failed} fallidos)")
    print(f"{'═'*50}")
    sys.exit(0 if failed == 0 else 1)
