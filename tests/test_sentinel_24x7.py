import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sentinel import auth
from sentinel.app import create_app
from sentinel.config import SentinelConfig, WatchedApp, load_config
from sentinel.health_monitor import HealthMonitor
import sentinel.health_monitor as health_monitor_module


ROOT = Path(__file__).resolve().parents[1]


def test_instalador_usa_tarea_system_y_no_pywin32():
    source = (ROOT / "scripts/operations/install_sentinel_task.ps1").read_text(encoding="utf-8")
    assert "Register-ScheduledTask" in source
    assert '-UserId "SYSTEM"' in source
    assert "-AtStartup" in source
    assert "-AllowStartIfOnBatteries" in source
    assert "-DontStopIfGoingOnBatteries" in source
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in source
    assert "-RestartCount 50" in source
    assert "-m sentinel.service run" in source
    assert "import win32" not in source.lower()
    assert "pythonservice.exe" not in source.split("$action =", 1)[1].lower()


def test_instalador_es_vista_previa_por_defecto_y_apply_obligatorio():
    source = (ROOT / "scripts/operations/install_sentinel_task.ps1").read_text(encoding="utf-8")
    assert "[switch]$Apply" in source
    assert "if (-not $Apply)" in source
    assert "Register-ScheduledTask" in source.split("if (-not $Apply)", 1)[1]


def test_instalador_admite_modo_usuario_sin_elevar_permisos():
    source = (ROOT / "scripts/operations/install_sentinel_task.ps1").read_text(encoding="utf-8")
    assert "[switch]$CurrentUser" in source
    assert "-AtLogOn" in source
    assert "-LogonType Interactive" in source
    assert "-not $CurrentUser -and -not (Test-IsAdministrator)" in source


def test_desinstalador_conserva_datos_y_requiere_apply():
    source = (ROOT / "scripts/operations/uninstall_sentinel_task.ps1").read_text(encoding="utf-8")
    assert "[switch]$Apply" in source
    assert "if (-not $Apply)" in source
    assert "Unregister-ScheduledTask" in source
    assert "Remove-Item" not in source


def test_instalador_antiguo_redirige_a_la_tarea_segura():
    source = (ROOT / "scripts/operations/install_sentinel_service.ps1").read_text(encoding="utf-8")
    active_prefix = source.split("# Implementacion historica", 1)[0]
    assert "install_sentinel_task.ps1" in active_prefix
    assert "HandleCommandLine" not in active_prefix
    assert "Register-ScheduledTask" not in active_prefix


def test_primera_apertura_ofrece_configuracion_local(monkeypatch, tmp_path):
    users = tmp_path / "users.json"
    secret = tmp_path / "secret.key"
    monkeypatch.setattr(auth, "USERS_PATH", users)
    monkeypatch.setattr(auth, "SECRET_KEY_PATH", secret)

    with TestClient(create_app()) as client:
        response = client.get("/login", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/setup"

        setup = client.get("/setup")
        assert setup.status_code == 200
        assert "Configuración inicial" in setup.text

        created = client.post(
            "/setup",
            data={
                "username": "admin",
                "password": "ClaveSegura123",
                "password_confirm": "ClaveSegura123",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        assert auth.authenticate("admin", "ClaveSegura123")


def test_configuracion_inicial_no_se_reabre_si_ya_hay_usuario(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(auth, "SECRET_KEY_PATH", tmp_path / "secret.key")
    auth.create_user("admin", "ClaveSegura123")

    with TestClient(create_app()) as client:
        response = client.get("/setup", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


def test_configuracion_inicial_remota_esta_bloqueada(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(auth, "SECRET_KEY_PATH", tmp_path / "secret.key")
    with TestClient(create_app(), client=("192.0.2.10", 50000)) as client:
        assert client.get("/setup").status_code == 403


def test_metricas_se_muestran_en_el_panel(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(auth, "SECRET_KEY_PATH", tmp_path / "secret.key")
    auth.create_user("admin", "ClaveSegura123")
    config_path = tmp_path / "apps.yaml"
    config_path.write_text(
        "sentinel:\n  host: 127.0.0.1\n  port: 9100\napps:\n"
        "  - id: demo\n    display_name: Demo\n    local_url: http://127.0.0.1:9999\n"
        "    health_path: /health\n    public_hostname: demo.local\n"
        "    failover_state_root: C:\\\\ProgramData\\\\Demo\\\\failover\n",
        encoding="utf-8",
    )
    with TestClient(create_app(config_path)) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.create_token("admin"))
        response = client.get("/")
        assert response.status_code == 200
        assert "CPU" in response.text
        assert "Memoria" in response.text
        assert "Equipo encendido" in response.text


def test_se_puede_anadir_aplicacion_y_se_recarga_sin_reinicio(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(auth, "SECRET_KEY_PATH", tmp_path / "secret.key")
    auth.create_user("admin", "ClaveSegura123")
    config_path = tmp_path / "apps.yaml"
    config_path.write_text(
        "sentinel:\n  host: 127.0.0.1\n  port: 9100\napps:\n"
        "  - id: demo\n    display_name: Demo\n    local_url: http://127.0.0.1:9999\n"
        "    health_path: /health\n    public_hostname: demo.local\n"
        "    failover_state_root: C:\\\\ProgramData\\\\Demo\\\\failover\n",
        encoding="utf-8",
    )
    with TestClient(create_app(config_path)) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.create_token("admin"))
        response = client.post("/apps", data={
            "id": "otra_app", "display_name": "Otra app",
            "local_url": "http://127.0.0.1:8100", "health_path": "/health",
            "public_hostname": "otra.local",
        }, follow_redirects=False)
        assert response.status_code == 303
        assert "otra_app" in response.headers["location"] or response.headers["location"] == "/?added=1"
        assert load_config(config_path).get_app("otra_app") is not None


def _config_con_una_app(tmp_path: Path) -> SentinelConfig:
    return SentinelConfig(
        host="127.0.0.1",
        port=9100,
        apps=[
            WatchedApp(
                id="demo",
                display_name="Demo",
                local_url="http://127.0.0.1:9999",
                health_path="/health",
                public_hostname="demo.local",
                failover_state_root=tmp_path / "failover",
                proxy_enabled=False,
            )
        ],
    )


def test_check_now_actualiza_la_cache_del_monitor(monkeypatch, tmp_path):
    monitor = HealthMonitor(_config_con_una_app(tmp_path))
    monkeypatch.setattr(health_monitor_module, "check_http_health", lambda url, timeout: True)

    result = monitor.check_now("demo")

    assert result is not None
    assert result.healthy is True
    assert monitor.get("demo") is result


def test_check_now_con_app_desconocida_devuelve_none(tmp_path):
    monitor = HealthMonitor(_config_con_una_app(tmp_path))
    assert monitor.check_now("no_existe") is None


def test_boton_comprobar_ahora_dispara_check_now(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(auth, "SECRET_KEY_PATH", tmp_path / "secret.key")
    auth.create_user("admin", "ClaveSegura123")
    config_path = tmp_path / "apps.yaml"
    config_path.write_text(
        "sentinel:\n  host: 127.0.0.1\n  port: 9100\napps:\n"
        "  - id: demo\n    display_name: Demo\n    local_url: http://127.0.0.1:9999\n"
        "    health_path: /health\n    public_hostname: demo.local\n"
        "    failover_state_root: C:\\\\ProgramData\\\\Demo\\\\failover\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(health_monitor_module, "check_http_health", lambda url, timeout: True)
    with TestClient(create_app(config_path)) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.create_token("admin"))
        response = client.post("/apps/demo/check", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/?checked=demo#app-demo"


def test_check_now_guarda_el_tiempo_de_respuesta(monkeypatch, tmp_path):
    monitor = HealthMonitor(_config_con_una_app(tmp_path))
    monkeypatch.setattr(health_monitor_module, "check_http_health", lambda url, timeout: True)

    result = monitor.check_now("demo")

    assert result is not None
    assert result.latency_ms is not None
    assert result.latency_ms >= 0
    assert monitor.latency_snapshot() == {"demo": result.latency_ms}


def test_historial_de_metricas_se_expone_de_forma_autenticada(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(auth, "SECRET_KEY_PATH", tmp_path / "secret.key")
    auth.create_user("admin", "ClaveSegura123")
    config_path = tmp_path / "apps.yaml"
    config_path.write_text(
        "sentinel:\n  host: 127.0.0.1\n  port: 9100\napps:\n"
        "  - id: demo\n    display_name: Demo\n    local_url: http://127.0.0.1:9999\n"
        "    health_path: /health\n    public_hostname: demo.local\n"
        "    failover_state_root: C:\\\\ProgramData\\\\Demo\\\\failover\n",
        encoding="utf-8",
    )
    with TestClient(create_app(config_path)) as client:
        sin_auth = client.get("/metrics/history", follow_redirects=False)
        assert sin_auth.status_code in (401, 303)

        client.cookies.set(auth.COOKIE_NAME, auth.create_token("admin"))
        response = client.get("/metrics/history")
        assert response.status_code == 200
        body = response.json()
        assert "points" in body
        assert isinstance(body["points"], list)
        # El sampler hace una toma inmediata al arrancar (ver _run), asi que
        # deberia haber al menos un punto tras el ciclo de vida de la app.
        assert len(body["points"]) >= 1
        primer_punto = body["points"][0]
        assert set(primer_punto) == {
            "timestamp", "cpu_percent", "memory_percent", "disk_percent", "response_ms",
        }
    # El historial debe quedar aislado en tmp_path, nunca en la ruta real de
    # ProgramData del equipo.
    assert (tmp_path / "metrics_history.json").exists()


def test_dashboard_incluye_grafico_de_historico_de_metricas(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(auth, "SECRET_KEY_PATH", tmp_path / "secret.key")
    auth.create_user("admin", "ClaveSegura123")
    config_path = tmp_path / "apps.yaml"
    config_path.write_text(
        "sentinel:\n  host: 127.0.0.1\n  port: 9100\napps:\n"
        "  - id: demo\n    display_name: Demo\n    local_url: http://127.0.0.1:9999\n"
        "    health_path: /health\n    public_hostname: demo.local\n"
        "    failover_state_root: C:\\\\ProgramData\\\\Demo\\\\failover\n",
        encoding="utf-8",
    )
    with TestClient(create_app(config_path)) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.create_token("admin"))
        response = client.get("/")
        assert response.status_code == 200
        assert 'id="metrics-chart"' in response.text
        assert "/metrics/history" in response.text


def test_historial_de_metricas_no_crece_sin_limite(tmp_path):
    from sentinel.metrics_history import MetricsHistory

    history = MetricsHistory(path=tmp_path / "metrics_history.json", max_points=5)
    for i in range(20):
        history.add_point(cpu_percent=float(i), memory_percent=None, disk_percent=None)

    assert len(history.recent()) == 5
    assert history.recent()[-1]["cpu_percent"] == 19.0


def test_tunnel_checks_no_inventa_estado_si_powershell_falla(monkeypatch):
    from sentinel import tunnel_checks

    class _FakeCompletedProcess:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(
        tunnel_checks.subprocess, "run",
        lambda *a, **k: _FakeCompletedProcess(),
    )
    servicio = tunnel_checks.check_cloudflared_service()
    tarea = tunnel_checks.check_cloudflared_backup_task()
    assert servicio.state == "not_available"
    assert tarea.state == "not_available"


def test_tunnel_checks_interpreta_estados_reales(monkeypatch):
    from sentinel import tunnel_checks

    respuestas = iter(["Running", "Ready"])

    class _FakeCompletedProcess:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout

    monkeypatch.setattr(
        tunnel_checks.subprocess, "run",
        lambda *a, **k: _FakeCompletedProcess(next(respuestas)),
    )
    servicio = tunnel_checks.check_cloudflared_service()
    tarea = tunnel_checks.check_cloudflared_backup_task()
    assert servicio.state == "running"
    assert tarea.state == "ready"


def test_tunnel_monitor_nunca_llama_subprocess_con_shell_true(monkeypatch):
    from sentinel import tunnel_checks

    llamadas = []

    class _FakeCompletedProcess:
        returncode = 0
        stdout = "Running"

    def _fake_run(args, **kwargs):
        llamadas.append((args, kwargs))
        return _FakeCompletedProcess()

    monkeypatch.setattr(tunnel_checks.subprocess, "run", _fake_run)
    monitor = tunnel_checks.TunnelMonitor()
    results = monitor.check_now()

    assert set(results) == {"cloudflared", "cloudflared_backup"}
    for args, kwargs in llamadas:
        assert isinstance(args, list)
        assert kwargs.get("shell", False) is False
    assert monitor.snapshot() == results


def test_component_check_nunca_pasa_allow_dr4_ni_modo_repair(monkeypatch):
    from sentinel import component_checks

    llamadas = []

    class _FakeCompletedProcess:
        returncode = 0
        stdout = (
            '{"ok": true, "timestamp": "2026-09-05T00:00:00+00:00", '
            '"components": {"base_datos": {"status": "ok", "detail": "Integridad SQLite correcta"}}, '
            '"remaining_errors": []}'
        )

    def _fake_run(args, **kwargs):
        llamadas.append(args)
        return _FakeCompletedProcess()

    monkeypatch.setattr(
        component_checks, "REPAIR_CENTER_SCRIPT",
        component_checks.REPO_ROOT / "sentinel" / "__init__.py",
    )
    monkeypatch.setattr(component_checks.subprocess, "run", _fake_run)

    result = component_checks.run_component_check()

    assert result.ok is True
    assert result.components["base_datos"]["status"] == "ok"
    assert len(llamadas) == 1
    args = llamadas[0]
    assert "--allow-dr4" not in args
    assert "repair" not in args
    assert "check" in args


def test_component_check_no_inventa_estado_si_falla(monkeypatch):
    from sentinel import component_checks

    monkeypatch.setattr(component_checks, "REPAIR_CENTER_SCRIPT", component_checks.REPO_ROOT / "no_existe.py")
    result = component_checks.run_component_check()
    assert result.ok is None
    assert result.error == "repair_center_no_disponible"


def test_dashboard_muestra_uptime_version_tuneles_y_componentes(monkeypatch, tmp_path):
    from sentinel import component_checks, tunnel_checks

    monkeypatch.setattr(auth, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(auth, "SECRET_KEY_PATH", tmp_path / "secret.key")
    auth.create_user("admin", "ClaveSegura123")
    config_path = tmp_path / "apps.yaml"
    config_path.write_text(
        "sentinel:\n  host: 127.0.0.1\n  port: 9100\napps:\n"
        "  - id: demo\n    display_name: Demo\n    local_url: http://127.0.0.1:9999\n"
        "    health_path: /health\n    public_hostname: demo.local\n"
        "    failover_state_root: C:\\\\ProgramData\\\\Demo\\\\failover\n",
        encoding="utf-8",
    )

    class _FakeTunnelProcess:
        def __init__(self, stdout):
            self.returncode = 0
            self.stdout = stdout

    respuestas = iter(["Running", "Ready"])
    monkeypatch.setattr(
        tunnel_checks.subprocess, "run",
        lambda *a, **k: _FakeTunnelProcess(next(respuestas)),
    )

    class _FakeComponentProcess:
        returncode = 0
        stdout = (
            '{"ok": true, "timestamp": "2026-09-05T00:00:00+00:00", '
            '"components": {"base_datos": {"status": "ok", "detail": "Integridad SQLite correcta"}}, '
            '"remaining_errors": []}'
        )

    monkeypatch.setattr(
        component_checks, "REPAIR_CENTER_SCRIPT",
        component_checks.REPO_ROOT / "sentinel" / "__init__.py",
    )
    monkeypatch.setattr(component_checks.subprocess, "run", lambda *a, **k: _FakeComponentProcess())

    with TestClient(create_app(config_path)) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.create_token("admin"))
        response = None
        for _ in range(50):
            response = client.get("/")
            if "Base datos" in response.text:
                break
            time.sleep(0.05)
        assert response.status_code == 200
        assert "Sentinel encendido" in response.text
        assert "Versión MRD" in response.text
        assert "Túnel principal (A)" in response.text
        assert "Túnel de respaldo (B)" in response.text
        assert "Base datos" in response.text


def test_vista_publica_no_requiere_login_y_es_solo_lectura(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(auth, "SECRET_KEY_PATH", tmp_path / "secret.key")
    auth.create_user("admin", "ClaveSegura123")
    config_path = tmp_path / "apps.yaml"
    config_path.write_text(
        "sentinel:\n  host: 127.0.0.1\n  port: 9100\napps:\n"
        "  - id: demo\n    display_name: Demo\n    local_url: http://127.0.0.1:9999\n"
        "    health_path: /health\n    public_hostname: demo.local\n"
        "    failover_state_root: C:\\\\ProgramData\\\\Demo\\\\failover\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(health_monitor_module, "check_http_health", lambda url, timeout: True)
    with TestClient(create_app(config_path)) as client:
        response = client.get("/status")
        assert response.status_code == 200
        assert "Estado del sistema" in response.text
        assert "http://127.0.0.1:9999" not in response.text
        assert "ProgramData" not in response.text

        response_json = client.get("/status.json")
        assert response_json.status_code == 200
        payload = response_json.json()
        assert payload["overall"] in ("ok", "atencion", "caido")
        assert set(payload["cards"]) == {
            "aplicacion_mrd", "base_datos", "escaner_qr", "acceso_remoto",
            "tunel_a", "tunel_b", "sentinel",
        }

        # De solo lectura: no existe ninguna accion publica sin login.
        response_post = client.post("/apps/demo/check", follow_redirects=False)
        assert response_post.status_code in (303, 401)
        if response_post.status_code == 303:
            assert response_post.headers["location"] == "/login"


def test_admin_actions_lista_cerrada_no_incluye_reinicios_ni_reparaciones(monkeypatch, tmp_path):
    from sentinel import admin_actions
    from sentinel.config import load_config

    config_path = tmp_path / "apps.yaml"
    config_path.write_text(
        "sentinel:\n  host: 127.0.0.1\n  port: 9100\napps:\n"
        "  - id: demo\n    display_name: Demo\n    local_url: http://127.0.0.1:9999\n"
        "    health_path: /health\n    public_hostname: demo.local\n"
        "    failover_state_root: C:\\\\ProgramData\\\\Demo\\\\failover\n",
        encoding="utf-8",
    )
    config = load_config(config_path)
    health_monitor = HealthMonitor(config)
    from sentinel import component_checks, tunnel_checks

    actions = admin_actions.build_actions(
        config, health_monitor,
        component_checks.ComponentMonitor(), tunnel_checks.TunnelMonitor(),
    )
    prohibidas_id = ("reiniciar", "restart", "reparar", "dr4")
    for action_id, action in actions.items():
        for palabra in prohibidas_id:
            assert palabra not in action_id.lower()
        assert action.component != "dr4"
        # Ninguna accion debe prometer ejecutar una reparacion, solo comprobarla.
        assert "ejecutar reparación" not in action.label.lower()
        assert "modo repair" not in action.label.lower()


def test_admin_action_runner_registra_auditoria_en_exito_y_error(tmp_path):
    from sentinel.admin_actions import ActionDef, ActionResult, AdminActionRunner, AuditLog

    audit_log = AuditLog(path=tmp_path / "audit_log.json")
    actions = {
        "ok_action": ActionDef(id="ok_action", label="Ok", component="demo", run=lambda: ActionResult(True, "bien")),
        "bad_action": ActionDef(id="bad_action", label="Mal", component="demo", run=lambda: ActionResult(False, "fallo")),
    }
    runner = AdminActionRunner(actions, audit_log)

    runner.execute("ok_action", "admin")
    runner.execute("bad_action", "otro_admin")

    entradas = audit_log.recent()
    assert len(entradas) == 2
    resultados = {(e["executor"], e["action_id"]): e["result"] for e in entradas}
    assert resultados[("admin", "ok_action")] == "ok"
    assert resultados[("otro_admin", "bad_action")] == "error: fallo"


def test_admin_action_runner_bloquea_doble_clic(tmp_path):
    from sentinel.admin_actions import ActionDef, ActionResult, AdminActionError, AdminActionRunner, AuditLog

    audit_log = AuditLog(path=tmp_path / "audit_log.json")
    actions = {"a": ActionDef(id="a", label="A", component="demo", run=lambda: ActionResult(True, "ok"))}
    runner = AdminActionRunner(actions, audit_log)

    runner.execute("a", "admin")
    with pytest.raises(AdminActionError, match="doble_clic_bloqueado"):
        runner.execute("a", "admin")


def test_admin_action_runner_limita_peticiones_por_usuario(tmp_path):
    from sentinel.admin_actions import (
        ActionDef, ActionResult, AdminActionError, AdminActionRunner,
        AuditLog, RATE_LIMIT_MAX_ACTIONS,
    )

    audit_log = AuditLog(path=tmp_path / "audit_log.json")
    actions = {
        f"a{i}": ActionDef(id=f"a{i}", label=f"A{i}", component="demo", run=lambda: ActionResult(True, "ok"))
        for i in range(RATE_LIMIT_MAX_ACTIONS + 1)
    }
    runner = AdminActionRunner(actions, audit_log)

    for i in range(RATE_LIMIT_MAX_ACTIONS):
        runner.execute(f"a{i}", "admin")

    with pytest.raises(AdminActionError, match="limite_de_peticiones_alcanzado"):
        runner.execute(f"a{RATE_LIMIT_MAX_ACTIONS}", "admin")


def test_admin_action_runner_una_sola_accion_a_la_vez(tmp_path):
    from sentinel.admin_actions import ActionDef, ActionResult, AdminActionError, AdminActionRunner, AuditLog

    audit_log = AuditLog(path=tmp_path / "audit_log.json")
    started = threading.Event()
    release = threading.Event()

    def _lenta() -> ActionResult:
        started.set()
        release.wait(timeout=5)
        return ActionResult(True, "ok")

    actions = {
        "lenta": ActionDef(id="lenta", label="Lenta", component="demo", run=_lenta),
        "rapida": ActionDef(id="rapida", label="Rapida", component="demo", run=lambda: ActionResult(True, "ok")),
    }
    runner = AdminActionRunner(actions, audit_log)

    hilo = threading.Thread(target=runner.execute, args=("lenta", "admin"))
    hilo.start()
    started.wait(timeout=5)
    try:
        with pytest.raises(AdminActionError, match="ya_hay_una_accion_en_curso"):
            runner.execute("rapida", "otro_admin")
    finally:
        release.set()
        hilo.join(timeout=5)


def test_endpoint_de_acciones_requiere_login_y_confirmacion(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(auth, "SECRET_KEY_PATH", tmp_path / "secret.key")
    auth.create_user("admin", "ClaveSegura123")
    config_path = tmp_path / "apps.yaml"
    config_path.write_text(
        "sentinel:\n  host: 127.0.0.1\n  port: 9100\napps:\n"
        "  - id: demo\n    display_name: Demo\n    local_url: http://127.0.0.1:9999\n"
        "    health_path: /health\n    public_hostname: demo.local\n"
        "    failover_state_root: C:\\\\ProgramData\\\\Demo\\\\failover\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(health_monitor_module, "check_http_health", lambda url, timeout: True)
    with TestClient(create_app(config_path)) as client:
        sin_auth = client.get("/admin/acciones", follow_redirects=False)
        assert sin_auth.status_code in (401, 303)

        client.cookies.set(auth.COOKIE_NAME, auth.create_token("admin"))
        response = client.get("/admin/acciones")
        assert response.status_code == 200
        assert "recheck_app_demo" in response.text or "Comprobar Demo ahora" in response.text

        sin_confirmar = client.post("/admin/acciones/recheck_app_demo", data={})
        # Sin confirmar=si, la accion debe rechazarse (400) y nunca ejecutarse.
        assert sin_confirmar.status_code in (400, 404)

        confirmado = client.post(
            "/admin/acciones/recheck_app_demo", data={"confirmar": "si"}, follow_redirects=False,
        )
        assert confirmado.status_code == 303
        assert "resultado=" in confirmado.headers["location"]


def test_tunnel_repair_nunca_llama_subprocess_con_shell_true(monkeypatch):
    from sentinel import tunnel_repair

    llamadas = []

    class _FakeCompletedProcess:
        def __init__(self, stdout=""):
            self.returncode = 0
            self.stdout = stdout

    def _fake_run(args, **kwargs):
        llamadas.append((args, kwargs))
        command = args[-1]
        if "Get-Service" in command:
            return _FakeCompletedProcess(stdout="Running")
        return _FakeCompletedProcess()

    # tunnel_repair y tunnel_checks comparten el mismo modulo "subprocess"
    # importado (import subprocess), asi que un unico parche cubre ambos
    # puntos de llamada (el reinicio y la verificacion posterior).
    monkeypatch.setattr(tunnel_repair.subprocess, "run", _fake_run)

    resultado = tunnel_repair.restart_cloudflared_service()

    assert resultado.ok is True
    assert llamadas
    for args, kwargs in llamadas:
        assert isinstance(args, list)
        assert kwargs.get("shell", False) is False


def test_tunnel_repair_reinicia_tarea_backup_con_stop_y_start(monkeypatch):
    from sentinel import tunnel_repair

    comandos = []

    class _FakeCompletedProcess:
        def __init__(self, stdout=""):
            self.returncode = 0
            self.stdout = stdout

    def _fake_run(args, **kwargs):
        command = args[-1]
        comandos.append(command)
        if "Get-ScheduledTask" in command:
            return _FakeCompletedProcess(stdout="Ready")
        return _FakeCompletedProcess()

    monkeypatch.setattr(tunnel_repair.subprocess, "run", _fake_run)

    resultado = tunnel_repair.restart_cloudflared_backup_task()

    assert resultado.ok is True
    assert any("Stop-ScheduledTask" in c for c in comandos)
    assert any("Start-ScheduledTask" in c for c in comandos)


def test_tunnel_repair_devuelve_mensaje_generico_si_falla(monkeypatch):
    from sentinel import tunnel_repair

    class _FakeCompletedProcess:
        returncode = 0
        stdout = "Stopped"

    monkeypatch.setattr(tunnel_repair.subprocess, "run", lambda *a, **k: _FakeCompletedProcess())
    monkeypatch.setattr(tunnel_repair, "_VERIFY_DELAY_SECONDS", 0.0)

    resultado = tunnel_repair.restart_cloudflared_service()

    assert resultado.ok is False
    assert resultado.detail == tunnel_repair.GENERIC_FAILURE_DETAIL
    assert "powershell" not in resultado.detail.lower()
    assert "C:\\" not in resultado.detail
    assert "ProgramData" not in resultado.detail


def test_build_tunnel_repair_actions_solo_incluye_tuneles_con_confirmacion_por_texto():
    from sentinel import admin_actions

    actions = admin_actions.build_tunnel_repair_actions()

    assert set(actions) == {"reiniciar_tunel_cloudflared", "reiniciar_tunel_cloudflared_backup"}
    for action in actions.values():
        assert action.confirm_text
        assert action.cooldown_seconds == admin_actions.REPAIR_COOLDOWN_SECONDS
        assert action.cooldown_seconds > admin_actions.DOUBLE_CLICK_WINDOW_SECONDS
        assert "mrd tool control" not in action.label.lower()
        assert "mrd_tool_control" not in action.component.lower()


def test_admin_action_runner_exige_confirmacion_por_texto_exacta(tmp_path):
    from sentinel.admin_actions import ActionDef, ActionResult, AdminActionError, AdminActionRunner, AuditLog

    audit_log = AuditLog(path=tmp_path / "audit_log.json")
    actions = {
        "reiniciar_tunel_cloudflared": ActionDef(
            id="reiniciar_tunel_cloudflared", label="Reiniciar túnel (Cloudflared)",
            component="cloudflared", run=lambda: ActionResult(True, "ok"),
            confirm_text="Cloudflared", cooldown_seconds=60.0,
        ),
    }
    runner = AdminActionRunner(actions, audit_log)

    with pytest.raises(AdminActionError, match="confirmacion_no_coincide"):
        runner.execute("reiniciar_tunel_cloudflared", "admin", "cloudflared")

    resultado = runner.execute("reiniciar_tunel_cloudflared", "admin", "Cloudflared")
    assert resultado.ok is True


def test_admin_action_runner_usa_cooldown_propio_no_el_generico(tmp_path):
    from sentinel.admin_actions import ActionDef, ActionResult, AdminActionRunner, AuditLog

    audit_log = AuditLog(path=tmp_path / "audit_log.json")
    actions = {
        "corta": ActionDef(
            id="corta", label="Corta", component="demo",
            run=lambda: ActionResult(True, "ok"), cooldown_seconds=0.05,
        ),
    }
    runner = AdminActionRunner(actions, audit_log)

    runner.execute("corta", "admin")
    time.sleep(0.1)
    # Con el cooldown por defecto (3s) esta segunda llamada estaria bloqueada;
    # con el cooldown propio (0.05s) ya paso tiempo suficiente y debe permitirse.
    resultado = runner.execute("corta", "admin")
    assert resultado.ok is True


def test_endpoint_reinicio_de_tunel_exige_confirmacion_por_texto_y_verifica_tras_reiniciar(monkeypatch, tmp_path):
    from sentinel import tunnel_repair

    monkeypatch.setattr(auth, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(auth, "SECRET_KEY_PATH", tmp_path / "secret.key")
    auth.create_user("admin", "ClaveSegura123")
    config_path = tmp_path / "apps.yaml"
    config_path.write_text(
        "sentinel:\n  host: 127.0.0.1\n  port: 9100\napps:\n"
        "  - id: demo\n    display_name: Demo\n    local_url: http://127.0.0.1:9999\n"
        "    health_path: /health\n    public_hostname: demo.local\n"
        "    failover_state_root: C:\\\\ProgramData\\\\Demo\\\\failover\n",
        encoding="utf-8",
    )

    class _FakeCompletedProcess:
        def __init__(self, stdout=""):
            self.returncode = 0
            self.stdout = stdout

    def _fake_run(args, **kwargs):
        command = args[-1]
        if "Get-Service" in command:
            return _FakeCompletedProcess(stdout="Running")
        return _FakeCompletedProcess()

    monkeypatch.setattr(tunnel_repair.subprocess, "run", _fake_run)
    monkeypatch.setattr(tunnel_repair, "_VERIFY_DELAY_SECONDS", 0.0)

    with TestClient(create_app(config_path)) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.create_token("admin"))

        mal_confirmado = client.post(
            "/admin/acciones/reiniciar_tunel_cloudflared",
            data={"confirmar": "si", "confirmacion": "cloudflared"},
        )
        assert mal_confirmado.status_code == 400

        bien_confirmado = client.post(
            "/admin/acciones/reiniciar_tunel_cloudflared",
            data={"confirmar": "si", "confirmacion": "Cloudflared"},
            follow_redirects=False,
        )
        assert bien_confirmado.status_code == 303
        assert "resultado=ok" in bien_confirmado.headers["location"]


def test_error_log_sanea_query_y_credenciales_de_la_ruta():
    from sentinel.error_log import sanitize_path

    ruta = sanitize_path("/api/login?token=abc123&password=secreto#fragmento")
    assert "token" not in ruta
    assert "secreto" not in ruta
    assert ruta == "/api/login"


def test_error_log_no_mezcla_pruebas_con_errores_reales(tmp_path):
    from sentinel.error_log import ErrorLog

    log = ErrorLog(path=tmp_path / "error_log.json")
    log.record(500, "/api/algo", source="real")
    log.record(500, "/api/algo", source="prueba")
    log.record(500, "/api/algo", source="prueba")

    solo_reales = log.recent()
    assert len(solo_reales) == 1
    assert solo_reales[0]["count"] == 1


def test_error_log_no_crece_sin_limite(tmp_path):
    from sentinel.error_log import ErrorLog

    log = ErrorLog(path=tmp_path / "error_log.json", max_entries=3)
    for i in range(10):
        log.record(500, f"/ruta{i}")

    with (tmp_path / "error_log.json").open(encoding="utf-8") as f:
        import json as _json
        assert len(_json.load(f)) == 3


def test_vista_de_incidencias_requiere_login(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(auth, "SECRET_KEY_PATH", tmp_path / "secret.key")
    auth.create_user("admin", "ClaveSegura123")
    config_path = tmp_path / "apps.yaml"
    config_path.write_text(
        "sentinel:\n  host: 127.0.0.1\n  port: 9100\napps:\n"
        "  - id: demo\n    display_name: Demo\n    local_url: http://127.0.0.1:9999\n"
        "    health_path: /health\n    public_hostname: demo.local\n"
        "    failover_state_root: C:\\\\ProgramData\\\\Demo\\\\failover\n",
        encoding="utf-8",
    )
    with TestClient(create_app(config_path)) as client:
        sin_auth = client.get("/incidencias", follow_redirects=False)
        assert sin_auth.status_code in (401, 303)

        client.cookies.set(auth.COOKIE_NAME, auth.create_token("admin"))
        response = client.get("/incidencias")
        assert response.status_code == 200
        assert "Incidencias" in response.text
