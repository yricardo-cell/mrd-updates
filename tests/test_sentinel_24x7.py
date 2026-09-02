from pathlib import Path

from fastapi.testclient import TestClient

from sentinel import auth
from sentinel.app import create_app
from sentinel.config import load_config


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
