import json
import re

import pytest
from sqlalchemy import text
from starlette.requests import Request

from auth import PERMISOS_ROL
from main import _get_qr_code_for, mostrador_unico_panel
from models import (
    Almacen,
    CatalogoEPI,
    EPIIndividual,
    ExistenciaVariante,
    Herramienta,
    IdentificadorGlobal,
    Maquinaria,
    Material,
    StockEPI,
    Ubicacion,
    Usuario,
    VarianteEPI,
    Vehiculo,
)
from mostrador_service import CounterError, operate_counter, resolve_counter_item


def _request(path: str) -> Request:
    return Request({
        "type": "http", "method": "GET", "path": path,
        "raw_path": path.encode(), "query_string": b"", "headers": [],
        "scheme": "http", "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345), "root_path": "",
    })


def test_scan_visitante_solo_muestra_navegacion_publica(client):
    response = client.get("/scan")
    assert response.status_code == 200
    html = response.text
    anchors = set(re.findall(r'<a[^>]+href=["\']([^"\']+)', html, flags=re.I))
    assert "/scan" in anchors
    assert "/instalar" in anchors
    assert "/login" in anchors
    assert not anchors & {
        "/", "/perfil", "/logout", "/herramientas", "/maquinaria",
        "/materiales", "/movimientos", "/almacenes", "/avisos",
        "/informes", "/configuracion",
    }
    assert "Mi perfil" not in html
    assert "Cerrar sesión" not in html
    assert "Dashboard" not in html


def test_scan_buscar_publico_no_expone_datos_operativos(client, db):
    tool = Herramienta(
        codigo="QR-PRIVADO-001", nombre="Nombre operativo secreto",
        marca="Marca privada", estado="entregada", activa=True,
    )
    db.add(tool)
    db.commit()
    response = client.get("/scan/buscar", params={"codigo": tool.codigo})
    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "found": True,
        "public": True,
        "message": "Código reconocido. Inicia sesión para consultar sus datos.",
        "requires_login": True,
        "login_url": "/login",
    }
    raw = json.dumps(payload, ensure_ascii=False)
    for secret in (tool.nombre, tool.marca, tool.estado, str(tool.id), tool.codigo):
        assert secret not in raw


def _write_legacy(db, obj, field: str, value: str):
    table = obj.__table__.name
    db.execute(text(f'UPDATE "{table}" SET "{field}" = :value WHERE id = :id'), {
        "value": value, "id": obj.id,
    })
    db.commit()
    db.expire_all()


def test_resolvedor_cubre_todas_las_columnas_historicas_no_normalizadas(db):
    warehouse = Almacen(codigo="ALM-BASE-LEGACY", nombre="Nave legacy", activo=True)
    db.add(warehouse)
    db.flush()

    cases = []
    for index, field in enumerate(("codigo", "num_serie"), 1):
        obj = Herramienta(
            codigo=f"HER-BASE-{index}", nombre=f"Herramienta legacy {index}",
            num_serie=f"HER-SERIE-{index}", estado="disponible", activa=True,
        )
        db.add(obj); db.flush(); cases.append(("herramienta", obj, field))

    for index, field in enumerate(("codigo_barras", "codigo_interno", "matricula", "num_serie"), 1):
        obj = Maquinaria(
            codigo_barras=f"MAQ-BAR-{index}", codigo_interno=f"MAQ-INT-{index}",
            matricula=f"MAQ-MAT-{index}", num_serie=f"MAQ-SER-{index}",
            nombre=f"Máquina legacy {index}", estado="disponible", activa=True,
        )
        db.add(obj); db.flush(); cases.append(("maquinaria", obj, field))

    for index, field in enumerate(("codigo", "matricula"), 1):
        obj = Vehiculo(
            codigo=f"VEH-BASE-{index}", matricula=f"VLEG{index:04d}",
            marca="MRD", estado="activo", activo=True,
        )
        db.add(obj); db.flush(); cases.append(("vehiculo", obj, field))

    for index, field in enumerate(("codigo_qr", "referencia_interna", "codigo_fabricacion"), 1):
        obj = EPIIndividual(
            tipo="ARNES", codigo_fabricacion=f"EPI-FAB-{index}",
            referencia_interna=f"EPI-REF-{index}", codigo_qr=f"EPI-QR-{index}",
            estado="activo",
        )
        db.add(obj); db.flush(); cases.append(("epi_individual", obj, field))

    stock = StockEPI(
        nombre="ROPA LEGACY", categoria="ropa", talla="L", cantidad=4,
        codigo="SEPI-BASE-LEGACY",
    )
    material = Material(
        codigo="MAT-BASE-LEGACY", nombre="Consumible legacy",
        stock_actual=5, activo=True,
    )
    db.add_all([stock, material]); db.flush()
    cases.extend((("stock_epi", stock, "codigo"), ("material", material, "codigo")))

    second_warehouse = Almacen(codigo="ALM-SECOND-LEGACY", nombre="Nave segunda", activo=True)
    db.add(second_warehouse); db.flush()
    location = Ubicacion(
        almacen_id=warehouse.id, nombre="Rack legacy",
        codigo="UBI-BASE-LEGACY", activo=True,
    )
    db.add(location); db.flush()
    cases.extend((("almacen", second_warehouse, "codigo"), ("ubicacion", location, "codigo")))

    catalog = CatalogoEPI(nombre="VARIANTE LEGACY", categoria="ropa", activo=True)
    db.add(catalog); db.flush()
    for index, field in enumerate(("codigo_qr", "referencia_interna", "referencia_proveedor"), 1):
        identifier = IdentificadorGlobal(
            referencia_interna=f"ID-REF-{index}", codigo_qr=f"ID-QR-{index}",
            propietario_tipo="variante", propietario_clave=f"legacy:{index}",
        )
        db.add(identifier); db.flush()
        variant = VarianteEPI(
            catalogo_epi_id=catalog.id, modelo=f"M{index}", color="", talla="L",
            identificador_id=identifier.id, referencia_interna=f"VAR-REF-{index}",
            codigo_qr=f"VAR-QR-{index}", referencia_proveedor=f"VAR-PROV-{index}",
            activo=True,
        )
        db.add(variant); db.flush()
        db.add(ExistenciaVariante(
            variante_id=variant.id, almacen_id=warehouse.id,
            ubicacion_clave=0, cantidad=3,
        ))
        db.flush()
        cases.append(("variante", variant, field))

    db.commit()
    for index, (expected_type, obj, field) in enumerate(cases, 1):
        legacy = f"  legacy-{index:02d}-{field.lower()}  "
        _write_legacy(db, obj, field, legacy)
        resolved = resolve_counter_item(db, legacy.strip().upper())
        assert resolved["tipo"] == expected_type
        if expected_type == "variante":
            assert resolved["id"] > 0
        else:
            assert resolved["id"] == obj.id


def test_pistola_bluetooth_tablet_resuelve_todas_las_referencias_de_maquinaria(db):
    machine = Maquinaria(
        codigo_barras="BAR-ST300-001", codigo_interno="MAQ-ST300-001",
        matricula="ST300MRD", num_serie="SERIE-ST300-001",
        nombre="ALIMAK ST300", estado="disponible", activa=True,
    )
    db.add(machine)
    db.commit()
    official_qr, _ = _get_qr_code_for("maquinaria", machine.id, db)
    inputs = (
        machine.codigo_barras,
        machine.codigo_interno,
        machine.matricula,
        machine.num_serie,
        official_qr,
        f"]Q3https://app.iasmrd.com/qr/maquinaria/{machine.id}\r\n",
        f"https://app.iasmrd.com/maquinaria/{machine.id}",
    )
    for scanned in inputs:
        resolved = resolve_counter_item(db, scanned)
        assert resolved["tipo"] == "maquinaria"
        assert resolved["id"] == machine.id


@pytest.mark.parametrize(
    "role,allowed_mode,forbidden_mode,forbidden_action",
    [
        ("solo_entregar_234", "salida", "entrada", "entrada"),
        ("solo_devolver_234", "entrada", "salida", "salida"),
    ],
)
def test_mostrador_oculta_accion_no_permitida_y_servidor_la_rechaza(
    db, monkeypatch, role, allowed_mode, forbidden_mode, forbidden_action,
):
    permissions = ["ver", "entregar"] if allowed_mode == "salida" else ["ver", "devolver"]
    monkeypatch.setitem(PERMISOS_ROL, role, permissions)
    user = Usuario(
        username=role, password_hash="x", nombre=role,
        rol=role, activo=True,
    )
    db.add(user)
    db.commit()

    response = mostrador_unico_panel(_request("/mostrador"), user, db)
    html = response.body.decode("utf-8")
    assert f'data-mode="{allowed_mode}"' in html
    assert f'data-mode="{forbidden_mode}"' not in html
    assert f"let mode=\"{allowed_mode}\"" in html

    with pytest.raises(CounterError) as exc:
        operate_counter(
            db, user, operation_id=f"forbidden-{role}", action=forbidden_action,
            lines=[], worker_id=None, work_id=None, warehouse_id=None,
        )
    assert exc.value.status_code == 403
