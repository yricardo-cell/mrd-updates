"""Mejora 35: decisión del reinicio del túnel."""
from datetime import datetime, timedelta
import main


def test_decidir():
    ahora = datetime(2026, 9, 8, 10, 0)
    assert main._tunel_decidir(0, {}, ahora) == "ok"
    assert main._tunel_decidir(1, {}, ahora) == "esperar"
    assert main._tunel_decidir(2, {}, ahora) == "reiniciar"
    reciente = {"ultimo_reinicio": (ahora - timedelta(minutes=10)).isoformat()}
    assert main._tunel_decidir(3, reciente, ahora) == "esperar"
    assert main._tunel_decidir(4, reciente, ahora) == "reiniciar_backup"
    assert main._tunel_decidir(6, reciente, ahora) == "avisar"
    viejo = {"ultimo_reinicio": (ahora - timedelta(hours=1)).isoformat()}
    assert main._tunel_decidir(3, viejo, ahora) == "reiniciar"
