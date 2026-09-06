"""Kits 2.7.39: maletín que contiene herramientas y sale/entra con ellas por Mostrador Único."""
from pathlib import Path

from models import Almacen, Herramienta, Trabajador, Usuario
from mostrador_service import operate_counter, resolve_counter_item

ROOT = Path(__file__).resolve().parents[1]


def _kit(db):
    almacen = Almacen(nombre="Nave kits", codigo="MRD-MAL", activo=True)
    db.add(almacen)
    db.flush()
    maletin = Herramienta(codigo="MAL-0012", nombre="Maletín Hilti rojo", estado="disponible", activa=True,
                          almacen_id=almacen.id, es_maletin=True)
    db.add(maletin)
    db.flush()
    piezas = [
        Herramienta(codigo="HER-0451", nombre="Taladro Hilti TE-6", estado="disponible", activa=True,
                    almacen_id=almacen.id, maletin_id=maletin.id),
        Herramienta(codigo="HER-0452", nombre="Batería 36V nº 1", estado="disponible", activa=True,
                    almacen_id=almacen.id, maletin_id=maletin.id),
        Herramienta(codigo="HER-0453", nombre="Cargador C4/36", estado="disponible", activa=True,
                    almacen_id=almacen.id, maletin_id=maletin.id),
    ]
    db.add_all(piezas)
    db.commit()
    return almacen, maletin, piezas


def test_resolver_maletin_lista_sus_piezas(db):
    almacen, maletin, piezas = _kit(db)
    item = resolve_counter_item(db, "MAL-0012", almacen.id)
    assert item["found"] and item["tipo"] == "herramienta" and item["es_maletin"] is True
    assert [p["codigo"] for p in item["contenido"]] == ["HER-0452", "HER-0453", "HER-0451"]
    assert all(p["dentro_de"] == "MAL-0012" and p["permite_cantidad"] is False for p in item["contenido"])
    pieza = resolve_counter_item(db, "HER-0451", almacen.id)
    assert pieza["es_maletin"] is False and pieza["maletin_id"] == maletin.id and "contenido" not in pieza


def test_salida_del_maletin_entrega_todas_las_piezas(db):
    almacen, maletin, piezas = _kit(db)
    user = Usuario(username="mal-admin", password_hash="x", nombre="Patio", rol="admin", activo=True)
    worker = Trabajador(nombre="Ana", apellidos="MRD", activo=True, almacen_id=almacen.id)
    db.add_all([user, worker])
    db.commit()
    item = resolve_counter_item(db, "MAL-0012", almacen.id)
    lines = [{"tipo": "herramienta", "id": maletin.id, "cantidad": 1}] + [
        {"tipo": "herramienta", "id": p["id"], "cantidad": 1} for p in item["contenido"]
    ]
    result = operate_counter(
        db, user, operation_id="counter-maletin-001", action="salida",
        worker_id=worker.id, work_id=None, warehouse_id=almacen.id, lines=lines, notes="Kit completo",
    )
    db.commit()
    assert result["total_lineas"] == 4
    for h in [maletin, *piezas]:
        db.refresh(h)
        assert h.estado == "entregada" and h.responsable_id == worker.id


def test_ficha_y_edicion_muestran_el_maletin(db):
    almacen, maletin, piezas = _kit(db)
    db.refresh(maletin)
    assert [p.codigo for p in maletin.contenido] == ["HER-0452", "HER-0453", "HER-0451"]
    assert piezas[0].maletin.id == maletin.id
    edit = (ROOT / "templates" / "editar_herramienta.html").read_text(encoding="utf-8")
    detail = (ROOT / "templates" / "herramienta_detalle.html").read_text(encoding="utf-8")
    counter = (ROOT / "templates" / "mostrador.html").read_text(encoding="utf-8")
    database = (ROOT / "database.py").read_text(encoding="utf-8")
    assert 'name="es_maletin"' in edit and 'name="maletin_id"' in edit
    assert "Contenido del maletín" in detail and "Va en el maletín" in detail
    assert "addMaletinPieces" in counter and "mrd:scanner-code" in counter
    assert '"es_maletin"' in database and '"maletin_id"' in database


def test_ficha_edicion_y_guardado_del_maletin_por_http(client, db):
    from auth import hash_password
    from security import generar_csrf_token

    almacen, maletin, piezas = _kit(db)
    suelta = Herramienta(codigo="HER-0454", nombre="Caladora", estado="disponible", activa=True, almacen_id=almacen.id)
    admin = Usuario(username="admin-maletin", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                    rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id)
    db.add_all([suelta, admin])
    db.commit()
    resp = client.post("/login", data={"username": "admin-maletin", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    headers = {"X-CSRF-Token": token}

    ficha = client.get(f"/herramientas/{maletin.id}")
    assert ficha.status_code == 200 and "Contenido del maletín" in ficha.text and "Completo" in ficha.text
    assert "HER-0451" in ficha.text and "HER-0453" in ficha.text

    edicion = client.get(f"/herramientas/{suelta.id}/editar")
    assert edicion.status_code == 200 and 'name="maletin_id"' in edicion.text and "MAL-0012" in edicion.text

    guardado = client.post(f"/herramientas/{suelta.id}/editar", data={
        "nombre": "Caladora", "categoria": "Otro", "maletin_id": str(maletin.id), "almacen_id": str(almacen.id),
    }, headers=headers, follow_redirects=False)
    assert guardado.status_code in (200, 302, 303), guardado.text[:300]
    db.expire_all()
    assert db.get(Herramienta, suelta.id).maletin_id == maletin.id

    # Una pieza fuera (entregada) deja el maletín "incompleto" en su ficha.
    piezas[1].estado = "entregada"
    db.commit()
    ficha = client.get(f"/herramientas/{maletin.id}")
    assert "Incompleto" in ficha.text
