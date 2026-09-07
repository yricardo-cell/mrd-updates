"""Mejora 31: vigilante de cuelgues (decisión y comprobación)."""
from datetime import datetime, timedelta
import main


def test_decidir():
    ahora = datetime(2026, 9, 8, 12, 0)
    arr = ahora - timedelta(minutes=10)
    assert main._vigilante_decidir(0, ahora, {}, arr, True) == "ok"
    assert main._vigilante_decidir(2, ahora, {}, arr, True) == "esperar"
    assert main._vigilante_decidir(4, ahora, {}, ahora - timedelta(seconds=30), True) == "esperar", "en el arranque no se reinicia"
    assert main._vigilante_decidir(4, ahora, {}, arr, True, actualizando=True) == "esperar"
    assert main._vigilante_decidir(4, ahora, {}, arr, True) == "reiniciar"
    assert main._vigilante_decidir(4, ahora, {}, arr, False) == "avisar", "sin supervisor solo avisa"
    reciente = {"ultimo_reinicio": (ahora - timedelta(minutes=10)).isoformat()}
    assert main._vigilante_decidir(6, ahora, reciente, arr, True) == "avisar", "no encadena reinicios"
    viejo = {"ultimo_reinicio": (ahora - timedelta(hours=2)).isoformat()}
    assert main._vigilante_decidir(6, ahora, viejo, arr, True) == "reiniciar"


def test_comprobar_sin_servidor(monkeypatch):
    monkeypatch.setenv("MRD_PORT", "1")
    monkeypatch.setattr(main, "_APP_LOOP", None)
    ok, motivo = main._vigilante_comprobar(timeout=1)
    assert not ok and "health" in motivo
