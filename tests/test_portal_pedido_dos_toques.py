"""2.7.72: P2 pedido en dos toques: repetir el último pedido y chips de lo que suele pedir."""
from auth import hash_password
from models import Almacen, LineaSolicitudTrabajador, SolicitudTrabajador, Trabajador


def _worker(db, sufijo):
    almacen = Almacen(nombre=f"Nave {sufijo}", codigo=f"MRD-{sufijo}", activo=True)
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre="Ana", apellidos=sufijo, activo=True, codigo=f"POR-{sufijo}", portal_token=f"portal-token-{sufijo}".lower(),
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add(t)
    db.flush()
    return almacen, t


def _login(client, t):
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200


def test_repetir_y_frecuentes(client, db):
    almacen, t = _worker(db, "P2A")
    s1 = SolicitudTrabajador(numero="SOL-P2-1", trabajador_id=t.id, almacen_id=almacen.id, estado="entregada", prioridad="normal", submission_id="p2-1")
    s2 = SolicitudTrabajador(numero="SOL-P2-2", trabajador_id=t.id, almacen_id=almacen.id, estado="pendiente", prioridad="normal", submission_id="p2-2")
    s3 = SolicitudTrabajador(numero="SOL-P2-3", trabajador_id=t.id, almacen_id=almacen.id, estado="cancelada", prioridad="normal", submission_id="p2-3")
    db.add_all([s1, s2, s3])
    db.flush()
    db.add_all([
        LineaSolicitudTrabajador(solicitud_id=s1.id, tipo="epi", descripcion="Guantes anticorte", talla="9", cantidad=2),
        LineaSolicitudTrabajador(solicitud_id=s1.id, tipo="herramienta", descripcion="taladro", cantidad=1),
        LineaSolicitudTrabajador(solicitud_id=s2.id, tipo="epi", descripcion="guantes anticorte", talla="9", cantidad=1),
        LineaSolicitudTrabajador(solicitud_id=s2.id, tipo="consumible", descripcion="discos de corte", cantidad=5),
        LineaSolicitudTrabajador(solicitud_id=s3.id, tipo="otro", descripcion="cosa cancelada", cantidad=1),
    ])
    db.commit()
    _login(client, t)
    html = client.get(f"/portal/{t.portal_token}").text
    assert 'id="quick-repeat"' in html and "Repetir mi último pedido (2)" in html
    assert "discos de corte" in html.split('id="quick-repeat"')[1].split("</button>")[0]  # el último pedido es SOL-P2-2
    chips = html.split('class="quick-chips"')[1].split("</div>")[0]
    assert "anticorte" in chips and chips.lower().index("guantes anticorte") < chips.index("taladro")
    assert "cosa cancelada" not in chips and 'data-linea=' in chips and "quick-chip" in chips


def test_sin_pedidos_no_hay_atajos(client, db):
    almacen, t = _worker(db, "P2B")
    db.commit()
    _login(client, t)
    html = client.get(f"/portal/{t.portal_token}").text
    assert "quick-order" not in html and 'id="request-form"' in html
