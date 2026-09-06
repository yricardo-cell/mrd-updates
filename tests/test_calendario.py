"""2.7.55: calendario de revisiones y caducidades (todas las fechas en una
pantalla), Hecho programa la siguiente, exportación .ics, aviso semanal y la
alerta de no retorno solo con plazo fijado y vencido."""
from datetime import date, datetime, timedelta

from auth import hash_password
import main
from models import (Almacen, Aviso, EPIIndividual, FormacionTrabajador, Herramienta, Maquinaria, Movimiento,
                    ReconocimientoMedico, Trabajador, Usuario, Vehiculo)
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave cal", codigo="MRD-CAL", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-cal", password_hash=hash_password("ClaveSegura123!"), nombre="Admin",
                   rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Erick", apellidos="Cal", activo=True, almacen_id=almacen.id)
    db.add(t)
    db.flush()
    hoy = date.today()
    epi = EPIIndividual(tipo="ARNES", codigo_fabricacion="ARN-CAL-1", estado="activo", proxima_revision=hoy - timedelta(days=5),
                        almacen_id=almacen.id, trabajador_id=t.id)
    herr = Herramienta(codigo="CAL-HER-1", nombre="Martillo cal", estado="disponible", activa=True, almacen_id=almacen.id,
                       fecha_proximo_mantenimiento=hoy, intervalo_mantenimiento_dias=180)
    maq = Maquinaria(codigo_interno="CAL-MAQ-1", nombre="Alimak cal", estado="disponible", activa=True, proxima_revision=hoy + timedelta(days=15))
    db.add_all([epi, herr, maq,
                FormacionTrabajador(trabajador_id=t.id, nombre_curso="PRL 20h", fecha_caducidad=hoy + timedelta(days=9)),
                ReconocimientoMedico(trabajador_id=t.id, fecha=hoy - timedelta(days=370), fecha_proxima=hoy - timedelta(days=12)),
                Vehiculo(codigo="CAL-VEH-1", matricula="1234CAL", marca="Ford", estado="activo", activo=True, itv_hasta=hoy + timedelta(days=40))])
    db.commit()
    return almacen, t, epi, herr, maq


def _login(client):
    resp = client.post("/login", data={"username": "admin-cal", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return {"X-CSRF-Token": token, "Accept": "application/json"}


def test_calendario_reune_todas_las_fechas(client, db):
    almacen, t, epi, herr, maq = _setup(db)
    _login(client)
    page = client.get("/calendario")
    assert page.status_code == 200
    html = page.text
    assert "ARNES ARN-CAL-1" in html and "Martillo cal" in html and "Alimak cal" in html and "PRL 20h" in html
    assert "Reconocimiento médico" in html and "Ford 1234CAL" in html and "/calendario.ics" in html
    data = client.get("/api/calendario/eventos").json()
    cats = {e["cat"] for e in data["eventos"]}
    assert cats == {"epi", "herramienta", "trabajador", "vehiculo"}
    assert data["resumen"]["vencidas"] == 2 and data["resumen"]["semana"] >= 1
    epi_ev = next(e for e in data["eventos"] if e["tipo"] == "epi")
    assert "la tiene Erick Cal" in epi_ev["detalle"] and epi_ev["hecho"] is False
    assert 'href="/calendario"' in client.get("/").text


def test_hecho_programa_la_siguiente_y_programar(client, db):
    almacen, t, epi, herr, maq = _setup(db)
    h = _login(client)
    r = client.post("/api/calendario/hecho", json={"tipo": "herramienta", "id": herr.id}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["siguiente"] == (date.today() + timedelta(days=180)).isoformat()
    db.expire_all()
    assert db.get(Herramienta, herr.id).fecha_ultimo_mantenimiento == date.today()
    r = client.post("/api/calendario/hecho", json={"tipo": "maquina", "id": maq.id}, headers=h)
    assert r.json()["siguiente"] == (date.today() + timedelta(days=365)).isoformat()
    r = client.post("/api/calendario/programar", json={"tipo": "herramienta", "id": herr.id, "fecha": "2027-03-01", "intervalo_dias": 90}, headers=h)
    assert r.status_code == 200, r.text
    db.expire_all()
    hh = db.get(Herramienta, herr.id)
    assert hh.fecha_proximo_mantenimiento == date(2027, 3, 1) and hh.intervalo_mantenimiento_dias == 90
    r = client.post("/api/calendario/hecho", json={"tipo": "epi", "id": epi.id}, headers=h)
    assert r.status_code == 400


def test_ics_y_aviso_semanal(client, db):
    almacen, t, epi, herr, maq = _setup(db)
    _login(client)
    r = client.get("/calendario.ics")
    assert r.status_code == 200 and "text/calendar" in r.headers["content-type"]
    assert "BEGIN:VEVENT" in r.text and "Martillo cal" in r.text and r.text.count("BEGIN:VEVENT") >= 5
    aviso = main._aviso_semanal_calendario(db)
    assert aviso is not None and aviso.enlace == "/calendario" and aviso.prioridad == "alta"
    assert "Vencidas (2)" in aviso.mensaje and "ARNES ARN-CAL-1" in aviso.mensaje
    assert main._aviso_semanal_calendario(db) is None
    assert db.query(Aviso).filter(Aviso.tipo == "calendario").count() == 1


def test_no_retorno_solo_con_plazo_vencido(client, db):
    almacen, t, epi, herr, maq = _setup(db)
    fuera = Herramienta(codigo="CAL-HER-2", nombre="Radial fuera", estado="entregada", activa=True, almacen_id=almacen.id)
    db.add(fuera)
    db.flush()
    db.add(Movimiento(tipo="entrega", estado_nuevo="entregada", herramienta_id=fuera.id, trabajador_id=t.id,
                      fecha=datetime.now() - timedelta(days=60)))
    db.commit()
    assert main._alertas_no_retorno_herramientas(db) == 0
    assert db.query(Aviso).filter(Aviso.titulo.like("No retorno herramienta%")).count() == 0
    db.add(Movimiento(tipo="entrega", estado_nuevo="entregada", herramienta_id=fuera.id, trabajador_id=t.id,
                      fecha=datetime.now() - timedelta(days=10), fecha_devolucion_prevista=datetime.now() - timedelta(days=2)))
    db.commit()
    assert main._alertas_no_retorno_herramientas(db) == 1
    db.commit()
    aviso = db.query(Aviso).filter(Aviso.titulo.like("No retorno herramienta%")).one()
    assert "debía volver el" in aviso.mensaje
    assert main._alertas_no_retorno_herramientas(db) == 0
