"""Mejora 19: reservas por día y choques cuando se pide más de lo que hay."""
from datetime import datetime, timedelta
import main
from models import Aviso, Herramienta, LineaSolicitudTrabajador, SolicitudTrabajador, Trabajador

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


def test_reservas_y_choque(client, db):
    almacen, hdr = _admin(client, db, "rsv")
    t = Trabajador(nombre="Res", apellidos="Erva", activo=True, codigo="RSV-1", almacen_id=almacen.id)
    db.add(t)
    db.add(Herramienta(codigo="RSV-H1", nombre="Taladro percutor", estado="disponible", activa=True, almacen_id=almacen.id))
    db.flush()
    manana = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)
    for i in range(2):
        s = SolicitudTrabajador(numero=f"SOL-RSV-{i}", trabajador_id=t.id, almacen_id=almacen.id, estado="aprobada", prioridad="normal", submission_id=f"rsv-{i}", necesario_para=manana)
        db.add(s)
        db.flush()
        db.add(LineaSolicitudTrabajador(solicitud_id=s.id, tipo="herramienta", descripcion="Taladro percutor", cantidad=1))
    db.commit()
    filas = main._reservas(db, 7)
    assert len(filas) == 2 and all(f["choque"] and f["existen"] == 1 and f["pedidas_ese_dia"] == 2 for f in filas)
    assert main._reservas_conflictos_bg(db_externa=db) == 1
    assert db.query(Aviso).filter(Aviso.titulo.like("Reservas que chocan%")).count() == 1
    main._reservas_conflictos_bg(db_externa=db)
    assert db.query(Aviso).filter(Aviso.titulo.like("Reservas que chocan%")).count() == 1
    html = client.get("/reservas?dias=7").text
    assert "Taladro percutor" in html and "solo hay 1" in html
