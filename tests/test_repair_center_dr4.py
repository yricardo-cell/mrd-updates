import json
import sqlite3
from pathlib import Path

import pytest

from scripts.operations import repair_center as rc


def _sqlite(path: Path, value: str = "ok", mrd_schema: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("create table control (value text not null)")
    db.execute("insert into control values (?)", (value,))
    if mrd_schema:
        for table in rc._MRD_SCHEMA_SIGNATURE:
            db.execute(f"create table {table} (id integer primary key)")
    db.commit()
    db.close()


@pytest.fixture
def repair_root(tmp_path, monkeypatch):
    root = tmp_path / "mrd"
    state = tmp_path / "programdata" / "repair"
    root.mkdir()
    for relatives in rc.COMPONENT_FILES.values():
        for relative in relatives:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"contenido estable: {relative}\n", encoding="utf-8")
    (root / "version.json").write_text(json.dumps({"version_actual": "9.9.9"}), encoding="utf-8")
    for relative in rc.REQUIRED_DIRS:
        (root / relative).mkdir(exist_ok=True)
    _sqlite(root / "data" / "mrd_tool.db")
    monkeypatch.setattr(rc, "_http_health", lambda *_a, **_k: ("ok", "simulado"))
    return root, state


def test_sella_y_verifica_linea_base_por_version(repair_root):
    root, state = repair_root
    sealed = rc.seal_baseline(root, state)
    assert sealed["ok"] is True and sealed["sealed"] is True

    report = rc.run_once(root, state)

    assert report["ok"] is True
    assert report["version"] == report["baseline"] == "9.9.9"
    assert all(report["components"][name]["status"] == "ok" for name in rc.COMPONENT_FILES)


def test_repara_solo_el_fichero_danado_y_guarda_cuarentena(repair_root, monkeypatch):
    root, state = repair_root
    rc.seal_baseline(root, state)
    damaged = root / "scanner_service.py"
    expected = damaged.read_text(encoding="utf-8")
    damaged.write_text("ROTURA\n", encoding="utf-8")
    # Un hash distinto por sí solo ya no basta para restaurar (podría ser una
    # edición manual legítima); aquí se corrobora con un fallo real de salud
    # local, como ocurriría si la rotura del componente rompe la app.
    monkeypatch.setattr(rc, "_http_health", lambda url, *_a, **_k: (
        ("error", "no responde") if "127.0.0.1" in url else ("ok", "simulado")
    ))

    report = rc.run_once(root, state, apply=True)

    assert report["repaired_files"] == ["scanner_service.py"]
    assert report["restart_required"] is True
    assert damaged.read_text(encoding="utf-8") == expected
    quarantined = list((state / "quarantine").glob("*/files/scanner_service.py"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "ROTURA\n"


def test_no_restaura_codigo_desde_linea_base_de_otra_version(repair_root):
    root, state = repair_root
    rc.seal_baseline(root, state)
    damaged = root / "main.py"
    damaged.write_text("CAMBIO DE OTRA VERSION\n", encoding="utf-8")
    (root / "version.json").write_text(json.dumps({"version_actual": "10.0.0"}), encoding="utf-8")

    report = rc.run_once(root, state, apply=True)

    assert report["baseline_error"] == "linea_base_de_otra_version"
    assert report["repaired_files"] == []
    assert damaged.read_text(encoding="utf-8") == "CAMBIO DE OTRA VERSION\n"


def test_base_ocupada_no_se_confunde_con_corrupcion(tmp_path, monkeypatch):
    path = tmp_path / "ocupada.db"
    path.write_bytes(b"ocupada")
    monkeypatch.setattr(sqlite3, "connect", lambda *_a, **_k: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")))
    status, detail = rc._sqlite_integrity(path)
    assert status == "warning"
    assert "ocupada" in detail.lower()


def test_dr4_exige_fallos_repetidos_servicio_detenido_y_backup_valido(repair_root):
    root, state = repair_root
    rc.seal_baseline(root, state)
    live = root / "data" / "mrd_tool.db"
    backup = root / "backups" / "segura" / "mrd_tool.db.bak"
    _sqlite(backup, "copia-segura", mrd_schema=True)
    live.write_bytes(b"base rota, no sqlite")

    first = rc.run_once(root, state, apply=True, allow_dr4=True, database_failure_threshold=2)
    assert first["dr4_ready"] is False
    second = rc.run_once(root, state, apply=True, allow_dr4=True, database_failure_threshold=2)
    assert second["dr4_ready"] is True
    assert second["dr4"]["ok"] is False
    assert "detenido" in second["dr4"]["detail"]
    assert live.read_bytes() == b"base rota, no sqlite"

    diagnosed = rc.run_once(
        root, state, apply=True, allow_dr4=True,
        service_confirmed_stopped=True, database_failure_threshold=2,
    )
    # La restauración automática de DR4 está desactivada: diagnostica y deja
    # constancia de la copia válida, pero nunca escribe sobre la BD en vivo.
    assert diagnosed["dr4"]["ok"] is False
    assert diagnosed["dr4"]["manual_intervention_required"] is True
    assert diagnosed["dr4"]["backup"] == str(backup)
    assert live.read_bytes() == b"base rota, no sqlite"
    quarantine = list((state / "quarantine").glob("*/database/mrd_tool.corrupt.db"))
    assert quarantine


def test_dr4_rechaza_backup_sano_pero_ajeno_a_mrd(repair_root):
    root, state = repair_root
    rc.seal_baseline(root, state)
    live = root / "data" / "mrd_tool.db"
    ajeno = root / "backups" / "otro" / "cualquier.db"
    _sqlite(ajeno, "no-es-mrd")  # SQLite sano (pasa quick_check) pero sin el esquema de MRD
    live.write_bytes(b"base rota, no sqlite")

    rc.run_once(root, state, apply=True, allow_dr4=True, database_failure_threshold=2)
    result = rc.run_once(
        root, state, apply=True, allow_dr4=True,
        service_confirmed_stopped=True, database_failure_threshold=2,
    )

    assert result["dr4_ready"] is True
    assert result["dr4"]["ok"] is False
    assert live.read_bytes() == b"base rota, no sqlite"


def test_crea_unicamente_carpetas_mrd_que_falten(repair_root):
    root, state = repair_root
    rc.seal_baseline(root, state)
    (root / "temp").rmdir()
    report = rc.run_once(root, state, apply=True)
    assert report["created_dirs"] == ["temp"]
    assert (root / "temp").is_dir()


def test_modulo_no_contiene_comandos_de_borrado_o_cierre_generico():
    source = Path(rc.__file__).read_text(encoding="utf-8")
    for forbidden in ("taskkill", "Stop-Process", "rm -rf", "shell=True"):
        assert forbidden not in source


def test_ciclo_check_apply_incrementa_el_contador_una_sola_vez_y_arma_dr4_en_el_umbral(repair_root):
    """Reproduce el ciclo real de watchdog_mrd.ps1: primero --mode check
    (apply=False), y si hay remaining_errors, --mode repair (apply=True).
    Antes del fix, _sqlite_integrity incrementaba database_failures en AMBAS
    llamadas, así que DR4 se armaba en ~2 ciclos en vez de los 3 configurados.
    """
    root, state = repair_root
    rc.seal_baseline(root, state)
    live = root / "data" / "mrd_tool.db"
    live.write_bytes(b"base rota, no sqlite")
    threshold = 3

    for ciclo in range(1, threshold + 1):
        checked = rc.run_once(root, state, apply=False, database_failure_threshold=threshold)
        assert checked["remaining_errors"]
        applied = rc.run_once(root, state, apply=True, database_failure_threshold=threshold)

        persisted = rc._load_state(state)["database_failures"]
        assert persisted == ciclo, f"tras {ciclo} ciclo(s) el contador debería ser {ciclo}, no {persisted}"
        assert applied["dr4_ready"] is (ciclo >= threshold)

    # El check en solitario nunca debe haber tocado el contador persistido.
    checked_de_mas = rc.run_once(root, state, apply=False, database_failure_threshold=threshold)
    assert rc._load_state(state)["database_failures"] == threshold
    assert checked_de_mas["dr4_ready"] is True


def test_no_revierte_una_edicion_manual_si_la_app_esta_sana(repair_root):
    """El check previo no debe bastar para autorizar una restauración: si el
    único problema es un fichero cuyo hash difiere del sellado (p. ej. una
    edición manual sin resellar) y la app está sana (BD y health local ok),
    el ciclo check->apply de watchdog_mrd.ps1 no debe revertirlo.
    """
    root, state = repair_root
    rc.seal_baseline(root, state)
    edited = root / "templates" / "scan.html"
    edited.write_text("<!-- ajuste manual sin resellar -->\n", encoding="utf-8")

    checked = rc.run_once(root, state, apply=False)
    assert "escaner_qr" in checked["remaining_errors"]

    applied = rc.run_once(root, state, apply=True)

    assert applied["repaired_files"] == []
    assert edited.read_text(encoding="utf-8") == "<!-- ajuste manual sin resellar -->\n"
