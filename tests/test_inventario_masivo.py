import threading
from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from auth import PERMISOS_ROL, ROLES_NOMBRE
from generador_codigos import reservar_identificadores
from models import (
    ActivoInventarioEscaneado, Almacen, Base, CatalogoEPI, ExistenciaVariante, Herramienta, IdentificadorGlobal,
    AjusteInventario, EventoOperacion, IntentoConteo, LineaInventario,
    DotacionTrabajador, EPIIndividual, EntregaEPI, LineaDotacion,
    LogImpresionEtiqueta, LoteVariante, Maquinaria, MovimientoStock, ReinicioInventarioRopa, SesionInventario,
    StockEPI, Trabajador, Usuario, VarianteEPI, Vehiculo,
)
from stock_service import (
    StockError, move_stock_epi, move_variante, start_stock_transaction,
)
import inventario_service
from inventario_service import (
    InventoryError, approve_count, close_inventory_session, open_inventory_session,
    register_count,
)
from dotacion_service import (
    RESET_PHRASE, clothing_reset_preview, confirm_dotation,
    create_pending_dotation, execute_clothing_reset, validate_exact_harnesses,
)
import config
from etiquetas_service import LABEL_SIZES, build_zpl, send_label
from main import (
    EscaneoActivoInventarioRequest, EtiquetaRequest, ResetRopaRequest, SesionEditarRequest, VarianteEditarRequest,
    VarianteNuevaRequest, _inventory_line_view, ficha_publica_qr, inventario_sesion_editar,
    inventario_escanear_activo, inventario_sesion_eliminar,
)


def _engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'inventario-v2.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    return engine


def test_rol_encargado_patio_tiene_solo_permisos_operativos():
    permissions = set(PERMISOS_ROL["encargado_patio"])
    assert ROLES_NOMBRE["encargado_patio"] == "Encargado de Patio"
    assert {"ver", "inventario", "stock_operar", "entregar", "devolver", "etiquetas"} <= permissions
    assert not {"usuarios", "config", "backup", "borrar"} & permissions
    assert set(PERMISOS_ROL["consulta"]) == {"ver"}
    assert {"etiquetas", "inventario", "stock_operar"} <= set(PERMISOS_ROL["admin"])


def test_referencias_y_qr_son_globalmente_unicos_bajo_concurrencia(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = threading.Barrier(8)
    values = []
    lock = threading.Lock()

    def worker(index):
        with Session() as db:
            barrier.wait()
            reserved = reservar_identificadores(
                db, prefijo="EPI", propietario_tipo="variante_epi",
                propietario_clave=f"variant-reservation-{index}", creado_por_id=None,
            )
            db.commit()
            result = (reserved.referencia_interna, reserved.codigo_qr)
        with lock:
            values.append(result)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert len(values) == 8
    assert len({item[0] for item in values}) == 8
    assert len({item[1] for item in values}) == 8
    with Session() as db:
        assert db.query(IdentificadorGlobal).count() == 8
    engine.dispose()


def _seed_stock(Session):
    with Session.begin() as db:
        user = Usuario(
            username="inventory-admin", password_hash="test", nombre="Admin",
            rol="admin", activo=True, must_change_password=False,
        )
        catalog = CatalogoEPI(nombre="PANTALON TEST", categoria="ropa", cantidad_kit=1)
        warehouse = Almacen(nombre="Almacén test", activo=True)
        db.add_all([user, catalog, warehouse])
        db.flush()
        identifiers = reservar_identificadores(
            db, prefijo="EPI", propietario_tipo="variante_epi",
            propietario_clave="seed-variant", creado_por_id=user.id,
        )
        variant = VarianteEPI(
            catalogo_epi_id=catalog.id, modelo="Cargo", color="Azul", talla="XL",
            identificador_id=identifiers.id,
            referencia_interna=identifiers.referencia_interna,
            codigo_qr=identifiers.codigo_qr, creado_por_id=user.id,
        )
        db.add(variant)
        db.flush()
        existence = ExistenciaVariante(
            variante_id=variant.id, almacen_id=warehouse.id,
            ubicacion_id=None, ubicacion_clave=0, cantidad=0, version=0,
        )
        stock = StockEPI(
            nombre="GUANTES TEST", categoria="epi", talla=None,
            cantidad=10, stock_minimo=1,
        )
        db.add_all([existence, stock])
        db.flush()
        return user.id, existence.id, stock.id


def test_dos_lotes_de_la_misma_variante_coexisten_y_suman_existencia(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    user_id, existence_id, _stock_id = _seed_stock(Session)
    with Session() as db:
        user = db.get(Usuario, user_id)
        start_stock_transaction(db)
        move_variante(
            db, user, existence_id, 5, tipo="entrada", event_id="lot-event-001",
            motivo="Entrada lote A", numero_lote="LOTE-A",
        )
        move_variante(
            db, user, existence_id, 7, tipo="entrada", event_id="lot-event-002",
            motivo="Entrada lote B", numero_lote="LOTE-B",
        )
        db.commit()
    with Session() as db:
        assert db.get(ExistenciaVariante, existence_id).cantidad == 12
        assert sorted(row.numero_lote for row in db.query(LoteVariante).all()) == ["LOTE-A", "LOTE-B"]
        assert db.query(MovimientoStock).count() == 2
        assert not hasattr(VarianteEPI, "cantidad")
    engine.dispose()


def test_movimiento_stock_es_idempotente_append_only_y_rechaza_otro_contenido(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    user_id, _existence_id, stock_id = _seed_stock(Session)
    with Session() as db:
        user = db.get(Usuario, user_id)
        start_stock_transaction(db)
        first = move_stock_epi(
            db, user, stock_id, -2, tipo="entrega", event_id="stock-event-001",
            motivo="Entrega de prueba",
        )
        db.commit()
    with Session() as db:
        user = db.get(Usuario, user_id)
        start_stock_transaction(db)
        repeated = move_stock_epi(
            db, user, stock_id, -2, tipo="entrega", event_id="stock-event-001",
            motivo="Entrega de prueba",
        )
        db.commit()
        assert repeated.reused is True
        assert repeated.movimiento_id == first.movimiento_id
    with Session() as db:
        user = db.get(Usuario, user_id)
        start_stock_transaction(db)
        try:
            move_stock_epi(
                db, user, stock_id, -1, tipo="entrega", event_id="stock-event-001",
                motivo="Contenido distinto",
            )
            assert False, "debe rechazar event_id reutilizado"
        except StockError as exc:
            assert exc.status_code == 409
            db.rollback()
    with Session() as db:
        movement = db.query(MovimientoStock).one()
        movement.motivo = "No permitido"
        try:
            db.commit()
            assert False, "el movimiento no debe ser editable"
        except ValueError:
            db.rollback()
        assert db.get(StockEPI, stock_id).cantidad == 8
        assert db.query(MovimientoStock).count() == 1
    engine.dispose()


def test_error_en_segundo_movimiento_revierte_el_lote_completo(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    user_id, _existence_id, stock_id = _seed_stock(Session)
    with Session() as db:
        user = db.get(Usuario, user_id)
        start_stock_transaction(db)
        try:
            move_stock_epi(
                db, user, stock_id, -3, tipo="entrega", event_id="rollback-stock-1",
                motivo="Primera línea",
            )
            move_stock_epi(
                db, user, stock_id, -99, tipo="entrega", event_id="rollback-stock-2",
                motivo="Segunda línea inválida",
            )
            db.commit()
            assert False, "debe fallar por stock insuficiente"
        except StockError:
            db.rollback()
    with Session() as db:
        assert db.get(StockEPI, stock_id).cantidad == 10
        assert db.query(MovimientoStock).count() == 0
    engine.dispose()


def _seed_session(Session, *, state="abierta", final=None):
    with Session.begin() as db:
        admin = Usuario(
            username=f"admin-{state}-{final}", password_hash="test", nombre="Admin",
            rol="admin", activo=True, must_change_password=False,
        )
        patio = Usuario(
            username=f"patio-{state}-{final}", password_hash="test", nombre="Patio",
            rol="encargado_patio", activo=True, must_change_password=False,
        )
        viewer = Usuario(
            username=f"viewer-{state}-{final}", password_hash="test", nombre="Consulta",
            rol="consulta", activo=True, must_change_password=False,
        )
        stock = StockEPI(
            nombre=f"ROPA-{state}-{final}", categoria="ropa", talla="M",
            cantidad=10, stock_minimo=1,
        )
        db.add_all([admin, patio, viewer, stock])
        db.flush()
        session = SesionInventario(
            nombre="Sesión test", scope="total", tipo_articulo="epi_ropa",
            estado=state, creado_por_id=patio.id,
        )
        db.add(session)
        db.flush()
        line = LineaInventario(
            sesion_id=session.id, stock_epi_id=stock.id,
            cantidad_esperada=10, cantidad_final=final,
            estado="aprobado" if final is not None else "pendiente",
            aprobado_por_id=admin.id if final is not None else None,
        )
        db.add(line)
        db.flush()
        return admin.id, patio.id, viewer.id, stock.id, session.id, line.id


def test_recuentos_son_append_only_idempotentes_y_detectan_conflicto(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    _admin_id, patio_id, viewer_id, _stock_id, session_id, line_id = _seed_session(Session)
    with Session() as db:
        patio = db.get(Usuario, patio_id)
        start_stock_transaction(db)
        first = register_count(
            db, patio, session_id=session_id, line_id=line_id,
            amount=5, count_number=1, scan_event_id="count-event-001",
        )
        db.commit()
        assert first["resultado"] == "ok"
    with Session() as db:
        patio = db.get(Usuario, patio_id)
        start_stock_transaction(db)
        repeated = register_count(
            db, patio, session_id=session_id, line_id=line_id,
            amount=5, count_number=1, scan_event_id="count-event-001",
        )
        db.commit()
        assert repeated["resultado"] == "ya_contado"
    with Session() as db:
        patio = db.get(Usuario, patio_id)
        start_stock_transaction(db)
        conflict = register_count(
            db, patio, session_id=session_id, line_id=line_id,
            amount=6, count_number=1, scan_event_id="count-event-002",
        )
        db.commit()
        assert conflict["resultado"] == "conflicto"
    with Session() as db:
        assert db.query(IntentoConteo).count() == 2
        assert db.get(LineaInventario, line_id).estado == "conflicto"
        viewer = db.get(Usuario, viewer_id)
        with pytest.raises(InventoryError) as exc:
            register_count(
                db, viewer, session_id=session_id, line_id=line_id,
                amount=1, count_number=1, scan_event_id="viewer-count-001",
            )
        assert exc.value.status_code == 403
    engine.dispose()


def test_cierre_es_idempotente_y_evento_distinto_en_sesion_cerrada_conflicta(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    admin_id, _patio_id, _viewer_id, stock_id, session_id, _line_id = _seed_session(
        Session, state="pendiente_cierre", final=8,
    )
    with Session() as db:
        result = close_inventory_session(
            db, db.get(Usuario, admin_id), session_id=session_id,
            cierre_event_id="close-event-001",
        )
        db.commit()
        assert result == {"resultado": "ok", "ajustes": 1}
    with Session() as db:
        repeated = close_inventory_session(
            db, db.get(Usuario, admin_id), session_id=session_id,
            cierre_event_id="close-event-001",
        )
        assert repeated == {"resultado": "ya_cerrada", "ajustes": 1}
        with pytest.raises(InventoryError) as exc:
            close_inventory_session(
                db, db.get(Usuario, admin_id), session_id=session_id,
                cierre_event_id="close-event-other",
            )
        assert exc.value.status_code == 409
    with Session() as db:
        assert db.get(StockEPI, stock_id).cantidad == 8
        assert db.query(AjusteInventario).count() == 1
        assert db.query(MovimientoStock).filter_by(tipo="cierre_inventario").count() == 1
    engine.dispose()


def test_movimiento_posterior_a_apertura_se_incluye_en_cierre(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    admin_id, _patio_id, _viewer_id, stock_id, session_id, _line_id = _seed_session(
        Session, state="pendiente_cierre", final=11,
    )
    with Session() as db:
        admin = db.get(Usuario, admin_id)
        start_stock_transaction(db)
        move_stock_epi(
            db, admin, stock_id, 2, tipo="entrada", event_id="during-session-001",
            motivo="Entrada durante sesión",
        )
        db.commit()
    with Session() as db:
        result = close_inventory_session(
            db, db.get(Usuario, admin_id), session_id=session_id,
            cierre_event_id="close-after-move-001",
        )
        db.commit()
        assert result["resultado"] == "ok"
    with Session() as db:
        adjustment = db.query(AjusteInventario).one()
        assert adjustment.movimientos_periodo == 2
        assert adjustment.cantidad_esperada_cierre == 12
        assert adjustment.diferencia == -1
        assert db.get(StockEPI, stock_id).cantidad == 11
    engine.dispose()


def test_error_intermedio_del_cierre_hace_rollback_y_permite_reintento(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    admin_id, _patio_id, _viewer_id, stock_id, session_id, _line_id = _seed_session(
        Session, state="pendiente_cierre", final=8,
    )

    def fail_adjustment(*_args, **_kwargs):
        raise RuntimeError("fallo crítico de prueba")

    monkeypatch.setattr(inventario_service, "_persist_adjustment", fail_adjustment)
    with Session() as db:
        with pytest.raises(RuntimeError):
            close_inventory_session(
                db, db.get(Usuario, admin_id), session_id=session_id,
                cierre_event_id="retry-close-001",
            )
        db.rollback()
    with Session() as db:
        assert db.get(StockEPI, stock_id).cantidad == 10
        assert db.get(SesionInventario, session_id).estado == "pendiente_cierre"
        assert db.query(AjusteInventario).count() == 0
        assert db.query(EventoOperacion).filter_by(event_id="retry-close-001").count() == 0
        assert db.query(MovimientoStock).count() == 0
    engine.dispose()


def test_esquemas_api_rechazan_codigos_y_cantidad_en_put():
    with pytest.raises(ValidationError):
        VarianteNuevaRequest.model_validate({
            "catalogo_epi_id": 1, "almacen_id": 1,
            "referencia_interna": "FALSIFICADA",
        })
    with pytest.raises(ValidationError):
        VarianteEditarRequest.model_validate({"cantidad": 99})
    with pytest.raises(ValidationError):
        VarianteEditarRequest.model_validate({"codigo_qr": "FALSIFICADO"})


def test_doble_cierre_simultaneo_crea_un_solo_conjunto_de_ajustes(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    admin_id, _patio_id, _viewer_id, _stock_id, session_id, _line_id = _seed_session(
        Session, state="pendiente_cierre", final=8,
    )
    barrier = threading.Barrier(2)
    results = []
    errors = []
    guard = threading.Lock()

    def worker():
        try:
            with Session() as db:
                user = db.get(Usuario, admin_id)
                barrier.wait()
                result = close_inventory_session(
                    db, user, session_id=session_id,
                    cierre_event_id="concurrent-close-001",
                )
                db.commit()
            with guard:
                results.append(result["resultado"])
        except Exception as exc:
            with guard:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert errors == []
    assert sorted(results) == ["ok", "ya_cerrada"]
    with Session() as db:
        assert db.query(AjusteInventario).count() == 1
        assert db.query(MovimientoStock).filter_by(tipo="cierre_inventario").count() == 1
    engine.dispose()


def test_movimiento_concurrente_espera_a_que_termine_el_cierre(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    admin_id, _patio_id, _viewer_id, stock_id, session_id, _line_id = _seed_session(
        Session, state="pendiente_cierre", final=8,
    )
    close_locked = threading.Event()
    mover_ready = threading.Event()
    release_close = threading.Event()
    errors = []
    original_delta = inventario_service._movement_delta

    def paused_delta(db, line, cursor):
        close_locked.set()
        assert release_close.wait(timeout=10)
        return original_delta(db, line, cursor)

    monkeypatch.setattr(inventario_service, "_movement_delta", paused_delta)

    def closer():
        try:
            with Session() as db:
                result = close_inventory_session(
                    db, db.get(Usuario, admin_id), session_id=session_id,
                    cierre_event_id="locked-close-001",
                )
                db.commit()
                assert result["resultado"] == "ok"
        except Exception as exc:
            errors.append(exc)

    def mover():
        try:
            assert close_locked.wait(timeout=10)
            with Session() as db:
                user = db.get(Usuario, admin_id)
                mover_ready.set()
                start_stock_transaction(db)
                move_stock_epi(
                    db, user, stock_id, 1, tipo="entrada",
                    event_id="after-locked-close", motivo="Movimiento concurrente",
                )
                db.commit()
        except Exception as exc:
            errors.append(exc)

    close_thread = threading.Thread(target=closer)
    move_thread = threading.Thread(target=mover)
    close_thread.start()
    assert close_locked.wait(timeout=10)
    move_thread.start()
    assert mover_ready.wait(timeout=10)
    release_close.set()
    close_thread.join(timeout=20)
    move_thread.join(timeout=20)
    assert errors == []
    with Session() as db:
        assert db.get(StockEPI, stock_id).cantidad == 9
        movements = db.query(MovimientoStock).order_by(MovimientoStock.id).all()
        assert [row.tipo for row in movements] == ["cierre_inventario", "entrada"]
    engine.dispose()


def test_nuevo_trabajador_genera_dotacion_pendiente_sin_descontar_stock(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        admin = Usuario(username="dot-admin", password_hash="x", nombre="Admin", rol="admin", activo=True)
        shirt = CatalogoEPI(nombre="CAMISETA DOT", categoria="ropa", cantidad_kit=3, activo=True)
        boots = CatalogoEPI(nombre="BOTAS DOT", categoria="ropa", cantidad_kit=1, activo=True)
        stock_shirt = StockEPI(nombre=shirt.nombre, categoria="ropa", talla="L", cantidad=9)
        stock_boots = StockEPI(nombre=boots.nombre, categoria="ropa", talla="43", cantidad=4)
        existing = Trabajador(nombre="Existente", activo=True)
        db.add_all([admin, shirt, boots, stock_shirt, stock_boots, existing])
        db.flush()
        assert db.query(DotacionTrabajador).filter_by(trabajador_id=existing.id).count() == 0
        worker = Trabajador(nombre="Nuevo", activo=True, talla_ropa="L", talla_calzado="43")
        db.add(worker)
        db.flush()
        dotation = create_pending_dotation(db, worker, admin)
        assert dotation.estado == "pendiente"
        assert [(line.nombre, line.talla, line.cantidad) for line in dotation.lineas] == [
            ("CAMISETA DOT", "L", 3), ("BOTAS DOT", "43", 1),
        ]
        assert (stock_shirt.cantidad, stock_boots.cantidad) == (9, 4)
    engine.dispose()


def test_confirmar_dotacion_descuenta_una_vez_y_registra_entrega(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        admin = Usuario(username="confirm-admin", password_hash="x", nombre="Admin", rol="admin", activo=True)
        catalog = CatalogoEPI(nombre="PANTALON DOT", categoria="ropa", cantidad_kit=2, activo=True)
        stock = StockEPI(nombre=catalog.nombre, categoria="ropa", talla="M", cantidad=5)
        worker = Trabajador(nombre="Operario", activo=True, talla_ropa="M")
        db.add_all([admin, catalog, stock, worker])
        db.flush()
        dotation = create_pending_dotation(db, worker, admin)
        dotation_id, admin_id, stock_id = dotation.id, admin.id, stock.id
    with Session() as db:
        result = confirm_dotation(db, db.get(Usuario, admin_id), dotation_id=dotation_id, event_id="confirm-dot-0001")
        db.commit()
        assert result["resultado"] == "ok"
    with Session() as db:
        result = confirm_dotation(db, db.get(Usuario, admin_id), dotation_id=dotation_id, event_id="confirm-dot-0001")
        db.commit()
        assert result["resultado"] == "ya_entregada"
        assert db.get(StockEPI, stock_id).cantidad == 3
        assert db.query(EntregaEPI).count() == 1
        assert db.query(MovimientoStock).filter_by(tipo="entrega_dotacion").count() == 1
    engine.dispose()


def test_error_de_dotacion_revierte_todos_los_items(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        admin = Usuario(username="rollback-dot", password_hash="x", nombre="Admin", rol="admin", activo=True)
        one = CatalogoEPI(nombre="UNO DOT", categoria="epi", cantidad_kit=1, activo=True)
        two = CatalogoEPI(nombre="DOS DOT", categoria="epi", cantidad_kit=1, activo=True)
        stock = StockEPI(nombre=one.nombre, categoria="epi", talla=None, cantidad=2)
        worker = Trabajador(nombre="Operario", activo=True)
        db.add_all([admin, one, two, stock, worker])
        db.flush()
        dotation = create_pending_dotation(db, worker, admin)
        ids = admin.id, dotation.id, stock.id
    with Session() as db:
        with pytest.raises(InventoryError):
            confirm_dotation(db, db.get(Usuario, ids[0]), dotation_id=ids[1], event_id="rollback-dot-001")
        db.rollback()
    with Session() as db:
        assert db.get(StockEPI, ids[2]).cantidad == 2
        assert db.get(DotacionTrabajador, ids[1]).estado == "pendiente"
        assert db.query(EntregaEPI).count() == 0
        assert db.query(MovimientoStock).count() == 0
    engine.dispose()


def test_reset_ropa_desactivado_rechaza_autorizacion_inyectada(tmp_path, monkeypatch):
    with pytest.raises(ValidationError):
        ResetRopaRequest(
            event_id="reset-clothes-01", frase=RESET_PHRASE, preview_hash="a" * 64,
            usuario_id=999,
        )
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine)
    with Session.begin() as db:
        admin = Usuario(username="reset-off", password_hash="x", nombre="Admin", rol="admin", activo=True)
        db.add(admin)
        db.flush()
        admin_id = admin.id
    monkeypatch.setattr(config, "ENABLE_INVENTARIO_RESET", False)
    with Session() as db, pytest.raises(InventoryError) as error:
        execute_clothing_reset(
            db, db.get(Usuario, admin_id), event_id="reset-clothes-01",
            phrase=RESET_PHRASE, preview_hash=clothing_reset_preview(db)["preview_hash"],
            backup_creator=lambda: {"ok": True, "ruta": "temporal.db"},
        )
    assert error.value.status_code == 403
    engine.dispose()


def test_reset_autorizado_afecta_solo_ropa_y_exige_backup_verificado(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        admin = Usuario(username="reset-on", password_hash="x", nombre="Admin", rol="admin", activo=True)
        clothing = StockEPI(nombre="CHAQUETA RESET", categoria="ropa", talla="L", cantidad=4)
        safety = StockEPI(nombre="GUANTES RESET", categoria="epi", talla=None, cantidad=7)
        db.add_all([admin, clothing, safety])
        db.flush()
        ids = admin.id, clothing.id, safety.id
    monkeypatch.setattr(config, "ENABLE_INVENTARIO_RESET", True)
    with Session() as db:
        preview = clothing_reset_preview(db)
        with pytest.raises(InventoryError):
            execute_clothing_reset(
                db, db.get(Usuario, ids[0]), event_id="reset-clothes-bad",
                phrase=RESET_PHRASE, preview_hash=preview["preview_hash"],
                backup_creator=lambda: {"ok": False},
            )
        db.rollback()
    with Session() as db:
        result = execute_clothing_reset(
            db, db.get(Usuario, ids[0]), event_id="reset-clothes-ok",
            phrase=RESET_PHRASE, preview_hash=clothing_reset_preview(db)["preview_hash"],
            backup_creator=lambda: {"ok": True, "ruta": str(tmp_path / "verified-copy.db")},
        )
        db.commit()
        assert result["filas"] == 1
    with Session() as db:
        assert db.get(StockEPI, ids[1]).cantidad == 0
        assert db.get(StockEPI, ids[2]).cantidad == 7
        assert db.query(ReinicioInventarioRopa).count() == 1
    engine.dispose()


def test_inventario_epi_exige_exactamente_los_dos_arneses_configurados(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        operator = Usuario(username="harness-admin", password_hash="x", nombre="Admin", rol="admin", activo=True)
        db.add_all([
            operator,
            EPIIndividual(tipo="ARNES", codigo_fabricacion="ARN-001", estado="activo", proxima_revision=date(2099, 1, 1)),
            EPIIndividual(tipo="ARNES", codigo_fabricacion="ARN-002", estado="activo", proxima_revision=date(2099, 1, 1)),
        ])
        db.flush()
        operator_id = operator.id
    monkeypatch.setattr(config, "ARNES_EXPECTED_CODES", ["ARN-001", "ARN-002"])
    with Session() as db:
        assert len(validate_exact_harnesses(db, config.ARNES_EXPECTED_CODES)) == 2
        session = open_inventory_session(
            db, db.get(Usuario, operator_id), nombre="Arneses", almacen_id=None,
            scope="total", tipo_articulo="epi_individual",
        )
        assert len(session.lineas) == 2
        db.rollback()
    monkeypatch.setattr(config, "ARNES_EXPECTED_CODES", ["ARN-001", "ARN-INEXISTENTE"])
    with Session() as db, pytest.raises(InventoryError):
        open_inventory_session(
            db, db.get(Usuario, operator_id), nombre="Arneses", almacen_id=None,
            scope="total", tipo_articulo="epi_individual",
        )
    engine.dispose()


@pytest.mark.parametrize("label_type,size", sorted(LABEL_SIZES.items()))
def test_zpl_zt231_usa_dimensiones_203_dpi_y_escapa_datos(label_type, size):
    assert size == (839, 440)
    zpl = build_zpl(
        tipo=label_type, referencia="MRD^~\\001",
        titulo="Artículo ^ peligroso", detalle="Detalle ~ prueba",
    )
    assert f"^PW{size[0]}" in zpl
    assert f"^LL{size[1]}" in zpl
    assert "MRD^~\\001" not in zpl
    assert zpl.startswith("^XA") and zpl.endswith("^XZ")


def test_impresora_solo_usa_configuracion_servidor_y_audita(tmp_path, monkeypatch):
    with pytest.raises(ValidationError):
        EtiquetaRequest(
            event_id="label-event-001", tipo="ropa", referencia="EPI-1",
            titulo="Pantalón", printer_host="equipo-del-navegador",
        )
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        operator = Usuario(username="label-user", password_hash="x", nombre="Patio", rol="encargado_patio", activo=True)
        catalog = CatalogoEPI(nombre="PANTALÓN ETIQUETA", categoria="ropa", cantidad_kit=1)
        db.add_all([operator, catalog])
        db.flush()
        identifier = reservar_identificadores(
            db, prefijo="EPI", propietario_tipo="variante_epi",
            propietario_clave="label-variant", creado_por_id=operator.id,
        )
        db.add(VarianteEPI(
            catalogo_epi_id=catalog.id, modelo="Cargo", color="Azul", talla="L",
            identificador_id=identifier.id,
            referencia_interna=identifier.referencia_interna,
            codigo_qr=identifier.codigo_qr, creado_por_id=operator.id,
        ))
        user_id, identifier_id = operator.id, identifier.id
    monkeypatch.setattr(config, "LABEL_PRINT_ENABLED", False)
    with Session() as db, pytest.raises(InventoryError):
        send_label(
            db, db.get(Usuario, user_id), event_id="label-event-off",
            identifier_id=identifier_id, copias=1,
            reimpresion=False,
        )

    sent = []
    class FakePrinter:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def sendall(self, payload): sent.append(payload)
    def fake_socket(address, timeout):
        assert address == ("10.20.30.40", 9100)
        assert timeout == 5
        return FakePrinter()
    monkeypatch.setattr(config, "LABEL_PRINT_ENABLED", True)
    monkeypatch.setattr(config, "LABEL_PRINTER_HOST", "10.20.30.40")
    monkeypatch.setattr(config, "LABEL_PRINTER_PORT", 9100)
    with Session() as db:
        result = send_label(
            db, db.get(Usuario, user_id), event_id="label-event-001",
            identifier_id=identifier_id, copias=2,
            reimpresion=True, motivo_reimpresion="Etiqueta deteriorada", socket_factory=fake_socket,
        )
        db.commit()
        assert result["resultado"] == "ok"
    with Session() as db:
        log = db.query(LogImpresionEtiqueta).one()
        assert log.impresora_host == "10.20.30.40"
        assert log.reimpresion and log.motivo_reimpresion == "Etiqueta deteriorada"
    assert len(sent) == 1 and sent[0].count(b"^XA") == 2
    zpl = sent[0].decode("utf-8")
    assert "PANTALÓN ETIQUETA" in zpl
    # La referencia libre enviada por el navegador no puede convertirse en un
    # campo de etiqueta. El identificador interno legítimo puede contener esa
    # secuencia como prefijo (p. ej. MRD-EPI-1...), por lo que se comprueba el
    # campo ZPL exacto y no una coincidencia parcial aleatoria.
    assert "^FDEPI-1^FS" not in zpl
    engine.dispose()


def test_transaccion_stock_nunca_confirma_cambios_previos(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        db.add(Usuario(username="tx-user", password_hash="x", nombre="Original", rol="admin", activo=True))
    with Session() as db:
        user = db.query(Usuario).filter_by(username="tx-user").one()
        user.nombre = "No debe confirmarse"
        with pytest.raises(StockError):
            start_stock_transaction(db)
        db.rollback()
    with Session() as db:
        assert db.query(Usuario).filter_by(username="tx-user").one().nombre == "Original"
    engine.dispose()


def test_conteo_de_ropa_rechaza_fracciones(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    _admin_id, patio_id, _viewer_id, _stock_id, session_id, line_id = _seed_session(Session)
    with Session() as db:
        with pytest.raises(InventoryError) as error:
            register_count(
                db, db.get(Usuario, patio_id), session_id=session_id, line_id=line_id,
                amount=1.5, count_number=1, scan_event_id="fraction-count-001",
            )
        assert error.value.status_code == 400
        db.rollback()
    engine.dispose()


def test_ficha_publica_qr_no_expone_stock_ubicacion_precio_personas_o_lotes(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        user = Usuario(username="public-seed", password_hash="x", nombre="Admin", rol="admin", activo=True)
        catalog = CatalogoEPI(nombre="CHAQUETA PUBLICA", categoria="ropa", cantidad_kit=1)
        db.add_all([user, catalog])
        db.flush()
        identifier = reservar_identificadores(
            db, prefijo="EPI", propietario_tipo="variante_epi",
            propietario_clave="public-variant", creado_por_id=user.id,
        )
        variant = VarianteEPI(
            catalogo_epi_id=catalog.id, modelo="Softshell", color="Azul", talla="L",
            identificador_id=identifier.id, referencia_interna=identifier.referencia_interna,
            codigo_qr=identifier.codigo_qr, creado_por_id=user.id,
        )
        db.add(variant)
        db.flush()
        qr = identifier.codigo_qr
    with Session() as db:
        response = ficha_publica_qr(qr, db)
        payload = response.body.decode("utf-8")
        assert "CHAQUETA PUBLICA" in payload
        for forbidden in ("stock", "ubicacion", "precio", "trabajador", "lote"):
            assert forbidden not in payload.lower()
    engine.dispose()


def test_ui_inventario_oculta_camara_en_pc_y_no_acepta_html_como_exito():
    template = (config.TEMPLATES_DIR / "inventario_v2.html").read_text(encoding="utf-8")
    session_template = (config.TEMPLATES_DIR / "inventario_sesion.html").read_text(encoding="utf-8")
    base = (config.TEMPLATES_DIR / "base.html").read_text(encoding="utf-8")
    assert 'id="inventory-camera-button"' in template and "hidden" in template
    assert "touch && compact && mobileSystem" in template
    assert "getUserMedia" in template and "cameraButton.addEventListener('click'" in template
    assert "includes('application/json')" in template
    assert "if (!response.ok)" in template
    assert "location.reload()" in template
    assert 'id="inventory-supply-form"' in template
    assert "Dar de alta suministro" in template
    assert "El programa crea la referencia y el QR únicos" in template
    assert "'/inventario/variantes/nueva'" in template
    assert 'name="referencia_interna"' not in template
    assert 'name="codigo_qr"' not in template
    assert 'id="inventory-scan-result"' in template
    assert "showInventoryItem(payload)" in template
    assert "Código reconocido en el inventario general" in template
    assert "data-item-key" in session_template
    assert "payload.tipo" in session_template and "payload.id" in session_template
    assert "useScannedLine(raw)" in session_template
    assert 'href="/inventario/v2"' in base
    assert "encargado_patio" in base
    assert "nav_user = user if user is defined else" in base
    assert "{% if user.rol" not in base
    report = (config.TEMPLATES_DIR / "informe_epis_trabajadores.html").read_text(encoding="utf-8")
    assert "ent['items']" in report
    assert "ent.items" not in report


def test_lineas_de_inventario_exponen_todos_los_codigos_escaneables(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        stock = StockEPI(
            nombre="CHALECO", categoria="ropa", talla="L", cantidad=12,
            codigo="QR-CHALECO-L",
        )
        epi = EPIIndividual(
            tipo="ARNES", codigo_fabricacion="FAB-ARN-01",
            referencia_interna="EPI-ARN-01", codigo_qr="QR-ARN-01", estado="activo",
        )
        db.add_all([stock, epi])
        db.flush()
        stock_view = _inventory_line_view(
            db, LineaInventario(id=101, stock_epi_id=stock.id), False,
        )
        epi_view = _inventory_line_view(
            db, LineaInventario(id=102, epi_individual_id=epi.id), False,
        )
        assert stock_view["tipo"] == "stock_epi"
        assert stock_view["item_id"] == stock.id
        assert "QR-CHALECO-L" in stock_view["codigos"]
        assert epi_view["tipo"] == "epi_individual"
        assert {"FAB-ARN-01", "EPI-ARN-01", "QR-ARN-01"} <= set(epi_view["codigos"])
    engine.dispose()


def test_sesion_todo_registra_presencia_de_herramienta_maquina_y_vehiculo(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        user = Usuario(
            username="patio-universal", password_hash="x", nombre="Patio",
            rol="encargado_patio", activo=True,
        )
        db.add_all([
            user,
            Herramienta(codigo="HER-NAVE-01", nombre="Taladro", estado="disponible", activa=True),
            Maquinaria(codigo_interno="MAQ-NAVE-01", nombre="Alimak", estado="disponible", activa=True),
            Vehiculo(codigo="VEH-NAVE-01", matricula="1234-MRD", marca="Ford", activo=True),
        ])
        db.flush()
        inventory = open_inventory_session(
            db, user, nombre="Todo nave", almacen_id=None,
            scope="total", tipo_articulo="todo",
        )
        inventory_id, user_id = inventory.id, user.id
    with Session() as db:
        rows = db.query(ActivoInventarioEscaneado).filter_by(sesion_id=inventory_id).all()
        assert {(row.tipo, row.codigo) for row in rows} == {
            ("herramienta", "HER-NAVE-01"),
            ("maquinaria", "MAQ-NAVE-01"),
            ("vehiculo", "VEH-NAVE-01"),
        }
        response = inventario_escanear_activo(
            inventory_id, EscaneoActivoInventarioRequest(codigo="HER-NAVE-01"),
            db.get(Usuario, user_id), db,
        )
        assert response.status_code == 200
        found = db.query(ActivoInventarioEscaneado).filter_by(
            sesion_id=inventory_id, tipo="herramienta",
        ).one()
        assert found.encontrado_en is not None
    engine.dispose()


def test_solo_admin_puede_modificar_y_borrar_sesion_no_cerrada(tmp_path):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    admin_id, patio_id, _viewer_id, _stock_id, session_id, _line_id = _seed_session(Session)
    with Session() as db:
        admin = db.get(Usuario, admin_id)
        response = inventario_sesion_editar(
            session_id, SesionEditarRequest(nombre="Conteo nave corregido", observaciones="Turno tarde"),
            admin, db,
        )
        assert response.status_code == 200
        assert db.get(SesionInventario, session_id).nombre == "Conteo nave corregido"
    with Session() as db:
        patio = db.get(Usuario, patio_id)
        with pytest.raises(Exception) as denied:
            inventario_sesion_eliminar(session_id, patio, db)
        assert getattr(denied.value, "status_code", None) == 403
    with Session() as db:
        admin = db.get(Usuario, admin_id)
        response = inventario_sesion_eliminar(session_id, admin, db)
        assert response.status_code == 200
        assert db.get(SesionInventario, session_id) is None
    engine.dispose()


def test_inventario_total_no_se_bloquea_por_configuracion_de_arneses(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        operator = Usuario(username="total-admin", password_hash="x", nombre="Admin", rol="admin", activo=True)
        db.add(operator)
        db.flush()
        operator_id = operator.id
    monkeypatch.setattr(config, "ARNES_EXPECTED_CODES", [])
    with Session() as db:
        session = open_inventory_session(
            db, db.get(Usuario, operator_id), nombre="Inventario general",
            almacen_id=None, scope="total", tipo_articulo="todo",
        )
        assert session.estado == "abierta"
        db.rollback()
    engine.dispose()
