import json
import threading
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

import main
import movement_service
from auth import hash_password
from models import (
    Base, Herramienta, Movimiento, ScanEvento, ScanNotificacion, Usuario,
)
from movement_service import MovementActor, MovementError, deliver_tool, start_movement_transaction
from database import apply_migrations
from scan_service import (
    changes_after, cleanup_scan_data, current_notification_cursor, request_hash,
    reserve_event,
)
from security import generar_csrf_token


def _engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'scan-1a.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )

    @event.listens_for(engine, "connect")
    def _pragmas(conn, _record):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")

    Base.metadata.create_all(engine)
    return engine


def _seed(engine, *, state="disponible", role="admin"):
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        user = Usuario(
            username=f"user-{role}", password_hash="test", nombre=f"Usuario {role}",
            rol=role, activo=True, must_change_password=False,
        )
        tool = Herramienta(
            codigo=f"SCAN-{state}", nombre="Taladro escáner",
            estado=state, activa=True,
        )
        db.add_all([user, tool])
        db.flush()
        return Session, user.id, tool.id


def _payload(event_id, tool_id, **changes):
    values = {
        "scan_event_id": event_id,
        "accion": "entregar",
        "herramienta_id": tool_id,
        "observaciones": "Prueba segura",
    }
    values.update(changes)
    return main.ScanOperationRequest(**values)


def _json(response):
    return json.loads(response.body.decode("utf-8"))


def test_dos_entregas_concurrentes_crean_un_solo_movimiento(tmp_path):
    engine = _engine(tmp_path)
    Session, user_id, tool_id = _seed(engine)
    barrier = threading.Barrier(2)
    outcomes = []
    lock = threading.Lock()

    def worker():
        db = Session()
        try:
            barrier.wait()
            start_movement_transaction(db)
            result = deliver_tool(db, MovementActor(user_id, "admin"), tool_id)
            db.commit()
            value = ("ok", result.movimiento_id)
        except MovementError as exc:
            db.rollback()
            value = ("error", exc.status_code)
        finally:
            db.close()
        with lock:
            outcomes.append(value)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert sorted(value[0] for value in outcomes) == ["error", "ok"]
    assert [value for value in outcomes if value[0] == "error"] == [("error", 409)]
    with Session() as db:
        assert db.query(Movimiento).filter_by(herramienta_id=tool_id).count() == 1
        assert db.get(Herramienta, tool_id).estado == "entregada"
    engine.dispose()


def test_scan_event_id_duplicado_simultaneo_no_duplica_movimiento(tmp_path):
    engine = _engine(tmp_path)
    Session, user_id, tool_id = _seed(engine)
    barrier = threading.Barrier(2)
    statuses = []
    lock = threading.Lock()

    def worker():
        db = Session()
        try:
            user = db.get(Usuario, user_id)
            barrier.wait()
            response = main.scan_operar(_payload("same-event-001", tool_id), user, db)
            status = response.status_code
        finally:
            db.close()
        with lock:
            statuses.append(status)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert len(statuses) == 2
    assert set(statuses) <= {200, 202}
    assert 200 in statuses
    with Session() as db:
        assert db.query(ScanEvento).filter_by(scan_event_id="same-event-001").count() == 1
        assert db.query(Movimiento).filter_by(herramienta_id=tool_id).count() == 1
        assert db.query(ScanNotificacion).filter_by(herramienta_id=tool_id).count() == 1
    engine.dispose()


def test_mismo_id_y_contenido_reutiliza_resultado_sin_nuevo_movimiento(tmp_path):
    engine = _engine(tmp_path)
    Session, user_id, tool_id = _seed(engine)
    payload = _payload("same-result-001", tool_id)
    with Session() as db:
        user = db.get(Usuario, user_id)
        first = main.scan_operar(payload, user, db)
        second = main.scan_operar(payload, user, db)
    assert first.status_code == second.status_code == 200
    assert _json(second)["movimiento_id"] == _json(first)["movimiento_id"]
    with Session() as db:
        assert db.query(ScanEvento).count() == 1
        assert db.query(Movimiento).count() == 1
        assert db.query(ScanNotificacion).count() == 1
    engine.dispose()


def test_mismo_id_con_contenido_distinto_devuelve_409(tmp_path):
    engine = _engine(tmp_path)
    Session, user_id, tool_id = _seed(engine)
    with Session() as db:
        user = db.get(Usuario, user_id)
        first = main.scan_operar(_payload("same-event-002", tool_id), user, db)
        second = main.scan_operar(
            _payload("same-event-002", tool_id, observaciones="Contenido distinto"), user, db,
        )
        assert first.status_code == 200
        assert second.status_code == 409
        assert _json(second)["resultado"] == "conflicto"
        assert db.query(Movimiento).filter_by(herramienta_id=tool_id).count() == 1
    engine.dispose()


def test_mismo_id_reutilizado_por_otro_usuario_devuelve_409(tmp_path):
    engine = _engine(tmp_path)
    Session, user_id, tool_id = _seed(engine)
    with Session.begin() as db:
        other = Usuario(
            username="other-admin", password_hash="test", nombre="Otro usuario",
            rol="admin", activo=True, must_change_password=False,
        )
        db.add(other)
        db.flush()
        other_id = other.id
    payload = _payload("cross-user-event-001", tool_id)
    with Session() as db:
        first = main.scan_operar(payload, db.get(Usuario, user_id), db)
        second = main.scan_operar(payload, db.get(Usuario, other_id), db)
    assert first.status_code == 200
    assert second.status_code == 409
    assert _json(second)["resultado"] == "conflicto"
    with Session() as db:
        assert db.query(Movimiento).count() == 1
    engine.dispose()


def test_evento_pending_responde_y_lease_vencido_se_recupera(tmp_path):
    engine = _engine(tmp_path)
    Session, user_id, tool_id = _seed(engine)
    content = request_hash({"accion": "entregar", "herramienta_id": tool_id})
    now = datetime(2026, 8, 20, 12, 0, 0)
    with Session() as db:
        first = reserve_event(
            db, scan_event_id="lease-event-001", content_hash=content,
            action="entregar", herramienta_id=tool_id, user_id=user_id, now=now,
        )
        pending = reserve_event(
            db, scan_event_id="lease-event-001", content_hash=content,
            action="entregar", herramienta_id=tool_id, user_id=user_id,
            now=now + timedelta(seconds=5),
        )
        recovered = reserve_event(
            db, scan_event_id="lease-event-001", content_hash=content,
            action="entregar", herramienta_id=tool_id, user_id=user_id,
            now=now + timedelta(seconds=31),
        )
    assert first.acquired is True
    assert pending.acquired is False and pending.estado == "pending"
    assert recovered.acquired is True
    assert recovered.lease_token != first.lease_token
    engine.dispose()


def test_endpoint_evento_pending_devuelve_202(tmp_path):
    engine = _engine(tmp_path)
    Session, user_id, tool_id = _seed(engine)
    payload = _payload("pending-endpoint-001", tool_id)
    signed = payload.model_dump(exclude={"scan_event_id"})
    signed["usuario_id"] = user_id
    content = request_hash(signed)
    with Session() as db:
        reserve_event(
            db, scan_event_id=payload.scan_event_id, content_hash=content,
            action="entregar", herramienta_id=tool_id, user_id=user_id,
        )
        response = main.scan_operar(payload, db.get(Usuario, user_id), db)
    assert response.status_code == 202
    assert _json(response)["resultado"] == "pending"
    with Session() as db:
        assert db.query(Movimiento).count() == 0
    engine.dispose()


@pytest.mark.parametrize("action", ["entregar", "devolver"])
def test_permiso_se_comprueba_antes_de_crear_evento(tmp_path, action):
    engine = _engine(tmp_path)
    state = "disponible" if action == "entregar" else "entregada"
    Session, user_id, tool_id = _seed(engine, state=state, role="consulta")
    with Session() as db:
        user = db.get(Usuario, user_id)
        with pytest.raises(HTTPException) as exc:
            main.scan_operar(_payload("permission-event", tool_id, accion=action), user, db)
        assert exc.value.status_code == 403
        assert db.query(ScanEvento).count() == 0
    engine.dispose()


def test_sesion_caducada_devuelve_401_json_y_no_crea_evento(client, db):
    client.cookies.clear()
    csrf = generar_csrf_token()
    client.cookies.set("mrd_csrf", csrf)
    before = db.query(ScanEvento).count()
    response = client.post(
        "/scan/operar",
        json={
            "scan_event_id": "expired-session-001",
            "accion": "entregar",
            "herramienta_id": 1,
        },
        headers={"X-CSRF-Token": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detalle"] == "Sesión caducada"
    assert db.query(ScanEvento).count() == before


def test_fallo_hace_rollback_y_marca_evento_en_transaccion_nueva(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    Session, user_id, tool_id = _seed(engine)

    def fail_persist(*_args, **_kwargs):
        raise RuntimeError("fallo después del update")

    monkeypatch.setattr(movement_service, "_persist_movement", fail_persist)
    with Session() as db:
        response = main.scan_operar(_payload("rollback-event-001", tool_id), db.get(Usuario, user_id), db)
        assert response.status_code == 500
    with Session() as db:
        assert db.get(Herramienta, tool_id).estado == "disponible"
        assert db.query(Movimiento).filter_by(herramienta_id=tool_id).count() == 0
        event_row = db.query(ScanEvento).filter_by(scan_event_id="rollback-event-001").one()
        assert event_row.estado == "error"
    engine.dispose()


def test_fallo_al_cerrar_evento_revierte_movimiento_y_herramienta(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    Session, user_id, tool_id = _seed(engine)

    def fail_finish(*_args, **_kwargs):
        raise RuntimeError("fallo antes del commit conjunto")

    monkeypatch.setattr(main, "finish_event", fail_finish)
    with Session() as db:
        response = main.scan_operar(
            _payload("finish-rollback-001", tool_id), db.get(Usuario, user_id), db,
        )
        assert response.status_code == 500
    with Session() as db:
        assert db.get(Herramienta, tool_id).estado == "disponible"
        assert db.query(Movimiento).count() == 0
        assert db.query(ScanNotificacion).count() == 0
        event_row = db.query(ScanEvento).filter_by(scan_event_id="finish-rollback-001").one()
        assert event_row.estado == "error"
    engine.dispose()


def test_cursor_incremental_no_pierde_notificaciones_con_misma_hora(tmp_path):
    engine = _engine(tmp_path)
    Session, _user_id, tool_id = _seed(engine)
    same_time = datetime(2026, 8, 20, 12, 30, 0)
    with Session.begin() as db:
        db.add_all([
            ScanNotificacion(herramienta_id=tool_id, tipo="estado_herramienta", payload_json='{"n":1}', created_at=same_time),
            ScanNotificacion(herramienta_id=tool_id, tipo="estado_herramienta", payload_json='{"n":2}', created_at=same_time),
        ])
    with Session() as db:
        first, cursor = changes_after(db, 0, 1)
        second, next_cursor = changes_after(db, cursor, 10)
    assert [item["n"] for item in first + second] == [1, 2]
    assert next_cursor > cursor > 0
    engine.dispose()


def test_cursor_inicial_omite_historial_y_no_pierde_misma_fecha(tmp_path):
    engine = _engine(tmp_path)
    Session, _user_id, tool_id = _seed(engine)
    same_time = datetime(2026, 8, 20, 12, 30, 0)
    with Session.begin() as db:
        db.add_all([
            ScanNotificacion(herramienta_id=tool_id, payload_json='{"n":1}', created_at=same_time),
            ScanNotificacion(herramienta_id=tool_id, payload_json='{"n":2}', created_at=same_time),
        ])
    with Session() as db:
        initial = current_notification_cursor(db)
        old, unchanged = changes_after(db, initial, 10)
    assert old == [] and unchanged == initial
    with Session.begin() as db:
        db.add(ScanNotificacion(
            herramienta_id=tool_id, payload_json='{"n":3}', created_at=same_time,
        ))
    with Session() as db:
        new, next_cursor = changes_after(db, initial, 10)
    assert [item["n"] for item in new] == [3]
    assert next_cursor > initial
    engine.dispose()


def test_endpoint_inicializacion_devuelve_solo_cursor_maximo(tmp_path):
    engine = _engine(tmp_path)
    Session, user_id, tool_id = _seed(engine)
    with Session.begin() as db:
        db.add_all([
            ScanNotificacion(herramienta_id=tool_id, payload_json='{"n":1}'),
            ScanNotificacion(herramienta_id=tool_id, payload_json='{"n":2}'),
        ])
    with Session() as db:
        response = main.scan_cambios(
            ultimo_id=0, limite=1, inicializar=True,
            user=db.get(Usuario, user_id), db=db,
        )
        maximum = db.query(ScanNotificacion.id).order_by(ScanNotificacion.id.desc()).first()[0]
    assert response.status_code == 200
    assert _json(response) == {"cambios": [], "next_cursor": maximum}
    engine.dispose()


def test_retencion_limpia_notificaciones_antes_de_eventos_y_respeta_pending(tmp_path):
    engine = _engine(tmp_path)
    Session, user_id, tool_id = _seed(engine)
    now = datetime(2026, 8, 20, 12, 0, 0)
    old = now - timedelta(days=91)
    with Session.begin() as db:
        finalized = ScanEvento(
            scan_event_id="old-finalized", request_hash="a" * 64, estado="ok",
            accion="entregar", herramienta_id=tool_id, usuario_id=user_id,
            lease_hasta=old, created_at=old, updated_at=old,
        )
        pending = ScanEvento(
            scan_event_id="old-pending", request_hash="b" * 64, estado="pending",
            accion="entregar", herramienta_id=tool_id, usuario_id=user_id,
            lease_token="vigente", lease_hasta=now + timedelta(minutes=1),
            created_at=old, updated_at=old,
        )
        recent = ScanEvento(
            scan_event_id="recent-finalized", request_hash="c" * 64, estado="error",
            accion="entregar", herramienta_id=tool_id, usuario_id=user_id,
            lease_hasta=now, created_at=now, updated_at=now,
        )
        retained_by_notification = ScanEvento(
            scan_event_id="old-with-recent-notification", request_hash="d" * 64,
            estado="ok", accion="entregar", herramienta_id=tool_id,
            usuario_id=user_id, lease_hasta=old, created_at=old, updated_at=old,
        )
        db.add_all([finalized, pending, recent, retained_by_notification])
        db.flush()
        db.add_all([
            ScanNotificacion(
                scan_evento_id=finalized.id, herramienta_id=tool_id,
                payload_json='{"old":true}', created_at=now - timedelta(minutes=6),
            ),
            ScanNotificacion(
                scan_evento_id=recent.id, herramienta_id=tool_id,
                payload_json='{"recent":true}', created_at=now - timedelta(minutes=4),
            ),
            ScanNotificacion(
                scan_evento_id=retained_by_notification.id, herramienta_id=tool_id,
                payload_json='{"recent_reference":true}', created_at=now - timedelta(minutes=4),
            ),
        ])
    with Session.begin() as db:
        assert cleanup_scan_data(db, now=now, batch=10) == {"notifications": 1, "events": 1}
    with Session.begin() as db:
        assert cleanup_scan_data(db, now=now, batch=10) == {"notifications": 0, "events": 0}
        assert db.query(ScanEvento).filter_by(scan_event_id="old-finalized").count() == 0
        assert db.query(ScanEvento).filter_by(scan_event_id="old-pending").count() == 1
        assert db.query(ScanEvento).filter_by(scan_event_id="recent-finalized").count() == 1
        assert db.query(ScanEvento).filter_by(scan_event_id="old-with-recent-notification").count() == 1
        assert db.query(ScanNotificacion).count() == 2
    engine.dispose()


def test_scan_cambios_rechaza_usuario_consulta_sin_exponer_actividad(tmp_path):
    engine = _engine(tmp_path)
    Session, user_id, tool_id = _seed(engine, role="consulta")
    with Session.begin() as db:
        db.add(ScanNotificacion(
            herramienta_id=tool_id,
            payload_json='{"usuario":"Nombre privado","estado":"entregada"}',
        ))
    with Session() as db:
        with pytest.raises(HTTPException) as exc:
            main.scan_cambios(
                ultimo_id=0, limite=50, inicializar=False,
                user=db.get(Usuario, user_id), db=db,
            )
    assert exc.value.status_code == 403
    engine.dispose()


def test_migracion_scan_crea_tablas_una_vez_y_conserva_datos(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy-scan.db').as_posix()}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE usuarios (id INTEGER PRIMARY KEY, nombre TEXT)"))
        conn.execute(text("CREATE TABLE herramientas (id INTEGER PRIMARY KEY, codigo TEXT)"))
        conn.execute(text("CREATE TABLE movimientos (id INTEGER PRIMARY KEY, herramienta_id INTEGER)"))
        conn.execute(text("INSERT INTO usuarios (id, nombre) VALUES (1, 'Original')"))
        conn.execute(text("INSERT INTO herramientas (id, codigo) VALUES (1, 'LEG-1')"))
        conn.execute(text("INSERT INTO movimientos (id, herramienta_id) VALUES (1, 1)"))

    first = apply_migrations(engine)
    second = apply_migrations(engine)

    inspector = inspect(engine)
    assert {"scan_eventos", "scan_notificaciones"}.issubset(inspector.get_table_names())
    assert second == {"columns_added": 0, "indexes_created": 0, "rows_updated": 0}
    assert first["indexes_created"] >= 1
    with engine.connect() as conn:
        assert conn.execute(text("SELECT nombre FROM usuarios WHERE id=1")).scalar_one() == "Original"
        assert conn.execute(text("SELECT codigo FROM herramientas WHERE id=1")).scalar_one() == "LEG-1"
        assert conn.execute(text("SELECT herramienta_id FROM movimientos WHERE id=1")).scalar_one() == 1
    engine.dispose()


def test_scan_template_oculta_camara_en_pc_y_no_la_autoactiva():
    html = (main.BASE_DIR / "templates" / "scan.html").read_text(encoding="utf-8")
    assert 'id="manual-scanner-panel"' in html
    assert 'id="manual-scanner-panel" hidden' not in html
    assert 'id="camera-panel" hidden' in html
    assert "function esMovilOTablet()" in html
    assert "navigator.userAgent" in html
    assert "navigator.maxTouchPoints" in html
    assert "screen.width" in html and "screen.height" in html
    assert "Ante duda permanece completamente oculto" in html
    assert "panel.hidden = false" in html
    assert "Permiso de cámara denegado" in html
    assert "La pistola y la entrada manual siguen disponibles" in html
    assert "iniciarCamara();" not in html


def test_camara_movil_usa_lector_continuo_y_se_recupera_sin_duplicados():
    html = (main.BASE_DIR / "templates" / "scan.html").read_text(encoding="utf-8")
    assert "decodeFromStream(_camStream, video, _onCameraDecode)" in html
    assert "decodeFromVideoElement(video)" not in html
    assert "facingMode: { ideal: 'environment' }" in html
    assert "focusMode:'continuous'" in html
    assert "timeBetweenDecodingAttempts = 80" in html
    assert "txt === _lastCameraCode" in html
    assert "document.addEventListener('visibilitychange'" in html
    assert "_programarReinicioCamara" in html
    assert "window.addEventListener('pagehide'" in html


def test_scan_fetch_rechaza_redireccion_login_y_respuesta_no_json():
    html = (main.BASE_DIR / "templates" / "scan.html").read_text(encoding="utf-8")
    assert "fetch('/scan/operar'" in html
    assert "r.redirected || destino === '/login' || r.status === 401" in html
    assert "contentType.includes('application/json')" in html
    assert "data.resultado !== 'ok'" in html
    assert "{% if puede_entregar or puede_devolver %}" in html
    assert "fetch('/scan/cambios?inicializar=true&limite=1')" in html


def test_scan_buscar_protege_contra_dobles_clics_y_respuestas_fuera_de_orden():
    html = (main.BASE_DIR / "templates" / "scan.html").read_text(encoding="utf-8")
    # Doble clic / segunda lectura del mismo código mientras ya se resuelve.
    assert "if (!desdePendientes && _scanActiveCode === codigo) return;" in html
    # Un código distinto cancela la búsqueda anterior con el mismo AbortController.
    assert "if (_scanAbort) { try { _scanAbort.abort(); } catch (_) {} }" in html
    assert "var myAbort = new AbortController();" in html
    # Número de secuencia: una respuesta obsoleta no puede pisar a una más reciente.
    assert "var mySeq = ++_scanSeq;" in html
    assert html.count("if (mySeq !== _scanSeq) return completed;") >= 3
    # El botón/indicador solo lo restaura la petición vigente.
    assert "if (mySeq === _scanSeq) {\n      setBuscandoUI(false);" in html


def test_scan_buscar_distingue_cancelacion_intencionada_de_error_real():
    html = (main.BASE_DIR / "templates" / "scan.html").read_text(encoding="utf-8")
    assert "err.mrdCancelled = true;" in html
    # La cancelación se resuelve antes que cualquier otro manejo de errores y no se registra.
    assert "if (e && e.mrdCancelled) return completed; // Cancelación intencionada: no se muestra como error." in html
    assert "if (controller.signal.aborted) throw _mrdCancelledError();" in html


def test_scan_buscar_usa_timeout_finito_sin_reintentos_automaticos():
    html = (main.BASE_DIR / "templates" / "scan.html").read_text(encoding="utf-8")
    assert "var SCAN_FETCH_TIMEOUT_MS = 8000;" in html
    assert "async function fetchCodigoConTimeout(codigo, controller)" in html
    assert "timedOut = true; controller.abort(); }, SCAN_FETCH_TIMEOUT_MS);" in html
    assert "throw new Error('La búsqueda tardó demasiado. Comprueba la conexión y vuelve a escanear.');" in html
    # No debe existir un bucle de reintentos automáticos (fuera de alcance de esta tanda).
    assert "fetchCodigoConReintento" not in html
    assert "for (var intento" not in html


def test_scan_buscar_indicador_visual_y_boton_siempre_se_recuperan():
    html = (main.BASE_DIR / "templates" / "scan.html").read_text(encoding="utf-8")
    assert 'id="scan-submit-btn"' in html
    assert 'id="scan-searching" class="scan-searching-badge" role="status" aria-live="polite" hidden' in html
    assert "function setBuscandoUI(activo) {" in html
    assert "btn.disabled = activo;" in html
    assert "if (badge) badge.hidden = !activo;" in html


def test_scan_buscar_mantiene_cola_offline_existente_intacta():
    html = (main.BASE_DIR / "templates" / "scan.html").read_text(encoding="utf-8")
    assert "var _pendingScanKey = 'mrd.pendingScans.v1';" in html
    assert "function guardarEscaneoPendiente(codigo) {" in html
    assert "localStorage.setItem(_pendingScanKey, JSON.stringify(rows.slice(-100)));" in html
    assert "showToast('Lectura guardada. Se comprobará cuando vuelva la conexión.', 'info');" in html
    assert "async function sincronizarEscaneosPendientes() {" in html
    assert "window.addEventListener('online', sincronizarEscaneosPendientes);" in html
    # Solo un error real sin conexión guarda en la cola; cancelación/obsoleta ya salieron antes.
    assert "if (!navigator.onLine && !desdePendientes) {\n      guardarEscaneoPendiente(codigo);" in html


def test_scan_operar_http_con_login_y_csrf_reales_devuelve_json(client, db):
    password = "ScanHttp@2026!"
    user = Usuario(
        username="scan-http-admin", password_hash=hash_password(password),
        nombre="Operador HTTP", rol="admin", activo=True,
        must_change_password=False,
    )
    tool = Herramienta(
        codigo="SCAN-HTTP-001", nombre="Herramienta HTTP",
        estado="disponible", activa=True,
    )
    db.add_all([user, tool])
    db.commit()

    client.cookies.clear()
    login = client.post(
        "/login", data={"username": user.username, "password": password},
        follow_redirects=False,
    )
    assert login.status_code == 303
    token = login.cookies.get("mrd_token")
    csrf = login.cookies.get("mrd_csrf")
    assert token and csrf
    client.cookies.clear()
    client.cookies.set("mrd_token", token)
    client.cookies.set("mrd_csrf", csrf)

    response = client.post(
        "/scan/operar",
        json={
            "scan_event_id": "http-real-event-001",
            "accion": "entregar",
            "herramienta_id": tool.id,
        },
        headers={"X-CSRF-Token": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["resultado"] == "ok"

    client.cookies.clear()
    client.cookies.set("mrd_csrf", csrf)
    expired = client.post(
        "/scan/operar",
        json={
            "scan_event_id": "http-expired-event-001",
            "accion": "entregar", "herramienta_id": tool.id,
        },
        headers={"X-CSRF-Token": csrf},
        follow_redirects=False,
    )
    assert expired.status_code == 401
    assert expired.headers["content-type"].startswith("application/json")

    client.cookies.clear()
    client.cookies.set("mrd_token", token)
    client.cookies.set("mrd_csrf", csrf)
    invalid_csrf = client.post(
        "/scan/operar",
        json={
            "scan_event_id": "http-html-event-001",
            "accion": "entregar", "herramienta_id": tool.id,
        },
        headers={"X-CSRF-Token": "token-invalido"},
        follow_redirects=False,
    )
    assert invalid_csrf.status_code == 403
    assert invalid_csrf.headers["content-type"].startswith("text/html")
    html = (main.BASE_DIR / "templates" / "scan.html").read_text(encoding="utf-8")
    assert "!contentType.includes('application/json')" in html
    client.cookies.clear()
