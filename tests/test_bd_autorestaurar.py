"""Mejora 33: la base de datos corrupta se aparta y se restaura la copia."""
import sqlite3
import main


def _sqlite_bytes(tmp_path, nombre, valor):
    p = tmp_path / nombre
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE t (v TEXT)")
    con.execute("INSERT INTO t VALUES (?)", (valor,))
    con.commit()
    con.close()
    return p.read_bytes()


def test_restaura_si_corrupta(tmp_path):
    buena = _sqlite_bytes(tmp_path, "copia.db", "copia")
    db = tmp_path / "mrd_tool.db"
    db.write_bytes(b"SQLite format 3" + bytes([0]) + b"basura" * 200)
    (tmp_path / "mrd_tool.db-wal").write_bytes(b"x")
    res = main._bd_autorestaurar(db, lambda: ("copia.db", buena), quick_check=lambda p: "*** in database main *** Page 1: btreeInitPage() returns error code 11")
    assert res["accion"] == "restaurada" and res["copia"] == "copia.db" and len(res["apartados"]) == 2
    assert sqlite3.connect(db).execute("SELECT v FROM t").fetchone()[0] == "copia"
    assert (tmp_path / "danadas").is_dir()


def test_no_toca_si_esta_bien_o_no_hay_copia(tmp_path):
    buena = _sqlite_bytes(tmp_path, "ok.db", "x")
    db = tmp_path / "mrd_tool.db"
    db.write_bytes(buena)
    assert main._bd_autorestaurar(db, lambda: ("c", b""))["accion"] == "ninguna"

    def _sin():
        raise RuntimeError("no hay ninguna copia")
    res = main._bd_autorestaurar(db, _sin, quick_check=lambda p: "corrupta")
    assert res["accion"] == "sin_copia" and db.read_bytes() == buena, "sin copia no se mueve nada"
