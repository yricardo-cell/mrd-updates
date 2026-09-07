"""Guardián Fase 2 (MRD): eventos de seguridad estructurados para Sentinel y
vigilancia mutua (MRD avisa si Sentinel deja de responder)."""
import json

import pytest

import security_events
from models import Aviso


@pytest.fixture
def eventos(tmp_path, monkeypatch):
    path = tmp_path / "eventos_seguridad.jsonl"
    monkeypatch.setattr(security_events, "EVENTOS_PATH", path)
    return path


def _leer(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_emitir_escribe_una_linea_json_sin_query_string(eventos):
    security_events.emitir("login_fallido", None, usuario="pepe", ip="203.0.113.5", pais="fr", ruta="/login?next=/x&token=abc")
    ev = _leer(eventos)
    assert len(ev) == 1
    assert ev[0]["tipo"] == "login_fallido" and ev[0]["ip"] == "203.0.113.5" and ev[0]["pais"] == "FR"
    assert ev[0]["usuario"] == "pepe" and ev[0]["ruta"] == "/login" and "token" not in ev[0]["ruta"]
    assert ev[0]["t"][:4].isdigit() and "+" in ev[0]["t"]  # ISO con zona horaria


def test_tipo_desconocido_se_anota_como_otro_y_nunca_lanza(eventos, monkeypatch):
    security_events.emitir("inventado", None, ip="1.2.3.4")
    assert _leer(eventos)[0]["tipo"] == "otro"
    monkeypatch.setattr(security_events, "EVENTOS_PATH", eventos / "no" / "existe" / "x.jsonl")
    security_events.emitir("login_ok", None)  # carpeta se crea sola
    monkeypatch.setattr(security_events, "EVENTOS_PATH", eventos.parent)  # es un directorio: falla, pero no lanza
    security_events.emitir("login_ok", None)


def test_rotacion_al_superar_el_tamano(eventos, monkeypatch):
    monkeypatch.setattr(security_events, "MAX_BYTES", 200)
    for i in range(10):
        security_events.emitir("http_404", None, ip="9.9.9.9", ruta=f"/ruta-{i}" * 5)
    assert eventos.with_suffix(".jsonl.1").exists()
    assert eventos.stat().st_size <= 600


def test_auditoria_sensible_solo_tablas_y_acciones_relevantes(eventos):
    security_events.emitir_auditoria_sensible("herramientas", "editar", 1, "cambio", "1.1.1.1")
    security_events.emitir_auditoria_sensible("usuarios", "ver", 1, "consulta", "1.1.1.1")
    assert not eventos.exists()
    security_events.emitir_auditoria_sensible("usuarios", "crear", 7, "Alta de usuario nuevo", "1.1.1.1")
    ev = _leer(eventos)
    assert ev[0]["tipo"] == "cambio_sensible" and ev[0]["ruta"] == "usuarios/crear" and ev[0]["usuario"] == "7"


def test_login_fallido_y_404_generan_eventos_desde_la_app(client, eventos):
    client.post("/login", data={"username": "nadie", "password": "malo"}, headers={"CF-IPCountry": "de"})
    client.get("/no-existe-esta-ruta-guardian")
    tipos = [e["tipo"] for e in _leer(eventos)]
    assert "login_fallido" in tipos and "http_404" in tipos
    fallido = next(e for e in _leer(eventos) if e["tipo"] == "login_fallido")
    assert fallido["usuario"] == "nadie" and fallido["pais"] == "DE"
    assert "malo" not in eventos.read_text(encoding="utf-8")


def test_vigilancia_de_sentinel_avisa_tras_tres_fallos_y_al_recuperarse(db, monkeypatch):
    security_events.reiniciar_estado_sentinel()
    avisos = []
    monkeypatch.setattr(security_events, "_avisar", lambda t, m, p, db=None: avisos.append((t, p)))
    estado = {"ok": False}
    check = lambda: estado["ok"]
    reloj = {"t": 1_000_000.0}
    now = lambda: reloj["t"]
    assert security_events.vigilar_sentinel(db, check=check, now=now) is None
    assert security_events.vigilar_sentinel(db, check=check, now=now) is None
    assert security_events.vigilar_sentinel(db, check=check, now=now) == "caido"
    assert avisos[-1][1] == "critica"
    assert security_events.vigilar_sentinel(db, check=check, now=now) is None  # sin repetir
    reloj["t"] += 1801
    assert security_events.vigilar_sentinel(db, check=check, now=now) == "recordatorio"
    estado["ok"] = True
    assert security_events.vigilar_sentinel(db, check=check, now=now) == "recuperado"
    assert [p for _, p in avisos] == ["critica", "alta", "media"]


def test_aviso_interno_se_guarda_en_la_tabla_de_avisos(db):
    security_events._avisar("Prueba guardián", "mensaje", "alta", db)
    aviso = db.query(Aviso).filter(Aviso.titulo == "Prueba guardián").first()
    assert aviso is not None and aviso.prioridad == "alta" and aviso.tipo == "sistema"
