"""
salidas_maquinaria.py — Router de fichas de salida a obra para maquinaria
Colocar en C:\\mrd_tool_control\\salidas_maquinaria.py

Registrar en main.py con:
    from salidas_maquinaria import router as salidas_router
    app.include_router(salidas_router)
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from auth import requiere_login, tiene_permiso
from models import Maquinaria, Herramienta, SalidaObra, SalidaItem
from codigos import generar_qr_base64

router = APIRouter()

# ─── Plantillas ───────────────────────────────────────────────────────────────
templates = Jinja2Templates(directory="templates")


def _require_operar(user) -> None:
    if not tiene_permiso(user, "stock_operar"):
        raise HTTPException(403, "Sin permiso para preparar salidas")


def _require_completa(salida: SalidaObra) -> None:
    if not salida.items or any(not item.checked for item in salida.items):
        raise HTTPException(409, "El checklist debe estar completo antes de cerrar la salida")


# ─── Definición de checklists ─────────────────────────────────────────────────

CHECKLISTS = {

    "alimak": [
        {
            "section": "Mástil y estructura",
            "items": [
                {"key": "tramos_mastil",   "name": "Tramos de mástil",
                 "detail": "Con pasadores y pernos incluidos"},
                {"key": "cremallera",      "name": "Cremallera (rack)",
                 "detail": "Un tramo de cremallera por cada tramo de mástil"},
                {"key": "guias_cable",     "name": "Guías de cable",
                 "detail": "Abrazaderas de fijación del cable al mástil"},
                {"key": "amarres",         "name": "Amarres / tirantes",
                 "detail": "Anclajes de arriostramiento a fachada o andamio"},
                {"key": "bastidor_base",   "name": "Bastidor base",
                 "detail": "Base de apoyo con fijaciones al suelo"},
                {"key": "caja_carga",      "name": "Caja / plataforma de carga",
                 "detail": "Con compuertas y enganche al carro · 300 kg máx."},
            ],
        },
        {
            "section": "Cable eléctrico",
            "items": [
                {"key": "cable_50m",    "name": "Cable eléctrico 50 m",
                 "detail": "Sin empalmes · conectores en buen estado"},
                {"key": "cable_mando",  "name": "Cable de mando / botonera",
                 "detail": "Longitud adecuada a la altura de trabajo"},
            ],
        },
        {
            "section": "Kit obligatorio",
            "kit": True,
            "items": [
                {"key": "llave_servicio",    "name": "🔑 Llave de servicio Alimak",
                 "detail": "Panel de control y armario eléctrico"},
                {"key": "cajon_herramientas","name": "🧰 Cajón de herramientas",
                 "detail": "Herramientas de ajuste y mantenimiento básico"},
                {"key": "botonera",          "name": "Botonera de mando",
                 "detail": "Subida · Bajada · Parada emergencia — AT00019385"},
                {"key": "estacion_prueba",   "name": "Estación de prueba",
                 "detail": "Verificación de seguridades y límites — AT00019386"},
                {"key": "documentos",        "name": "Portadocumentos + Manual + CE",
                 "detail": "Manual ES, declaración CE, libro revisiones — AT00019557"},
                {"key": "kit_senalizacion",  "name": "Kit de señalización",
                 "detail": "Carteles carga máxima, prohibiciones — AT00019748"},
                {"key": "grasa",             "name": "Cartuchos de grasa (×2)",
                 "detail": "Sistema engrase piñón-cremallera — AT00019454"},
            ],
        },
    ],

    "geda_120s": [
        {
            "section": "Máquina",
            "items": [
                {"key": "maquina_completa", "name": "Maquinillo GEDA MAXI 120S completo",
                 "detail": "Motor, tambor, estructura y carcasa"},
                {"key": "cable_acero",      "name": "Cable de acero en tambor",
                 "detail": "Enrollado, sin daños ni empalmes"},
                {"key": "brazo_giratorio",  "name": "Brazo giratorio con soporte de andamio",
                 "detail": "Con fijaciones incluidas"},
            ],
        },
        {
            "section": "Kit obligatorio",
            "kit": True,
            "items": [
                {"key": "botonera",         "name": "Botonera de mando 10 m",
                 "detail": "Subida / bajada + parada emergencia — Art. 10970"},
                {"key": "ganchos",          "name": "Juego de 4 ganchos con enganches",
                 "detail": "Art. 01408"},
                {"key": "pertiga",          "name": "Pértiga guía de cable",
                 "detail": "Tubo por el que pasa el cable de elevación"},
                {"key": "amarre_gancho",    "name": "Amarre del gancho",
                 "detail": "Eslinga de seguridad del gancho principal — Art. 01827"},
                {"key": "candado",          "name": "Candado de bloqueo",
                 "detail": "Bloqueo del armario eléctrico — Art. 01429"},
                {"key": "documentos",       "name": "Manual de instrucciones + Declaración CE",
                 "detail": "En fundas protegidas, idioma español"},
            ],
        },
        {
            "section": "Eléctrico",
            "items": [
                {"key": "cable_alimentacion", "name": "Cable de alimentación CEE 16A 230V",
                 "detail": "Longitud suficiente para el punto de toma"},
            ],
        },
    ],

    "geda_150s": [
        {
            "section": "Máquina",
            "items": [
                {"key": "maquina_completa", "name": "Maquinillo GEDA MAXI 150S completo",
                 "detail": "Motor, tambor, estructura y carcasa"},
                {"key": "cable_acero",      "name": "Cable de acero en tambor",
                 "detail": "Enrollado, sin daños ni empalmes"},
                {"key": "brazo_giratorio",  "name": "Brazo giratorio con soporte de andamio",
                 "detail": "Con fijaciones incluidas"},
            ],
        },
        {
            "section": "Kit obligatorio",
            "kit": True,
            "items": [
                {"key": "botonera",         "name": "Botonera de mando 10 m",
                 "detail": "Subida / bajada + parada emergencia — Art. 10970"},
                {"key": "ganchos",          "name": "Juego de 4 ganchos con enganches",
                 "detail": "Art. 01408"},
                {"key": "pertiga",          "name": "Pértiga guía de cable",
                 "detail": "Tubo por el que pasa el cable de elevación"},
                {"key": "amarre_gancho",    "name": "Amarre del gancho",
                 "detail": "Eslinga de seguridad del gancho principal — Art. 01827"},
                {"key": "candado",          "name": "Candado de bloqueo",
                 "detail": "Bloqueo del armario eléctrico — Art. 01429"},
                {"key": "documentos",       "name": "Manual de instrucciones + Declaración CE",
                 "detail": "En fundas protegidas, idioma español"},
            ],
        },
        {
            "section": "Eléctrico",
            "items": [
                {"key": "cable_alimentacion", "name": "Cable de alimentación CEE 16A 230V",
                 "detail": "Longitud suficiente para el punto de toma"},
            ],
        },
    ],
}


def _tipo_checklist(maquina: Maquinaria, subtipo: str = None) -> Optional[str]:
    """Devuelve la clave de CHECKLISTS para esta máquina, o None si no aplica."""
    tipo = (maquina.tipo or "").lower()
    if "alimak" in tipo:
        return "alimak"
    if "maquinillo" in tipo:
        return f"geda_{subtipo}" if subtipo in ("120s", "150s") else "geda_120s"
    return None


def _tipo_checklist_herr(herramienta: Herramienta, subtipo: str = None) -> Optional[str]:
    """Devuelve la clave de CHECKLISTS para una herramienta, o None si no aplica."""
    sub = (herramienta.subcategoria or "").lower()
    cat = (herramienta.categoria or "").lower()
    nom = (herramienta.nombre or "").lower()
    if "alimak" in sub or "alimak" in cat or "alimak" in nom:
        return "alimak"
    if any(k in sub or k in cat or k in nom for k in ("geda", "maquinillo")):
        return f"geda_{subtipo}" if subtipo in ("120s", "150s") else "geda_120s"
    return None


def _todos_items(tipo_checklist: str) -> list:
    """Devuelve la lista plana de todos los ítems del checklist."""
    items = []
    for section in CHECKLISTS.get(tipo_checklist, []):
        items.extend(section["items"])
    return items


def _base_url(request: Request) -> str:
    """URL base de la app (proto + host)."""
    return str(request.base_url).rstrip("/")


# ─── RUTAS ────────────────────────────────────────────────────────────────────

@router.get("/maquinaria/{mid}/salida/nueva", response_class=HTMLResponse)
async def salida_nueva_form(
    mid: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(requiere_login),
):
    maquina = db.get(Maquinaria, mid)
    if not maquina:
        raise HTTPException(404)
    _require_operar(user)
    tipo_check = _tipo_checklist(maquina)
    return templates.TemplateResponse(request, "salida_nueva.html", {
        "user": user,
        "maquina": maquina,
        "es_geda": tipo_check and tipo_check.startswith("geda"),
        "es_alimak": tipo_check == "alimak",
    })


@router.post("/maquinaria/{mid}/salida/crear")
async def salida_crear(
    mid: int,
    request: Request,
    subtipo: str = Form(None),
    obra: str = Form(""),
    conductor: str = Form(""),
    responsable_patio: str = Form(""),
    jefe_obra: str = Form(""),
    kit_altura: str = Form(None),
    n_tramos: int = Form(None),
    cable_diametro: str = Form(None),
    observaciones: str = Form(""),
    event_id: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(requiere_login),
):
    maquina = db.get(Maquinaria, mid)
    if not maquina:
        raise HTTPException(404)
    _require_operar(user)

    event_id = event_id.strip() or None
    if event_id:
        previa = db.query(SalidaObra).filter(SalidaObra.event_id == event_id).first()
        if previa:
            return RedirectResponse(f"/maquinaria/{mid}/salida/{previa.id}", status_code=303)

    tipo_check = _tipo_checklist(maquina, subtipo)
    if not tipo_check:
        raise HTTPException(400, "Esta máquina no tiene checklist de salida")
    activa = db.query(SalidaObra).filter(
        SalidaObra.maquinaria_id == mid, SalidaObra.estado == "en_proceso"
    ).first()
    if activa:
        raise HTTPException(409, f"Ya existe una salida activa: {activa.id}")

    # Crear registro de salida
    salida = SalidaObra(
        maquinaria_id=mid,
        tipo_checklist=tipo_check,
        obra=obra or None,
        conductor=conductor or None,
        responsable_patio=responsable_patio or None,
        jefe_obra=jefe_obra or None,
        kit_altura=kit_altura or None,
        n_tramos=n_tramos,
        cable_diametro=cable_diametro or None,
        observaciones=observaciones or None,
        usuario_id=user.id,
        estado="en_proceso",
        event_id=event_id,
    )
    db.add(salida)
    try:
        db.flush()  # obtener salida.id
    except IntegrityError:
        db.rollback()
        if event_id:
            previa = db.query(SalidaObra).filter(SalidaObra.event_id == event_id).first()
            if previa:
                return RedirectResponse(f"/maquinaria/{mid}/salida/{previa.id}", status_code=303)
        raise

    # Crear ítems del checklist (todos desmarcados)
    for item in _todos_items(tipo_check):
        db.add(SalidaItem(
            salida_id=salida.id,
            item_key=item["key"],
            checked=False,
        ))

    db.commit()
    return RedirectResponse(
        f"/maquinaria/{mid}/salida/{salida.id}",
        status_code=303,
    )


@router.get("/maquinaria/{mid}/salida/{sid}", response_class=HTMLResponse)
async def salida_detalle(
    mid: int,
    sid: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(requiere_login),
):
    maquina = db.get(Maquinaria, mid)
    salida = db.get(SalidaObra, sid)
    if not maquina or not salida or salida.maquinaria_id != mid:
        raise HTTPException(404)

    # Mapa item_key → checked
    estado_items = {i.item_key: i.checked for i in salida.items}

    # URL base para QR estáticos
    base = _base_url(request)

    checklist = CHECKLISTS.get(salida.tipo_checklist, [])
    sections_con_qr = []
    for section in checklist:
        items_con_qr = []
        for item in section["items"]:
            url_qr = f"{base}/scan/salida/{mid}/{item['key']}"
            qr_b64 = generar_qr_base64(url_qr)
            items_con_qr.append({
                **item,
                "qr_b64": qr_b64,
                "qr_url": url_qr,
                "checked": estado_items.get(item["key"], False),
            })
        sections_con_qr.append({**section, "items": items_con_qr})

    total_checked = sum(1 for v in estado_items.values() if v)
    total_items = len(estado_items)

    return templates.TemplateResponse(request, "salida_maquinaria.html", {
        "user": user,
        "maquina": maquina,
        "salida": salida,
        "sections": sections_con_qr,
        "total_checked": total_checked,
        "total_items": total_items,
        "completo": total_items > 0 and total_checked == total_items,
    })


@router.get("/maquinaria/{mid}/salida/{sid}/estado")
async def salida_estado_json(
    mid: int,
    sid: int,
    db: Session = Depends(get_db),
    user=Depends(requiere_login),
):
    """Polling autenticado del estado actual de los ítems."""
    salida = db.get(SalidaObra, sid)
    if not salida or salida.maquinaria_id != mid:
        raise HTTPException(404)
    _require_operar(user)
    return JSONResponse({
        "items": {i.item_key: i.checked for i in salida.items},
        "estado": salida.estado,
    })


@router.post("/maquinaria/{mid}/salida/{sid}/completar")
async def salida_completar(
    mid: int,
    sid: int,
    db: Session = Depends(get_db),
    user=Depends(requiere_login),
):
    salida = db.get(SalidaObra, sid)
    if not salida or salida.maquinaria_id != mid:
        raise HTTPException(404)
    _require_operar(user)
    _require_completa(salida)
    salida.estado = "completada"
    db.commit()
    return RedirectResponse(f"/maquinaria/{mid}/salida/{sid}", status_code=303)


@router.get("/maquinaria/{mid}/salidas", response_class=HTMLResponse)
async def salidas_historial(
    mid: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(requiere_login),
):
    maquina = db.get(Maquinaria, mid)
    if not maquina:
        raise HTTPException(404)
    salidas = (
        db.query(SalidaObra)
        .filter(SalidaObra.maquinaria_id == mid)
        .order_by(SalidaObra.fecha_salida.desc())
        .all()
    )
    return templates.TemplateResponse(request, "salidas_historial.html", {
        "user": user,
        "maquina": maquina,
        "salidas": salidas,
    })


# ─── SCAN QR ──────────────────────────────────────────────────────────────────

@router.get("/scan/salida/{mid}/{item_key}", response_class=HTMLResponse)
async def scan_item_salida(
    mid: int,
    item_key: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(requiere_login),
):
    """
    URL codificada en el QR estático.
    Busca la salida activa (en_proceso) de la máquina y marca el ítem.
    Requiere sesión y permiso operativo también desde móvil.
    """
    _require_operar(user)
    maquina = db.get(Maquinaria, mid)
    if not maquina:
        return templates.TemplateResponse(request, "scan_salida.html", {
            "ok": False,
            "error": "Máquina no encontrada",
            "maquina": None,
            "item_name": item_key,
            "item_detail": "",
            "obra": "—",
            "marcados": 0,
            "total": 0,
        }, status_code=404)

    # Buscar salida activa
    salida = (
        db.query(SalidaObra)
        .filter(
            SalidaObra.maquinaria_id == mid,
            SalidaObra.estado == "en_proceso",
        )
        .order_by(SalidaObra.created_at.desc())
        .first()
    )

    if not salida:
        return templates.TemplateResponse(request, "scan_salida.html", {
            "ok": False,
            "error": "No hay ninguna salida activa para esta máquina",
            "maquina": maquina,
            "item_name": item_key,
            "item_detail": "",
            "obra": "—",
            "marcados": 0,
            "total": 0,
        }, status_code=404)

    # Buscar el ítem y su nombre legible en el checklist
    checklist = CHECKLISTS.get(salida.tipo_checklist, [])
    item_info = None
    for section in checklist:
        for it in section["items"]:
            if it["key"] == item_key:
                item_info = it
                break
        if item_info:
            break

    if not item_info:
        return templates.TemplateResponse(request, "scan_salida.html", {
            "ok": False,
            "error": f"Ítem '{item_key}' no reconocido en este checklist",
            "maquina": maquina,
            "item_name": item_key,
            "item_detail": "",
            "obra": salida.obra or "—",
            "marcados": 0,
            "total": len(salida.items),
        }, status_code=400)

    # Obtener el ítem de BD y marcarlo si no lo estaba
    db_item = (
        db.query(SalidaItem)
        .filter(
            SalidaItem.salida_id == salida.id,
            SalidaItem.item_key == item_key,
        )
        .first()
    )

    ya_marcado = db_item.checked if db_item else False

    if db_item and not db_item.checked:
        db_item.checked = True
        db_item.checked_at = datetime.utcnow()
        db_item.checked_by = request.client.host if request.client else "—"
        db.commit()

    # Contar ítems marcados (re-consultar tras el commit para datos frescos)
    total = db.query(SalidaItem).filter(SalidaItem.salida_id == salida.id).count()
    marcados = db.query(SalidaItem).filter(
        SalidaItem.salida_id == salida.id,
        SalidaItem.checked == True,
    ).count()

    return templates.TemplateResponse(request, "scan_salida.html", {
        "ok": True,
        "ya_marcado": ya_marcado,
        "maquina": maquina,
        "salida": salida,
        "item_name": item_info["name"],
        "item_detail": item_info.get("detail", ""),
        "marcados": marcados,
        "total": total,
        "obra": salida.obra or "—",
    })


# ─── RUTAS HERRAMIENTAS ───────────────────────────────────────────────────────

@router.get("/herramienta/{hid}/salida/nueva", response_class=HTMLResponse)
async def herr_salida_nueva_form(
    hid: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(requiere_login),
):
    herr = db.get(Herramienta, hid)
    if not herr:
        raise HTTPException(404)
    _require_operar(user)
    tipo_check = _tipo_checklist_herr(herr)
    return templates.TemplateResponse(request, "salida_nueva.html", {
        "user": user,
        "maquina": herr,          # reutiliza la misma plantilla
        "es_herramienta": True,
        "es_geda": tipo_check and tipo_check.startswith("geda"),
        "es_alimak": tipo_check == "alimak",
    })


@router.post("/herramienta/{hid}/salida/crear")
async def herr_salida_crear(
    hid: int,
    request: Request,
    subtipo: str = Form(None),
    obra: str = Form(""),
    conductor: str = Form(""),
    responsable_patio: str = Form(""),
    jefe_obra: str = Form(""),
    kit_altura: str = Form(None),
    n_tramos: int = Form(None),
    cable_diametro: str = Form(None),
    observaciones: str = Form(""),
    event_id: str = Form(""),
    db: Session = Depends(get_db),
    user=Depends(requiere_login),
):
    herr = db.get(Herramienta, hid)
    if not herr:
        raise HTTPException(404)
    _require_operar(user)

    event_id = event_id.strip() or None
    if event_id:
        previa = db.query(SalidaObra).filter(SalidaObra.event_id == event_id).first()
        if previa:
            return RedirectResponse(f"/herramienta/{hid}/salida/{previa.id}", status_code=303)

    tipo_check = _tipo_checklist_herr(herr, subtipo)
    if not tipo_check:
        raise HTTPException(400, "Esta herramienta no tiene checklist de salida")
    activa = db.query(SalidaObra).filter(
        SalidaObra.herramienta_id == hid, SalidaObra.estado == "en_proceso"
    ).first()
    if activa:
        raise HTTPException(409, f"Ya existe una salida activa: {activa.id}")

    salida = SalidaObra(
        herramienta_id=hid,
        tipo_checklist=tipo_check,
        obra=obra or None,
        conductor=conductor or None,
        responsable_patio=responsable_patio or None,
        jefe_obra=jefe_obra or None,
        kit_altura=kit_altura or None,
        n_tramos=n_tramos,
        cable_diametro=cable_diametro or None,
        observaciones=observaciones or None,
        usuario_id=user.id,
        estado="en_proceso",
        event_id=event_id,
    )
    db.add(salida)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        if event_id:
            previa = db.query(SalidaObra).filter(SalidaObra.event_id == event_id).first()
            if previa:
                return RedirectResponse(f"/herramienta/{hid}/salida/{previa.id}", status_code=303)
        raise

    for item in _todos_items(tipo_check):
        db.add(SalidaItem(salida_id=salida.id, item_key=item["key"], checked=False))

    db.commit()
    return RedirectResponse(f"/herramienta/{hid}/salida/{salida.id}", status_code=303)


@router.get("/herramienta/{hid}/salida/{sid}", response_class=HTMLResponse)
async def herr_salida_detalle(
    hid: int,
    sid: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(requiere_login),
):
    herr = db.get(Herramienta, hid)
    salida = db.get(SalidaObra, sid)
    if not herr or not salida or salida.herramienta_id != hid:
        raise HTTPException(404)

    estado_items = {i.item_key: i.checked for i in salida.items}
    base = _base_url(request)
    checklist = CHECKLISTS.get(salida.tipo_checklist, [])
    sections_con_qr = []
    for section in checklist:
        items_con_qr = []
        for item in section["items"]:
            url_qr = f"{base}/scan/salida/h/{hid}/{item['key']}"
            qr_b64 = generar_qr_base64(url_qr)
            items_con_qr.append({
                **item,
                "qr_b64": qr_b64,
                "qr_url": url_qr,
                "checked": estado_items.get(item["key"], False),
            })
        sections_con_qr.append({**section, "items": items_con_qr})

    total_checked = sum(1 for v in estado_items.values() if v)
    total_items = len(estado_items)

    return templates.TemplateResponse(request, "salida_maquinaria.html", {
        "user": user,
        "maquina": herr,
        "salida": salida,
        "sections": sections_con_qr,
        "total_checked": total_checked,
        "total_items": total_items,
        "completo": total_items > 0 and total_checked == total_items,
        "es_herramienta": True,
    })


@router.get("/herramienta/{hid}/salida/{sid}/estado")
async def herr_salida_estado_json(
    hid: int,
    sid: int,
    db: Session = Depends(get_db),
    user=Depends(requiere_login),
):
    salida = db.get(SalidaObra, sid)
    if not salida or salida.herramienta_id != hid:
        raise HTTPException(404)
    _require_operar(user)
    return JSONResponse({
        "items": {i.item_key: i.checked for i in salida.items},
        "estado": salida.estado,
    })


@router.post("/herramienta/{hid}/salida/{sid}/completar")
async def herr_salida_completar(
    hid: int,
    sid: int,
    db: Session = Depends(get_db),
    user=Depends(requiere_login),
):
    salida = db.get(SalidaObra, sid)
    if not salida or salida.herramienta_id != hid:
        raise HTTPException(404)
    _require_operar(user)
    _require_completa(salida)
    salida.estado = "completada"
    db.commit()
    return RedirectResponse(f"/herramienta/{hid}/salida/{sid}", status_code=303)


@router.get("/herramienta/{hid}/salidas", response_class=HTMLResponse)
async def herr_salidas_historial(
    hid: int,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(requiere_login),
):
    herr = db.get(Herramienta, hid)
    if not herr:
        raise HTTPException(404)
    salidas = (
        db.query(SalidaObra)
        .filter(SalidaObra.herramienta_id == hid)
        .order_by(SalidaObra.fecha_salida.desc())
        .all()
    )
    return templates.TemplateResponse(request, "salidas_historial.html", {
        "user": user,
        "maquina": herr,
        "salidas": salidas,
        "es_herramienta": True,
    })


@router.get("/scan/salida/h/{hid}/{item_key}", response_class=HTMLResponse)
async def scan_item_salida_herr(
    hid: int,
    item_key: str,
    request: Request,
    db: Session = Depends(get_db),
    user=Depends(requiere_login),
):
    _require_operar(user)
    herr = db.get(Herramienta, hid)
    if not herr:
        return templates.TemplateResponse(request, "scan_salida.html", {
            "ok": False, "error": "Herramienta no encontrada",
            "maquina": None, "item_name": item_key, "item_detail": "",
            "obra": "—", "marcados": 0, "total": 0,
        }, status_code=404)

    salida = (
        db.query(SalidaObra)
        .filter(SalidaObra.herramienta_id == hid, SalidaObra.estado == "en_proceso")
        .order_by(SalidaObra.created_at.desc())
        .first()
    )
    if not salida:
        return templates.TemplateResponse(request, "scan_salida.html", {
            "ok": False, "error": "No hay ninguna salida activa para esta herramienta",
            "maquina": herr, "item_name": item_key, "item_detail": "",
            "obra": "—", "marcados": 0, "total": 0,
        }, status_code=404)

    checklist = CHECKLISTS.get(salida.tipo_checklist, [])
    item_info = None
    for section in checklist:
        for it in section["items"]:
            if it["key"] == item_key:
                item_info = it
                break
        if item_info:
            break

    if not item_info:
        return templates.TemplateResponse(request, "scan_salida.html", {
            "ok": False, "error": f"Ítem '{item_key}' no reconocido en este checklist",
            "maquina": herr, "item_name": item_key, "item_detail": "",
            "obra": salida.obra or "—", "marcados": 0, "total": len(salida.items),
        }, status_code=400)

    db_item = (
        db.query(SalidaItem)
        .filter(SalidaItem.salida_id == salida.id, SalidaItem.item_key == item_key)
        .first()
    )
    ya_marcado = db_item.checked if db_item else False
    if db_item and not db_item.checked:
        db_item.checked = True
        db_item.checked_at = datetime.utcnow()
        db_item.checked_by = request.client.host if request.client else "—"
        db.commit()

    total = db.query(SalidaItem).filter(SalidaItem.salida_id == salida.id).count()
    marcados = db.query(SalidaItem).filter(
        SalidaItem.salida_id == salida.id, SalidaItem.checked == True,
    ).count()

    return templates.TemplateResponse(request, "scan_salida.html", {
        "ok": True,
        "ya_marcado": ya_marcado,
        "maquina": herr,
        "salida": salida,
        "item_name": item_info["name"],
        "item_detail": item_info.get("detail", ""),
        "marcados": marcados,
        "total": total,
        "obra": salida.obra or "—",
    })
