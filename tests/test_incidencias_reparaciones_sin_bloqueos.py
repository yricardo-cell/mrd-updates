from starlette.requests import Request

from main import incidencia_detalle, incidencias_list, reparacion_detalle, reparaciones_list
from models import Incidencia, Reparacion, Usuario


def _request(path):
    return Request({
        "type": "http", "method": "GET", "path": path,
        "raw_path": path.encode(), "query_string": b"", "headers": [],
        "scheme": "http", "server": ("testserver", 80),
        "client": ("127.0.0.1", 1234), "root_path": "",
    })


def _admin(db):
    user = Usuario(username="admin-fichas", password_hash="test", nombre="Admin",
                   rol="admin", activo=True, must_change_password=False)
    db.add(user)
    db.flush()
    return user


def test_listados_no_renderizan_ventanas_que_bloquean(db):
    user = _admin(db)
    db.add_all([
        Incidencia(numero="INC-SIN-MODAL", titulo="Avería", estado="abierta"),
        Reparacion(numero="REP-SIN-MODAL", estado="diagnostico"),
    ])
    db.flush()

    incidencias_html = incidencias_list(_request("/incidencias"), user, db).body.decode()
    reparaciones_html = reparaciones_list(_request("/reparaciones"), user, db).body.decode()

    assert "modal-overlay" not in incidencias_html
    assert "modal-overlay" not in reparaciones_html
    assert "/incidencias/" in incidencias_html and "> Abrir" in incidencias_html
    assert "/reparaciones/" in reparaciones_html and "> Abrir" in reparaciones_html


def test_fichas_independientes_muestran_formularios_normales(db):
    user = _admin(db)
    inc = Incidencia(numero="INC-FICHA", titulo="Golpe", estado="abierta")
    rep = Reparacion(numero="REP-FICHA", estado="en_reparacion", diagnostico="Cable")
    db.add_all([inc, rep])
    db.flush()

    inc_html = incidencia_detalle(inc.id, _request(f"/incidencias/{inc.id}"), user, db).body.decode()
    rep_html = reparacion_detalle(rep.id, _request(f"/reparaciones/{rep.id}"), user, db).body.decode()

    assert "Datos y seguimiento" in inc_html
    assert f'action="/incidencias/{inc.id}/editar"' in inc_html
    assert "Diagnóstico y seguimiento" in rep_html
    assert f'action="/reparaciones/{rep.id}/editar"' in rep_html
    assert "modal-overlay" not in inc_html + rep_html
