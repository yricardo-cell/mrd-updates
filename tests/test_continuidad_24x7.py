from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATCHDOG = ROOT / "scripts" / "operations" / "watchdog_mrd.ps1"
INSTALLER = ROOT / "scripts" / "operations" / "install_continuity_24x7.ps1"
DOC = ROOT / "docs" / "operations" / "CONTINUIDAD_24X7.md"


def test_archivos_de_continuidad_existen():
    assert WATCHDOG.is_file()
    assert INSTALLER.is_file()
    assert DOC.is_file()


def test_panel_admin_puede_instalar_vigilante_sin_comandos_variables():
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    panel = (ROOT / "templates" / "servicio.html").read_text(encoding="utf-8")
    assert '@app.post("/api/service/watchdog")' in main
    assert 'install_continuity_24x7.ps1' in main
    assert "shell=True" not in main
    assert "svcAction('watchdog')" in panel


def test_watchdog_tiene_umbral_cooldown_y_limite_antibucle():
    source = WATCHDOG.read_text(encoding="utf-8")
    assert "FailureThreshold = 3" in source
    assert "CooldownSeconds = 300" in source
    assert "MaxRestartsPerHour = 3" in source
    assert "Limite de reinicios alcanzado" in source


def test_watchdog_respeta_mantenimiento_y_evitar_solapes():
    source = WATCHDOG.read_text(encoding="utf-8")
    assert ".maintenance_mode" in source
    assert "Global\\MRDToolControlWatchdog" in source
    assert "Otra comprobacion sigue en curso" in source
    assert "foreach ($property in @($state.Keys))" in source


def test_fallo_publico_no_reinicia_el_tunel():
    source = WATCHDOG.read_text(encoding="utf-8")
    assert "no se reinicia un servicio sano por este motivo" in source
    assert "Restart-Service -Name $TunnelServiceName" not in source


def test_instalacion_exige_apply_y_no_reinicia_servicios():
    source = INSTALLER.read_text(encoding="utf-8")
    assert "[switch]$Apply" in source
    assert "if (-not $Apply)" in source
    assert "sc.exe config $serviceName start= auto" in source
    assert "sc.exe failure" in source
    assert "Register-ScheduledTask" in source
    assert "Restart-Service" not in source


def test_documentacion_declara_limites_de_un_solo_pc():
    source = DOC.read_text(encoding="utf-8")
    assert "punto único de fallo" in source
    assert "UPS" in source
    assert "backups verificados fuera del PC" in source
