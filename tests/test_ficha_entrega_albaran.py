"""Entregar desde la ficha de la herramienta deja albarán y arrastra las piezas del maletín (2.7.80)."""
from auth import hash_password
from security import generar_csrf_token
from models import Almacen, AlbaranSalida, Herramienta, ItemAlbaranSalida, Trabajador, Usuario


def _setup(db):
    almacen = Almacen(nombre="Nave alb", codigo="MRD-ALB", activo=True)
    db.add(almacen)
    db.flush()
    admin = Usuario(username="admin-alb", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin",
                    activo=True, must_change_password=False, almacen_id=almacen.id)
    juan = Trabajador(codigo="ALB-01", nombre="Juan", apellidos="Albaran", activo=True, almacen_id=almacen.id)
    suelta = Herramienta(codigo="ALB-H1", nombre="Radial", estado="disponible", activa=True, almacen_id=almacen.id)
    maletin = Herramienta(codigo="ALB-MAL", nombre="Cajón", estado="disponible", activa=True, almacen_id=almacen.id, es_maletin=True)
    db.add_all([admin, juan, suelta, maletin])
    db.flush()
    piezas = [Herramienta(codigo=f"ALB-P{i}", nombre=f"Pieza {i}", estado="disponible", activa=True,
                          almacen_id=almacen.id, maletin_id=maletin.id) for i in (1, 2)]
    db.add_all(piezas)
    db.commit()
    return almacen, admin, juan, suelta, maletin, piezas


def _login(client):
    resp = client.post("/login", data={"username": "admin-alb", "password": "ClaveSegura123!"}, follow_redirects=False)
    assert resp.status_code in (302, 303)
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return {"X-CSRF-Token": token}


def test_entregar_desde_la_ficha_crea_albaran(client, db):
    almacen, admin, juan, suelta, maletin, piezas = _setup(db)
    H = _login(client)
    r = client.post(f"/herramientas/{suelta.id}/accion", data={"accion": "entregar", "trabajador_id": str(juan.id), "observaciones": "desde la ficha"},
                    headers={**H, "Accept": "application/json"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and d["albaran_id"] and d["albaran_url"] == f"/albaranes-salida/{d['albaran_id']}"
    alb = db.get(AlbaranSalida, d["albaran_id"])
    assert alb.responsable_id == juan.id and alb.tipo_documento == "salida"
    lineas = db.query(ItemAlbaranSalida).filter(ItemAlbaranSalida.albaran_id == alb.id).all()
    assert [l.herramienta_id for l in lineas] == [suelta.id]
    db.refresh(suelta)
    assert suelta.estado == "entregada" and suelta.responsable_id == juan.id


def test_entregar_maletin_desde_la_ficha_arrastra_y_albaran_con_piezas(client, db):
    almacen, admin, juan, suelta, maletin, piezas = _setup(db)
    H = _login(client)
    r = client.post(f"/herramientas/{maletin.id}/accion", data={"accion": "entregar", "trabajador_id": str(juan.id)},
                    headers={**H, "Accept": "application/json"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["piezas_movidas"] == 2
    lineas = db.query(ItemAlbaranSalida).filter(ItemAlbaranSalida.albaran_id == d["albaran_id"]).all()
    assert sorted(l.herramienta_id for l in lineas) == sorted([maletin.id, *[p.id for p in piezas]])
    for p in piezas:
        db.refresh(p)
        assert p.estado == "entregada" and p.responsable_id == juan.id
    # Devolver desde la ficha trae las piezas y no crea albarán de salida nuevo.
    n_alb = db.query(AlbaranSalida).count()
    r = client.post(f"/herramientas/{maletin.id}/accion", data={"accion": "devolver", "almacen_id": str(almacen.id)},
                    headers={**H, "Accept": "application/json"})
    assert r.status_code == 200, r.text
    assert r.json()["albaran_id"] is None and db.query(AlbaranSalida).count() == n_alb
    for p in piezas:
        db.refresh(p)
        assert p.estado == "disponible" and p.responsable_id is None


def test_entregar_desde_la_ficha_sin_json_redirige_al_albaran(client, db):
    almacen, admin, juan, suelta, maletin, piezas = _setup(db)
    H = _login(client)
    r = client.post(f"/herramientas/{suelta.id}/accion", data={"accion": "entregar", "trabajador_id": str(juan.id)}, headers=H, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/albaranes-salida/")
