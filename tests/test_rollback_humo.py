"""Mejora 34: vuelta atrás automática si la prueba de humo falla tras actualizar."""
import main


def test_decidir_y_aplicar(tmp_path):
    assert not main._rollback_decidir({"ok": True}, "2.7.76", {}, True)
    assert not main._rollback_decidir({"ok": False}, "2.7.76", {}, False), "sin copia de la versión anterior no hay vuelta atrás"
    assert main._rollback_decidir({"ok": False}, "2.7.76", {}, True)
    assert not main._rollback_decidir({"ok": False}, "2.7.76", {"version": "2.7.76"}, True), "solo un intento por versión"
    bk = tmp_path / "rollback_2.7.76"
    (bk / "templates").mkdir(parents=True)
    (bk / "main.py").write_text("viejo", encoding="utf-8")
    (bk / "templates" / "x.html").write_text("v", encoding="utf-8")
    base = tmp_path / "app"
    base.mkdir()
    (base / "main.py").write_text("nuevo roto", encoding="utf-8")
    assert main._rollback_aplicar(bk, base) == 2
    assert (base / "main.py").read_text(encoding="utf-8") == "viejo" and (base / "templates" / "x.html").is_file()
