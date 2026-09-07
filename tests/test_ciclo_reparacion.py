"""Mejora 26: al devolver una herramienta dañada se abre la reparación, sale de disponible y se puede avisar al proveedor."""
import main
from auth import hash_password
from models import Almacen, Aviso, Herramienta, Proveedor, Reparacion, Trabajador, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave rep", codigo="MRD-REP", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-rep", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    prov = Proveedor(nombre="Talleres Rep", telefono="+34 600 11 22 33", email="taller@rep.es", activo=True)
    t = Trabajador(nombre="Rompe", apellidos="Todo", activo=True, codigo="POR-REP", almacen_id=almacen.id)
    db.add_all([prov, t])
    db.flush()
    h = Herramienta(codigo="REP-H1", nombre="Radial rep", estado="entregada", activa=True, almacen_id=almacen.id, responsable_id=t.id, proveedor_id=prov.id)
    db.add(h)
    db.commit()
    return almacen, t, h, prov


def test_devolucion_danada_abre_reparacion(client, db):
    almacen, t, h, prov = _setup(db)
    resp = client.post("/login", data={"username": "admin-rep", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    r = client.post("/movimientos/devolver", data={"_csrf_token": csrf, "herramienta_id": str(h.id), "almacen_id": str(almacen.id), "condicion": "danada", "observaciones": "Disco partido"}, follow_redirects=False)
    assert r.status_code in (200, 303), r.text
    db.expire_all()
    rep = db.query(Reparacion).filter_by(herramienta_id=h.id).one()
    assert rep.estado == "recibida" and rep.proveedor_id == prov.id and "Disco partido" in (rep.descripcion or "")
    assert db.get(Herramienta, h.id).estado == "en_reparacion"
    assert db.query(Aviso).filter(Aviso.titulo.like("Radial rep vuelve dañada%")).count() == 1
    html = client.get(f"/reparaciones/{rep.id}").text
    assert "Avisar al proveedor" in html and "wa.me/34600112233" in html and "mailto:taller@rep.es" in html
    assert main._abrir_reparacion_si_danada(db, db.get(Herramienta, h.id), "otra vez", None).id == rep.id
    assert db.query(Reparacion).count() == 1
    r = client.post(f"/reparaciones/{rep.id}/finalizar", data={"_csrf_token": csrf, "resultado": "reparada", "coste_final": "40"}, follow_redirects=False)
    assert r.status_code in (200, 303), r.text
    db.expire_all()
    assert db.get(Reparacion, rep.id).estado == "finalizada" and db.get(Herramienta, h.id).estado == "disponible"
