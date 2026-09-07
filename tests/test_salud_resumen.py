"""Mejora 39: el resumen diario lleva la línea de salud del sistema."""
import main


def test_resumen_lleva_sistema(db):
    txt = main._resumen_diario_texto(db)
    assert "Sistema:" in txt
    assert main._salud_linea_resumen(db).startswith("Sistema:")
