"""Bloque A, fallo 7: favicon, robots.txt e icono de Apple ya no dan 404."""


def test_ficheros_que_piden_los_navegadores(client):
    for u, ct in (("/favicon.ico", "image/png"), ("/apple-touch-icon.png", "image/png"), ("/apple-touch-icon-precomposed.png", "image/png"), ("/robots.txt", "text/plain")):
        r = client.get(u)
        assert r.status_code == 200 and r.headers["content-type"].startswith(ct), u
    assert "Disallow: /" in client.get("/robots.txt").text
