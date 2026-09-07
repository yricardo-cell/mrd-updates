"""Mejora 37: qué arrancar tras un reinicio de Windows."""
import main


def test_decidir():
    acc = main._arranque_decidir({"MRD Sentinel 24x7": "Running", "MRD Remote Telegram": "Ready"}, {"Cloudflared": "Stopped"})
    assert ("tarea", "MRD Remote Telegram") in acc and ("servicio", "Cloudflared") in acc and ("tarea", "MRD Sentinel 24x7") not in acc
    assert main._arranque_decidir({"MRD Sentinel 24x7": "En ejecución"}, {"Cloudflared": "Running"}) == []
    assert main._arranque_decidir({"X": "no_existe"}, {}) == []
