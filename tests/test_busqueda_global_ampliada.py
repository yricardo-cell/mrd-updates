"""Mejora 31: la búsqueda global también encuentra pedidos, huecos, EPI individual, materiales e incidencias."""
from auth import hash_password
from models import Almacen, EPIIndividual, IncidenciaPortalTrabajador, LineaSolicitudTrabajador, Material, SolicitudTrabajador, Trabajador, Ubicacion, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave bus", codigo="MRD-BUS", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-bus", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Busca", apellidos="Dor", activo=True, codigo="POR-BUS", almacen_id=almacen.id)
    db.add(t)
    db.flush()
    s = SolicitudTrabajador(numero="SOL-ZETA-1", trabajador_id=t.id, almacen_id=almacen.id, estado="pendiente", prioridad="normal", submission_id="bus-1")
    db.add(s); db.flush()
    db.add(LineaSolicitudTrabajador(solicitud_id=s.id, tipo="consumible", descripcion="Discos zetaflex", cantidad=2))
    db.add(Ubicacion(almacen_id=almacen.id, nombre="ESTANTERIA ZETA", codigo="MRD-UBI-ZETA", zona="ZETA", estanteria="Z", posicion="1", activo=True))
    db.add(EPIIndividual(tipo="ARNES ZETA", codigo_fabricacion="ZETA-ARN-1", trabajador_id=t.id, estado="activo", almacen_id=almacen.id))
    db.add(Material(nombre="Tornillo zeta", codigo="MAT-ZETA", activo=True, almacen_id=almacen.id, stock_actual=7))
    db.add(IncidenciaPortalTrabajador(numero="INC-ZETA-1", trabajador_id=t.id, almacen_id=almacen.id, categoria="averia", descripcion="Se rompió la zeta"))
    db.commit()


def test_busqueda_ampliada(client, db):
    _setup(db)
    resp = client.post("/login", data={"username": "admin-bus", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); client.cookies.set("mrd_csrf", generar_csrf_token())
    d = client.get("/api/buscar?q=zeta").json()
    assert d["pedidos"][0]["numero"] == "SOL-ZETA-1" and d["pedidos"][0]["quien"] == "Busca Dor"
    assert d["huecos"][0]["nombre"] == "ESTANTERIA ZETA" and d["epis"][0]["tipo"] == "ARNES ZETA"
    assert d["materiales"][0]["nombre"] == "Tornillo zeta" and d["materiales"][0]["stock"] == 7
    assert d["incidencias"][0]["numero"] == "INC-ZETA-1"
    html = client.get("/buscar?q=zeta").text
    for txt in ("SOL-ZETA-1", "ESTANTERIA ZETA", "ARNES ZETA", "Tornillo zeta", "INC-ZETA-1", "Pedidos de trabajadores", "Huecos"):
        assert txt in html, txt
    js = open("static/js/mrd.js", encoding="utf-8").read()
    assert "search-drop-section\">Pedidos" in js and "pedidos = []" in js and "/trabajadores/${mrdSafeId(t.id)}/epis" in js
