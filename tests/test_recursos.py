"""Mejora 36: disco casi lleno → limpieza y aviso."""
import main


def test_decidir():
    assert main._recursos_decidir(50.0, False) == []
    assert main._recursos_decidir(4.2, False) == ["limpiar", "avisar"]
    assert main._recursos_decidir(4.2, True) == ["limpiar"]
    assert main._recursos_decidir(None, False) == []


def test_tick_sin_problema(db):
    res = main._recursos_tick(db_externa=db)
    assert "libre_gb" in res and isinstance(res["acciones"], list)
