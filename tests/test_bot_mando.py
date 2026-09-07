"""Mejora 38: mando a distancia desde Telegram (lado app)."""


def test_rutas_bot_protegidas(client, monkeypatch):
    monkeypatch.setenv("MRD_BOT_TOKEN", "tok-mando")
    for u in ("/api/bot/reiniciar", "/api/bot/reparar", "/api/bot/copia", "/api/bot/actualizar"):
        assert client.post(u).status_code == 401, u
    monkeypatch.delenv("MRD_SUPERVISADO", raising=False)
    r = client.post("/api/bot/reiniciar", headers={"X-MRD-Bot-Token": "tok-mando"})
    assert r.status_code == 200 and r.json()["ok"] is False, "sin supervisor no se reinicia solo"
