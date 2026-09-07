"""Mejora 21: tiempos pedido→listo y listo→recogido."""
from datetime import datetime, timedelta
import main
from models import SolicitudTrabajador, Trabajador

from auth import hash_password
from models import Almacen, Usuario
from security import generar_csrf_token


def _admin(client, db, tag):
    almacen = Almacen(nombre="Nave " + tag, codigo="MRD-" + tag.upper(), activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-" + tag, password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    db.commit()
    resp = client.post("/login", data={"username": "admin-" + tag, "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    csrf = generar_csrf_token()
    client.cookies.set("mrd_csrf", csrf)
    return almacen, {"X-CSRF-Token": csrf, "Accept": "application/json"}


PNG_1PX_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAX+G1qQAAAABJRU5ErkJggg=="


def test_tiempos(client, db):
    almacen, hdr = _admin(client, db, "tmp")
    t = Trabajador(nombre="Tie", apellidos="Mpo", activo=True, codigo="TMP-1", almacen_id=almacen.id)
    db.add(t)
    db.flush()
    ahora = datetime.now()
    uid = db.query(Usuario).filter_by(username="admin-tmp").first().id
    db.add(SolicitudTrabajador(numero="SOL-TMP-1", trabajador_id=t.id, almacen_id=almacen.id, estado="entregada", prioridad="normal", submission_id="tmp-1",
                               creado_en=datetime.utcnow() - timedelta(hours=10), lista_en=ahora - timedelta(hours=6), recogida_confirmada_en=ahora - timedelta(hours=4), revisado_por_id=uid))
    db.add(SolicitudTrabajador(numero="SOL-TMP-2", trabajador_id=t.id, almacen_id=almacen.id, estado="lista", prioridad="normal", submission_id="tmp-2",
                               creado_en=datetime.utcnow() - timedelta(hours=3), lista_en=ahora - timedelta(hours=1), revisado_por_id=uid))
    db.commit()
    d = main._tiempos_pedidos(db, 4)
    assert d["pedidos"] == 2 and 2.5 <= d["media_h_listo"] <= 3.5 and 1.9 <= d["media_h_recogido"] <= 2.1
    assert d["personas"][0]["pedidos"] == 2 and sum(g["sin_recoger"] for g in d["semanas"]) == 1
    html = client.get("/informes/tiempos-pedidos?semanas=4").text
    assert "Tiempo de respuesta del almacén" in html and "Por quien prepara" in html
    assert client.get("/informes/tiempos-pedidos/excel").status_code == 200
    assert 'href="/informes/tiempos-pedidos"' in client.get("/informes").text
