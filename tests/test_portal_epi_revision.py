"""Mejora 7: revisión mensual de EPI con un toque desde el portal."""
from datetime import date

import main
from auth import hash_password
from models import Almacen, CatalogoEPI, EPIIndividual, IncidenciaPortalTrabajador, NotificacionTrabajador, SolicitudTrabajador, Trabajador
from security import generar_csrf_token


def _setup(db):
    almacen = Almacen(nombre="Nave epi", codigo="MRD-EPR", activo=True)
    db.add(almacen)
    db.flush()
    t = Trabajador(nombre="Eva", apellidos="Epi", activo=True, codigo="POR-EPR", portal_token="portal-token-epr",
                   portal_pin_hash=hash_password("1234"), portal_pin_cambio_obligatorio=False, almacen_id=almacen.id)
    db.add(t)
    db.flush()
    e = EPIIndividual(tipo="ARNES", codigo_fabricacion="ARN-EPR-1", marca="Petzl", trabajador_id=t.id, estado="activo", almacen_id=almacen.id)
    db.add(e)
    if not db.query(CatalogoEPI).filter_by(nombre="Guantes epr").first():
        db.add(CatalogoEPI(nombre="Guantes epr", categoria="epi", cantidad_kit=1, activo=True, orden=1))
        db.add(CatalogoEPI(nombre="Casco epr", categoria="epi", cantidad_kit=1, activo=True, orden=2))
    db.commit()
    return t, e


def test_revision_epi_crea_incidencia_y_pedido(client, db):
    t, e = _setup(db)
    assert main._avisos_trabajador_util(db) >= 1
    assert db.query(NotificacionTrabajador).filter(NotificacionTrabajador.evento_clave == f"epirev:{t.id}:{date.today():%Y-%m}").count() == 1
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    html = client.get(f"/portal/{t.portal_token}").text
    assert "Todavía no has revisado tu EPI" in html and f'name="epi_{e.id}"' in html and 'name="kit_nombre" value="Guantes epr"' in html
    r = client.post(f"/portal/{t.portal_token}/epi/revision", data={
        "_csrf_token": csrf, f"epi_{e.id}": "mal", "kit_nombre": ["Guantes epr", "Casco epr"], "kit_estado_0": "falta", "kit_estado_1": "bien", "detalle": "cinta rozada",
    }, follow_redirects=False)
    assert r.status_code == 303 and "ok=epi_revisado" in r.headers["location"]
    inc = db.query(IncidenciaPortalTrabajador).filter(IncidenciaPortalTrabajador.trabajador_id == t.id).one()
    assert inc.categoria == "seguridad" and inc.activo_tipo == "epi" and "ARNES" in (inc.activo_nombre or "") and "cinta rozada" in inc.descripcion
    sol = db.query(SolicitudTrabajador).filter(SolicitudTrabajador.trabajador_id == t.id).one()
    assert [l.descripcion for l in sol.lineas] == ["Guantes epr"] and sol.lineas[0].tipo == "epi" and "revisión mensual" in (sol.motivo or "")
    db.expire_all()
    assert db.get(Trabajador, t.id).epi_revisado_en is not None
    html = client.get(f"/portal/{t.portal_token}?ok=epi_revisado").text
    assert "Revisión de EPI anotada" in html and "Última revisión" in html
    # ya revisado este mes: no vuelve a avisar
    main._avisos_trabajador_util(db)
    assert db.query(NotificacionTrabajador).filter(NotificacionTrabajador.evento_clave.like(f"epirev:{t.id}:%")).count() == 1


def test_sin_problemas_no_crea_nada(client, db):
    t, e = _setup(db)
    assert client.post("/portal-trabajador/acceso", data={"codigo": t.codigo, "pin": "1234"}).status_code == 200
    csrf = generar_csrf_token(); client.cookies.set("mrd_csrf", csrf)
    r = client.post(f"/portal/{t.portal_token}/epi/revision", data={"_csrf_token": csrf, f"epi_{e.id}": "bien", "kit_nombre": ["Guantes epr"], "kit_estado_0": "bien"}, follow_redirects=False)
    assert r.status_code == 303
    assert db.query(IncidenciaPortalTrabajador).count() == 0 and db.query(SolicitudTrabajador).count() == 0
    db.expire_all()
    assert db.get(Trabajador, t.id).epi_revisado_en is not None
