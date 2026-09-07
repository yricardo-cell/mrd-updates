"""Mejoras 42-43: funciones puras del script de arreglo automático (sin lanzar Claude)."""
import importlib.util
import json
from pathlib import Path


def _mod():
    ruta = Path("scripts/operations/autoarreglo.py")
    spec = importlib.util.spec_from_file_location("autoarreglo", ruta)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_resumen_y_prompt():
    m = _mod()
    txt = "bla bla" + chr(10) + "RESUMEN: se pasaba una lista" + chr(10) + "CAUSA: argumento mal" + chr(10) + "CAMBIO: una línea"
    assert m.resumen_de(txt) == "RESUMEN: se pasaba una lista CAUSA: argumento mal CAMBIO: una línea"
    p = m.prompt_arreglo({"id": 7, "ruta": "/x", "tipo": "TypeError", "mensaje": "m", "veces": 2, "version": "2.7.76", "traza": "tb"})
    assert "tests/test_autoarreglo_7.py" in p and "NO hagas commit" in p


def test_bump_version(tmp_path):
    m = _mod()
    (tmp_path / "static" / "js").mkdir(parents=True)
    (tmp_path / "version.json").write_text(json.dumps({"version_actual": "2.7.76", "cambios": ["a", "b"]}), encoding="utf-8")
    (tmp_path / "static" / "js" / "sw.js").write_text("const CACHE_NAME = 'mrd-static-v2.7.76';", encoding="utf-8")
    nueva = m.bump_version(tmp_path, "Arreglo automático #1: x")
    assert nueva == "2.7.77"
    d = json.loads((tmp_path / "version.json").read_text(encoding="utf-8"))
    assert d["version_actual"] == "2.7.77" and d["cambios"][0].startswith("Arreglo automático") and d["version_anterior"] == "2.7.76"
    assert "mrd-static-v2.7.77" in (tmp_path / "static" / "js" / "sw.js").read_text(encoding="utf-8")
