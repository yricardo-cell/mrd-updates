import json
import subprocess
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from main import _asegurar_tallas_ropa
from models import Base, Herramienta, StockEPI, Usuario
from mostrador_service import (
    COUNTER_ASSET_TYPES,
    COUNTER_STOCK_TYPES,
    CounterError,
    allowed_counter_types,
    operate_counter,
    resolve_counter_item,
)
from scanner_service import normalize_scanned_code


ROOT = Path(__file__).resolve().parents[1]


def _node_detector(events):
    script = f"""
const api = require({json.dumps(str(ROOT / 'static/js/scanner_hid.js'))});
const detector = new api.Detector();
const events = {json.dumps(events)};
const output = events.map(e => detector.feed(e.key, e.at, e.complete));
process.stdout.write(JSON.stringify(output));
"""
    result = subprocess.run(
        ["node", "-e", script], check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def _keys(value, start=0, step=35, terminator="Enter", pause_after=None, pause_ms=0):
    events = []
    current = start
    for index, char in enumerate(value):
        if pause_after is not None and index == pause_after:
            current += pause_ms
        events.append({"key": char, "at": current})
        current += step
    events.append({"key": terminator, "at": current, "complete": value})
    return events


@pytest.mark.parametrize(
    "terminator,expected", [("Enter", "Enter"), ("Tab", "Tab"), ("\r", "CR"), ("\n", "LF")],
)
def test_detector_envia_el_valor_completo_con_sufijo_hid(terminator, expected):
    value = "]Q3https://app.iasmrd.com/scan?codigo=TOOL-QR-001"
    result = _node_detector(_keys(value, terminator=terminator))[-1]
    assert result["terminated"] is True
    assert result["scannerLike"] is True
    assert result["code"] == value
    assert result["terminator"] == expected
    assert normalize_scanned_code(result["code"]) == "TOOL-QR-001"


def test_detector_tolera_pausa_bluetooth_sin_truncar_inicio():
    value = "MRD-MAQ-ST300-001"
    result = _node_detector(_keys(value, step=45, pause_after=7, pause_ms=900))[-1]
    assert result["scannerLike"] is True
    assert result["code"] == value


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SEPI'0009", "SEPI-0009"),
        ("SEPI´0052", "SEPI-0052"),
        ("MRD'MAQ'ST300'001", "MRD-MAQ-ST300-001"),
        ("https://app.iasmrd.com/scan?codigo=SEPI%270053", "SEPI-0053"),
    ],
)
def test_normaliza_guion_emitido_como_apostrofo_por_teclado_hid(raw, expected):
    assert normalize_scanned_code(raw) == expected


def test_scan_vacia_lectura_hid_antes_de_buscar_para_no_concatenar():
    scan = (ROOT / "templates/scan.html").read_text(encoding="utf-8")
    handler = scan[scan.index("function _onScanKeydown"):scan.index("document.addEventListener('click'")]
    assert handler.index("scanInput.value = ''") < handler.index("buscarCodigo(null, codigoCompleto")


def test_mostrador_e_inventarios_consumen_pistola_sin_saltar_a_scan():
    common = (ROOT / "static/js/mrd.js").read_text(encoding="utf-8")
    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
    counter = (ROOT / "templates/mostrador.html").read_text(encoding="utf-8")
    inventory = (ROOT / "templates/inventario_v2.html").read_text(encoding="utf-8")
    session = (ROOT / "templates/inventario_sesion.html").read_text(encoding="utf-8")
    receipt = (ROOT / "templates/inventario_recepcion.html").read_text(encoding="utf-8")
    assert "detector.feed(event.key, now, completeValue)" in common
    assert "window.MRDGlobalScanner = GlobalScanner" in common
    assert "mrd.js?v={{ version }}-scanner-inventory-v3" in base
    for source in (counter, inventory, session, receipt):
        assert "mrd:scanner-code" in source
        handler = source[source.index("mrd:scanner-code") - 80:source.index("mrd:scanner-code") + 180]
        assert "preventDefault" in handler
    assert "useInventoryScan(event.detail.code)" in inventory
    assert "useScannedLine(event.detail.code)" in session
    assert "code.value=window.MRDGlobalScanner.normalize(event.detail.code)" in receipt


def test_pistola_se_queda_en_flujos_locales_y_mostrador_limpia_lectura():
    common = (ROOT / "static/js/mrd.js").read_text(encoding="utf-8")
    counter = (ROOT / "templates/mostrador.html").read_text(encoding="utf-8")
    assert "#counter-scan,#inventory-scan-input,#line-filter,#receipt-code" in common
    assert "!scanEvent.defaultPrevented && !localWorkflow" in common
    add_start = counter.index("async function add(rawCode)")
    fetch_start = counter.index("fetch('/api/mostrador/resolver", add_start)
    assert counter.index("scan.value=''", add_start) < fetch_start
    assert "await searchByName(code)" in counter


def test_inventario_acepta_bluetooth_lento_y_resuelve_qr_oficial_en_servidor():
    common = (ROOT / "static" / "js" / "mrd.js").read_text(encoding="utf-8")
    panel = (ROOT / "templates" / "inventario_v2.html").read_text(encoding="utf-8")
    session = (ROOT / "templates" / "inventario_sesion.html").read_text(encoding="utf-8")
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")

    assert "result.scannerLike || localInput" in common
    assert "#counter-scan,#inventory-scan-input,#line-filter,#receipt-code" in common
    assert panel.count("/scan/buscar?codigo=") == 1
    assert session.count("/scan/buscar?codigo=") == 1
    assert "setTimeout(() => scannerInput.focus(), 100)" in panel
    assert "setTimeout(()=>filter.focus(),100)" in session
    assert "sidebar-section-operations" in base
    assert "sidebar-list-operations" in base


def test_detector_usa_tiempos_solo_para_clasificar_escritura_manual():
    value = "TOOL-MANUAL-001"
    result = _node_detector(_keys(value, step=600))[-1]
    assert result["code"] == value
    assert result["scannerLike"] is False


def test_detector_evitar_doble_lectura_simultanea_sin_bloquear_otro_codigo():
    first = _keys("TOOL-001", start=0, step=25)
    second = _keys("TOOL-001", start=350, step=25)
    third = _keys("TOOL-002", start=700, step=25)
    outputs = _node_detector(first + second + third)
    terminated = [item for item in outputs if item.get("terminated")]
    assert [item["duplicate"] for item in terminated] == [False, True, False]


def test_scan_y_javascript_no_insertan_datos_sin_escapar():
    scan = (ROOT / "templates/scan.html").read_text(encoding="utf-8")
    common = (ROOT / "static/js/mrd.js").read_text(encoding="utf-8")
    assert "function scanEsc" in scan
    assert "function mrdEscapeHtml" in common
    function_source = common[common.index("function mrdEscapeHtml"):common.index("function mrdSafeId")]
    dangerous = '<img src=x onerror="alert(1)">\' > <svg>'
    script = function_source + "\nprocess.stdout.write(mrdEscapeHtml(" + json.dumps(dangerous) + "));"
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    assert result.stdout == "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&#39; &gt; &lt;svg&gt;"
    assert "SCAN_AUTHENTICATED" in scan
    assert "codigoNoEncontrado && SCAN_AUTHENTICATED" in scan
    assert "SCAN_AUTHENTICATED ? '<a href='" not in scan  # no enlace formado sin URL segura


def test_botones_no_quedan_bloqueados_por_temporizador_global():
    common = (ROOT / "static/js/mrd.js").read_text(encoding="utf-8")
    scan = (ROOT / "templates/scan.html").read_text(encoding="utf-8")
    counter = (ROOT / "templates/mostrador.html").read_text(encoding="utf-8")
    assert "8000" not in common
    assert "data-managed-submit" in common
    assert "event.defaultPrevented" in common
    assert "pageshow" in common and "restoreSubmitButtons" in common
    assert "finally" in counter
    assert "btn.disabled = false" in scan


def test_normalizacion_en_escritura_permita_resolver_con_indice(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'normal.db').as_posix()}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    tool = Herramienta(codigo="  tool-mixed-001  ", nombre="Taladro", estado="disponible", activa=True)
    db.add(tool)
    db.commit()
    assert tool.codigo == "TOOL-MIXED-001"
    assert resolve_counter_item(db, "tool-mixed-001")["id"] == tool.id
    plan = db.execute(text(
        "EXPLAIN QUERY PLAN SELECT id FROM herramientas WHERE codigo='TOOL-MIXED-001'"
    )).all()
    assert any("INDEX" in str(row).upper() for row in plan)


def test_resolvedor_indexado_mide_acierto_y_fallo_sin_regresion(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'perf.db').as_posix()}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.execute(Herramienta.__table__.insert(), [
        {"codigo": f"PERF-{n:06d}", "nombre": f"Herramienta {n}", "estado": "disponible", "activa": True}
        for n in range(5000)
    ])
    db.commit()
    target = "PERF-004999"
    resolve_counter_item(db, target)
    old_plan = db.execute(text(
        "EXPLAIN QUERY PLAN SELECT id FROM herramientas WHERE upper(trim(codigo))='PERF-004999'"
    )).all()
    new_plan = db.execute(text(
        "EXPLAIN QUERY PLAN SELECT id FROM herramientas WHERE codigo='PERF-004999'"
    )).all()
    assert any("SCAN" in str(row).upper() for row in old_plan)
    assert any("INDEX" in str(row).upper() for row in new_plan)

    hit_start = time.perf_counter()
    for _ in range(60):
        assert resolve_counter_item(db, target)["codigo"] == target
    hit = time.perf_counter() - hit_start
    miss_start = time.perf_counter()
    for _ in range(20):
        with pytest.raises(CounterError) as exc:
            resolve_counter_item(db, "PERF-NO-EXISTE")
        assert exc.value.status_code == 404
    miss = time.perf_counter() - miss_start
    assert hit < 1.0
    assert miss < 4.0  # incluye compatibilidad legacy, ejecutada solo tras fallar el camino exacto


def test_roles_solo_operan_tipos_permitidos(tmp_path):
    encargado = Usuario(username="enc", password_hash="x", nombre="Enc", rol="encargado", activo=True)
    patio = Usuario(username="patio", password_hash="x", nombre="Patio", rol="encargado_patio", activo=True)
    consulta = Usuario(username="see", password_hash="x", nombre="See", rol="consulta", activo=True)
    assert allowed_counter_types(encargado) == set(COUNTER_ASSET_TYPES)
    assert allowed_counter_types(patio) == set(COUNTER_ASSET_TYPES | COUNTER_STOCK_TYPES)
    assert allowed_counter_types(consulta) == set()

    engine = create_engine(f"sqlite:///{(tmp_path / 'roles.db').as_posix()}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(encargado)
    stock = StockEPI(nombre="CAMISETA", categoria="ropa", talla="L", cantidad=4, codigo="SEPI-ROLE-L")
    db.add(stock)
    db.commit()
    with pytest.raises(CounterError) as exc:
        operate_counter(
            db, encargado, operation_id="role-denied-0001", action="salida",
            worker_id=None, work_id=None, warehouse_id=None,
            lines=[{"tipo": "stock_epi", "id": stock.id, "cantidad": 1}],
        )
    assert exc.value.status_code == 403
    assert stock.cantidad == 4


def test_contrato_tallas_no_crea_automaticas_y_solo_acepta_explicitas(db):
    db.add(StockEPI(nombre="FORRO TEST", categoria="ropa", talla=None, cantidad=0, codigo="SEPI-FORRO-BASE"))
    db.flush()
    assert _asegurar_tallas_ropa(db, "FORRO TEST") == 0
    assert db.query(StockEPI).filter(StockEPI.nombre == "FORRO TEST").count() == 1
    assert _asegurar_tallas_ropa(db, "FORRO TEST", "L, 3XL") == 1
    assert {row.talla for row in db.query(StockEPI).filter(StockEPI.nombre == "FORRO TEST")} == {"L", "3XL"}


def test_pwa_publica_detector_y_version_candidata_real():
    sw = (ROOT / "static/js/sw.js").read_text(encoding="utf-8")
    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
    version = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    assert version["version_actual"] == "2.7.0"
    assert version["estado"] == "en_desarrollo"
    assert "/static/js/scanner_hid.js" in sw
    assert "mrd-static-v2.7.0" in sw
    assert 'scanner_hid.js?v={{ version }}"></script>' in base


def test_pistola_bluetooth_tablet_carga_detector_y_recupera_foco_sin_robar_campos():
    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
    scan = (ROOT / "templates/scan.html").read_text(encoding="utf-8")
    common = (ROOT / "static/js/mrd.js").read_text(encoding="utf-8")
    assert base.index("scanner_hid.js") < base.index("mrd.js") < base.index("{% block extra_js %}")
    scan_scripts = scan[scan.index("<!-- Toast -->"):]
    assert scan_scripts.index("{% endblock %}") < scan_scripts.index("{% block extra_js %}") < scan_scripts.index("function _loadZXing")
    assert 'autofocus onkeydown="_onScanKeydown(event)"' in scan
    assert "var scanInput = document.getElementById('scan-input')" in scan
    assert "var codigoCompleto = scanInput.value" in scan
    assert "refocusScanInput(false)" in scan
    assert scan.count("refocusScanInput(true)") >= 2
    assert "userIsEditing" in scan
    assert "captureField(event.target)" in common
    assert "releaseField(true)" in common
    assert "input:not([type=\"password\"]), textarea" in common


def test_botones_scan_y_mostrador_recuperan_estado_y_rechazan_html_o_redireccion():
    scan = (ROOT / "templates/scan.html").read_text(encoding="utf-8")
    counter = (ROOT / "templates/mostrador.html").read_text(encoding="utf-8")
    for button_id in (
        "btn-cam-start", "btn-cam-stop", "modal-confirm-btn", "scan-add",
    ):
        assert button_id in scan or button_id in counter
    for button_id in ("clear-cart", "confirm-counter", "camera-button", "scan-add"):
        assert button_id in counter
    assert "btn.disabled = true" in scan and "btn.disabled = false" in scan
    assert "content-type" in scan and "application/json" in scan
    assert "redirect:'manual'" in counter
    assert "Respuesta no válida del servidor" in counter
    assert "finally{busy=false;render();scan.value='';refocusCounter(false)}" in counter
