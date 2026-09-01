"""
api_externa.py — API REST para integración con ERP / sistemas externos
Autenticación: cabecera X-API-Key (configura en config/local.env: MRD_API_KEY=tu_clave)
Swagger UI disponible en: http://localhost:8000/api/docs

Endpoints:
  GET  /api/v1/herramientas          Lista paginada de herramientas
  GET  /api/v1/herramientas/{id}     Detalle de herramienta
  GET  /api/v1/trabajadores          Lista de trabajadores activos
  GET  /api/v1/movimientos           Últimos movimientos (paginado)
  GET  /api/v1/materiales            Stock de materiales
  GET  /api/v1/stock/alertas         Materiales bajo mínimo
  POST /api/v1/movimientos/entrada   Registrar entrada de material
"""
from __future__ import annotations

import os
import logging
from datetime import datetime
from typing import Optional, List

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("mrd.api_externa")

# ── Sub-aplicación FastAPI con sus propios docs ────────────────────────────────
api_app = FastAPI(
    title="MRD TOOL CONTROL — API Externa",
    description="""
## API REST para integración con ERP y sistemas externos.

**Autenticación**: incluye la cabecera `X-API-Key` en todas las peticiones.
Configura la clave en `config/local.env`:
```
MRD_API_KEY=tu_clave_secreta_aqui
```

**Base URL**: `http://tu-servidor:8000/api`
""",
    version="1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# ── Autenticación ──────────────────────────────────────────────────────────────

def _api_key_valida(x_api_key: str = Header(..., alias="X-API-Key")) -> str:
    clave = os.getenv("MRD_API_KEY", "").strip()
    if not clave:
        raise HTTPException(503, "API no configurada: define MRD_API_KEY en config/local.env")
    if x_api_key != clave:
        raise HTTPException(401, "API Key inválida")
    return x_api_key


# ── Schemas de respuesta ───────────────────────────────────────────────────────

class HerramientaOut(BaseModel):
    id: int
    codigo: str
    nombre: str
    categoria: Optional[str]
    marca: Optional[str]
    modelo: Optional[str]
    estado: str
    ubicacion: Optional[str]
    precio_compra: Optional[float]
    valor_actual: Optional[float]
    responsable: Optional[str]
    obra: Optional[str]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class TrabajadorOut(BaseModel):
    id: int
    nombre: str
    apellidos: Optional[str]
    dni: Optional[str]
    puesto: Optional[str]
    activo: bool

    class Config:
        from_attributes = True


class MovimientoOut(BaseModel):
    id: int
    tipo: str
    herramienta_codigo: Optional[str]
    herramienta_nombre: Optional[str]
    estado_anterior: Optional[str]
    estado_nuevo: Optional[str]
    destino: Optional[str]
    usuario: Optional[str]
    trabajador: Optional[str]
    obra: Optional[str]
    fecha: Optional[datetime]
    observaciones: Optional[str]


class MaterialOut(BaseModel):
    id: int
    nombre: str
    referencia: Optional[str]
    categoria: Optional[str]
    unidad: Optional[str]
    stock_actual: Optional[float]
    stock_minimo: Optional[float]
    stock_maximo: Optional[float]
    precio_unidad: Optional[float]
    bajo_minimo: bool


class EntradaMaterialIn(BaseModel):
    material_id: int
    cantidad: float
    referencia: Optional[str] = None
    observaciones: Optional[str] = None


# ── Endpoints ──────────────────────────────────────────────────────────────────

@api_app.get(
    "/v1/herramientas",
    response_model=List[HerramientaOut],
    tags=["Herramientas"],
    summary="Lista de herramientas",
)
def api_herramientas(
    estado: Optional[str] = Query(None, description="Filtrar por estado (disponible, entregada, en_obra...)"),
    categoria: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _: str = Depends(_api_key_valida),
):
    """Devuelve la lista paginada de herramientas activas."""
    from database import SessionLocal
    from models import Herramienta
    db = SessionLocal()
    try:
        q = db.query(Herramienta).filter(Herramienta.activa == True)
        if estado:
            q = q.filter(Herramienta.estado == estado)
        if categoria:
            q = q.filter(Herramienta.categoria == categoria)
        herrs = q.order_by(Herramienta.codigo).offset((page-1)*page_size).limit(page_size).all()
        return [HerramientaOut(
            id=h.id, codigo=h.codigo, nombre=h.nombre,
            categoria=h.categoria, marca=h.marca, modelo=h.modelo,
            estado=h.estado, ubicacion=h.ubicacion_texto,
            precio_compra=h.precio_compra, valor_actual=h.valor_actual,
            responsable=h.responsable.nombre_completo if h.responsable else None,
            obra=h.obra.nombre if h.obra else None,
            updated_at=h.updated_at,
        ) for h in herrs]
    finally:
        db.close()


@api_app.get(
    "/v1/herramientas/{hid}",
    response_model=HerramientaOut,
    tags=["Herramientas"],
    summary="Detalle de herramienta",
)
def api_herramienta_detalle(
    hid: int,
    _: str = Depends(_api_key_valida),
):
    """Devuelve el detalle completo de una herramienta por ID."""
    from database import SessionLocal
    from models import Herramienta
    db = SessionLocal()
    try:
        h = db.query(Herramienta).filter(Herramienta.id == hid, Herramienta.activa == True).first()
        if not h:
            raise HTTPException(404, "Herramienta no encontrada")
        return HerramientaOut(
            id=h.id, codigo=h.codigo, nombre=h.nombre,
            categoria=h.categoria, marca=h.marca, modelo=h.modelo,
            estado=h.estado, ubicacion=h.ubicacion_texto,
            precio_compra=h.precio_compra, valor_actual=h.valor_actual,
            responsable=h.responsable.nombre_completo if h.responsable else None,
            obra=h.obra.nombre if h.obra else None,
            updated_at=h.updated_at,
        )
    finally:
        db.close()


@api_app.get(
    "/v1/trabajadores",
    response_model=List[TrabajadorOut],
    tags=["Trabajadores"],
    summary="Lista de trabajadores",
)
def api_trabajadores(
    activo: Optional[bool] = Query(None),
    _: str = Depends(_api_key_valida),
):
    """Devuelve la lista de trabajadores."""
    from database import SessionLocal
    from models import Trabajador
    db = SessionLocal()
    try:
        q = db.query(Trabajador)
        if activo is not None:
            q = q.filter(Trabajador.activo == activo)
        return [TrabajadorOut(
            id=t.id,
            nombre=t.nombre,
            apellidos=t.apellidos,
            dni=t.dni,
            puesto=getattr(t, "puesto", None),
            activo=t.activo,
        ) for t in q.order_by(Trabajador.nombre).all()]
    finally:
        db.close()


@api_app.get(
    "/v1/movimientos",
    response_model=List[MovimientoOut],
    tags=["Movimientos"],
    summary="Últimos movimientos",
)
def api_movimientos(
    tipo: Optional[str] = Query(None, description="entrega, devolucion, traslado..."),
    herramienta_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    _: str = Depends(_api_key_valida),
):
    """Devuelve los últimos movimientos de herramientas, ordenados por fecha descendente."""
    from database import SessionLocal
    from models import Movimiento
    db = SessionLocal()
    try:
        q = db.query(Movimiento)
        if tipo:
            q = q.filter(Movimiento.tipo == tipo)
        if herramienta_id:
            q = q.filter(Movimiento.herramienta_id == herramienta_id)
        movs = q.order_by(Movimiento.fecha.desc()).offset((page-1)*page_size).limit(page_size).all()
        return [MovimientoOut(
            id=m.id, tipo=m.tipo,
            herramienta_codigo=m.herramienta.codigo if m.herramienta else None,
            herramienta_nombre=m.herramienta.nombre if m.herramienta else None,
            estado_anterior=m.estado_anterior, estado_nuevo=m.estado_nuevo,
            destino=m.destino,
            usuario=m.usuario.username if m.usuario else None,
            trabajador=m.trabajador.nombre_completo if m.trabajador else None,
            obra=m.obra.nombre if m.obra else None,
            fecha=m.fecha, observaciones=m.observaciones,
        ) for m in movs]
    finally:
        db.close()


@api_app.get(
    "/v1/materiales",
    response_model=List[MaterialOut],
    tags=["Materiales"],
    summary="Stock de materiales",
)
def api_materiales(
    bajo_minimo: Optional[bool] = Query(None, description="True para mostrar solo los que están bajo mínimo"),
    _: str = Depends(_api_key_valida),
):
    """Devuelve el inventario de materiales con su stock actual."""
    from database import SessionLocal
    from models import Material
    db = SessionLocal()
    try:
        mats = db.query(Material).filter(Material.activo == True).order_by(Material.nombre).all()
        result = []
        for m in mats:
            bm = (m.stock_actual or 0) <= (m.stock_minimo or 0) and (m.stock_minimo or 0) > 0
            if bajo_minimo is not None and bm != bajo_minimo:
                continue
            result.append(MaterialOut(
                id=m.id, nombre=m.nombre, referencia=m.referencia,
                categoria=m.categoria, unidad=m.unidad,
                stock_actual=m.stock_actual, stock_minimo=m.stock_minimo,
                stock_maximo=m.stock_maximo, precio_unidad=m.precio_unidad,
                bajo_minimo=bm,
            ))
        return result
    finally:
        db.close()


@api_app.get(
    "/v1/stock/alertas",
    tags=["Materiales"],
    summary="Materiales bajo stock mínimo",
)
def api_stock_alertas(_: str = Depends(_api_key_valida)):
    """Devuelve solo los materiales cuyo stock actual está por debajo del mínimo configurado."""
    from database import SessionLocal
    from models import Material
    db = SessionLocal()
    try:
        mats = db.query(Material).filter(
            Material.activo == True,
            Material.stock_minimo > 0,
        ).all()
        return [
            {"id": m.id, "nombre": m.nombre, "referencia": m.referencia,
             "stock_actual": m.stock_actual, "stock_minimo": m.stock_minimo,
             "unidad": m.unidad, "faltante": max(0, (m.stock_minimo or 0) - (m.stock_actual or 0))}
            for m in mats if (m.stock_actual or 0) <= (m.stock_minimo or 0)
        ]
    finally:
        db.close()


@api_app.post(
    "/v1/movimientos/entrada",
    tags=["Materiales"],
    summary="Registrar entrada de material",
    status_code=201,
)
def api_entrada_material(
    body: EntradaMaterialIn,
    _: str = Depends(_api_key_valida),
):
    """Registra una entrada de stock para un material (desde pedido ERP)."""
    from database import SessionLocal
    from models import Material, MovimientoMaterial
    db = SessionLocal()
    try:
        mat = db.query(Material).filter(Material.id == body.material_id, Material.activo == True).first()
        if not mat:
            raise HTTPException(404, "Material no encontrado")
        mat.stock_actual = (mat.stock_actual or 0) + body.cantidad
        mov = MovimientoMaterial(
            material_id=mat.id,
            tipo="entrada",
            cantidad=body.cantidad,
            referencia=body.referencia,
            observaciones=body.observaciones or "Entrada vía API externa",
        )
        db.add(mov)
        db.commit()
        return {"ok": True, "material_id": mat.id, "stock_nuevo": mat.stock_actual}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()


@api_app.get("/v1/health", tags=["Sistema"], summary="Estado del sistema")
def api_health(_: str = Depends(_api_key_valida)):
    """Comprueba que la API está activa."""
    from config import VERSION
    return {"status": "ok", "version": VERSION, "timestamp": datetime.now().isoformat()}
