"""Inventario guiado en tres pasos (2.7.33, aprobado sobre maqueta el
06/09/2026). Antes, crear una sesión desde la interfaz fallaba siempre
("Cambia primero al almacén...") porque el formulario enviaba almacen_id=null;
en producción nunca llegó a existir una sesión. El flujo nuevo: elegir grupo,
contar viendo lo esperado, cerrar en bloque manteniendo lo no contado."""
from auth import hash_password
from models import Almacen, LineaInventario, Material, SesionInventario, Usuario
from security import generar_csrf_token


def _preparar(db):
    almacen = Almacen(nombre="Almacén guiado", codigo="MRD-GUIADO", activo=True)
    db.add(almacen)
    db.flush()
    admin = Usuario(username="admin-guiado", password_hash=hash_password("ClaveSegura123!"),
                    nombre="Admin Guiado", rol="admin", activo=True, must_change_password=False,
                    almacen_id=almacen.id)
    guantes = Material(codigo="MAT-G9", nombre="Guantes nitrilo 9", unidad="par", stock_actual=92, activo=True, almacen_id=almacen.id)
    discos = Material(codigo="MAT-D230", nombre="Disco corte 230", unidad="ud", stock_actual=9, activo=True, almacen_id=almacen.id)
    db.add_all([admin, guantes, discos])
    db.commit()
    return almacen, guantes, discos


def _login(client, username="admin-guiado"):
    resp = client.post("/login", data={"username": username, "password": "ClaveSegura123!"}, follow_redirects=False)
    client.cookies.set("mrd_token", resp.cookies["mrd_token"])
    token = generar_csrf_token()
    client.cookies.set("mrd_csrf", token)
    return {"X-CSRF-Token": token, "Accept": "application/json"}


def test_flujo_guiado_completo_crea_cuenta_y_cierra_manteniendo_lo_no_contado(client, db):
    almacen, guantes, discos = _preparar(db)
    headers = _login(client)

    pagina = client.get("/inventario")
    assert pagina.status_code == 200
    assert "¿Qué vas a contar hoy" in pagina.text and "Materiales y consumibles" in pagina.text

    creado = client.post("/inventario/guiado/iniciar", json={"tipo_articulo": "material"}, headers=headers)
    assert creado.status_code == 201, creado.text
    datos = creado.json()
    assert datos["reanudada"] is False and datos["lineas"] == 2
    sesion_id = datos["sesion_id"]
    nombre = db.get(SesionInventario, sesion_id).nombre
    assert nombre.startswith("Inventario ") and "Materiales" in nombre

    # Volver a empezar el mismo grupo continúa la sesión abierta: nunca un 409.
    de_nuevo = client.post("/inventario/guiado/iniciar", json={"tipo_articulo": "material"}, headers=headers)
    assert de_nuevo.status_code == 200 and de_nuevo.json()["sesion_id"] == sesion_id

    detalle = client.get(f"/inventario/sesiones/{sesion_id}")
    assert detalle.status_code == 200
    assert "Paso 2 de 3" in detalle.text and "Había" in detalle.text
    assert "Conteo ciego activo" not in detalle.text  # se ve lo esperado
    assert ">92<" in detalle.text or "92" in detalle.text

    linea = db.query(LineaInventario).filter_by(sesion_id=sesion_id, material_id=guantes.id).one()
    contado = client.post(f"/inventario/sesiones/{sesion_id}/contar", json={
        "linea_id": linea.id, "cantidad": 86, "numero_conteo": 1,
        "scan_event_id": "count-guiado-0001", "modo_entrada": "unidad",
    }, headers=headers)
    assert contado.status_code == 200, contado.text

    revision = client.get(f"/inventario/sesiones/{sesion_id}")
    assert "1 con diferencia" in revision.text and "1 sin contar" in revision.text
    assert "Aceptar todo lo contado y cerrar" in revision.text

    cerrado = client.post(f"/inventario/sesiones/{sesion_id}/cerrar-guiado", json={
        "cierre_event_id": "close-guiado-0001", "no_contados": "mantener",
    }, headers=headers)
    assert cerrado.status_code == 200, cerrado.text

    db.expire_all()
    assert db.get(SesionInventario, sesion_id).estado == "cerrada"
    assert db.get(Material, guantes.id).stock_actual == 86      # ajustado a lo contado
    assert db.get(Material, discos.id).stock_actual == 9        # no contado: se mantiene
    estados = {l.estado for l in db.query(LineaInventario).filter_by(sesion_id=sesion_id)}
    assert estados == {"ajustado"}

    resultado = client.get(f"/inventario/sesiones/{sesion_id}")
    assert "Inventario cerrado" in resultado.text and "Guardar (Enter)" not in resultado.text


def test_sin_almacen_activo_explica_en_vez_de_romper(client, db):
    admin = Usuario(username="admin-guiado", password_hash=hash_password("ClaveSegura123!"),
                    nombre="Admin Guiado", rol="admin", activo=True, must_change_password=False)
    db.add(admin)
    db.commit()
    headers = _login(client)
    pagina = client.get("/inventario")
    assert pagina.status_code == 200 and "No hay un almacén activo" in pagina.text
    inicio = client.post("/inventario/guiado/iniciar", json={"tipo_articulo": "material"}, headers=headers)
    assert inicio.status_code == 409 and "almacén activo" in inicio.json()["detail"]


def test_cierre_a_cero_pone_a_cero_lo_no_contado(client, db):
    almacen, guantes, discos = _preparar(db)
    headers = _login(client)
    sesion_id = client.post("/inventario/guiado/iniciar", json={"tipo_articulo": "material"}, headers=headers).json()["sesion_id"]
    cerrado = client.post(f"/inventario/sesiones/{sesion_id}/cerrar-guiado", json={
        "cierre_event_id": "close-guiado-0002", "no_contados": "cero",
    }, headers=headers)
    assert cerrado.status_code == 200, cerrado.text
    db.expire_all()
    assert db.get(Material, guantes.id).stock_actual == 0 and db.get(Material, discos.id).stock_actual == 0
