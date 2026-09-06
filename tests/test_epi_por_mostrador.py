"""2.7.42: EPI y ropa solo por el Mostrador Único. Estado del kit calculado con
las entregas reales, panel 'EPI del trabajador' y rutas manuales retiradas."""
import json
from datetime import datetime, timedelta
from pathlib import Path

from auth import hash_password
from models import Almacen, CatalogoEPI, EntregaEPI, StockEPI, Trabajador, Usuario
from security import generar_csrf_token

import main

ROOT = Path(__file__).resolve().parents[1]


def _base(db):
    almacen = Almacen(nombre="Nave EPI", codigo="MRD-EPI", activo=True)
    db.add(almacen)
    db.flush()
    admin = Usuario(username="admin-epi", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                    rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id)
    t = Trabajador(nombre="Erick", apellidos="Gómez", activo=True, almacen_id=almacen.id, talla_ropa="XL", talla_calzado="44")
    db.add_all([admin, t])
    db.add_all([
        CatalogoEPI(nombre="Casco", categoria="epi", cantidad_kit=1, activo=True, orden=1),
        CatalogoEPI(nombre="Gafas", categoria="epi", cantidad_kit=1, activo=True, orden=2),
        CatalogoEPI(nombre="Botas", categoria="epi", cantidad_kit=1, activo=True, orden=3),
        CatalogoEPI(nombre="Pantalón", categoria="ropa", cantidad_kit=2, activo=True, orden=1),
    ])
    db.flush()
    db.add_all([
        StockEPI(nombre="Casco", categoria="epi", talla=None, cantidad=12, stock_minimo=1, codigo="SEPI-CASCO", almacen_id=almacen.id),
        StockEPI(nombre="Botas", categoria="epi", talla="43", cantidad=5, stock_minimo=1, codigo="SEPI-BOTAS-43", almacen_id=almacen.id),
        StockEPI(nombre="Botas", categoria="epi", talla="44", cantidad=3, stock_minimo=1, codigo="SEPI-BOTAS-44", almacen_id=almacen.id),
        StockEPI(nombre="Pantalón", categoria="ropa", talla="XL", cantidad=9, stock_minimo=1, codigo="SEPI-PANT-XL", almacen_id=almacen.id),
    ])
    db.commit()
    return almacen, admin, t


def _login(client):
    resp = client.post("/login", data={"username": "admin-epi", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return {"X-CSRF-Token": token, "Accept": "application/json"}


def test_estado_del_kit_segun_entregas_reales(db):
    almacen, admin, t = _base(db)
    kit = [{"nombre": "Casco", "cantidad": 1}, {"nombre": "Gafas", "cantidad": 1}, {"nombre": "Botas", "cantidad": 1}]
    assert main._kit_epi_estado(db, t.id, kit)["faltan"] == ["Casco", "Gafas", "Botas"]
    db.add(EntregaEPI(trabajador_id=t.id, tipo="mostrador", items_json=json.dumps([{"nombre": "casco", "cantidad": 1}, {"nombre": "Botas", "talla": "44", "cantidad": 1}])))
    db.commit()
    estado = main._kit_epi_estado(db, t.id, kit)
    assert estado["faltan"] == ["Gafas"] and estado["completo"] is False
    vieja = EntregaEPI(trabajador_id=t.id, tipo="epi", items_json=json.dumps([{"nombre": "Gafas", "cantidad": 1}]), fecha=datetime.utcnow() - timedelta(days=400))
    db.add(vieja)
    db.commit()
    assert main._kit_epi_estado(db, t.id, kit)["faltan"] == ["Gafas"]
    db.add(EntregaEPI(trabajador_id=t.id, tipo="epi", items_json="[]", observaciones="Kit previamente entregado — marcado manualmente"))
    db.commit()
    assert main._kit_epi_estado(db, t.id, kit)["completo"] is True


def test_panel_epi_del_trabajador_y_tallas(client, db):
    almacen, admin, t = _base(db)
    headers = _login(client)
    data = client.get(f"/api/mostrador/epi-trabajador?trabajador_id={t.id}").json()
    assert data["trabajador"]["talla_calzado"] == "44" and data["kit_completo"] is False
    por_nombre = {i["nombre"]: i for i in data["items"]}
    assert por_nombre["Botas"]["talla"] == "44" and por_nombre["Botas"]["stock"] == 3 and por_nombre["Botas"]["falta"] is True
    assert por_nombre["Botas"]["item"]["tipo"] == "stock_epi" and por_nombre["Botas"]["item"]["codigo"] == "SEPI-BOTAS-44"
    assert por_nombre["Casco"]["item"]["codigo"] == "SEPI-CASCO"
    assert por_nombre["Gafas"]["item"] is None and por_nombre["Gafas"]["stock"] == 0
    assert por_nombre["Pantalón"]["falta"] is False and por_nombre["Pantalón"]["cantidad_kit"] == 2
    resp = client.post("/api/mostrador/epi-trabajador/tallas", json={"trabajador_id": t.id, "talla_ropa": "L", "talla_calzado": "43"}, headers=headers)
    assert resp.status_code == 200, resp.text
    db.expire_all()
    assert db.get(Trabajador, t.id).talla_calzado == "43"
    data = client.get(f"/api/mostrador/epi-trabajador?trabajador_id={t.id}").json()
    assert {i["nombre"]: i for i in data["items"]}["Botas"]["talla"] == "43"


def test_rutas_manuales_llevan_al_mostrador(client, db):
    almacen, admin, t = _base(db)
    headers = _login(client)
    r = client.post(f"/trabajadores/{t.id}/epis/entregar", data={"tipo": "epi"}, headers=headers, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(f"/mostrador?trabajador={t.id}")
    r = client.post(f"/trabajadores/{t.id}/epis/marcar-kit", headers=headers, follow_redirects=False)
    assert r.status_code == 303 and "/mostrador" in r.headers["location"]
    r = client.post("/epis/stock/entrada", data={"nombre": "Casco", "cantidad": 1}, headers=headers, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/mostrador?modo=entrada")
    assert db.query(StockEPI).filter_by(codigo="SEPI-CASCO").one().cantidad == 12
    pagina = client.get("/epis")
    assert pagina.status_code == 200 and "Entregar en Mostrador" in pagina.text and "Faltan:" in pagina.text
    ficha = client.get(f"/trabajadores/{t.id}/epis")
    assert ficha.status_code == 200 and "Kit: faltan" in ficha.text
    mostrador = client.get(f"/mostrador?trabajador={t.id}&epi=1&modo=entrada")
    assert mostrador.status_code == 200 and 'id="epi-panel"' in mostrador.text


def test_plantillas_sin_vias_paralelas():
    epis = (ROOT / "templates" / "epis.html").read_text(encoding="utf-8")
    ficha = (ROOT / "templates" / "trabajador_epis.html").read_text(encoding="utf-8")
    stock = (ROOT / "templates" / "epis_stock.html").read_text(encoding="utf-8")
    counter = (ROOT / "templates" / "mostrador.html").read_text(encoding="utf-8")
    assert "modalEntregarKit" not in epis and "marcar-kit" not in epis and "/mostrador?trabajador=" in epis
    assert 'id="modalEPI"' not in ficha and "/epis/entregar" not in ficha and 'id="modalAsignarArnes"' in ficha
    assert "/epis/stock/entrada" not in stock and "/mostrador?modo=entrada" in stock
    assert 'id="epi-panel"' in counter and "/api/mostrador/epi-trabajador" in counter and "mrd:scanner-code" in counter
