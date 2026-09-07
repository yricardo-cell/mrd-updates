"""Mejora 32: decisión de la reparación automática de ficheros."""
import main


def test_decidir():
    assert main._reparacion_decidir({"result": "error_interno"}, "2.7.76") == "error"
    assert main._reparacion_decidir({"ok": True, "result": "ok", "baseline": "2.7.75"}, "2.7.76") == "sellar"
    assert main._reparacion_decidir({"ok": True, "result": "ok", "baseline": "2.7.76", "components": {"app": {"status": "ok"}}}, "2.7.76") == "ok"
    assert main._reparacion_decidir({"ok": False, "result": "problemas", "baseline": "2.7.76", "components": {"ficheros": {"status": "error"}}}, "2.7.76") == "reparar"
    assert main._reparacion_decidir({"ok": True, "result": "ok", "baseline": "2.7.76", "missing_files": ["main.py"]}, "2.7.76") == "reparar"
    assert main._reparacion_decidir({"ok": True, "result": "ok", "baseline": "2.7.76", "components": {"base_datos": {"status": "error"}}}, "2.7.76") == "ok", "la base de datos la trata el 33"
