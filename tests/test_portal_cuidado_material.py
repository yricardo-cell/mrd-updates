"""Mejora 18: marcador de cuidado del material (portal y ranking de oficina)."""
from datetime import datetime, timedelta

import main
from auth import hash_password
from models import Almacen, Herramienta, IncidenciaPortalTrabajador, Movimiento, Trabajador, Usuario
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave cui", codigo="MRD-CUI", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-cui", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Cuida", apellidos="Bien", activo=True, codigo="POR-CUI", portal_token="portal-token-cui",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id, epi_revisado_en=datetime.now())
    db.add(t)
    db.flush()
    h1 = Herramienta(codigo="CUI-H1", nombre="Taladro cui", estado="disponible", activa=True, almacen_id=almacen.id)
    h2 = Herramienta(codigo="CUI-H2", nombre="Radial cui", estado="disponible", activa=True, almacen_id=almacen.id)
    db.add_all([h1, h2])
    db.flush()
    ahora = datetime.utcnow()
    db.add_all([
        Movimiento(herramienta_id=h1.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=t.id, fecha=ahora - timedelta(days=20), fecha_devolucion_prevista=datetime.now() - timedelta(days=10)),
        Movimiento(herramienta_id=h1.id, tipo="devolucion", estado_nuevo="disponible", trabajador_id=t.id, fecha=ahora - timedelta(days=12)),
        Movimiento(herramienta_id=h2.id, tipo="entrega", estado_nuevo="entregada", trabajador_id=t.id, fecha=ahora - timedelta(days=20), fecha_devolucion_prevista=datetime.now() - timedelta(days=15)),
        Movimiento(herramienta_id=h2.id, tipo="devolucion", estado_nuevo="disponible", trabajador_id=t.id, fecha=ahora - timedelta(days=5)),
        IncidenciaPortalTrabajador(numero="INC-CUI-1", trabajador_id=t.id, categoria="averia", descripcion="Se ha roto el cable del taladro"),
    ])
    db.commit()
    return t


def test_puntos_y_estrellas(client, db):
    t = _setup(db)
    c = main._cuidado_material(db, t)
    # 50 +10 (a tiempo) -10 (tarde) +5 (incidencia) +15 (EPI revisado) = 70 -> 4 estrellas
    assert c["puntos"] == 70 and c["estrellas"] == 4, c
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    client.cookies.set("mrd_csrf", generar_csrf_token())
    html = client.get(f"/portal/{t.portal_token}").text
    assert "Mi cuidado del material" in html and "70 puntos" in html and html.count("bi-star-fill") >= 4 and "EPI revisado este mes" in html
    client.cookies.clear()
    resp = client.post("/login", data={"username": "admin-cui", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); client.cookies.set("mrd_csrf", generar_csrf_token())
    r = client.get("/trabajadores/cuidado")
    assert r.status_code == 200 and "Cuida Bien" in r.text and "<strong>70</strong>" in r.text
    assert 'href="/trabajadores/cuidado"' in client.get("/trabajadores").text
