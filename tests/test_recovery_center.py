"""
MRD TOOL CONTROL — Sistema doble de recuperación (Nivel 1 + Nivel 2)

Cubre:
  - _restart_exec_target / _restart_target_is_valid (raíz del incidente 2026-09-01)
  - POST /admin/reiniciar (Nivel 1): validación previa, bloqueo anti-doble-clic,
    auditoría, y que el proceso actual no se detiene si el destino no existe.
  - Centro de recuperación (GET/POST /api/service/recovery/*): estado
    consolidado MRD+Cloudflare, recuperación completa en orden seguro,
    bloqueo anti-doble-pulsación, control de acceso admin, CSRF, auditoría.
  - watchdog_mrd.ps1 / install_continuity_24x7.ps1 (Nivel 2 externo): orden
    de recuperación, nombres de servicio reales, parámetros explícitos.

Todas las pruebas usan mocks, ficheros temporales y la base de datos aislada
de tests/conftest.py. Ninguna toca el servicio Windows real, el túnel de
Cloudflare real, ni la base de datos de producción.
"""
from pathlib import Path

import pytest

import cloudflare_tunnel
import main
import service_health
from auth import hash_password
from models import Usuario
from security import generar_csrf_token


ROOT = Path(__file__).resolve().parents[1]
WATCHDOG = ROOT / "scripts" / "operations" / "watchdog_mrd.ps1"
INSTALLER = ROOT / "scripts" / "operations" / "install_continuity_24x7.ps1"


# ─── Aislamiento entre tests ───────────────────────────────────────────────────
# _RESTART_LOCK/_RECOVERY_LOCK son objetos globales de módulo compartidos por
# todos los tests; sin este reseteo, un test que falle a mitad podría dejar
# el candado tomado y bloquear falsamente a los siguientes.

@pytest.fixture(autouse=True)
def _reset_recovery_state():
    if main._RESTART_LOCK.locked():
        main._RESTART_LOCK.release()
    if main._RECOVERY_LOCK.locked():
        main._RECOVERY_LOCK.release()
    main._RESTART_STATE["in_progress"] = False
    main._RESTART_STATE["started_at"] = None
    main._RECOVERY_STATE["in_progress"] = False
    main._RECOVERY_STATE["started_at"] = None
    yield
    if main._RESTART_LOCK.locked():
        main._RESTART_LOCK.release()
    if main._RECOVERY_LOCK.locked():
        main._RECOVERY_LOCK.release()


@pytest.fixture
def _sandbox_recovery_files(tmp_path, monkeypatch):
    """Redirige historial/señal/estado a una carpeta temporal: ningún test
    debe escribir en los ficheros reales del proyecto en disco."""
    monkeypatch.setattr(main, "_RECOVERY_HISTORY_FILE", tmp_path / ".recovery_history.json")
    monkeypatch.setattr(main, "_SVC_RESTART_FLAG", tmp_path / ".service_restart")
    monkeypatch.setattr(main, "_SVC_STATUS_FILE", tmp_path / ".service_status")
    return tmp_path


class _SyncThread:
    """Sustituye threading.Thread para que el hilo de reinicio se ejecute de
    forma síncrona y determinista dentro del test: evita dejar un hilo con
    vida propia que pudiera llamar a os.execv (reemplazo real de proceso)
    después de que el test haya terminado."""

    def __init__(self, target=None, daemon=None, **kwargs):
        self._target = target

    def start(self):
        if self._target:
            self._target()


class _FakeHealth:
    def __init__(self, ok, detail="check simulado"):
        self.ok = ok
        self.detail = detail

    def to_dict(self):
        return {"status": "ok" if self.ok else "error", "detail": self.detail}


def _crear_admin(db, username="admin-recovery"):
    admin = Usuario(
        username=username, password_hash=hash_password("ClaveSegura123!"),
        nombre="Admin Recovery", rol="admin", activo=True, must_change_password=False,
    )
    db.add(admin)
    db.commit()
    return admin


def _crear_no_admin(db, username="consulta-recovery"):
    user = Usuario(
        username=username, password_hash=hash_password("ClaveSegura123!"),
        nombre="Consulta Recovery", rol="consulta", activo=True, must_change_password=False,
    )
    db.add(user)
    db.commit()
    return user


def _login(client, username, password="ClaveSegura123!"):
    resp = client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])


def _csrf_headers(client):
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return {"X-CSRF-Token": token}


# ═══════════════════════════════════════════════════════════════════════════════
# Nivel 1 — _restart_exec_target / _restart_target_is_valid
# ═══════════════════════════════════════════════════════════════════════════════

class TestRestartExecTarget:

    def test_ruta_con_espacios_usa_uvicorn_junto_a_python_sin_duplicar(self, tmp_path):
        proyecto = tmp_path / "mrd tool" / "mrd-tool-control-2.5.0"
        venv_scripts = proyecto / "venv" / "Scripts"
        venv_scripts.mkdir(parents=True)
        python_exe = venv_scripts / "python.exe"
        uvicorn_exe = venv_scripts / "uvicorn.exe"
        python_exe.write_text("")
        uvicorn_exe.write_text("")

        argv = [str(uvicorn_exe), "main:app", "--port", "8000"]
        executable, args = main._restart_exec_target(argv, str(python_exe), "nt")

        assert Path(executable).resolve() == uvicorn_exe.resolve()
        assert args[1:] == ["main:app", "--port", "8000"]
        assert len(args) == 4  # ejecutable + 3 argumentos originales, sin duplicar rutas

    def test_argv0_absoluto_valido_se_usa_directamente(self, tmp_path):
        launcher = tmp_path / "uvicorn.exe"
        launcher.write_text("")
        python_exe = tmp_path / "otra_carpeta" / "python.exe"

        argv = [str(launcher), "main:app"]
        executable, args = main._restart_exec_target(argv, str(python_exe), "nt")

        assert Path(executable).resolve() == launcher.resolve()
        assert args[0] == executable
        assert args[1:] == ["main:app"]

    def test_argv0_relativo_sin_sibling_hace_fallback_a_python_sin_reutilizar_argv0(self, tmp_path):
        python_exe = tmp_path / "python.exe"
        python_exe.write_text("")

        argv = ["uvicorn", "main:app", "--port", "8000"]
        executable, args = main._restart_exec_target(argv, str(python_exe), "nt")

        assert executable == str(python_exe)
        assert args == [str(python_exe), "main:app", "--port", "8000"]
        assert "uvicorn" not in args

    def test_reproduce_incidente_confirmado_sin_duplicar_ruta(self):
        """Reproduce el escenario exacto del incidente del 2026-09-01 22:50:37:
        reutilizar argv completo generaba
        ...\\mrd-tool-control-2.5.0\\tool\\mrd-tool-control-2.5.0\\venv\\Scripts\\python.exe
        """
        python_exe = r"C:\mrd tool\mrd-tool-control-2.5.0\venv\Scripts\python.exe"
        argv = [python_exe, "-m", "uvicorn", "main:app"]

        executable, args = main._restart_exec_target(argv, python_exe, "nt")

        assert executable == python_exe
        assert args == [python_exe, "-m", "uvicorn", "main:app"]
        assert args.count(python_exe) == 1

    def test_target_inexistente_no_es_valido(self, tmp_path):
        assert main._restart_target_is_valid(str(tmp_path / "no_existe.exe")) is False

    def test_target_existente_es_valido(self, tmp_path):
        exe = tmp_path / "python.exe"
        exe.write_text("")
        assert main._restart_target_is_valid(str(exe)) is True


# ═══════════════════════════════════════════════════════════════════════════════
# Nivel 1 — POST /admin/reiniciar
# ═══════════════════════════════════════════════════════════════════════════════

class TestReiniciarEndpoint:

    def test_requiere_admin(self, client, db, monkeypatch):
        _crear_no_admin(db)
        _login(client, "consulta-recovery")
        headers = _csrf_headers(client)

        resp = client.post("/admin/reiniciar", headers=headers)
        assert resp.status_code == 403

    def test_csrf_invalido_es_rechazado(self, client, db):
        _crear_admin(db)
        _login(client, "admin-recovery")

        resp = client.post("/admin/reiniciar", headers={"X-CSRF-Token": "token-falso"})
        assert resp.status_code == 403

    def test_ejecutable_valido_dispara_reinicio_y_registra_auditoria(
        self, client, db, monkeypatch, _sandbox_recovery_files,
    ):
        _crear_admin(db)
        _login(client, "admin-recovery")
        headers = _csrf_headers(client)

        target = _sandbox_recovery_files / "venv" / "Scripts" / "python.exe"
        target.parent.mkdir(parents=True)
        target.write_text("")

        execv_calls = []
        monkeypatch.setattr(main, "_restart_exec_target", lambda argv, py, osname: (str(target), [str(target)]))
        monkeypatch.setattr(main.threading, "Thread", _SyncThread)
        monkeypatch.setattr(main.time, "sleep", lambda *a, **k: None)
        monkeypatch.setattr(main.os, "execv", lambda exe, args: execv_calls.append((exe, args)))

        resp = client.post("/admin/reiniciar", headers=headers)

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert execv_calls == [(str(target), [str(target)])]

        history = main._recovery_history_read()
        assert any(h["action"] == "restart_direct" and h["result"] == "iniciado" for h in history)
        assert any(h["user"] == "admin-recovery" for h in history)

    def test_ejecutable_inexistente_cancela_y_no_detiene_proceso_actual(
        self, client, db, monkeypatch, _sandbox_recovery_files,
    ):
        _crear_admin(db)
        _login(client, "admin-recovery")
        headers = _csrf_headers(client)

        target_inexistente = str(_sandbox_recovery_files / "no_existe" / "python.exe")
        execv_calls = []
        monkeypatch.setattr(main, "_restart_exec_target", lambda argv, py, osname: (target_inexistente, [target_inexistente]))
        monkeypatch.setattr(main.os, "execv", lambda exe, args: execv_calls.append((exe, args)))

        resp = client.post("/admin/reiniciar", headers=headers)

        assert resp.status_code == 409
        assert execv_calls == []  # el proceso actual nunca se toca
        assert not main._RESTART_LOCK.locked()  # el candado se libera: se puede reintentar

        history = main._recovery_history_read()
        assert any(h["action"] == "restart_direct" and h["result"] == "cancelado" for h in history)

    def test_doble_clic_devuelve_409_y_no_arranca_dos_reinicios(
        self, client, db, monkeypatch, _sandbox_recovery_files,
    ):
        _crear_admin(db)
        _login(client, "admin-recovery")
        headers = _csrf_headers(client)

        assert main._RESTART_LOCK.acquire(blocking=False)  # simula un reinicio ya en curso
        try:
            resp = client.post("/admin/reiniciar", headers=headers)
            assert resp.status_code == 409
            assert "en curso" in resp.json()["detail"].lower()
        finally:
            main._RESTART_LOCK.release()


# ═══════════════════════════════════════════════════════════════════════════════
# Centro de recuperación — GET /api/service/recovery/status y /history
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecoveryStatus:

    def test_requiere_admin(self, client, db):
        _crear_no_admin(db)
        _login(client, "consulta-recovery")
        assert client.get("/api/service/recovery/status").status_code == 403
        assert client.get("/api/service/recovery/history").status_code == 403

    @pytest.mark.parametrize(
        ("mrd_ok", "cf_ok"),
        [(True, True), (False, True), (True, False), (False, False)],
        ids=["mrd_ok_cf_ok", "mrd_down_cf_ok", "mrd_ok_cf_down", "ambos_caidos"],
    )
    def test_estado_consolidado_refleja_combinaciones_mrd_cloudflare(
        self, client, db, monkeypatch, mrd_ok, cf_ok,
    ):
        _crear_admin(db)
        _login(client, "admin-recovery")

        monkeypatch.setattr(main, "_svc_windows_state", lambda: "RUNNING" if mrd_ok else "STOPPED")
        monkeypatch.setattr(service_health, "check_port", lambda *a, **k: _FakeHealth(mrd_ok, "puerto 8000"))
        monkeypatch.setattr(
            service_health, "run_all_checks",
            lambda *a, **k: {"healthy": mrd_ok, "checks": {}, "timestamp": "2026-09-01T22:50:00Z"},
        )
        monkeypatch.setattr(
            cloudflare_tunnel, "get_service_status",
            lambda name: {"installed": True, "running": cf_ok, "state": "RUNNING" if cf_ok else "STOPPED"},
        )

        resp = client.get("/api/service/recovery/status")
        assert resp.status_code == 200
        data = resp.json()

        assert (data["mrd"]["windows_state"] == "RUNNING") is mrd_ok
        assert data["mrd"]["port_status"]["status"] == ("ok" if mrd_ok else "error")
        assert data["mrd"]["health"]["healthy"] is mrd_ok
        assert data["cloudflare"]["running"] is cf_ok

    def test_historial_vacio_por_defecto(self, client, db, _sandbox_recovery_files):
        _crear_admin(db)
        _login(client, "admin-recovery")
        resp = client.get("/api/service/recovery/history")
        assert resp.status_code == 200
        assert resp.json() == {"history": []}


# ═══════════════════════════════════════════════════════════════════════════════
# Centro de recuperación — POST /api/service/recovery/full
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecoveryFull:

    def test_requiere_admin(self, client, db):
        _crear_no_admin(db)
        _login(client, "consulta-recovery")
        headers = _csrf_headers(client)
        resp = client.post("/api/service/recovery/full", headers=headers)
        assert resp.status_code == 403

    def test_csrf_invalido_es_rechazado(self, client, db):
        _crear_admin(db)
        _login(client, "admin-recovery")
        resp = client.post("/api/service/recovery/full", headers={"X-CSRF-Token": "invalido"})
        assert resp.status_code == 403

    def test_doble_pulsacion_devuelve_409(self, client, db):
        _crear_admin(db)
        _login(client, "admin-recovery")
        headers = _csrf_headers(client)

        assert main._RECOVERY_LOCK.acquire(blocking=False)
        try:
            resp = client.post("/api/service/recovery/full", headers=headers)
            assert resp.status_code == 409
        finally:
            main._RECOVERY_LOCK.release()

    def test_cloudflare_ya_activo_no_reinicia_nada(
        self, client, db, monkeypatch, _sandbox_recovery_files,
    ):
        _crear_admin(db)
        _login(client, "admin-recovery")
        headers = _csrf_headers(client)

        restart_calls = []
        monkeypatch.setattr(
            cloudflare_tunnel, "get_service_status",
            lambda name: {"installed": True, "running": True, "state": "RUNNING"},
        )
        monkeypatch.setattr(cloudflare_tunnel, "restart_service", lambda name: restart_calls.append(name) or {"ok": True})

        resp = client.post("/api/service/recovery/full", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert restart_calls == []  # no se toca un servicio que ya está sano
        cf_paso = next(p for p in data["pasos"] if p["paso"] == "cloudflare")
        assert "sin cambios" in cf_paso["message"]

    def test_cloudflare_no_instalado_marca_paso_como_fallido(
        self, client, db, monkeypatch, _sandbox_recovery_files,
    ):
        _crear_admin(db)
        _login(client, "admin-recovery")
        headers = _csrf_headers(client)

        monkeypatch.setattr(
            cloudflare_tunnel, "get_service_status",
            lambda name: {"installed": False, "running": False, "state": "NOT_INSTALLED"},
        )

        resp = client.post("/api/service/recovery/full", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        cf_paso = next(p for p in data["pasos"] if p["paso"] == "cloudflare")
        assert cf_paso["ok"] is False

    def test_cloudflare_caido_se_reinicia_una_sola_vez_y_orden_mrd_primero(
        self, client, db, monkeypatch, _sandbox_recovery_files,
    ):
        _crear_admin(db)
        _login(client, "admin-recovery")
        headers = _csrf_headers(client)

        orden = []
        original_write_text = Path.write_text

        def _spy_write_text(self, *a, **k):
            if self == main._SVC_RESTART_FLAG:
                orden.append("mrd")
            return original_write_text(self, *a, **k)

        restart_calls = []

        def _fake_restart(name):
            orden.append("cloudflare")
            restart_calls.append(name)
            return {"ok": True, "message": f"Servicio '{name}' reiniciado."}

        monkeypatch.setattr(Path, "write_text", _spy_write_text)
        monkeypatch.setattr(
            cloudflare_tunnel, "get_service_status",
            lambda name: {"installed": True, "running": False, "state": "STOPPED"},
        )
        monkeypatch.setattr(cloudflare_tunnel, "restart_service", _fake_restart)

        resp = client.post("/api/service/recovery/full", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert restart_calls == ["cloudflared"]  # una sola llamada, sin bucle
        assert orden == ["mrd", "cloudflare"]  # orden seguro exigido: MRD antes que Cloudflare

    def test_recuperacion_fallida_no_reintenta_indefinidamente(
        self, client, db, monkeypatch, _sandbox_recovery_files,
    ):
        _crear_admin(db)
        _login(client, "admin-recovery")
        headers = _csrf_headers(client)

        restart_calls = []
        monkeypatch.setattr(
            cloudflare_tunnel, "get_service_status",
            lambda name: {"installed": True, "running": False, "state": "STOPPED"},
        )
        monkeypatch.setattr(
            cloudflare_tunnel, "restart_service",
            lambda name: restart_calls.append(name) or {"ok": False, "message": "fallo simulado"},
        )

        resp = client.post("/api/service/recovery/full", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert len(restart_calls) == 1  # un único intento; no hay reintento en bucle
        assert not main._RECOVERY_LOCK.locked()  # el candado se libera para permitir un reintento manual

    def test_registra_auditoria_con_usuario_ip_duracion_y_resultado(
        self, client, db, monkeypatch, _sandbox_recovery_files,
    ):
        _crear_admin(db)
        _login(client, "admin-recovery")
        headers = _csrf_headers(client)
        monkeypatch.setattr(
            cloudflare_tunnel, "get_service_status",
            lambda name: {"installed": True, "running": True, "state": "RUNNING"},
        )

        client.post("/api/service/recovery/full", headers=headers)

        history = main._recovery_history_read()
        assert len(history) == 1
        entry = history[0]
        assert entry["action"] == "recovery_full"
        assert entry["user"] == "admin-recovery"
        assert "ip" in entry and entry["ip"]
        assert entry["duration_s"] >= 0
        assert entry["result"] in ("ok", "parcial")

    def test_no_modifica_la_base_de_datos_real(
        self, client, db, monkeypatch, _sandbox_recovery_files,
    ):
        _crear_admin(db)
        _login(client, "admin-recovery")
        headers = _csrf_headers(client)
        monkeypatch.setattr(
            cloudflare_tunnel, "get_service_status",
            lambda name: {"installed": True, "running": True, "state": "RUNNING"},
        )

        usuarios_antes = db.query(Usuario).count()
        client.post("/api/service/recovery/full", headers=headers)
        db.expire_all()
        assert db.query(Usuario).count() == usuarios_antes


# ═══════════════════════════════════════════════════════════════════════════════
# Nivel 2 — watchdog_mrd.ps1 / install_continuity_24x7.ps1 (estático, sin ejecutar)
# ═══════════════════════════════════════════════════════════════════════════════

class TestWatchdogNivel2:

    def test_recupera_mrd_antes_que_cloudflare(self):
        source = WATCHDOG.read_text(encoding="utf-8")
        idx_app = source.index("$app = Get-ServiceSafely $AppServiceName")
        idx_tunnel = source.index("$tunnel = Get-ServiceSafely $TunnelServiceName")
        assert idx_app < idx_tunnel

    def test_nombre_de_servicio_cloudflare_por_defecto_es_el_real(self):
        source = WATCHDOG.read_text(encoding="utf-8")
        assert '$TunnelServiceName = "Cloudflared"' in source
        assert "CloudflaredMRD" not in source

    def test_maintenance_marker_coincide_con_ruta_real_del_proyecto(self):
        source = WATCHDOG.read_text(encoding="utf-8")
        assert "mrd-tool-control-2.5.0" in source

    def test_nunca_usa_stop_process_ni_taskkill(self):
        source = WATCHDOG.read_text(encoding="utf-8")
        for patron in ("taskkill", "Stop-Process", "killall"):
            assert patron not in source

    def test_installer_pasa_parametros_explicitos_a_la_tarea_programada(self):
        source = INSTALLER.read_text(encoding="utf-8")
        assert "-AppServiceName" in source
        assert "-TunnelServiceName" in source
        assert "-HealthUrl" in source
        assert "-MaintenanceMarker" in source
        assert '$TunnelServiceName = "Cloudflared"' in source
        assert "CloudflaredMRD" not in source

    def test_installer_repository_root_por_defecto_coincide_con_ruta_real(self):
        source = INSTALLER.read_text(encoding="utf-8")
        assert 'C:\\mrd tool\\mrd-tool-control-2.5.0' in source


class TestSinComandosDestructivosGlobales:
    """Ningún componente del sistema de recuperación puede cerrar procesos
    ajenos ni genéricos (solo servicios identificados por nombre/PID)."""

    ARCHIVOS = [
        ROOT / "main.py",
        ROOT / "cloudflare_tunnel.py",
        WATCHDOG,
        INSTALLER,
    ]

    @pytest.mark.parametrize("patron", ["taskkill", "Stop-Process", "killall", "pkill "])
    def test_patron_prohibido_ausente(self, patron):
        for archivo in self.ARCHIVOS:
            contenido = archivo.read_text(encoding="utf-8")
            assert patron not in contenido, f"{archivo.name} contiene '{patron}'"

    def test_main_py_no_usa_shell_true_en_llamadas_de_recuperacion(self):
        contenido = (ROOT / "main.py").read_text(encoding="utf-8")
        assert "shell=True" not in contenido
