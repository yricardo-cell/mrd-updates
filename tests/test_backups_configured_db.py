import sqlite3

import backups
import config


def _value(path):
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT value FROM marker").fetchone()[0]


def test_backup_y_restauracion_usan_solo_base_sqlite_configurada(tmp_path, monkeypatch):
    active = tmp_path / "configured-active.db"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    with sqlite3.connect(active) as conn:
        conn.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        conn.execute("INSERT INTO marker VALUES ('original')")

    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{active.as_posix()}")
    monkeypatch.setattr(backups, "BACKUPS_DIR", backup_dir)

    created = backups.crear_backup()
    assert created["ok"] is True
    backup_path = backup_dir / created["archivo"]
    assert backup_path.exists()
    assert backups._sqlite_integrity(backup_path)
    assert _value(backup_path) == "original"

    with sqlite3.connect(active) as conn:
        conn.execute("UPDATE marker SET value='modified'")
    assert _value(active) == "modified"

    restored = backups.restaurar_backup(created["archivo"])
    assert restored["ok"] is True
    assert _value(active) == "original"
    assert list(backup_dir.glob("antes_restaurar_*.db"))


def test_resolver_rechaza_memoria_y_motores_no_sqlite():
    for url in ("sqlite:///:memory:", "postgresql://user:pass@localhost/db"):
        try:
            backups._resolver_db_path(url)
        except ValueError:
            pass
        else:
            raise AssertionError(f"URL no rechazada: {url}")


def test_restauracion_rechaza_escape_de_directorio(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr(backups, "BACKUPS_DIR", backup_dir)
    assert backups.restaurar_backup("../fuera.db")["ok"] is False


def test_backup_automatico_crea_uno_por_dia_y_omite_si_ya_existe(tmp_path, monkeypatch):
    active = tmp_path / "configured-active.db"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    with sqlite3.connect(active) as conn:
        conn.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        conn.execute("INSERT INTO marker VALUES ('original')")

    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{active.as_posix()}")
    monkeypatch.setattr(backups, "BACKUPS_DIR", backup_dir)

    primero = backups.crear_backup_automatico_si_corresponde()
    assert primero is not None and primero["ok"] is True
    assert len(list(backup_dir.glob("backup_*.db"))) == 1

    segundo = backups.crear_backup_automatico_si_corresponde()
    assert segundo is None
    assert len(list(backup_dir.glob("backup_*.db"))) == 1


def test_backup_automatico_rota_segun_mantener(tmp_path, monkeypatch):
    active = tmp_path / "configured-active.db"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    with sqlite3.connect(active) as conn:
        conn.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        conn.execute("INSERT INTO marker VALUES ('original')")
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{active.as_posix()}")
    monkeypatch.setattr(backups, "BACKUPS_DIR", backup_dir)

    # Simula 5 días de copias ya existentes (nombres con fechas distintas).
    for dia in ("20260101", "20260102", "20260103", "20260104", "20260105"):
        (backup_dir / f"backup_{dia}_000000.db").write_bytes(b"")

    backups.crear_backup_automatico_si_corresponde(mantener=3)
    restantes = sorted(f.name for f in backup_dir.glob("backup_*.db"))
    assert len(restantes) == 3
