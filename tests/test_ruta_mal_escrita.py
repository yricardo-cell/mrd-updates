"""Bloque A, fallo 6: /portal-trajador y otras erratas redirigen; el 404 ofrece el portal."""
import main


def test_ruta_parecida():
    assert main._ruta_parecida("/portal-trajador") == "/portal-trabajador"
    assert main._ruta_parecida("/portal-trajador?c") == "/portal-trabajador"
    assert main._ruta_parecida("/portal") == "/portal-trabajador"
    assert main._ruta_parecida("/mostrado") == "/mostrador"
    assert main._ruta_parecida("/portal-trabajador") is None
    assert main._ruta_parecida("/api/x") is None
    assert main._ruta_parecida("/zzzzzz") is None


def test_redirige_y_404_util(client):
    r = client.get("/portal-trajador", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/portal-trabajador"
    r = client.get("/no-existe-esta-pagina", follow_redirects=False)
    assert r.status_code == 404 and "/portal-trabajador" in r.text and "Portal del trabajador" in r.text
    r = client.get("/api/no-existe", headers={"Accept": "application/json"})
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")
