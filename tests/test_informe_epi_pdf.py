"""Mejora 30: informe de EPI para la inspección (PDF por trabajador)."""
import json
from datetime import date, datetime, timedelta

from auth import hash_password
from models import Almacen, EPIIndividual, EntregaEPI, FormacionTrabajador, ReconocimientoMedico, RevisionEPI, Trabajador, Usuario
from security import generar_csrf_token


def test_informe_epi_pdf(client, db):
    almacen = Almacen(nombre="Nave ins", codigo="MRD-INS", activo=True)
    db.add(almacen)
    db.flush()
    db.add(Usuario(username="admin-ins", password_hash=hash_password("ClaveSegura123!"), nombre="Admin", rol="admin", activo=True, must_change_password=False, almacen_id=almacen.id))
    t = Trabajador(nombre="Ines", apellidos="Inspeccion", activo=True, codigo="POR-INS", dni="11111111A", almacen_id=almacen.id, epi_revisado_en=datetime.now())
    db.add(t)
    db.flush()
    e = EPIIndividual(tipo="ARNES", codigo_fabricacion="ARN-INS-1", marca="Petzl", trabajador_id=t.id, estado="activo", almacen_id=almacen.id, fecha_puesta_servicio=date(2025, 1, 10), proxima_revision=date.today() + timedelta(days=100))
    db.add(e); db.flush()
    db.add(RevisionEPI(epi_id=e.id, resultado="apto", tecnico="Juan", proxima_revision=date.today() + timedelta(days=100)))
    db.add(EntregaEPI(trabajador_id=t.id, tipo="epi", items_json=json.dumps([{"nombre": "Casco", "cantidad": 1}, {"nombre": "Guantes", "cantidad": 2, "talla": "9"}]), fecha=datetime.now(), entregado_por="Almacén", firmado_por="Ines"))
    db.add(FormacionTrabajador(trabajador_id=t.id, nombre_curso="Trabajos en altura", entidad="Fremap", fecha_realizacion=date(2025, 3, 1), fecha_caducidad=date.today() + timedelta(days=200), num_certificado="C-1"))
    db.add(FormacionTrabajador(trabajador_id=t.id, nombre_curso="PRL basico", fecha_caducidad=date.today() - timedelta(days=5)))
    db.add(ReconocimientoMedico(trabajador_id=t.id, fecha=date.today() - timedelta(days=100), resultado="apto", fecha_proxima=date.today() + timedelta(days=265), centro="Quirón"))
    db.commit()
    resp = client.post("/login", data={"username": "admin-ins", "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"]); client.cookies.set("mrd_csrf", generar_csrf_token())
    r = client.get(f"/trabajadores/{t.id}/informe-epi.pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF" and "informe_epi_Ines_Inspeccion.pdf" in r.headers["content-disposition"]
    assert len(r.content) > 3000
    assert f'href="/trabajadores/{t.id}/informe-epi.pdf"' in client.get(f"/trabajadores/{t.id}/epis").text
    assert client.get("/trabajadores/999999/informe-epi.pdf").status_code == 404
