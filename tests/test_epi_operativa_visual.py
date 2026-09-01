from pathlib import Path
import asyncio
import re
import urllib.parse

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from main import (
    _normalizar_tallas_elegidas,
    _reclasificar_chalecos_como_ropa,
    _restart_exec_target,
    epis_catalogo_nuevo,
    epis_catalogo_editar,
    epis_catalogo_eliminar,
    epis_stock_entrada,
    epis_stock_etiquetas_lote,
    epis_stock_nueva_talla,
    epis_stock_salida,
)
from models import Base, CatalogoEPI, MovimientoStock, StockEPI, Usuario
from label_printer import (
    LABEL_HEIGHT_MM, LABEL_WIDTH_MM, ZEBRA_HEIGHT_DOTS, ZEBRA_WIDTH_DOTS,
    generar_pdf_etiquetas, generar_zpl_herramienta,
)


def _request():
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


def _form_request(values):
    body = urllib.parse.urlencode(values).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http", "method": "POST", "path": "/epis/catalogo/1/editar",
        "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
    }, receive)


def _session(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'epi-operativa.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _user(db, rol="encargado_patio"):
    user = Usuario(
        username=f"usuario-{rol}", password_hash="x", nombre="Operador",
        rol=rol, activo=True, must_change_password=False,
    )
    db.add(user)
    db.commit()
    return user


def test_entrada_nueva_crea_codigo_qr_y_movimiento_atomico(tmp_path):
    engine, Session = _session(tmp_path)
    with Session() as db:
        user = _user(db)
        response = epis_stock_entrada(
            _request(), user, db, nombre="GUANTE QR", cantidad=12,
            talla="", tipo_seguimiento="generico",
        )
        stock = db.query(StockEPI).filter_by(nombre="GUANTE QR").one()
        assert response.status_code == 303
        assert stock.codigo == f"SEPI-{stock.id:04d}"
        assert stock.cantidad == 12
        assert db.query(MovimientoStock).filter_by(stock_epi_id=stock.id).count() == 1
    engine.dispose()


def test_salida_insuficiente_no_descuenta_ni_crea_movimiento(tmp_path):
    engine, Session = _session(tmp_path)
    with Session() as db:
        user = _user(db)
        stock = StockEPI(
            nombre="BOTA SEGURA", categoria="ropa", talla="42",
            cantidad=2, stock_minimo=1, codigo="SEPI-TEST-42",
        )
        db.add(stock)
        db.commit()
        with pytest.raises(HTTPException) as exc:
            epis_stock_salida(
                _request(), user, db, nombre=stock.nombre, cantidad=3, talla="42",
            )
        assert exc.value.status_code == 409
        db.expire_all()
        assert db.get(StockEPI, stock.id).cantidad == 2
        assert db.query(MovimientoStock).count() == 0
    engine.dispose()


def test_nueva_talla_del_encargado_nace_con_codigo_unico(tmp_path):
    engine, Session = _session(tmp_path)
    with Session() as db:
        user = _user(db)
        response = epis_stock_nueva_talla(
            _request(), user, db, nombre="PANTALÓN", talla="L",
        )
        stock = db.query(StockEPI).filter_by(nombre="PANTALÓN", talla="L").one()
        assert response.status_code == 303
        assert stock.codigo == f"SEPI-{stock.id:04d}"
    engine.dispose()


def test_se_puede_ampliar_un_pantalon_que_ya_tiene_tallas(tmp_path):
    engine, Session = _session(tmp_path)
    with Session() as db:
        user = _user(db)
        db.add(StockEPI(
            nombre="PANTALON", categoria="ropa", talla="50",
            cantidad=2, stock_minimo=3, codigo="SEPI-PANT-50",
        ))
        db.commit()
        response = epis_stock_nueva_talla(
            _request(), user, db, nombre="PANTALON", talla="52",
        )
        nueva = db.query(StockEPI).filter_by(nombre="PANTALON", talla="52").one()
        assert response.status_code == 303
        assert nueva.codigo == f"SEPI-{nueva.id:04d}"
        assert nueva.cantidad == 0
    engine.dispose()


def test_paquete_etiquetas_pdf_y_zebra_repite_copias(tmp_path):
    engine, Session = _session(tmp_path)
    with Session() as db:
        user = _user(db)
        stock = StockEPI(
            nombre="CHAQUETA", categoria="ropa", talla="XL", cantidad=8,
            stock_minimo=2, codigo="SEPI-CHAQ-XL",
        )
        db.add(stock)
        db.commit()
        pdf = epis_stock_etiquetas_lote(user, db, ids=str(stock.id), copias=2, formato="pdf")
        zpl = epis_stock_etiquetas_lote(user, db, ids=str(stock.id), copias=2, formato="zpl")
        assert pdf.media_type == "application/pdf"
        assert pdf.body.startswith(b"%PDF")
        assert zpl.body.count(b"^XA") == 2
        assert b"SEPI-CHAQ-XL" in zpl.body
    engine.dispose()


def test_etiquetas_salen_exactamente_a_105_por_55_mm():
    item = {"codigo": "SEPI-105X55", "nombre": "PANTALÓN 52", "marca": "MRD", "num_serie": ""}
    pdf = generar_pdf_etiquetas([item])
    media_box = re.search(
        rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", pdf,
    )
    assert media_box
    width_points, height_points = map(float, media_box.groups())
    assert abs(width_points - (LABEL_WIDTH_MM * 72 / 25.4)) < 0.1
    assert abs(height_points - (LABEL_HEIGHT_MM * 72 / 25.4)) < 0.1
    zpl = generar_zpl_herramienta(**item)
    assert f"^PW{ZEBRA_WIDTH_DOTS}" in zpl
    assert f"^LL{ZEBRA_HEIGHT_DOTS}" in zpl


def test_vistas_de_impresion_declaran_105_por_55_mm():
    root = Path(__file__).resolve().parents[1] / "templates"
    for filename in ("qr_imprimir.html", "etiqueta_imprimir.html", "maquinaria_etiqueta.html"):
        html = (root / filename).read_text(encoding="utf-8")
        assert "size:105mm55mm" in html.replace(" ", "")


def test_consulta_no_puede_imprimir_paquetes(tmp_path):
    engine, Session = _session(tmp_path)
    with Session() as db:
        user = _user(db, "consulta")
        with pytest.raises(HTTPException) as exc:
            epis_stock_etiquetas_lote(user, db, ids="1", copias=1, formato="pdf")
        assert exc.value.status_code == 403
    engine.dispose()


def test_pantallas_incluyen_alta_qr_operaciones_y_etiquetas_masivas():
    root = Path(__file__).resolve().parents[1]
    catalog = (root / "templates" / "epis_catalogo.html").read_text(encoding="utf-8")
    stock = (root / "templates" / "epis_stock.html").read_text(encoding="utf-8")
    config = (root / "templates" / "configuracion.html").read_text(encoding="utf-8")
    assert "Código y QR automáticos" in catalog
    assert "/epis/stock/entrada" in stock and "/epis/stock/salida" in stock
    assert "/epis/stock/etiquetas" in stock and "Zebra" in stock
    assert "Añadir tallas o medidas" in stock and "Ej. XS, 3XL, 40 o 52" in stock
    assert "/admin/recuperar-sistema" in config


def test_mostrador_ofrece_camara_en_movil_y_albaran_automatico():
    root = Path(__file__).resolve().parents[1]
    counter = (root / "templates" / "mostrador.html").read_text(encoding="utf-8")
    delivery = (root / "templates" / "movimiento_entregar.html").read_text(encoding="utf-8")
    assert "mobileCamera" in counter
    assert "navigator.mediaDevices?.getUserMedia" in counter
    assert "decodeFromStream" in counter
    assert "albaran_url" in counter and "albaran_url" in delivery


def test_pwa_se_sirve_desde_raiz_y_puede_controlar_toda_la_app(client):
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert response.headers["service-worker-allowed"] == "/"
    assert "mrd-static-v2.7.6" in response.text


def test_listado_herramientas_usa_miniaturas_y_carga_diferida():
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "herramientas.html").read_text(encoding="utf-8")
    assert "/media/herramientas/thumb/{{ h.foto }}" in template
    assert 'loading="lazy"' in template
    assert 'decoding="async"' in template


def test_tallas_manual_normaliza_y_respeta_exactamente_la_eleccion():
    assert _normalizar_tallas_elegidas(" s, M; l\nM, 3xl ") == ("S", "M", "L", "3XL")


def test_alta_ropa_crea_solo_tallas_elegidas_y_qr_unico(tmp_path):
    engine, Session = _session(tmp_path)
    with Session() as db:
        user = _user(db)
        response = asyncio.run(epis_catalogo_nuevo(
            _form_request({
                "nombre": "CHALECO REFLECTANTE",
                "categoria": "ropa",
                "cantidad_kit": "1",
                "tallas": "S, L, 4XL",
            }),
            user, db,
        ))
        assert response.headers["location"].endswith("ok=creado")
        rows = db.query(StockEPI).filter(StockEPI.nombre == "CHALECO REFLECTANTE").all()
        assert {row.talla for row in rows} == {"S", "L", "4XL"}
        assert len({row.codigo for row in rows}) == 3
        assert all(row.codigo for row in rows)
    engine.dispose()


def test_reclasificar_chaleco_no_inventa_tallas_ni_modifica_stock_o_qr(tmp_path):
    engine, Session = _session(tmp_path)
    with Session() as db:
        item = CatalogoEPI(nombre="CHALECO AMARILLO", categoria="epi", cantidad_kit=1)
        stock = StockEPI(
            nombre=item.nombre, categoria="epi", talla=None, cantidad=169,
            stock_minimo=20, codigo="SEPI-0002",
        )
        db.add_all([item, stock])
        db.commit()
        assert _reclasificar_chalecos_como_ropa(db) == 2
        db.flush()
        assert item.categoria == stock.categoria == "ropa"
        assert (stock.talla, stock.cantidad, stock.codigo) == (None, 169, "SEPI-0002")
        assert db.query(StockEPI).count() == 1
    engine.dispose()


def test_reinicio_windows_reutiliza_el_lanzador_uvicorn(tmp_path):
    launcher = tmp_path / "uvicorn.exe"
    launcher.write_bytes(b"launcher de prueba")
    executable, args = _restart_exec_target(
        [str(launcher), "main:app", "--port", "8000"],
        r"C:\Python\python.exe", "nt",
    )
    assert executable == str(launcher.resolve())
    assert args == [str(launcher.resolve()), "main:app", "--port", "8000"]


def test_renombrar_catalogo_a_nombre_existente_avisa_sin_error_500(tmp_path):
    engine, Session = _session(tmp_path)
    with Session() as db:
        user = _user(db)
        old = CatalogoEPI(nombre="CHALECO AMARILLO", categoria="epi", cantidad_kit=1)
        existing = CatalogoEPI(nombre="CHALECO", categoria="epi", cantidad_kit=1)
        db.add_all([old, existing])
        db.commit()
        response = asyncio.run(epis_catalogo_editar(
            old.id,
            _form_request({"nombre": "CHALECO", "categoria": "epi", "cantidad_kit": "1"}),
            user, db,
        ))
        assert response.status_code == 303
        assert response.headers["location"].endswith("err=nombre_duplicado")
        db.expire_all()
        assert db.get(CatalogoEPI, old.id).nombre == "CHALECO AMARILLO"
    engine.dispose()


def test_renombrar_y_cambiar_a_ropa_actualiza_stock_sin_perder_qr(tmp_path):
    engine, Session = _session(tmp_path)
    with Session() as db:
        user = _user(db)
        item = CatalogoEPI(nombre="GORRA ANTIGUA", categoria="epi", cantidad_kit=1)
        stock = StockEPI(
            nombre="GORRA ANTIGUA", categoria="epi", talla=None, cantidad=14,
            stock_minimo=2, codigo="SEPI-GORRA-001",
        )
        db.add_all([item, stock])
        db.commit()
        response = asyncio.run(epis_catalogo_editar(
            item.id,
            _form_request({"nombre": "GORRA", "categoria": "ropa", "cantidad_kit": "2"}),
            user, db,
        ))
        assert response.headers["location"].endswith("ok=editado")
        db.expire_all()
        assert db.get(CatalogoEPI, item.id).categoria == "ropa"
        updated = db.get(StockEPI, stock.id)
        assert (updated.nombre, updated.categoria, updated.cantidad, updated.codigo) == (
            "GORRA", "ropa", 14, "SEPI-GORRA-001",
        )
    engine.dispose()


def test_admin_elimina_error_sin_stock_ni_historial(tmp_path):
    engine, Session = _session(tmp_path)
    with Session() as db:
        admin = _user(db, "admin")
        item = CatalogoEPI(nombre="CAMISETA CREADA POR ERROR", categoria="ropa", cantidad_kit=1)
        stock = StockEPI(nombre=item.nombre, categoria="ropa", talla="M", cantidad=0, codigo="SEPI-ERROR-M")
        db.add_all([item, stock])
        db.commit()
        response = epis_catalogo_eliminar(item.id, _request(), admin, db)
        assert response.headers["location"].endswith("ok=eliminado")
        assert db.get(CatalogoEPI, item.id) is None
        assert db.get(StockEPI, stock.id) is None
    engine.dispose()


def test_catalogo_con_existencias_se_oculta_sin_borrar_historial(tmp_path):
    engine, Session = _session(tmp_path)
    with Session() as db:
        admin = _user(db, "admin")
        item = CatalogoEPI(nombre="CAMISETA EN USO", categoria="ropa", cantidad_kit=1, activo=True)
        stock = StockEPI(nombre=item.nombre, categoria="ropa", talla="L", cantidad=4, codigo="SEPI-USO-L")
        db.add_all([item, stock])
        db.commit()
        response = epis_catalogo_eliminar(item.id, _request(), admin, db)
        assert response.headers["location"].endswith("ok=desactivado")
        assert db.get(CatalogoEPI, item.id).activo is False
        assert db.get(StockEPI, stock.id).cantidad == 4
    engine.dispose()
