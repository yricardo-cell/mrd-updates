"""
Modelos SQLAlchemy V2 - MRD TOOL CONTROL
Basado en especificaciones completas Vol I + Tomo III
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean,
    DateTime, Text, ForeignKey, Date, Index, UniqueConstraint, CheckConstraint,
    event as sqlalchemy_event, text
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


# ─── Configuración y Metadatos ───────────────────────────────────────────────

class Delegacion(Base):
    __tablename__ = "delegaciones"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(20), unique=True, index=True, nullable=False)
    nombre = Column(String(100), nullable=False)
    direccion = Column(String(255), nullable=True)
    telefono = Column(String(20), nullable=True)
    email = Column(String(100), nullable=True)
    responsable = Column(String(100), nullable=True)
    activa = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class ConfigSistema(Base):
    __tablename__ = "config_sistema"

    id = Column(Integer, primary_key=True)
    clave = Column(String(100), unique=True, nullable=False, index=True)
    valor = Column(Text, nullable=True)
    tipo = Column(String(20), default="string")  # string, int, bool, json, color
    descripcion = Column(String(255), nullable=True)
    modulo = Column(String(50), nullable=True)
    updated_at = Column(DateTime, onupdate=func.now())
    updated_by_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)


class Categoria(Base):
    __tablename__ = "categorias"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), nullable=False)
    tipo = Column(String(50), nullable=False, index=True)  # herramienta, material, vehiculo
    descripcion = Column(Text, nullable=True)
    icono = Column(String(50), nullable=True)
    color = Column(String(20), nullable=True)
    activa = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())


class Proveedor(Base):
    __tablename__ = "proveedores"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), unique=True, index=True, nullable=True)
    nombre = Column(String(200), nullable=False)
    cif = Column(String(20), nullable=True)
    direccion = Column(String(255), nullable=True)
    telefono = Column(String(20), nullable=True)
    email = Column(String(100), nullable=True)
    web = Column(String(255), nullable=True)
    contacto = Column(String(100), nullable=True)
    observaciones = Column(Text, nullable=True)
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    herramientas = relationship("Herramienta", back_populates="proveedor_rel",
                                foreign_keys="Herramienta.proveedor_id")
    reparaciones = relationship("Reparacion", back_populates="proveedor",
                                foreign_keys="Reparacion.proveedor_id")


# ─── Usuarios ────────────────────────────────────────────────────────────────

class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    nombre = Column(String(100), nullable=False)
    email = Column(String(100), nullable=True)
    telefono = Column(String(20), nullable=True)
    rol = Column(String(20), default="consulta", index=True)
    delegacion_id = Column(Integer, ForeignKey("delegaciones.id"), nullable=True)
    # Los administradores dejan este campo vacío y pueden cambiar de almacén.
    # El resto de usuarios queda limitado al almacén asignado.
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=True, index=True)
    activo = Column(Boolean, default=True)
    avatar = Column(String(255), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    last_login = Column(DateTime, nullable=True)
    must_change_password = Column(Boolean, default=True, nullable=False, server_default='1')
    totp_secret = Column(String(64), nullable=True)
    totp_habilitado = Column(Boolean, default=False, nullable=False, server_default='0')

    almacen = relationship("Almacen", foreign_keys=[almacen_id])
    movimientos = relationship("Movimiento", back_populates="usuario",
                               foreign_keys="Movimiento.usuario_id")
    auditorias = relationship("AuditoriaLog", back_populates="usuario",
                              foreign_keys="AuditoriaLog.usuario_id")


class SecuenciaCodigo(Base):
    """Secuencia auxiliar; nunca contiene el identificador asignado al artículo."""
    __tablename__ = "secuencias_codigo"

    prefijo = Column(String(20), primary_key=True)
    ultimo = Column(Integer, nullable=False, default=0)


class IdentificadorGlobal(Base):
    """Reserva central y global de referencias internas y códigos QR."""
    __tablename__ = "identificadores_globales"
    __table_args__ = (
        UniqueConstraint("referencia_interna", name="uq_identificador_referencia_global"),
        UniqueConstraint("codigo_qr", name="uq_identificador_qr_global"),
        UniqueConstraint("propietario_clave", name="uq_identificador_propietario"),
    )

    id = Column(Integer, primary_key=True)
    referencia_interna = Column(String(50), nullable=False)
    codigo_qr = Column(String(50), nullable=False)
    propietario_tipo = Column(String(30), nullable=False)
    propietario_clave = Column(String(64), nullable=False)
    creado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, server_default=func.now())


# ─── Trabajadores ────────────────────────────────────────────────────────────

class Trabajador(Base):
    __tablename__ = "trabajadores"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), unique=True, index=True, nullable=True)
    nombre = Column(String(100), nullable=False)
    apellidos = Column(String(100), nullable=True, default="")
    dni = Column(String(20), nullable=True)
    telefono = Column(String(20), nullable=True)
    email = Column(String(100), nullable=True)
    empresa = Column(String(100), nullable=True, default="MRD Estructuras")
    cargo = Column(String(100), nullable=True)
    departamento = Column(String(100), nullable=True)
    delegacion_id = Column(Integer, ForeignKey("delegaciones.id"), nullable=True)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=True, index=True)
    activo = Column(Boolean, default=True)
    foto = Column(String(255), nullable=True)
    observaciones = Column(Text, nullable=True)
    talla_ropa = Column(String(20), nullable=True)
    talla_calzado = Column(String(20), nullable=True)
    portal_token = Column(String(64), nullable=True, unique=True, index=True)
    portal_pin_hash = Column(String(255), nullable=True)
    portal_pin_actualizado_en = Column(DateTime, nullable=True)
    portal_pin_cambio_obligatorio = Column(Boolean, nullable=False, default=False)
    portal_contacto_verificado_en = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    herramientas = relationship("Herramienta", back_populates="responsable",
                                foreign_keys="Herramienta.responsable_id")
    movimientos = relationship("Movimiento", back_populates="trabajador",
                               foreign_keys="Movimiento.trabajador_id")
    solicitudes = relationship(
        "SolicitudTrabajador", back_populates="trabajador",
        foreign_keys="SolicitudTrabajador.trabajador_id",
    )
    comunicaciones = relationship(
        "ComunicacionTrabajador", back_populates="trabajador",
        foreign_keys="ComunicacionTrabajador.trabajador_id",
    )
    notificaciones_portal = relationship(
        "NotificacionTrabajador", back_populates="trabajador",
        cascade="all, delete-orphan",
    )
    incidencias_portal = relationship(
        "IncidenciaPortalTrabajador", back_populates="trabajador",
        cascade="all, delete-orphan",
    )
    devoluciones_portal = relationship(
        "SolicitudDevolucionTrabajador", back_populates="trabajador",
        cascade="all, delete-orphan",
    )

    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellidos or ''}".strip()


ESTADOS_SOLICITUD_TRABAJADOR = (
    "pendiente", "revision", "aprobada", "preparando", "lista",
    "entregada", "rechazada", "cancelada",
)
TIPOS_SOLICITUD_TRABAJADOR = ("ropa", "epi", "herramienta", "maquinaria", "consumible", "otro")
TIPOS_COMUNICACION_TRABAJADOR = ("sugerencia", "queja", "material", "seguridad")
PRIVACIDAD_COMUNICACION_TRABAJADOR = ("identificada", "confidencial", "anonima")


class SolicitudTrabajador(Base):
    """Petición trazable de ropa, EPI, herramienta o consumible."""
    __tablename__ = "solicitudes_trabajador"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('pendiente','revision','aprobada','preparando','lista','entregada','rechazada','cancelada')",
            name="ck_solicitud_trabajador_estado",
        ),
        UniqueConstraint("submission_id", name="uq_solicitud_trabajador_submission"),
    )

    id = Column(Integer, primary_key=True)
    numero = Column(String(40), nullable=False, unique=True, index=True)
    submission_id = Column(String(64), nullable=False, unique=True, index=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=False, index=True)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=True, index=True)
    estado = Column(String(20), nullable=False, default="pendiente", index=True)
    prioridad = Column(String(20), nullable=False, default="normal")
    # Compatibilidad con el buzón móvil anterior a 2.6.
    tipo = Column(String(20), nullable=True)
    categoria = Column(String(50), nullable=True)
    asunto = Column(String(200), nullable=True)
    mensaje = Column(Text, nullable=True)
    cantidad = Column(Integer, nullable=True)
    respuesta = Column(Text, nullable=True)
    respondido_en = Column(DateTime, nullable=True)
    obra_destino = Column(String(200), nullable=True)
    motivo = Column(Text, nullable=True)
    notas_gestion = Column(Text, nullable=True)
    revisado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    actualizado_en = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    entregado_en = Column(DateTime, nullable=True)
    fecha_estimada = Column(DateTime, nullable=True)
    cancelada_por_trabajador_en = Column(DateTime, nullable=True)
    recogida_confirmada_en = Column(DateTime, nullable=True)

    trabajador = relationship("Trabajador", back_populates="solicitudes", foreign_keys=[trabajador_id])
    almacen = relationship("Almacen", foreign_keys=[almacen_id])
    revisado_por = relationship("Usuario", foreign_keys=[revisado_por_id])
    lineas = relationship(
        "LineaSolicitudTrabajador", back_populates="solicitud",
        cascade="all, delete-orphan", order_by="LineaSolicitudTrabajador.id",
    )
    comentarios = relationship(
        "ComentarioSolicitudTrabajador", back_populates="solicitud",
        cascade="all, delete-orphan", order_by="ComentarioSolicitudTrabajador.creado_en",
    )


class LineaSolicitudTrabajador(Base):
    __tablename__ = "lineas_solicitud_trabajador"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_linea_solicitud_cantidad"),
        CheckConstraint(
            "tipo IN ('ropa','epi','herramienta','maquinaria','consumible','otro')",
            name="ck_linea_solicitud_tipo",
        ),
    )

    id = Column(Integer, primary_key=True)
    solicitud_id = Column(Integer, ForeignKey("solicitudes_trabajador.id"), nullable=False, index=True)
    tipo = Column(String(20), nullable=False)
    descripcion = Column(String(200), nullable=False)
    talla = Column(String(30), nullable=True)
    cantidad = Column(Integer, nullable=False, default=1)
    cantidad_aprobada = Column(Integer, nullable=True)
    observaciones = Column(Text, nullable=True)

    solicitud = relationship("SolicitudTrabajador", back_populates="lineas")


class ComunicacionTrabajador(Base):
    """Buzón privado. En modo anónimo nunca conserva trabajador_id."""
    __tablename__ = "comunicaciones_trabajador"
    __table_args__ = (
        CheckConstraint(
            "tipo IN ('sugerencia','queja','material','seguridad')",
            name="ck_comunicacion_trabajador_tipo",
        ),
        CheckConstraint(
            "privacidad IN ('identificada','confidencial','anonima')",
            name="ck_comunicacion_trabajador_privacidad",
        ),
        CheckConstraint(
            "estado IN ('recibida','revision','actuacion','resuelta','archivada')",
            name="ck_comunicacion_trabajador_estado",
        ),
    )

    id = Column(Integer, primary_key=True)
    numero = Column(String(40), nullable=False, unique=True, index=True)
    seguimiento_token = Column(String(64), nullable=False, unique=True, index=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=True, index=True)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=True, index=True)
    tipo = Column(String(20), nullable=False)
    privacidad = Column(String(20), nullable=False, default="identificada")
    asunto = Column(String(200), nullable=False)
    mensaje = Column(Text, nullable=False)
    obra = Column(String(200), nullable=True)
    estado = Column(String(20), nullable=False, default="recibida", index=True)
    respuesta = Column(Text, nullable=True)
    respondido_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    respondido_en = Column(DateTime, nullable=True)

    trabajador = relationship("Trabajador", back_populates="comunicaciones", foreign_keys=[trabajador_id])
    almacen = relationship("Almacen", foreign_keys=[almacen_id])
    respondido_por = relationship("Usuario", foreign_keys=[respondido_por_id])


class NotificacionTrabajador(Base):
    """Aviso privado visible únicamente para el trabajador destinatario."""
    __tablename__ = "notificaciones_trabajador"

    id = Column(Integer, primary_key=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=False, index=True)
    tipo = Column(String(40), nullable=False, default="sistema")
    titulo = Column(String(160), nullable=False)
    mensaje = Column(Text, nullable=False)
    enlace = Column(String(500), nullable=True)
    evento_clave = Column(String(120), nullable=True, unique=True)
    creado_en = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    leida_en = Column(DateTime, nullable=True)

    trabajador = relationship("Trabajador", back_populates="notificaciones_portal")


class ComentarioSolicitudTrabajador(Base):
    __tablename__ = "comentarios_solicitud_trabajador"

    id = Column(Integer, primary_key=True)
    solicitud_id = Column(Integer, ForeignKey("solicitudes_trabajador.id"), nullable=False, index=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    autor_tipo = Column(String(20), nullable=False, default="trabajador")
    comentario = Column(Text, nullable=False)
    creado_en = Column(DateTime, nullable=False, server_default=func.now())

    solicitud = relationship("SolicitudTrabajador", back_populates="comentarios")
    trabajador = relationship("Trabajador", foreign_keys=[trabajador_id])
    usuario = relationship("Usuario", foreign_keys=[usuario_id])


class IncidenciaPortalTrabajador(Base):
    __tablename__ = "incidencias_portal_trabajador"

    id = Column(Integer, primary_key=True)
    numero = Column(String(40), nullable=False, unique=True, index=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=False, index=True)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=True, index=True)
    categoria = Column(String(30), nullable=False)
    activo_tipo = Column(String(30), nullable=True)
    activo_codigo = Column(String(100), nullable=True)
    activo_nombre = Column(String(200), nullable=True)
    descripcion = Column(Text, nullable=False)
    foto_path = Column(String(255), nullable=True)
    estado = Column(String(20), nullable=False, default="recibida", index=True)
    respuesta = Column(Text, nullable=True)
    creado_en = Column(DateTime, nullable=False, server_default=func.now())
    actualizado_en = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    resuelta_en = Column(DateTime, nullable=True)

    trabajador = relationship("Trabajador", back_populates="incidencias_portal")
    almacen = relationship("Almacen", foreign_keys=[almacen_id])


class SolicitudDevolucionTrabajador(Base):
    __tablename__ = "devoluciones_trabajador"

    id = Column(Integer, primary_key=True)
    numero = Column(String(40), nullable=False, unique=True, index=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=False, index=True)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=True, index=True)
    activo_tipo = Column(String(30), nullable=False)
    activo_codigo = Column(String(100), nullable=True)
    descripcion = Column(String(250), nullable=False)
    cantidad = Column(Float, nullable=False, default=1)
    estado_material = Column(String(30), nullable=False, default="correcto")
    motivo = Column(Text, nullable=True)
    foto_path = Column(String(255), nullable=True)
    estado = Column(String(20), nullable=False, default="solicitada", index=True)
    notas_gestion = Column(Text, nullable=True)
    creado_en = Column(DateTime, nullable=False, server_default=func.now())
    actualizado_en = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    completada_en = Column(DateTime, nullable=True)

    trabajador = relationship("Trabajador", back_populates="devoluciones_portal")
    almacen = relationship("Almacen", foreign_keys=[almacen_id])


class SesionPortalTrabajador(Base):
    __tablename__ = "sesiones_portal_trabajador"

    id = Column(Integer, primary_key=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    dispositivo = Column(String(200), nullable=True)
    ip_hash = Column(String(64), nullable=True)
    creado_en = Column(DateTime, nullable=False, server_default=func.now())
    ultimo_uso_en = Column(DateTime, nullable=False, server_default=func.now())
    expira_en = Column(DateTime, nullable=False)
    revocado_en = Column(DateTime, nullable=True)

    trabajador = relationship("Trabajador", foreign_keys=[trabajador_id])


# ─── Almacenes y Ubicaciones ─────────────────────────────────────────────────

class Almacen(Base):
    __tablename__ = "almacenes"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), unique=True, index=True, nullable=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(Text, nullable=True)
    direccion = Column(String(255), nullable=True)
    responsable = Column(String(100), nullable=True)
    delegacion_id = Column(Integer, ForeignKey("delegaciones.id"), nullable=True)
    foto = Column(String(255), nullable=True)
    mapa_json = Column(Text, nullable=True)
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

    herramientas = relationship("Herramienta", back_populates="almacen",
                                foreign_keys="Herramienta.almacen_id")
    materiales  = relationship("Material",   back_populates="almacen",
                                foreign_keys="Material.almacen_id")
    ubicaciones = relationship("Ubicacion",  back_populates="almacen",
                                cascade="all, delete-orphan",
                                order_by="Ubicacion.nombre")


class Ubicacion(Base):
    """Sub-ubicación dentro de un almacén: estantería, cajón, zona, vehículo…"""
    __tablename__ = "ubicaciones"

    id          = Column(Integer, primary_key=True, index=True)
    almacen_id  = Column(Integer, ForeignKey("almacenes.id"), nullable=False, index=True)
    nombre      = Column(String(100), nullable=False)          # "Estantería A"
    codigo      = Column(String(50),  nullable=True, unique=True, index=True)
    descripcion = Column(Text, nullable=True)
    zona        = Column(String(100), nullable=True)
    pasillo     = Column(String(50), nullable=True)
    estanteria  = Column(String(50), nullable=True)
    balda       = Column(String(50), nullable=True)
    posicion    = Column(String(50), nullable=True)
    activo      = Column(Boolean, default=True)
    created_at  = Column(DateTime, server_default=func.now())

    almacen     = relationship("Almacen",    back_populates="ubicaciones")
    herramientas= relationship("Herramienta",back_populates="ubicacion",
                                foreign_keys="Herramienta.ubicacion_id")
    materiales  = relationship("Material",   back_populates="ubicacion",
                                foreign_keys="Material.ubicacion_id")

    @property
    def ruta_completa(self):
        partes = [self.zona, self.pasillo, self.estanteria or self.nombre, self.balda, self.posicion]
        return " → ".join(str(parte).strip() for parte in partes if parte and str(parte).strip())


# ─── Obras ───────────────────────────────────────────────────────────────────

class Obra(Base):
    __tablename__ = "obras"

    id = Column(Integer, primary_key=True, index=True)
    numero = Column(String(50), unique=True, index=True, nullable=False)
    nombre = Column(String(200), nullable=False)
    cliente = Column(String(200), nullable=True)
    direccion = Column(String(255), nullable=True)
    responsable = Column(String(100), nullable=True)
    responsable_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=True)
    estado = Column(String(50), default="activa", index=True)
    fecha_inicio = Column(Date, nullable=True)
    fecha_fin = Column(Date, nullable=True)
    presupuesto = Column(Float, nullable=True)
    coste_acumulado = Column(Float, default=0.0)
    delegacion_id = Column(Integer, ForeignKey("delegaciones.id"), nullable=True)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=True, index=True)
    observaciones = Column(Text, nullable=True)
    activa = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    herramientas = relationship("Herramienta", back_populates="obra",
                                foreign_keys="Herramienta.obra_id")
    movimientos = relationship("Movimiento", back_populates="obra",
                               foreign_keys="Movimiento.obra_id")
    incidencias = relationship("Incidencia", back_populates="obra",
                               foreign_keys="Incidencia.obra_id")


# ─── Vehículos ───────────────────────────────────────────────────────────────

class Vehiculo(Base):
    __tablename__ = "vehiculos"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), unique=True, index=True, nullable=True)
    matricula = Column(String(20), unique=True, index=True, nullable=False)
    marca = Column(String(50), nullable=True)
    modelo = Column(String(50), nullable=True)
    tipo = Column(String(50), nullable=True, default="furgoneta")  # furgoneta, camion, maquinaria
    anio = Column(Integer, nullable=True)
    descripcion = Column(String(200), nullable=True)
    conductor_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=True)
    delegacion_id = Column(Integer, ForeignKey("delegaciones.id"), nullable=True)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=True, index=True)
    estado = Column(String(50), default="activo", index=True)
    itv_hasta = Column(Date, nullable=True)
    seguro_hasta = Column(Date, nullable=True)
    proxima_revision = Column(Date, nullable=True)
    compania_seguro = Column(String(100), nullable=True)
    num_poliza = Column(String(100), nullable=True)
    kilometros = Column(Integer, default=0)
    foto = Column(String(255), nullable=True)
    observaciones = Column(Text, nullable=True)
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    herramientas = relationship("Herramienta", back_populates="vehiculo",
                                foreign_keys="Herramienta.vehiculo_id")
    incidencias = relationship("Incidencia", back_populates="vehiculo",
                               foreign_keys="Incidencia.vehiculo_id")


# ─── HERRAMIENTA (Modelo principal) ──────────────────────────────────────────

class Herramienta(Base):
    """
    Modelo central de MRD TOOL CONTROL.
    Tomo III - Módulo 1: Gestión de Herramientas.
    """
    __tablename__ = "herramientas"

    id = Column(Integer, primary_key=True, index=True)

    # ── Identificación ────────────────────────────────────────────────────────
    codigo = Column(String(50), unique=True, index=True, nullable=False)
    nombre = Column(String(200), nullable=False, index=True)
    descripcion = Column(Text, nullable=True)

    # ── Clasificación ─────────────────────────────────────────────────────────
    categoria = Column(String(100), nullable=True, default="Otro", index=True)
    subcategoria = Column(String(100), nullable=True)
    familia = Column(String(100), nullable=True)

    # ── Datos técnicos ────────────────────────────────────────────────────────
    marca = Column(String(100), nullable=True)
    modelo = Column(String(100), nullable=True)
    fabricante = Column(String(100), nullable=True)
    num_serie = Column(String(100), nullable=True, index=True)
    activo_fijo = Column(String(100), nullable=True)
    dimensiones = Column(String(100), nullable=True)   # LxAxH cm o libre
    peso = Column(Float, nullable=True)          # kg
    color = Column(String(50), nullable=True)
    potencia = Column(String(50), nullable=True) # W, CV, etc.
    voltaje = Column(String(50), nullable=True)
    capacidad = Column(String(50), nullable=True)

    # ── Estado ────────────────────────────────────────────────────────────────
    estado = Column(String(50), default="disponible", index=True)
    # nueva | disponible | reservada | entregada | en_obra | en_transporte
    # en_mantenimiento | en_reparacion | fuera_servicio | extraviada | robada | baja | archivada

    # ── Ubicación ─────────────────────────────────────────────────────────────
    ubicacion_texto = Column(String(200), nullable=True, default="Almacén principal")
    delegacion_id = Column(Integer, ForeignKey("delegaciones.id"), nullable=True)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=True)
    obra_id = Column(Integer, ForeignKey("obras.id"), nullable=True)
    vehiculo_id = Column(Integer, ForeignKey("vehiculos.id"), nullable=True)
    responsable_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=True)

    # ── Adquisición ───────────────────────────────────────────────────────────
    fecha_compra = Column(Date, nullable=True)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=True)
    proveedor_texto = Column(String(200), nullable=True)
    precio_compra = Column(Float, nullable=True)
    valor_actual = Column(Float, nullable=True)
    numero_factura = Column(String(100), nullable=True)
    garantia_hasta = Column(Date, nullable=True)
    vida_util_anos = Column(Integer, nullable=True)

    # ── Mantenimiento ─────────────────────────────────────────────────────────
    fecha_ultimo_mantenimiento = Column(Date, nullable=True)
    fecha_proximo_mantenimiento = Column(Date, nullable=True)
    intervalo_mantenimiento_dias = Column(Integer, nullable=True)

    # ── Imagen ────────────────────────────────────────────────────────────────
    foto = Column(String(255), nullable=True)
    foto_path = Column(String(255), nullable=True)

    # ── Control ───────────────────────────────────────────────────────────────
    observaciones = Column(Text, nullable=True)
    activa = Column(Boolean, default=True, index=True)
    tipo_seguimiento = Column(String(20), nullable=False, default="individual", server_default="individual")  # individual | generico
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    # ── Relaciones ────────────────────────────────────────────────────────────
    ubicacion_id = Column(Integer, ForeignKey("ubicaciones.id"), nullable=True, index=True)

    almacen   = relationship("Almacen",   back_populates="herramientas",
                             foreign_keys=[almacen_id])
    ubicacion = relationship("Ubicacion", back_populates="herramientas",
                             foreign_keys="Herramienta.ubicacion_id")
    obra = relationship("Obra", back_populates="herramientas",
                        foreign_keys=[obra_id])
    vehiculo = relationship("Vehiculo", back_populates="herramientas",
                            foreign_keys=[vehiculo_id])
    responsable = relationship("Trabajador", back_populates="herramientas",
                               foreign_keys=[responsable_id])
    proveedor_rel = relationship("Proveedor", back_populates="herramientas",
                                 foreign_keys=[proveedor_id])
    movimientos = relationship("Movimiento", back_populates="herramienta",
                               order_by="Movimiento.fecha.desc()",
                               foreign_keys="Movimiento.herramienta_id")
    incidencias = relationship("Incidencia", back_populates="herramienta",
                               foreign_keys="Incidencia.herramienta_id",
                               order_by="Incidencia.fecha_apertura.desc()")
    reparaciones = relationship("Reparacion", back_populates="herramienta",
                                foreign_keys="Reparacion.herramienta_id",
                                order_by="Reparacion.fecha_entrada.desc()")
    documentos = relationship("Documento", back_populates="herramienta",
                              foreign_keys="Documento.herramienta_id")


# ─── Motor de Movimientos ────────────────────────────────────────────────────

class Movimiento(Base):
    """
    Todo cambio de estado/ubicación pasa por aquí.
    Registro inmutable - nunca se borra.
    """
    __tablename__ = "movimientos"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(DateTime, server_default=func.now(), index=True)
    tipo = Column(String(50), nullable=False, index=True)
    # alta | entrega | devolucion | traslado | reparacion | retorno_reparacion
    # inventario | baja | restauracion | perdida | robo | mantenimiento

    estado_anterior = Column(String(50), nullable=True)
    estado_nuevo = Column(String(50), nullable=False)
    origen = Column(String(200), nullable=True)
    destino = Column(String(200), nullable=True)
    motivo = Column(String(200), nullable=True)
    observaciones = Column(Text, nullable=True)
    fecha_devolucion_prevista = Column(DateTime, nullable=True, index=True)

    # Firma digital (opcional)
    firma_nombre = Column(String(100), nullable=True)
    firma_datos = Column(Text, nullable=True)  # base64

    # ── Referencias ───────────────────────────────────────────────────────────
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    herramienta_id = Column(Integer, ForeignKey("herramientas.id"),
                            nullable=False, index=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=True)
    obra_id = Column(Integer, ForeignKey("obras.id"), nullable=True)

    usuario = relationship("Usuario", back_populates="movimientos",
                           foreign_keys=[usuario_id])
    herramienta = relationship("Herramienta", back_populates="movimientos",
                               foreign_keys=[herramienta_id])
    trabajador = relationship("Trabajador", back_populates="movimientos",
                              foreign_keys=[trabajador_id])
    obra = relationship("Obra", back_populates="movimientos",
                        foreign_keys=[obra_id])


class ScanEvento(Base):
    """Reserva idempotente y resultado durable de una operación del escáner."""
    __tablename__ = "scan_eventos"

    id = Column(Integer, primary_key=True)
    scan_event_id = Column(String(64), nullable=False, unique=True, index=True)
    request_hash = Column(String(64), nullable=False)
    estado = Column(String(20), nullable=False, default="pending", index=True)
    resultado_json = Column(Text, nullable=True)
    accion = Column(String(20), nullable=False)
    herramienta_id = Column(Integer, ForeignKey("herramientas.id"), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    lease_token = Column(String(64), nullable=True)
    lease_hasta = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class ScanNotificacion(Base):
    """Cursor durable de cambios del escáner, independiente de la hora."""
    __tablename__ = "scan_notificaciones"

    id = Column(Integer, primary_key=True)
    scan_evento_id = Column(Integer, ForeignKey("scan_eventos.id"), nullable=True, index=True)
    herramienta_id = Column(Integer, ForeignKey("herramientas.id"), nullable=False, index=True)
    tipo = Column(String(30), nullable=False, default="estado_herramienta")
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)


# ─── Incidencias ─────────────────────────────────────────────────────────────

class Incidencia(Base):
    __tablename__ = "incidencias"

    id = Column(Integer, primary_key=True, index=True)
    numero = Column(String(50), unique=True, index=True, nullable=False)
    titulo = Column(String(200), nullable=False)
    descripcion = Column(Text, nullable=True)
    tipo = Column(String(50), nullable=True, index=True)
    # golpe | rotura | perdida | robo | mal_funcionamiento | mantenimiento | otro
    prioridad = Column(String(20), default="media", index=True)
    # baja | media | alta | critica
    estado = Column(String(20), default="abierta", index=True)
    # abierta | en_curso | pendiente | resuelta | cerrada

    herramienta_id = Column(Integer, ForeignKey("herramientas.id"), nullable=True)
    vehiculo_id = Column(Integer, ForeignKey("vehiculos.id"), nullable=True)
    obra_id = Column(Integer, ForeignKey("obras.id"), nullable=True)
    responsable_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=True)
    creado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=True, index=True)

    fecha_apertura = Column(DateTime, server_default=func.now(), index=True)
    fecha_resolucion = Column(DateTime, nullable=True)
    observaciones = Column(Text, nullable=True)
    solucion = Column(Text, nullable=True)
    foto_path = Column(String(255), nullable=True)

    herramienta = relationship("Herramienta", back_populates="incidencias",
                               foreign_keys=[herramienta_id])
    vehiculo = relationship("Vehiculo", back_populates="incidencias",
                            foreign_keys=[vehiculo_id])
    obra = relationship("Obra", back_populates="incidencias",
                        foreign_keys=[obra_id])
    reparaciones = relationship("Reparacion", back_populates="incidencia",
                                foreign_keys="Reparacion.incidencia_id")


# ─── Reparaciones ────────────────────────────────────────────────────────────

class Reparacion(Base):
    __tablename__ = "reparaciones"

    id = Column(Integer, primary_key=True, index=True)
    numero = Column(String(50), unique=True, index=True, nullable=False)
    descripcion = Column(Text, nullable=True)
    diagnostico = Column(Text, nullable=True)
    estado = Column(String(50), default="recibida", index=True)
    # recibida | diagnostico | esperando_repuestos | en_reparacion | finalizada | sin_reparacion
    prioridad = Column(String(20), default="media")

    herramienta_id = Column(Integer, ForeignKey("herramientas.id"), nullable=True)
    incidencia_id = Column(Integer, ForeignKey("incidencias.id"), nullable=True)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=True)
    responsable_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=True)
    creado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=True, index=True)

    fecha_entrada = Column(DateTime, server_default=func.now())
    fecha_prevista = Column(Date, nullable=True)
    fecha_salida = Column(DateTime, nullable=True)

    coste_estimado = Column(Float, nullable=True)
    coste_final = Column(Float, nullable=True)
    garantia_reparacion_hasta = Column(Date, nullable=True)
    resultado = Column(String(50), nullable=True)  # reparada | no_reparable | pendiente

    observaciones = Column(Text, nullable=True)

    herramienta = relationship("Herramienta", back_populates="reparaciones",
                               foreign_keys=[herramienta_id])
    incidencia = relationship("Incidencia", back_populates="reparaciones",
                              foreign_keys=[incidencia_id])
    proveedor = relationship("Proveedor", back_populates="reparaciones",
                             foreign_keys=[proveedor_id])


# ─── Documentos ──────────────────────────────────────────────────────────────

class Documento(Base):
    __tablename__ = "documentos"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(200), nullable=False)
    tipo = Column(String(50), nullable=True)  # factura | garantia | manual | certificado | otro
    archivo = Column(String(255), nullable=True)
    tamano = Column(Integer, nullable=True)  # bytes
    extension = Column(String(10), nullable=True)

    herramienta_id = Column(Integer, ForeignKey("herramientas.id"), nullable=True)
    subido_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    created_at = Column(DateTime, server_default=func.now())

    herramienta = relationship("Herramienta", back_populates="documentos",
                               foreign_keys=[herramienta_id])


# ─── Materiales ──────────────────────────────────────────────────────────────

class Material(Base):
    __tablename__ = "materiales"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(50), unique=True, index=True, nullable=False)
    nombre = Column(String(200), nullable=False, index=True)
    descripcion = Column(Text, nullable=True)
    categoria = Column(String(100), nullable=True, index=True)
    subcategoria = Column(String(100), nullable=True)
    unidad = Column(String(20), nullable=True, default="ud")  # ud, kg, m, m2, m3, l
    stock_actual = Column(Float, default=0.0)
    stock_minimo = Column(Float, default=0.0)
    stock_maximo = Column(Float, nullable=True)
    precio_unidad = Column(Float, nullable=True)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=True)
    almacen_id    = Column(Integer, ForeignKey("almacenes.id"),   nullable=True, index=True)
    ubicacion_id  = Column(Integer, ForeignKey("ubicaciones.id"), nullable=True, index=True)
    ubicacion_texto = Column(String(200), nullable=True)  # texto libre legacy
    foto = Column(String(255), nullable=True)
    referencia_proveedor = Column(String(100), nullable=True)
    observaciones = Column(Text, nullable=True)
    activo = Column(Boolean, default=True, index=True)
    tipo_seguimiento = Column(String(20), nullable=False, default="generico", server_default="generico")  # individual | generico
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    almacen   = relationship("Almacen",   back_populates="materiales",
                           foreign_keys="Material.almacen_id")
    ubicacion = relationship("Ubicacion", back_populates="materiales",
                             foreign_keys="Material.ubicacion_id")

    # Relación con movimientos de almacén (añadida en v2.2)
    movimientos_almacen = relationship('MovimientoMaterial', back_populates='material',
                                       cascade='all, delete-orphan',
                                       order_by='MovimientoMaterial.fecha.desc()')

    @property
    def bajo_minimo(self):
        return self.stock_actual <= self.stock_minimo and self.stock_minimo > 0


# ─── Auditoría ───────────────────────────────────────────────────────────────

class AuditoriaLog(Base):
    """
    Registro de auditoría. NUNCA se borra. Solo se archiva.
    """
    __tablename__ = "auditoria_logs"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(DateTime, server_default=func.now(), index=True)
    tabla = Column(String(50), nullable=False, index=True)
    registro_id = Column(Integer, nullable=True, index=True)
    accion = Column(String(50), nullable=False, index=True)
    # crear | editar | borrar | ver | exportar | importar | login | logout | config
    datos_anteriores = Column(Text, nullable=True)   # JSON string
    datos_nuevos = Column(Text, nullable=True)        # JSON string
    resumen = Column(String(500), nullable=True)

    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    ip = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)

    usuario = relationship("Usuario", back_populates="auditorias",
                           foreign_keys=[usuario_id])


# ─── Logs del Sistema ────────────────────────────────────────────────────────

class SistemaLog(Base):
    """
    Logs técnicos del sistema (Motor de Logs DOC-41).
    """
    __tablename__ = "sistema_logs"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(DateTime, server_default=func.now(), index=True)
    nivel = Column(String(10), nullable=False, index=True)  # DEBUG | INFO | WARNING | ERROR | CRITICAL
    modulo = Column(String(50), nullable=True, index=True)
    mensaje = Column(Text, nullable=False)
    detalle = Column(Text, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    ip = Column(String(45), nullable=True)


# ─── Maquinaria ──────────────────────────────────────────────────────────────

ESTADOS_MAQUINARIA = {
    "disponible":    "Disponible",
    "en_uso":        "En uso",
    "en_obra":       "En obra",
    "en_taller":     "En taller",
    "en_transito":   "En tránsito",
    "baja":          "Baja",
}

TIPOS_MAQUINARIA = [
    "Alimak", "Maquinillo", "Transpaleta eléctrica",
    "Toro", "Carretilla", "Carretilla elevadora",
    "Excavadora", "Retroexcavadora", "Grúa",
    "Furgoneta", "Camión", "Compactadora", "Generador", "Compresor",
    "Hormigonera", "Plataforma elevadora", "Otro",
]


class Maquinaria(Base):
    """
    Activos de maquinaria pesada / vehículos — identificados por código de barras.
    El Zebra DS3678-SR (HID) escribe el codigo_barras + Enter directamente.
    """
    __tablename__ = "maquinaria"

    id              = Column(Integer, primary_key=True, index=True)
    codigo_barras   = Column(String(100), unique=True, index=True, nullable=True)
    codigo_interno  = Column(String(50), unique=True, index=True, nullable=True)
    nombre          = Column(String(200), nullable=False)
    tipo            = Column(String(50), nullable=True)
    marca           = Column(String(100), nullable=True)
    modelo          = Column(String(100), nullable=True)
    matricula       = Column(String(20), nullable=True, index=True)
    num_serie       = Column(String(100), nullable=True)
    anio            = Column(Integer, nullable=True)
    color           = Column(String(50), nullable=True)

    # Estado y ubicación
    estado          = Column(String(30), default="disponible", index=True)
    ubicacion       = Column(String(200), nullable=True)
    almacen_id      = Column(Integer, ForeignKey("almacenes.id"), nullable=True, index=True)
    responsable     = Column(String(100), nullable=True)
    obra_actual     = Column(String(200), nullable=True)

    # Datos económicos
    valor_compra    = Column(Float, nullable=True)
    fecha_compra    = Column(Date, nullable=True)
    num_bastidor    = Column(String(50), nullable=True)

    # Mantenimiento
    ultima_itv      = Column(Date, nullable=True)
    proxima_itv     = Column(Date, nullable=True)
    km_actuales     = Column(Integer, nullable=True)
    horas_uso       = Column(Float, nullable=True)

    foto            = Column(String(255), nullable=True)
    notas           = Column(Text, nullable=True)
    activa          = Column(Boolean, default=True, index=True)
    creado_en       = Column(DateTime, server_default=func.now())
    actualizado_en  = Column(DateTime, onupdate=func.now())

    # Documentación legal
    fecha_seguro    = Column(Date, nullable=True)
    vencimiento_seguro = Column(Date, nullable=True)
    num_poliza      = Column(String(100), nullable=True)

    # Pasaporte digital / localizador externo. El localizador es solo un dato
    # inventariable: la aplicación no consulta redes privadas de terceros.
    proxima_revision = Column(Date, nullable=True, index=True)
    localizador_tipo = Column(String(30), nullable=True)
    localizador_alias = Column(String(100), nullable=True)
    localizador_identificador = Column(String(120), nullable=True)
    localizador_ultima_verificacion = Column(DateTime, nullable=True)
    localizador_estado = Column(String(30), nullable=True)
    localizador_notas = Column(Text, nullable=True)


class EventoMaquinaria(Base):
    """Cronología auditable del pasaporte digital de una máquina."""
    __tablename__ = "eventos_maquinaria"
    __table_args__ = (
        CheckConstraint(
            "tipo IN ('revision','averia','reparacion','pieza','cambio','horas','otro')",
            name="ck_evento_maquinaria_tipo",
        ),
    )

    id = Column(Integer, primary_key=True)
    maquinaria_id = Column(Integer, ForeignKey("maquinaria.id"), nullable=False, index=True)
    tipo = Column(String(30), nullable=False, index=True)
    titulo = Column(String(200), nullable=False)
    descripcion = Column(Text, nullable=True)
    fecha = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    horas_maquina = Column(Float, nullable=True)
    coste = Column(Float, nullable=True)
    proveedor = Column(String(200), nullable=True)
    pieza_referencia = Column(String(150), nullable=True)
    proxima_revision = Column(Date, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    creado_en = Column(DateTime, nullable=False, server_default=func.now())

    maquinaria = relationship("Maquinaria", backref="eventos_pasaporte")
    usuario = relationship("Usuario", foreign_keys=[usuario_id])


class DocumentoMaquinaria(Base):
    """Documentos y fotografías anexos al pasaporte digital."""
    __tablename__ = "documentos_maquinaria"

    id = Column(Integer, primary_key=True)
    maquinaria_id = Column(Integer, ForeignKey("maquinaria.id"), nullable=False, index=True)
    tipo = Column(String(30), nullable=False, default="documento")
    nombre_original = Column(String(255), nullable=False)
    archivo_path = Column(String(255), nullable=False, unique=True)
    notas = Column(Text, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    creado_en = Column(DateTime, nullable=False, server_default=func.now())

    maquinaria = relationship("Maquinaria", backref="documentos_pasaporte")
    usuario = relationship("Usuario", foreign_keys=[usuario_id])


# ─── Formación y Habilitaciones ──────────────────────────────────────────────

TIPOS_FORMACION = [
    "Trabajo en altura", "Plataformas elevadoras", "Carretilla elevadora",
    "Prevención de riesgos", "Primeros auxilios", "Soldadura", "Electricidad BT",
    "Gruista / Aparejador", "Conducción segura", "Otro",
]

class FormacionTrabajador(Base):
    """Cursos, certificados y habilitaciones por trabajador con caducidad."""
    __tablename__ = "formacion_trabajadores"

    id               = Column(Integer, primary_key=True, index=True)
    trabajador_id    = Column(Integer, ForeignKey("trabajadores.id"), nullable=False, index=True)
    nombre_curso     = Column(String(200), nullable=False)
    tipo             = Column(String(100), nullable=True)
    entidad          = Column(String(200), nullable=True)
    fecha_realizacion = Column(Date, nullable=True)
    fecha_caducidad  = Column(Date, nullable=True)
    num_certificado  = Column(String(100), nullable=True)
    archivo_path     = Column(String(255), nullable=True)
    notas            = Column(Text, nullable=True)
    usuario_id       = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at       = Column(DateTime, server_default=func.now())

    trabajador = relationship("Trabajador", backref="formaciones")
    usuario    = relationship("Usuario", foreign_keys=[usuario_id])

    @property
    def caducada(self):
        if not self.fecha_caducidad:
            return False
        from datetime import date as _d
        return _d.today() > self.fecha_caducidad

    @property
    def dias_para_caducidad(self):
        if not self.fecha_caducidad:
            return None
        from datetime import date as _d
        return (self.fecha_caducidad - _d.today()).days


# ─── Reconocimientos Médicos ──────────────────────────────────────────────────

class ReconocimientoMedico(Base):
    """Reconocimientos médicos por trabajador."""
    __tablename__ = "reconocimientos_medicos"

    id               = Column(Integer, primary_key=True, index=True)
    trabajador_id    = Column(Integer, ForeignKey("trabajadores.id"), nullable=False, index=True)
    fecha            = Column(Date, nullable=False)
    resultado        = Column(String(50), nullable=False, default="apto")
    # apto | apto_con_restricciones | no_apto | pendiente
    fecha_proxima    = Column(Date, nullable=True)
    medico           = Column(String(150), nullable=True)
    centro           = Column(String(200), nullable=True)
    restricciones    = Column(Text, nullable=True)
    archivo_path     = Column(String(255), nullable=True)
    usuario_id       = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at       = Column(DateTime, server_default=func.now())

    trabajador = relationship("Trabajador", backref="reconocimientos")
    usuario    = relationship("Usuario", foreign_keys=[usuario_id])

    @property
    def vencido(self):
        if not self.fecha_proxima:
            return False
        from datetime import date as _d
        return _d.today() > self.fecha_proxima

    @property
    def dias_para_vencimiento(self):
        if not self.fecha_proxima:
            return None
        from datetime import date as _d
        return (self.fecha_proxima - _d.today()).days


# ─── Documentación del Trabajador ────────────────────────────────────────────

TIPOS_DOCUMENTO_TRABAJADOR = [
    "DNI", "NIE", "Pasaporte", "Carné de conducir", "Tarjeta Seguridad Social",
    "Permiso de trabajo", "Tarjeta de residencia", "Certificado de delitos sexuales", "Otro",
]

class DocumentoTrabajador(Base):
    """Documentos oficiales del trabajador con fecha de caducidad."""
    __tablename__ = "documentos_trabajadores"

    id             = Column(Integer, primary_key=True, index=True)
    trabajador_id  = Column(Integer, ForeignKey("trabajadores.id"), nullable=False, index=True)
    tipo           = Column(String(100), nullable=False)
    numero         = Column(String(100), nullable=True)
    fecha_emision  = Column(Date, nullable=True)
    fecha_caducidad = Column(Date, nullable=True)
    archivo_path   = Column(String(255), nullable=True)
    notas          = Column(Text, nullable=True)
    usuario_id     = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at     = Column(DateTime, server_default=func.now())

    trabajador = relationship("Trabajador", backref="documentos_oficiales")
    usuario    = relationship("Usuario", foreign_keys=[usuario_id])

    @property
    def caducado(self):
        if not self.fecha_caducidad:
            return False
        from datetime import date as _d
        return _d.today() > self.fecha_caducidad

    @property
    def dias_para_caducidad(self):
        if not self.fecha_caducidad:
            return None
        from datetime import date as _d
        return (self.fecha_caducidad - _d.today()).days


# ─── Partes de Presencia ─────────────────────────────────────────────────────

class PartePresencia(Base):
    """Registro diario de presencia de trabajadores en obras."""
    __tablename__ = "partes_presencia"

    id            = Column(Integer, primary_key=True, index=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=False, index=True)
    obra_id       = Column(Integer, ForeignKey("obras.id"), nullable=True, index=True)
    fecha         = Column(Date, nullable=False, index=True)
    hora_entrada  = Column(String(10), nullable=True)   # "08:00"
    hora_salida   = Column(String(10), nullable=True)   # "17:00"
    horas_extras  = Column(Float, default=0.0)
    notas         = Column(Text, nullable=True)
    usuario_id    = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at    = Column(DateTime, server_default=func.now())

    trabajador = relationship("Trabajador", backref="partes_presencia")
    obra       = relationship("Obra", backref="partes_presencia")
    usuario    = relationship("Usuario", foreign_keys=[usuario_id])


# ─── Planning de Obras ───────────────────────────────────────────────────────

class PlanningObra(Base):
    """Asignación de trabajadores y maquinaria a obras en fechas concretas."""
    __tablename__ = "planning_obras"

    id            = Column(Integer, primary_key=True, index=True)
    obra_id       = Column(Integer, ForeignKey("obras.id"), nullable=False, index=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=True, index=True)
    maquinaria_id = Column(Integer, ForeignKey("maquinaria.id"), nullable=True, index=True)
    fecha_inicio  = Column(Date, nullable=False, index=True)
    fecha_fin     = Column(Date, nullable=True)
    rol           = Column(String(100), nullable=True)
    notas         = Column(Text, nullable=True)
    usuario_id    = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at    = Column(DateTime, server_default=func.now())

    obra       = relationship("Obra", backref="planning")
    trabajador = relationship("Trabajador", backref="planning")
    maquinaria = relationship("Maquinaria", backref="planning")
    usuario    = relationship("Usuario", foreign_keys=[usuario_id])


# ─── Sprint 4.1 — Motor de Automatizaciones ──────────────────────────────────

ESTADOS_AUTOMATIZACION = {
    "activa":     "Activa",
    "inactiva":   "Inactiva",
    "pausada":    "Pausada",
    "error":      "Error",
    "archivada":  "Archivada",
}

PRIORIDADES_AUTOMATIZACION = {
    "baja":    "Baja",
    "media":   "Media",
    "alta":    "Alta",
    "critica": "Crítica",
}

# Disparadores disponibles (Sprint 4.1 + 4.2)
TIPOS_DISPARADOR = {
    "intervalo":              "Cada N minutos",
    "diario":                 "Diario a una hora",
    "manual":                 "Solo manual",
    "evento_herramienta":     "Al cambiar estado de herramienta",
    "evento_maquinaria":      "Al cambiar estado de maquinaria",
}

# Condiciones disponibles (Sprint 4.1 + 4.2)
TIPOS_CONDICION = {
    # Sprint 4.1
    "herramienta_dias_entregada":    "Herramienta lleva X días entregada",
    "reparacion_retrasada":          "Reparación supera X días sin resolver",
    "mantenimiento_proximo_itv":     "ITV vence en menos de X días",
    "maquinaria_sin_movimiento":     "Maquinaria sin cambio de estado en X días",
    "siempre":                       "Siempre (sin condición adicional)",
    # Sprint 4.2
    "stock_material_bajo":           "Stock de material por debajo del mínimo",
    "incidencia_abierta_dias":       "Incidencia abierta más de X días",
    "herramienta_garantia_vence":    "Garantía de herramienta vence en X días",
    "herramienta_estado_es":         "Herramienta en estado específico",
    "maquinaria_estado_es":          "Maquinaria en estado específico",
}

# Acciones disponibles (Sprint 4.1 + 4.2)
TIPOS_ACCION = {
    # Sprint 4.1
    "crear_aviso":                   "Crear aviso en el sistema",
    "registrar_log":                 "Registrar en el log del sistema",
    # Sprint 4.2
    "cambiar_estado_herramienta":    "Cambiar estado de herramienta",
    "notificar_usuario":             "Crear aviso para usuario específico",
}

PRIORIDADES_AVISO = {
    "informacion": "Información",
    "baja":        "Baja",
    "media":       "Media",
    "alta":        "Alta",
    "critica":     "Crítica",
    "urgente":     "Urgente",
}


class Automatizacion(Base):
    """
    Regla de automatización configurable por el usuario.
    Evalúa condiciones sobre datos del sistema y ejecuta acciones si se cumplen.
    """
    __tablename__ = "automatizaciones"

    id                  = Column(Integer, primary_key=True, index=True)
    nombre              = Column(String(200), nullable=False)
    descripcion         = Column(Text, nullable=True)

    # Estado del ciclo de vida
    estado              = Column(String(20), default="activa", index=True)
    prioridad           = Column(String(20), default="media")
    version             = Column(Integer, default=1)

    # Disparador
    tipo_disparador     = Column(String(50), default="manual")
    config_disparador   = Column(Text, nullable=True)   # JSON: {"intervalo_min": 60} | {"hora": "08:00"}

    # Condiciones (JSON array)
    condiciones         = Column(Text, default="[]")    # [{"tipo":"herramienta_dias_entregada","dias":30}]

    # Acciones (JSON array)
    acciones            = Column(Text, default="[]")    # [{"tipo":"crear_aviso","titulo":"...","prioridad":"alta","mensaje":"..."}]

    # Estadísticas de ejecución
    total_ejecuciones   = Column(Integer, default=0)
    total_acciones      = Column(Integer, default=0)
    ultimo_resultado    = Column(String(20), nullable=True)   # ok | error | sin_accion
    ultimo_error        = Column(Text, nullable=True)

    # Timestamps
    creado_por_id       = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en           = Column(DateTime, server_default=func.now())
    actualizado_en      = Column(DateTime, onupdate=func.now())
    ultima_ejecucion    = Column(DateTime, nullable=True)
    proxima_ejecucion   = Column(DateTime, nullable=True)

    # Relaciones
    ejecuciones         = relationship("EjecucionAutomatizacion", back_populates="automatizacion",
                                       cascade="all, delete-orphan", lazy="dynamic")


class EjecucionAutomatizacion(Base):
    """
    Registro de cada ejecución de una automatización (manual, automática o simulación).
    """
    __tablename__ = "ejecuciones_automatizacion"

    id                  = Column(Integer, primary_key=True, index=True)
    automatizacion_id   = Column(Integer, ForeignKey("automatizaciones.id"), nullable=False, index=True)
    fecha               = Column(DateTime, server_default=func.now(), index=True)
    modo                = Column(String(20), default="auto")    # auto | manual | simulacion | prueba
    resultado           = Column(String(20), nullable=True)     # ok | error | sin_accion
    acciones_ejecutadas = Column(Integer, default=0)
    items_afectados     = Column(Integer, default=0)
    detalle             = Column(Text, nullable=True)           # JSON: {"acciones": [...]}
    error               = Column(Text, nullable=True)
    duracion_ms         = Column(Integer, nullable=True)
    usuario_id          = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    # Relación
    automatizacion      = relationship("Automatizacion", back_populates="ejecuciones")


class Aviso(Base):
    """
    Avisos y notificaciones generados por automatizaciones o manualmente.
    Visible en el panel de control. Base para Sprint 4.3 (notificaciones).
    """
    __tablename__ = "avisos"

    id                  = Column(Integer, primary_key=True, index=True)
    titulo              = Column(String(200), nullable=False)
    mensaje             = Column(Text, nullable=True)
    prioridad           = Column(String(20), default="media", index=True)
    tipo                = Column(String(50), default="sistema")   # automatizacion | sistema | manual

    # Estado de lectura
    leido               = Column(Boolean, default=False, index=True)
    archivado           = Column(Boolean, default=False, index=True)

    # Origen
    automatizacion_id   = Column(Integer, ForeignKey("automatizaciones.id"), nullable=True, index=True)
    usuario_id          = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)

    # Enlace al activo relacionado (opcional)
    enlace              = Column(String(500), nullable=True)
    datos               = Column(Text, nullable=True)  # JSON con contexto adicional

    # Timestamps
    creado_en           = Column(DateTime, server_default=func.now(), index=True)
    leido_en            = Column(DateTime, nullable=True)


# ═══════════════════════════════════════════════════════════════════
# SPRINT 4.3 — CENTRO INTELIGENTE DE NOTIFICACIONES
# ═══════════════════════════════════════════════════════════════════

TIPOS_CANAL = {
    "email":   "Correo electrónico (SMTP)",
    "webhook": "Webhook HTTP (POST)",
    "webpush": "Notificación push (navegador)",
}

PRIORIDADES_CANAL = {
    "baja":   "Baja y superior",
    "media":  "Media y superior",
    "alta":   "Solo Alta y Crítica",
    "critica":"Solo Crítica",
}

RESULTADOS_NOTIF = {
    "ok":      "Enviado",
    "error":   "Error",
    "reintento": "Pendiente reintento",
}


class CanalNotificacion(Base):
    """Canal de salida: email SMTP o webhook HTTP."""
    __tablename__ = "canales_notificacion"

    id              = Column(Integer, primary_key=True, index=True)
    nombre          = Column(String(120), nullable=False)
    tipo            = Column(String(30), nullable=False, index=True)  # email | webhook
    activo          = Column(Boolean, default=True, index=True)

    # JSON con config específica del canal:
    # email:   {smtp_host, smtp_port, smtp_user, smtp_pass, smtp_tls, destinatarios:[]}
    # webhook: {url, metodo:"POST", headers:{}, incluir_enlace:true}
    config          = Column(Text, nullable=False, default="{}")

    # Filtro de prioridad mínima para activar el canal
    prioridad_minima = Column(String(20), default="media")

    # Estadísticas
    total_enviados  = Column(Integer, default=0)
    total_errores   = Column(Integer, default=0)
    ultimo_envio    = Column(DateTime, nullable=True)

    creado_en       = Column(DateTime, server_default=func.now())
    actualizado_en  = Column(DateTime, server_default=func.now(), onupdate=func.now())

    notificaciones  = relationship("NotificacionEnviada", back_populates="canal",
                                   cascade="all, delete-orphan")


class NotificacionEnviada(Base):
    """Registro de cada notificación enviada o fallida."""
    __tablename__ = "notificaciones_enviadas"

    id              = Column(Integer, primary_key=True, index=True)
    canal_id        = Column(Integer, ForeignKey("canales_notificacion.id"), nullable=False, index=True)
    aviso_id        = Column(Integer, ForeignKey("avisos.id"), nullable=True, index=True)

    fecha_envio     = Column(DateTime, server_default=func.now(), index=True)
    resultado       = Column(String(20), default="ok", index=True)  # ok | error | reintento
    detalle         = Column(Text, nullable=True)   # error message o response body
    reintentos      = Column(Integer, default=0)
    proximo_reintento = Column(DateTime, nullable=True)

    # Snapshot del aviso al momento del envío
    aviso_titulo    = Column(String(255), nullable=True)
    aviso_prioridad = Column(String(30), nullable=True)

    canal           = relationship("CanalNotificacion", back_populates="notificaciones")


class PushSuscripcion(Base):
    """Suscripción de un navegador a notificaciones push (Web Push / VAPID)."""
    __tablename__ = "push_suscripciones"

    id              = Column(Integer, primary_key=True, index=True)
    usuario_id      = Column(Integer, ForeignKey("usuarios.id"), nullable=True, index=True)
    endpoint        = Column(Text, nullable=False, unique=True)
    p256dh          = Column(String(255), nullable=False)
    auth            = Column(String(255), nullable=False)
    user_agent      = Column(String(255), nullable=True)
    creado_en       = Column(DateTime, server_default=func.now())

    usuario         = relationship("Usuario")


# ═══════════════════════════════════════════════════════════════════
# SPRINT 4.9 — MANTENIMIENTO PREDICTIVO
# ═══════════════════════════════════════════════════════════════════

TIPOS_MANTENIMIENTO = {
    "preventivo":  "Preventivo (programado)",
    "correctivo":  "Correctivo (avería)",
    "predictivo":  "Predictivo (recomendado por sistema)",
    "itv":         "ITV / Inspección técnica",
    "calibracion": "Calibración / Verificación",
    "limpieza":    "Limpieza / Conservación",
}

ESTADOS_MANTENIMIENTO = {
    "pendiente":   "Pendiente",
    "en_proceso":  "En proceso",
    "completado":  "Completado",
    "vencido":     "Vencido",
    "cancelado":   "Cancelado",
}

NIVELES_RIESGO = {
    "critico":  (75, 100),
    "alto":     (50, 74),
    "medio":    (25, 49),
    "bajo":     (0,  24),
}


class MantenimientoProgramado(Base):
    """Registro de mantenimientos programados y realizados por activo."""
    __tablename__ = "mantenimientos_programados"

    id               = Column(Integer, primary_key=True, index=True)

    # Activo asociado (herramienta o maquinaria)
    tipo_activo      = Column(String(30), nullable=False, index=True)  # herramienta | maquinaria
    activo_id        = Column(Integer, nullable=False, index=True)
    nombre_activo    = Column(String(200), nullable=False)
    codigo_activo    = Column(String(80), nullable=True)

    # Tipo y descripción
    tipo             = Column(String(30), nullable=False, default="preventivo")
    descripcion      = Column(Text, nullable=True)

    # Fechas
    fecha_programada = Column(DateTime, nullable=False, index=True)
    fecha_realizada  = Column(DateTime, nullable=True)
    intervalo_dias   = Column(Integer, nullable=True)  # Para calcular siguiente

    # Estado
    estado           = Column(String(30), default="pendiente", index=True)

    # Costes
    coste_estimado   = Column(Float, nullable=True)
    coste_real       = Column(Float, nullable=True)

    # Proveedor / técnico
    proveedor_texto  = Column(String(200), nullable=True)

    # Score de riesgo al programar
    score_riesgo     = Column(Integer, nullable=True)

    notas            = Column(Text, nullable=True)

    creado_por_id    = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en        = Column(DateTime, server_default=func.now(), index=True)
    actualizado_en   = Column(DateTime, server_default=func.now(), onupdate=func.now())


# ─── Sprint EPI — Entregas de EPIs y Ropa ────────────────────────────────────

KIT_EPI_INICIAL = [
    {"nombre": "CASCO",               "cantidad": 1},
    {"nombre": "CHALECO",             "cantidad": 1},
    {"nombre": "ARNES",               "cantidad": 1},
    {"nombre": "ABSORBEDOR",          "cantidad": 1},
    {"nombre": "CINTURON",            "cantidad": 1},
    {"nombre": "MARTILLO",            "cantidad": 1},
    {"nombre": "CARRACA",             "cantidad": 1},
    {"nombre": "METRO",               "cantidad": 1},
    {"nombre": "PORTAMARTILLO",       "cantidad": 1},
    {"nombre": "PORTAMETRO",          "cantidad": 1},
    {"nombre": "GAFAS TRANSPARENTES", "cantidad": 1},
    {"nombre": "GAFAS DE SOL",        "cantidad": 1},
]

KIT_ROPA_SEMESTRAL = [
    {"nombre": "FORRO",     "cantidad": 1},
    {"nombre": "JERSEI",    "cantidad": 2},
    {"nombre": "CAMISETA",  "cantidad": 5},
    {"nombre": "PANTALON",  "cantidad": 2},
    {"nombre": "BOTAS",     "cantidad": 1},
]

INTERVALO_ROPA_DIAS = 180  # 6 meses


class EntregaEPI(Base):
    __tablename__ = "entregas_epi"

    id            = Column(Integer, primary_key=True, index=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=False, index=True)
    tipo          = Column(String(20), nullable=False, default="epi")   # 'epi' | 'ropa'
    items_json    = Column(Text, nullable=False)                        # JSON lista de items
    fecha         = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    entregado_por = Column(String(100), nullable=True)
    firmado_por   = Column(String(100), nullable=True)
    observaciones = Column(Text, nullable=True)
    firma_base64  = Column(Text, nullable=True)
    usuario_id    = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    trabajador = relationship("Trabajador", backref="entregas_epi",
                              foreign_keys=[trabajador_id])


class StockEPI(Base):
    __tablename__ = "stock_epi"
    __table_args__ = (
        UniqueConstraint('nombre', 'talla', name='uq_stock_nombre_talla'),
    )

    id           = Column(Integer, primary_key=True, index=True)
    nombre       = Column(String(100), nullable=False)
    categoria    = Column(String(20), nullable=False, default="epi")  # 'epi' | 'ropa'
    talla        = Column(String(20), nullable=True)   # None para EPIs; talla para ropa ('M', '42', ...)
    cantidad     = Column(Integer, nullable=False, default=0)
    stock_minimo = Column(Integer, nullable=False, default=3)
    codigo       = Column(String(50), nullable=True, unique=True)     # código escaneable por tipo+talla
    almacen_id   = Column(Integer, ForeignKey("almacenes.id"), nullable=True, index=True)
    ubicacion_id = Column(Integer, ForeignKey("ubicaciones.id"), nullable=True, index=True)
    tipo_seguimiento = Column(String(20), nullable=False, default="generico", server_default="generico")  # individual | generico
    updated_at   = Column(DateTime, onupdate=func.now(), server_default=func.now())

    @property
    def bajo_minimo(self):
        return self.cantidad <= self.stock_minimo

    @property
    def sin_stock(self):
        return self.cantidad <= 0

    @property
    def nombre_display(self):
        return f"{self.nombre} T.{self.talla}" if self.talla else self.nombre


# ─── Sprint EPI — EPIs individuales con número de serie y revisiones ──────────

TIPOS_EPI_INDIVIDUAL = ["ARNES", "ABSORBEDOR"]
INTERVALO_REVISION_EPI_DIAS = 365  # revisión anual


class EPIIndividual(Base):
    __tablename__ = "epis_individuales"

    id                    = Column(Integer, primary_key=True, index=True)
    tipo                  = Column(String(50), nullable=False)          # ARNES, ABSORBEDOR
    codigo_fabricacion    = Column(String(150), nullable=False)
    marca                 = Column(String(100), nullable=True)
    modelo                = Column(String(100), nullable=True)
    fecha_fabricacion     = Column(Date, nullable=True)
    fecha_puesta_servicio = Column(Date, nullable=True)
    trabajador_id         = Column(Integer, ForeignKey("trabajadores.id"), nullable=True, index=True)
    estado                = Column(String(20), nullable=False, default="activo")  # activo | en_revision | baja
    proxima_revision      = Column(Date, nullable=True)
    notas                 = Column(Text, nullable=True)
    foto_path             = Column(String(255), nullable=True)
    identificador_id      = Column(Integer, ForeignKey("identificadores_globales.id"), nullable=True, unique=True)
    referencia_interna    = Column(String(50), nullable=True, unique=True)
    codigo_qr             = Column(String(50), nullable=True, unique=True)
    almacen_id             = Column(Integer, ForeignKey("almacenes.id"), nullable=True, index=True)
    ubicacion_id           = Column(Integer, ForeignKey("ubicaciones.id"), nullable=True, index=True)
    created_at            = Column(DateTime, server_default=func.now())

    trabajador = relationship("Trabajador", backref="epis_individuales")
    revisiones = relationship("RevisionEPI", back_populates="epi",
                              cascade="all, delete-orphan")
    historial  = relationship("HistorialEPIIndividual", back_populates="epi",
                              cascade="all, delete-orphan", order_by="HistorialEPIIndividual.fecha_asignacion.desc()")

    @property
    def revision_vencida(self):
        if not self.proxima_revision:
            return False
        from datetime import date as _d
        return _d.today() >= self.proxima_revision

    @property
    def dias_para_revision(self):
        if not self.proxima_revision:
            return None
        from datetime import date as _d
        return (self.proxima_revision - _d.today()).days


class RevisionEPI(Base):
    __tablename__ = "revisiones_epi"

    id               = Column(Integer, primary_key=True, index=True)
    epi_id           = Column(Integer, ForeignKey("epis_individuales.id"), nullable=False, index=True)
    fecha            = Column(DateTime, nullable=False, server_default=func.now())
    resultado        = Column(String(30), nullable=False)   # apto | apto_con_obs | retirar
    tecnico          = Column(String(150), nullable=True)
    proxima_revision = Column(Date, nullable=True)
    observaciones    = Column(Text, nullable=True)
    usuario_id       = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    epi     = relationship("EPIIndividual", back_populates="revisiones")
    usuario = relationship("Usuario", foreign_keys=[usuario_id])


class HistorialEPIIndividual(Base):
    """Registro histórico de asignaciones de cada EPI individual."""
    __tablename__ = "historial_epis_individuales"

    id               = Column(Integer, primary_key=True, index=True)
    epi_id           = Column(Integer, ForeignKey("epis_individuales.id"), nullable=False, index=True)
    trabajador_id    = Column(Integer, ForeignKey("trabajadores.id"), nullable=True, index=True)
    fecha_asignacion = Column(DateTime, nullable=False, server_default=func.now())
    fecha_devolucion = Column(DateTime, nullable=True)
    usuario_id       = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    notas            = Column(Text, nullable=True)

    epi        = relationship("EPIIndividual", back_populates="historial")
    trabajador = relationship("Trabajador", foreign_keys=[trabajador_id])
    usuario    = relationship("Usuario", foreign_keys=[usuario_id])


# ─── Catálogo dinámico de EPIs y Ropa ────────────────────────────────────────
# Permite añadir/editar/eliminar artículos sin tocar el código.

class CatalogoEPI(Base):
    """Catálogo editable de artículos EPI y ropa de trabajo."""
    __tablename__ = "catalogo_epi"

    id           = Column(Integer, primary_key=True, index=True)
    nombre       = Column(String(100), nullable=False, unique=True)
    categoria    = Column(String(20),  nullable=False, default="epi")   # 'epi' | 'ropa'
    cantidad_kit = Column(Integer,     nullable=False, default=1)       # uds por kit/dotación
    activo       = Column(Boolean,     nullable=False, default=True)    # aparece en kits y stock
    orden        = Column(Integer,     nullable=False, default=0)       # orden en la UI
    marca        = Column(String(100), nullable=True)
    notas        = Column(Text,        nullable=True)
    created_at   = Column(DateTime, server_default=func.now())


# ─── Materiales / Consumibles de almacén ─────────────────────────────────────

UNIDADES_MATERIAL = ['ud', 'm', 'm²', 'm³', 'kg', 'l', 'caja', 'rollo', 'saco', 'ml', 't']
TIPOS_MOVIMIENTO_MAT = ['salida', 'entrada', 'ajuste']
CATEGORIAS_MATERIAL = [
    'Tornillería y fijaciones', 'Cables y electricidad', 'Tuberías y fontanería',
    'Herramientas de consumo', 'Productos químicos', 'Madera y tableros',
    'Áridos y morteros', 'Hierro y acero', 'Impermeabilización', 'Pintura',
    'Señalización y seguridad', 'Varios',
]


class MovimientoMaterial(Base):
    """Registro de entrada/salida de un material del almacén."""
    __tablename__ = "movimientos_materiales"

    id            = Column(Integer, primary_key=True, index=True)
    material_id   = Column(Integer, ForeignKey("materiales.id"), nullable=False, index=True)
    tipo          = Column(String(20), nullable=False)          # salida | entrada | ajuste
    cantidad      = Column(Float, nullable=False)
    obra_id       = Column(Integer, ForeignKey("obras.id"), nullable=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=True)
    fecha         = Column(DateTime, default=datetime.utcnow)
    referencia    = Column(String(100), nullable=True)          # nº albarán, pedido …
    notas         = Column(Text, nullable=True)
    usuario_id    = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow)

    material    = relationship('Material', back_populates='movimientos_almacen')
    obra        = relationship('Obra', foreign_keys=[obra_id])
    trabajador  = relationship('Trabajador', foreign_keys=[trabajador_id])
    usuario     = relationship('Usuario', foreign_keys=[usuario_id])


# ─── Movimientos de Vehículos ────────────────────────────────────────────────

class MovimientoVehiculo(Base):
    """Registro de salida/retorno de un vehículo de la nave."""
    __tablename__ = "movimientos_vehiculos"

    id              = Column(Integer, primary_key=True, index=True)
    vehiculo_id     = Column(Integer, ForeignKey("vehiculos.id"), nullable=False, index=True)
    conductor_id    = Column(Integer, ForeignKey("trabajadores.id"), nullable=True)
    obra_id         = Column(Integer, ForeignKey("obras.id"), nullable=True)
    destino         = Column(String(200), nullable=True)
    fecha_salida    = Column(DateTime, nullable=False, default=datetime.utcnow)
    km_salida       = Column(Integer, nullable=True)
    fecha_retorno   = Column(DateTime, nullable=True)
    km_retorno      = Column(Integer, nullable=True)
    observaciones   = Column(Text, nullable=True)
    usuario_id      = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)

    vehiculo    = relationship('Vehiculo', foreign_keys=[vehiculo_id])
    conductor   = relationship('Trabajador', foreign_keys=[conductor_id])
    obra        = relationship('Obra', foreign_keys=[obra_id])
    usuario     = relationship('Usuario', foreign_keys=[usuario_id])

    @property
    def en_ruta(self):
        return self.fecha_retorno is None

    @property
    def km_recorridos(self):
        if self.km_salida is not None and self.km_retorno is not None:
            return self.km_retorno - self.km_salida
        return None


# ─── Albarán de Salida Unificado ─────────────────────────────────────────────

ESTADOS_ALBARAN = ['abierto', 'cerrado', 'parcial']


class AlbaranSalida(Base):
    """Documento que agrupa una salida/suministro o una entrada al almacén."""
    __tablename__ = "albaranes_salida"

    id                    = Column(Integer, primary_key=True, index=True)
    numero                = Column(String(30), unique=True, nullable=False, index=True)
    tipo_documento        = Column(String(20), default='salida', nullable=False)
    obra_id               = Column(Integer, ForeignKey("obras.id"), nullable=True)
    responsable_id        = Column(Integer, ForeignKey("trabajadores.id"), nullable=True)
    almacen_id            = Column(Integer, ForeignKey("almacenes.id"), nullable=True)
    origen_destino        = Column(String(160), nullable=True)
    fecha_salida          = Column(DateTime, default=datetime.utcnow, nullable=False)
    fecha_retorno_prevista = Column(DateTime, nullable=True)
    fecha_retorno_real    = Column(DateTime, nullable=True)
    estado                = Column(String(20), default='abierto')  # abierto | parcial | cerrado
    notas                 = Column(Text, nullable=True)
    firma_datos           = Column(Text, nullable=True)   # base64
    firma_nombre          = Column(String(100), nullable=True)
    firma_fecha           = Column(DateTime, nullable=True)
    portal_conformidad    = Column(String(20), nullable=False, default='pendiente')
    portal_motivo         = Column(Text, nullable=True)
    portal_firma_datos    = Column(Text, nullable=True)
    portal_firmado_en     = Column(DateTime, nullable=True)
    usuario_id            = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at            = Column(DateTime, default=datetime.utcnow)

    items       = relationship('ItemAlbaranSalida', back_populates='albaran',
                               cascade='all, delete-orphan')
    obra        = relationship('Obra', foreign_keys=[obra_id])
    responsable = relationship('Trabajador', foreign_keys=[responsable_id])
    almacen     = relationship('Almacen', foreign_keys=[almacen_id])
    usuario     = relationship('Usuario', foreign_keys=[usuario_id])

    @property
    def dias_fuera(self):
        if self.tipo_documento == 'entrada':
            return 0
        fin = self.fecha_retorno_real or datetime.utcnow()
        return (fin - self.fecha_salida).days

    @property
    def todo_retornado(self):
        return all(i.retornado for i in self.items) if self.items else False


class ItemAlbaranSalida(Base):
    """Línea de un albarán: herramienta, material o descripción libre."""
    __tablename__ = "items_albaran_salida"

    id               = Column(Integer, primary_key=True, index=True)
    albaran_id       = Column(Integer, ForeignKey("albaranes_salida.id"), nullable=False, index=True)
    tipo             = Column(String(20), nullable=False)   # herramienta | material | libre
    herramienta_id   = Column(Integer, ForeignKey("herramientas.id"), nullable=True)
    material_id      = Column(Integer, ForeignKey("materiales.id"), nullable=True)
    cantidad         = Column(Float, default=1.0, nullable=False)
    descripcion_libre = Column(String(255), nullable=True)
    retornado        = Column(Boolean, default=False)
    fecha_retorno    = Column(DateTime, nullable=True)
    notas            = Column(Text, nullable=True)

    albaran     = relationship('AlbaranSalida', back_populates='items')
    herramienta = relationship('Herramienta', foreign_keys=[herramienta_id])
    material    = relationship('Material', foreign_keys=[material_id])

    @property
    def descripcion(self):
        if self.herramienta:
            h = self.herramienta
            partes = [
                h.nombre,
                f"Código: {h.codigo}" if h.codigo else None,
                f"Marca: {h.marca}" if h.marca else None,
                f"Modelo: {h.modelo}" if h.modelo else None,
                f"N.º serie: {h.num_serie}" if h.num_serie else None,
                h.descripcion,
            ]
            return " · ".join(str(p).strip() for p in partes if p and str(p).strip())
        if self.material:
            m = self.material
            partes = [
                m.nombre,
                f"Código: {m.codigo}" if m.codigo else None,
                f"Ref. proveedor: {m.referencia_proveedor}" if m.referencia_proveedor else None,
                m.descripcion,
            ]
            return " · ".join(str(p).strip() for p in partes if p and str(p).strip())
        return self.descripcion_libre or "—"


class TransferenciaAlmacen(Base):
    """Traspaso auditable entre dos almacenes con recepción obligatoria."""
    __tablename__ = "transferencias_almacen"
    __table_args__ = (
        CheckConstraint("origen_id <> destino_id", name="ck_transferencia_almacenes_distintos"),
        CheckConstraint(
            "estado IN ('en_transito','recibida','cancelada')",
            name="ck_transferencia_estado",
        ),
    )

    id = Column(Integer, primary_key=True)
    numero = Column(String(40), nullable=False, unique=True, index=True)
    origen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=False, index=True)
    destino_id = Column(Integer, ForeignKey("almacenes.id"), nullable=False, index=True)
    estado = Column(String(20), nullable=False, default="en_transito", index=True)
    creado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    recibido_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    recibido_en = Column(DateTime, nullable=True)
    notas = Column(Text, nullable=True)
    firma_recepcion = Column(Text, nullable=True)
    firma_recepcion_nombre = Column(String(100), nullable=True)
    creacion_event_id = Column(String(64), nullable=False, unique=True)
    recepcion_event_id = Column(String(64), nullable=True, unique=True)

    origen = relationship("Almacen", foreign_keys=[origen_id])
    destino = relationship("Almacen", foreign_keys=[destino_id])
    creado_por = relationship("Usuario", foreign_keys=[creado_por_id])
    recibido_por = relationship("Usuario", foreign_keys=[recibido_por_id])
    lineas = relationship(
        "LineaTransferenciaAlmacen", back_populates="transferencia",
        cascade="all, delete-orphan", order_by="LineaTransferenciaAlmacen.id",
    )


class LineaTransferenciaAlmacen(Base):
    __tablename__ = "lineas_transferencia_almacen"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_linea_transferencia_cantidad"),
        CheckConstraint(
            "tipo IN ('herramienta','maquinaria','vehiculo','epi_individual','material','stock_epi','variante')",
            name="ck_linea_transferencia_tipo",
        ),
    )

    id = Column(Integer, primary_key=True)
    transferencia_id = Column(Integer, ForeignKey("transferencias_almacen.id"), nullable=False, index=True)
    tipo = Column(String(30), nullable=False, index=True)
    objeto_id = Column(Integer, nullable=False, index=True)
    referencia = Column(String(100), nullable=False)
    descripcion = Column(String(300), nullable=False)
    estado_anterior = Column(String(50), nullable=True)
    cantidad = Column(Float, nullable=False, default=1)
    cantidad_recibida = Column(Float, nullable=True)
    cantidad_danada = Column(Float, nullable=False, default=0, server_default="0")
    notas_recepcion = Column(Text, nullable=True)
    foto_recepcion = Column(String(255), nullable=True)
    incidencia_id = Column(Integer, ForeignKey("incidencias.id"), nullable=True)
    ubicacion_origen_id = Column(Integer, ForeignKey("ubicaciones.id"), nullable=True)
    ubicacion_destino_id = Column(Integer, ForeignKey("ubicaciones.id"), nullable=True)

    transferencia = relationship("TransferenciaAlmacen", back_populates="lineas")
    ubicacion_origen = relationship("Ubicacion", foreign_keys=[ubicacion_origen_id])
    ubicacion_destino = relationship("Ubicacion", foreign_keys=[ubicacion_destino_id])
    incidencia = relationship("Incidencia", foreign_keys=[incidencia_id])


class RecepcionTransferencia(Base):
    """Confirmación parcial o completa, idempotente y firmada, de un traspaso."""
    __tablename__ = "recepciones_transferencia"

    id = Column(Integer, primary_key=True)
    transferencia_id = Column(Integer, ForeignKey("transferencias_almacen.id"), nullable=False, index=True)
    event_id = Column(String(64), nullable=False, unique=True, index=True)
    lineas_json = Column(Text, nullable=False)
    firma_datos = Column(Text, nullable=True)
    firma_nombre = Column(String(100), nullable=True)
    recibido_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    recibido_en = Column(DateTime, nullable=False, server_default=func.now(), index=True)

    transferencia = relationship("TransferenciaAlmacen", foreign_keys=[transferencia_id])
    recibido_por = relationship("Usuario", foreign_keys=[recibido_por_id])


class PedidoProveedor(Base):
    """Pedido de reposición asociado a un único almacén."""
    __tablename__ = "pedidos_proveedor"
    __table_args__ = (
        CheckConstraint("estado IN ('borrador','enviado','parcial','recibido','cancelado')", name="ck_pedido_estado"),
    )

    id = Column(Integer, primary_key=True)
    numero = Column(String(40), nullable=False, unique=True, index=True)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=False, index=True)
    proveedor = Column(String(150), nullable=True)
    estado = Column(String(20), nullable=False, default="borrador", index=True)
    fecha_pedido = Column(DateTime, nullable=False, server_default=func.now())
    fecha_prevista = Column(Date, nullable=True)
    notas = Column(Text, nullable=True)
    creado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    cerrado_en = Column(DateTime, nullable=True)

    almacen = relationship("Almacen", foreign_keys=[almacen_id])
    creado_por = relationship("Usuario", foreign_keys=[creado_por_id])
    lineas = relationship("LineaPedidoProveedor", back_populates="pedido", cascade="all, delete-orphan", order_by="LineaPedidoProveedor.id")


class LineaPedidoProveedor(Base):
    __tablename__ = "lineas_pedido_proveedor"

    id = Column(Integer, primary_key=True)
    pedido_id = Column(Integer, ForeignKey("pedidos_proveedor.id"), nullable=False, index=True)
    tipo = Column(String(30), nullable=False)
    objeto_id = Column(Integer, nullable=False)
    referencia = Column(String(100), nullable=False)
    descripcion = Column(String(300), nullable=False)
    cantidad_pedida = Column(Float, nullable=False)
    cantidad_recibida = Column(Float, nullable=False, default=0, server_default="0")
    precio_anterior = Column(Float, nullable=True)
    precio_pedido = Column(Float, nullable=True)

    pedido = relationship("PedidoProveedor", back_populates="lineas")


class RecepcionPedidoProveedor(Base):
    """Reserva idempotente de una recepción parcial de proveedor."""
    __tablename__ = "recepciones_pedido_proveedor"

    id = Column(Integer, primary_key=True)
    pedido_id = Column(Integer, ForeignKey("pedidos_proveedor.id"), nullable=False, index=True)
    event_id = Column(String(64), nullable=False, unique=True, index=True)
    lineas_json = Column(Text, nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    creado_en = Column(DateTime, nullable=False, server_default=func.now())

    pedido = relationship("PedidoProveedor", foreign_keys=[pedido_id])
    usuario = relationship("Usuario", foreign_keys=[usuario_id])


class PreparacionEntrega(Base):
    """Cesta preparada antes de que el trabajador llegue al mostrador."""
    __tablename__ = "preparaciones_entrega"
    __table_args__ = (
        CheckConstraint("estado IN ('preparada','entregada','cancelada')", name="ck_preparacion_estado"),
    )

    id = Column(Integer, primary_key=True)
    numero = Column(String(40), nullable=False, unique=True, index=True)
    qr_token = Column(String(64), nullable=True, unique=True, index=True)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=False, index=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=True)
    obra_id = Column(Integer, ForeignKey("obras.id"), nullable=True)
    destino = Column(String(200), nullable=True)
    lineas_json = Column(Text, nullable=False)
    estado = Column(String(20), nullable=False, default="preparada", index=True)
    creado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    creado_en = Column(DateTime, nullable=False, server_default=func.now())
    entregado_en = Column(DateTime, nullable=True)
    albaran_id = Column(Integer, ForeignKey("albaranes_salida.id"), nullable=True)
    notas = Column(Text, nullable=True)

    almacen = relationship("Almacen", foreign_keys=[almacen_id])
    trabajador = relationship("Trabajador", foreign_keys=[trabajador_id])
    obra = relationship("Obra", foreign_keys=[obra_id])
    creado_por = relationship("Usuario", foreign_keys=[creado_por_id])
    albaran = relationship("AlbaranSalida", foreign_keys=[albaran_id])


class LoteAlmacen(Base):
    """Lote y caducidad para consumibles y stock EPI histórico."""
    __tablename__ = "lotes_almacen"
    __table_args__ = (
        UniqueConstraint("tipo", "objeto_id", "almacen_id", "numero_lote", name="uq_lote_almacen"),
        CheckConstraint("cantidad >= 0", name="ck_lote_almacen_cantidad"),
    )

    id = Column(Integer, primary_key=True)
    tipo = Column(String(30), nullable=False, index=True)
    objeto_id = Column(Integer, nullable=False, index=True)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=False, index=True)
    numero_lote = Column(String(100), nullable=False)
    fecha_caducidad = Column(Date, nullable=True, index=True)
    cantidad = Column(Float, nullable=False, default=0)
    proveedor = Column(String(150), nullable=True)
    recibido_en = Column(DateTime, nullable=False, server_default=func.now())

    almacen = relationship("Almacen", foreign_keys=[almacen_id])


class CierreDiarioAlmacen(Base):
    """Foto inmutable y firmada de la actividad diaria de un almacén."""
    __tablename__ = "cierres_diarios_almacen"
    __table_args__ = (UniqueConstraint("almacen_id", "fecha", name="uq_cierre_diario_almacen"),)

    id = Column(Integer, primary_key=True)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=False, index=True)
    fecha = Column(Date, nullable=False, index=True)
    resumen_json = Column(Text, nullable=False)
    firma_datos = Column(Text, nullable=False)
    firma_nombre = Column(String(100), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    creado_en = Column(DateTime, nullable=False, server_default=func.now())

    almacen = relationship("Almacen", foreign_keys=[almacen_id])
    usuario = relationship("Usuario", foreign_keys=[usuario_id])


# ─── Repostaje de Vehículos (histórico externo) ───────────────────────────────

class RepostajeVehiculo(Base):
    """Repostaje de vehículo en gasolinera externa.
    Solo vincula a un Vehiculo; para el surtidor interno usar RepostajeSurtidor.
    """
    __tablename__ = "repostajes_vehiculos"

    id           = Column(Integer, primary_key=True, index=True)
    vehiculo_id  = Column(Integer, ForeignKey("vehiculos.id"), nullable=True, index=True)
    fecha        = Column(DateTime, default=datetime.utcnow)
    litros       = Column(Float, nullable=False)
    precio_litro = Column(Float, nullable=True)
    total_euros  = Column(Float, nullable=True)
    km_actuales  = Column(Integer, nullable=True)
    gasolinera   = Column(String(100), nullable=True)
    notas        = Column(Text, nullable=True)
    usuario_id   = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)

    vehiculo = relationship('Vehiculo', foreign_keys=[vehiculo_id])
    usuario  = relationship('Usuario',  foreign_keys=[usuario_id])

    @property
    def activo_nombre(self):
        if self.vehiculo:
            v = self.vehiculo
            return f"{v.matricula} {v.marca or ''}".strip()
        return "—"

    @property
    def activo_tipo(self):
        if self.vehiculo:
            return (self.vehiculo.tipo or "vehículo").capitalize()
        return "Vehículo"


# ─── Surtidor interno (toros + furgonetas en la nave) ─────────────────────────

class RepostajeSurtidor(Base):
    """Registro del surtidor propio de la nave.
    Puede ser un Vehiculo (furgoneta) O una Maquinaria (toro/carretilla).
    Exactamente uno de vehiculo_id / maquinaria_id debe estar relleno.
    """
    __tablename__ = "repostajes_surtidor"

    id               = Column(Integer, primary_key=True, index=True)
    # 'repostaje' = un activo echa combustible | 'compra' = se compra combustible para el depósito
    tipo_registro    = Column(String(20), nullable=False, default='repostaje')
    vehiculo_id      = Column(Integer, ForeignKey("vehiculos.id"),  nullable=True, index=True)
    maquinaria_id    = Column(Integer, ForeignKey("maquinaria.id"), nullable=True, index=True)
    tipo_combustible = Column(String(20), nullable=True, default='gasoil')  # gasoil | gasolina
    fecha            = Column(DateTime, default=datetime.utcnow)
    litros           = Column(Float, nullable=False)
    precio_litro     = Column(Float, nullable=True)
    total_euros      = Column(Float, nullable=True)
    km_actuales      = Column(Integer, nullable=True)
    proveedor        = Column(String(100), nullable=True)   # para compras: quién suministra
    notas            = Column(Text, nullable=True)
    usuario_id       = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)

    vehiculo   = relationship('Vehiculo',   foreign_keys=[vehiculo_id])
    maquinaria = relationship('Maquinaria', foreign_keys=[maquinaria_id])
    usuario    = relationship('Usuario',    foreign_keys=[usuario_id])

    @property
    def activo_nombre(self):
        if self.tipo_registro == 'compra':
            return self.proveedor or "Compra combustible"
        if self.vehiculo:
            v = self.vehiculo
            return f"{v.matricula} {v.marca or ''}".strip()
        if self.maquinaria:
            return self.maquinaria.nombre
        return "—"

    @property
    def activo_tipo(self):
        if self.tipo_registro == 'compra':
            return "Compra"
        if self.vehiculo:
            return (self.vehiculo.tipo or "furgoneta").capitalize()
        if self.maquinaria:
            return (self.maquinaria.tipo or "maquinaria").capitalize()


# ─── Inventario masivo V2: variantes, lotes y libro append-only ──────────────

class VarianteEPI(Base):
    __tablename__ = "variantes_epi"
    __table_args__ = (
        UniqueConstraint(
            "catalogo_epi_id", "modelo", "color", "talla",
            name="uq_variante_epi_catalogo_modelo_color_talla",
        ),
    )

    id = Column(Integer, primary_key=True)
    catalogo_epi_id = Column(Integer, ForeignKey("catalogo_epi.id"), nullable=False, index=True)
    modelo = Column(String(100), nullable=False, default="")
    color = Column(String(50), nullable=False, default="")
    talla = Column(String(20), nullable=False, default="")
    identificador_id = Column(Integer, ForeignKey("identificadores_globales.id"), nullable=False, unique=True)
    referencia_interna = Column(String(50), nullable=False, unique=True)
    codigo_qr = Column(String(50), nullable=False, unique=True)
    referencia_proveedor = Column(String(100), nullable=True, index=True)
    stock_minimo = Column(Integer, nullable=False, default=0)
    activo = Column(Boolean, nullable=False, default=True)
    creado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, server_default=func.now())

    catalogo = relationship("CatalogoEPI", foreign_keys=[catalogo_epi_id])
    identificador = relationship("IdentificadorGlobal", foreign_keys=[identificador_id])


class ExistenciaVariante(Base):
    __tablename__ = "existencias_variantes"
    __table_args__ = (
        UniqueConstraint(
            "variante_id", "almacen_id", "ubicacion_clave",
            name="uq_existencia_variante_almacen_ubicacion",
        ),
        CheckConstraint("cantidad >= 0", name="ck_existencia_cantidad_no_negativa"),
        CheckConstraint("ubicacion_clave >= 0", name="ck_existencia_ubicacion_clave"),
    )

    id = Column(Integer, primary_key=True)
    variante_id = Column(Integer, ForeignKey("variantes_epi.id"), nullable=False, index=True)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=False, index=True)
    ubicacion_id = Column(Integer, ForeignKey("ubicaciones.id"), nullable=True, index=True)
    # SQLite considera NULL distintos; la clave 0 hace la unicidad efectiva.
    ubicacion_clave = Column(Integer, nullable=False, default=0)
    cantidad = Column(Integer, nullable=False, default=0)
    stock_minimo = Column(Integer, nullable=False, default=0, server_default="0")
    version = Column(Integer, nullable=False, default=0)

    variante = relationship("VarianteEPI", foreign_keys=[variante_id])
    almacen = relationship("Almacen", foreign_keys=[almacen_id])
    ubicacion = relationship("Ubicacion", foreign_keys=[ubicacion_id])


class LoteVariante(Base):
    __tablename__ = "lotes_variantes"
    __table_args__ = (
        UniqueConstraint(
            "existencia_id", "numero_lote", "caducidad_clave",
            name="uq_lote_variante_real",
        ),
        CheckConstraint("cantidad >= 0", name="ck_lote_cantidad_no_negativa"),
    )

    id = Column(Integer, primary_key=True)
    existencia_id = Column(Integer, ForeignKey("existencias_variantes.id"), nullable=False, index=True)
    numero_lote = Column(String(100), nullable=False)
    fecha_caducidad = Column(Date, nullable=True)
    # Igual que ubicación: nunca NULL dentro de la restricción UNIQUE.
    caducidad_clave = Column(String(10), nullable=False, default="")
    cantidad = Column(Integer, nullable=False, default=0)
    version = Column(Integer, nullable=False, default=0)

    existencia = relationship("ExistenciaVariante", foreign_keys=[existencia_id])


class RecepcionSuministro(Base):
    """Cabecera auditable de cada entrada física de una variante."""
    __tablename__ = "recepciones_suministros"
    __table_args__ = (
        CheckConstraint("cantidad > 0", name="ck_recepcion_cantidad_positiva"),
        CheckConstraint("precio_unitario IS NULL OR precio_unitario >= 0", name="ck_recepcion_precio_no_negativo"),
    )

    id = Column(Integer, primary_key=True)
    event_id = Column(String(64), nullable=False, unique=True, index=True)
    request_hash = Column(String(64), nullable=False)
    variante_id = Column(Integer, ForeignKey("variantes_epi.id"), nullable=False, index=True)
    existencia_id = Column(Integer, ForeignKey("existencias_variantes.id"), nullable=False, index=True)
    lote_id = Column(Integer, ForeignKey("lotes_variantes.id"), nullable=True, index=True)
    cantidad = Column(Integer, nullable=False)
    proveedor = Column(String(150), nullable=True)
    albaran = Column(String(100), nullable=True, index=True)
    precio_unitario = Column(Float, nullable=True)
    numero_lote = Column(String(100), nullable=True)
    fecha_caducidad = Column(Date, nullable=True)
    ubicacion_id = Column(Integer, ForeignKey("ubicaciones.id"), nullable=True)
    recibido_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    recibido_en = Column(DateTime, nullable=False, server_default=func.now(), index=True)

    variante = relationship("VarianteEPI", foreign_keys=[variante_id])
    existencia = relationship("ExistenciaVariante", foreign_keys=[existencia_id])
    lote = relationship("LoteVariante", foreign_keys=[lote_id])


class MovimientoStock(Base):
    """Libro común e inmutable para ropa, variantes y consumibles."""
    __tablename__ = "movimientos_stock"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN stock_epi_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN material_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN existencia_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_movimiento_stock_un_articulo",
        ),
        CheckConstraint("cantidad != 0", name="ck_movimiento_stock_cantidad_no_cero"),
        CheckConstraint("saldo_anterior >= 0 AND saldo_posterior >= 0", name="ck_movimiento_stock_saldos"),
    )

    id = Column(Integer, primary_key=True)
    tipo_articulo = Column(String(20), nullable=False, index=True)
    stock_epi_id = Column(Integer, ForeignKey("stock_epi.id"), nullable=True, index=True)
    material_id = Column(Integer, ForeignKey("materiales.id"), nullable=True, index=True)
    existencia_id = Column(Integer, ForeignKey("existencias_variantes.id"), nullable=True, index=True)
    lote_id = Column(Integer, ForeignKey("lotes_variantes.id"), nullable=True, index=True)
    cantidad = Column(Float, nullable=False)
    tipo = Column(String(30), nullable=False, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=True)
    obra_id = Column(Integer, ForeignKey("obras.id"), nullable=True)
    event_id = Column(String(64), nullable=False, unique=True, index=True)
    request_hash = Column(String(64), nullable=False)
    saldo_anterior = Column(Float, nullable=False)
    saldo_posterior = Column(Float, nullable=False)
    motivo = Column(String(300), nullable=False)
    creado_en = Column(DateTime, nullable=False, server_default=func.now(), index=True)


@sqlalchemy_event.listens_for(MovimientoStock, "before_update")
def _movimiento_stock_no_actualizable(*_args):
    raise ValueError("El libro de movimientos de stock es append-only")


@sqlalchemy_event.listens_for(MovimientoStock, "before_delete")
def _movimiento_stock_no_eliminable(*_args):
    raise ValueError("El libro de movimientos de stock es append-only")


class EventoOperacion(Base):
    """Idempotencia común de las operaciones del inventario V2."""
    __tablename__ = "eventos_operacion"

    id = Column(Integer, primary_key=True)
    event_id = Column(String(64), nullable=False, unique=True, index=True)
    tipo = Column(String(30), nullable=False)
    recurso = Column(String(100), nullable=False)
    request_hash = Column(String(64), nullable=False)
    estado = Column(String(20), nullable=False, default="pending")
    resultado_json = Column(Text, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    creado_en = Column(DateTime, nullable=False, server_default=func.now())


class SesionInventario(Base):
    __tablename__ = "sesiones_inventario"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('abierta','en_conteo','revision','segundo_conteo','pendiente_cierre','cerrada','cancelada')",
            name="ck_sesion_inventario_estado",
        ),
        CheckConstraint(
            "scope IN ('almacen','ubicacion','categoria','total')",
            name="ck_sesion_inventario_scope",
        ),
        CheckConstraint(
            "tipo_articulo IN ('todo','material','epi_ropa','epi_individual')",
            name="ck_sesion_inventario_tipo",
        ),
    )

    id = Column(Integer, primary_key=True)
    nombre = Column(String(200), nullable=False)
    almacen_id = Column(Integer, ForeignKey("almacenes.id"), nullable=True, index=True)
    scope = Column(String(30), nullable=False, default="almacen")
    scope_detalle = Column(String(200), nullable=True)
    tipo_articulo = Column(String(30), nullable=False, default="todo")
    estado = Column(String(30), nullable=False, default="abierta", index=True)
    creado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    autorizado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    opened_at = Column(DateTime, nullable=False, server_default=func.now())
    movimiento_cursor = Column(Integer, nullable=False, default=0)
    cerrado_en = Column(DateTime, nullable=True)
    observaciones = Column(Text, nullable=True)
    umbral_desviacion = Column(Float, nullable=False, default=5.0)
    cierre_event_id = Column(String(64), nullable=True, unique=True)

    lineas = relationship(
        "LineaInventario", back_populates="sesion", cascade="all, delete-orphan",
    )


class LineaInventario(Base):
    __tablename__ = "lineas_inventario"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN material_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN existencia_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN stock_epi_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN epi_individual_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_linea_inventario_un_articulo",
        ),
        CheckConstraint("cantidad_esperada >= 0", name="ck_linea_snapshot_no_negativo"),
        CheckConstraint(
            "estado IN ('pendiente','contado_1','contado_2','conflicto','aprobado','ajustado')",
            name="ck_linea_inventario_estado",
        ),
    )

    id = Column(Integer, primary_key=True)
    sesion_id = Column(Integer, ForeignKey("sesiones_inventario.id"), nullable=False, index=True)
    material_id = Column(Integer, ForeignKey("materiales.id"), nullable=True, index=True)
    existencia_id = Column(Integer, ForeignKey("existencias_variantes.id"), nullable=True, index=True)
    stock_epi_id = Column(Integer, ForeignKey("stock_epi.id"), nullable=True, index=True)
    epi_individual_id = Column(Integer, ForeignKey("epis_individuales.id"), nullable=True, index=True)
    cantidad_esperada = Column(Float, nullable=False, default=0)
    cantidad_contada_1 = Column(Float, nullable=True)
    cantidad_contada_2 = Column(Float, nullable=True)
    cantidad_final = Column(Float, nullable=True)
    diferencia = Column(Float, nullable=True)
    estado = Column(String(30), nullable=False, default="pendiente")
    aprobado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    aprobado_en = Column(DateTime, nullable=True)
    notas = Column(Text, nullable=True)
    conteo_ciego = Column(Boolean, nullable=False, default=True)

    sesion = relationship("SesionInventario", back_populates="lineas")
    intentos = relationship("IntentoConteo", back_populates="linea", order_by="IntentoConteo.id")


class ActivoInventarioEscaneado(Base):
    """Presencia física de activos unitarios dentro de una sesión de inventario."""
    __tablename__ = "activos_inventario_escaneados"
    __table_args__ = (
        UniqueConstraint("sesion_id", "tipo", "item_id", name="uq_activo_inventario_sesion"),
        CheckConstraint(
            "tipo IN ('herramienta','maquinaria','vehiculo')",
            name="ck_activo_inventario_tipo",
        ),
    )

    id = Column(Integer, primary_key=True)
    sesion_id = Column(Integer, ForeignKey("sesiones_inventario.id"), nullable=False, index=True)
    tipo = Column(String(30), nullable=False, index=True)
    item_id = Column(Integer, nullable=False, index=True)
    codigo = Column(String(150), nullable=False)
    nombre = Column(String(250), nullable=False)
    estado_snapshot = Column(String(80), nullable=True)
    esperado = Column(Boolean, nullable=False, default=True)
    encontrado_en = Column(DateTime, nullable=True)
    encontrado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)


class IntentoConteo(Base):
    __tablename__ = "intentos_conteo"
    __table_args__ = (
        CheckConstraint("numero_conteo IN (1,2)", name="ck_intento_numero"),
        CheckConstraint("cantidad >= 0 AND cantidad_calculada >= 0", name="ck_intento_cantidad"),
        CheckConstraint("modo_entrada IN ('unidad','incremento','caja')", name="ck_intento_modo"),
        CheckConstraint(
            "(modo_entrada = 'caja' AND unidades_por_caja IS NOT NULL AND unidades_por_caja > 0) "
            "OR (modo_entrada != 'caja' AND unidades_por_caja IS NULL)",
            name="ck_intento_caja",
        ),
    )

    id = Column(Integer, primary_key=True)
    linea_id = Column(Integer, ForeignKey("lineas_inventario.id"), nullable=False, index=True)
    sesion_id = Column(Integer, ForeignKey("sesiones_inventario.id"), nullable=False, index=True)
    scan_event_id = Column(String(64), nullable=False, unique=True, index=True)
    numero_conteo = Column(Integer, nullable=False)
    cantidad = Column(Float, nullable=False)
    modo_entrada = Column(String(20), nullable=False, default="unidad")
    unidades_por_caja = Column(Integer, nullable=True)
    cantidad_calculada = Column(Float, nullable=False)
    registrado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    registrado_en = Column(DateTime, nullable=False, server_default=func.now())
    puesto_id = Column(String(64), nullable=True)
    notas = Column(Text, nullable=True)

    linea = relationship("LineaInventario", back_populates="intentos")


class AjusteInventario(Base):
    __tablename__ = "ajustes_inventario"

    id = Column(Integer, primary_key=True)
    sesion_id = Column(Integer, ForeignKey("sesiones_inventario.id"), nullable=True, index=True)
    linea_id = Column(Integer, ForeignKey("lineas_inventario.id"), nullable=True, unique=True)
    material_id = Column(Integer, ForeignKey("materiales.id"), nullable=True)
    existencia_id = Column(Integer, ForeignKey("existencias_variantes.id"), nullable=True)
    stock_epi_id = Column(Integer, ForeignKey("stock_epi.id"), nullable=True)
    cantidad_snapshot = Column(Float, nullable=False)
    movimientos_periodo = Column(Float, nullable=False)
    cantidad_esperada_cierre = Column(Float, nullable=False)
    cantidad_fisica = Column(Float, nullable=False)
    diferencia = Column(Float, nullable=False)
    tipo = Column(String(30), nullable=False, default="inventario")
    motivo = Column(String(300), nullable=False)
    aplicado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    aplicado_en = Column(DateTime, nullable=False, server_default=func.now())
    operacion_id = Column(String(64), nullable=True, index=True)


@sqlalchemy_event.listens_for(AjusteInventario, "before_update")
@sqlalchemy_event.listens_for(AjusteInventario, "before_delete")
def _ajuste_inventario_inmutable(*_args):
    raise ValueError("Los ajustes de inventario son append-only")


class DotacionTrabajador(Base):
    __tablename__ = "dotaciones_trabajador"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('pendiente','preparada','entregada','cancelada')",
            name="ck_dotacion_estado",
        ),
    )

    id = Column(Integer, primary_key=True)
    trabajador_id = Column(Integer, ForeignKey("trabajadores.id"), nullable=False, index=True)
    estado = Column(String(20), nullable=False, default="pendiente", index=True)
    creado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    confirmado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    creado_en = Column(DateTime, nullable=False, server_default=func.now())
    confirmado_en = Column(DateTime, nullable=True)
    confirmacion_event_id = Column(String(64), nullable=True, unique=True)
    firmado_por = Column(String(150), nullable=True)
    firma_base64 = Column(Text, nullable=True)
    actualizado_en = Column(DateTime, nullable=True)

    lineas = relationship(
        "LineaDotacion", back_populates="dotacion", cascade="all, delete-orphan",
    )


class LineaDotacion(Base):
    __tablename__ = "lineas_dotacion"
    __table_args__ = (
        CheckConstraint(
            "estado IN ('pendiente','preparada','entregada','devuelta','sustituida','cancelada','sin_stock')",
            name="ck_linea_dotacion_estado",
        ),
    )

    id = Column(Integer, primary_key=True)
    dotacion_id = Column(Integer, ForeignKey("dotaciones_trabajador.id"), nullable=False, index=True)
    catalogo_epi_id = Column(Integer, ForeignKey("catalogo_epi.id"), nullable=False)
    nombre = Column(String(100), nullable=False)
    categoria = Column(String(20), nullable=False)
    talla = Column(String(20), nullable=True)
    cantidad = Column(Integer, nullable=False)
    estado = Column(String(20), nullable=False, default="pendiente", index=True)
    existencia_id = Column(Integer, ForeignKey("existencias_variantes.id"), nullable=True)
    epi_individual_id = Column(Integer, ForeignKey("epis_individuales.id"), nullable=True)
    codigo_preparado = Column(String(50), nullable=True)
    preparado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    preparado_en = Column(DateTime, nullable=True)
    entregado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    entregado_en = Column(DateTime, nullable=True)
    entrega_event_id = Column(String(64), nullable=True, unique=True)
    devuelto_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    devuelto_en = Column(DateTime, nullable=True)
    devolucion_event_id = Column(String(64), nullable=True, unique=True)
    sustituye_linea_id = Column(Integer, ForeignKey("lineas_dotacion.id"), nullable=True)
    observaciones = Column(Text, nullable=True)

    dotacion = relationship("DotacionTrabajador", back_populates="lineas")


class ReinicioInventarioRopa(Base):
    """Auditoría inmutable de una puesta a cero exclusiva de ropa."""
    __tablename__ = "reinicios_inventario_ropa"

    id = Column(Integer, primary_key=True)
    operacion_id = Column(String(64), nullable=False, unique=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    backup_path = Column(String(500), nullable=False)
    preview_hash = Column(String(64), nullable=False)
    filas_afectadas = Column(Integer, nullable=False)
    creado_en = Column(DateTime, nullable=False, server_default=func.now())


@sqlalchemy_event.listens_for(ReinicioInventarioRopa, "before_update")
@sqlalchemy_event.listens_for(ReinicioInventarioRopa, "before_delete")
def _reinicio_ropa_inmutable(*_args):
    raise ValueError("La auditoría de reinicios de ropa es append-only")


class LogImpresionEtiqueta(Base):
    __tablename__ = "logs_impresion_etiquetas"

    id = Column(Integer, primary_key=True)
    event_id = Column(String(64), nullable=False, unique=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    tipo = Column(String(30), nullable=False)
    referencia = Column(String(100), nullable=False)
    copias = Column(Integer, nullable=False)
    reimpresion = Column(Boolean, nullable=False, default=False)
    motivo_reimpresion = Column(String(300), nullable=True)
    zpl_hash = Column(String(64), nullable=False)
    impresora_host = Column(String(255), nullable=False)
    creado_en = Column(DateTime, nullable=False, server_default=func.now())


@sqlalchemy_event.listens_for(LogImpresionEtiqueta, "before_update")
@sqlalchemy_event.listens_for(LogImpresionEtiqueta, "before_delete")
def _log_impresion_inmutable(*_args):
    raise ValueError("El registro de impresión es append-only")


# ─── Fichas de Salida a Obra (Maquinaria) ─────────────────────────────────────

class SalidaObra(Base):
    __tablename__ = "salidas_obra"

    id                = Column(Integer, primary_key=True, index=True)
    maquinaria_id     = Column(Integer, ForeignKey("maquinaria.id"), nullable=True, index=True)
    herramienta_id    = Column(Integer, ForeignKey("herramientas.id"), nullable=True, index=True)
    tipo_checklist    = Column(String(30), nullable=False)
    fecha_salida      = Column(DateTime, nullable=False, server_default=func.now())
    obra              = Column(String(200), nullable=True)
    conductor         = Column(String(100), nullable=True)
    responsable_patio = Column(String(100), nullable=True)
    jefe_obra         = Column(String(100), nullable=True)
    kit_altura        = Column(String(20), nullable=True)
    n_tramos          = Column(Integer, nullable=True)
    cable_diametro    = Column(String(5), nullable=True)
    estado            = Column(String(20), default='en_proceso', index=True)
    observaciones     = Column(Text, nullable=True)
    usuario_id        = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at        = Column(DateTime, server_default=func.now())

    maquinaria  = relationship("Maquinaria", backref="salidas_obra", foreign_keys="[SalidaObra.maquinaria_id]")
    herramienta = relationship("Herramienta", backref="salidas_obra", foreign_keys="[SalidaObra.herramienta_id]")
    items       = relationship("SalidaItem", back_populates="salida",
                              cascade="all, delete-orphan",
                              order_by="SalidaItem.id")


class SalidaItem(Base):
    __tablename__ = "salida_items"
    __table_args__ = (
        UniqueConstraint("salida_id", "item_key", name="uq_salida_item"),
    )

    id         = Column(Integer, primary_key=True, index=True)
    salida_id  = Column(Integer, ForeignKey("salidas_obra.id"), nullable=False, index=True)
    item_key   = Column(String(100), nullable=False)
    checked    = Column(Boolean, default=False, nullable=False)
    checked_at = Column(DateTime, nullable=True)
    checked_by = Column(String(100), nullable=True)

    salida = relationship("SalidaObra", back_populates="items")


# Los identificadores escaneables se guardan en una forma canónica. Así las
# búsquedas exactas usan sus índices y no aplican UPPER/TRIM sobre cada fila.
_SCANNABLE_FIELDS = {
    Herramienta: ("codigo", "num_serie"),
    Maquinaria: ("codigo_barras", "codigo_interno", "matricula", "num_serie"),
    Vehiculo: ("codigo", "matricula"),
    Material: ("codigo",),
    StockEPI: ("codigo",),
    EPIIndividual: ("codigo_qr", "referencia_interna", "codigo_fabricacion"),
    VarianteEPI: ("codigo_qr", "referencia_interna", "referencia_proveedor"),
    Almacen: ("codigo",),
    Ubicacion: ("codigo",),
}


def _normalize_scannable_identifiers(_mapper, _connection, target):
    for field in _SCANNABLE_FIELDS.get(type(target), ()):
        value = getattr(target, field, None)
        if isinstance(value, str):
            setattr(target, field, value.strip().upper() or None)


for _scannable_model in _SCANNABLE_FIELDS:
    sqlalchemy_event.listen(_scannable_model, "before_insert", _normalize_scannable_identifiers)
    sqlalchemy_event.listen(_scannable_model, "before_update", _normalize_scannable_identifiers)
