// ── Modelos de datos MRD TOOL CONTROL ────────────────────────────────────────

class UserModel {
  final int id;
  final String username;
  final String email;
  final String nombre;
  final String? apellidos;
  final String role;
  final String? avatar;

  UserModel({
    required this.id, required this.username, required this.email,
    required this.nombre, this.apellidos, required this.role, this.avatar,
  });

  factory UserModel.fromJson(Map<String, dynamic> j) => UserModel(
    id: j['id'], username: j['username'] ?? '', email: j['email'] ?? '',
    nombre: j['nombre'] ?? j['username'] ?? '',
    apellidos: j['apellidos'], role: j['role'] ?? 'user', avatar: j['avatar'],
  );

  Map<String, dynamic> toJson() => {
    'id': id, 'username': username, 'email': email,
    'nombre': nombre, 'apellidos': apellidos, 'role': role, 'avatar': avatar,
  };

  String get fullName => apellidos != null ? '$nombre $apellidos' : nombre;
}

class Herramienta {
  final int id;
  final String codigo;
  final String nombre;
  final String? descripcion;
  final String estado;
  final String? categoria;
  final String? ubicacion;
  final String? foto;
  final String? numeroSerie;
  final DateTime? fechaCompra;
  final double? valorActual;

  Herramienta({
    required this.id, required this.codigo, required this.nombre,
    this.descripcion, required this.estado, this.categoria,
    this.ubicacion, this.foto, this.numeroSerie,
    this.fechaCompra, this.valorActual,
  });

  factory Herramienta.fromJson(Map<String, dynamic> j) => Herramienta(
    id: j['id'], codigo: j['codigo'] ?? '', nombre: j['nombre'] ?? '',
    descripcion: j['descripcion'], estado: j['estado'] ?? 'disponible',
    categoria: j['categoria'], ubicacion: j['ubicacion_texto'],
    foto: j['foto'], numeroSerie: j['numero_serie'],
    fechaCompra: j['fecha_compra'] != null ? DateTime.tryParse(j['fecha_compra']) : null,
    valorActual: (j['valor_actual'] as num?)?.toDouble(),
  );

  Map<String, dynamic> toJson() => {
    'id': id, 'codigo': codigo, 'nombre': nombre,
    'descripcion': descripcion, 'estado': estado,
    'categoria': categoria, 'ubicacion_texto': ubicacion,
    'foto': foto, 'numero_serie': numeroSerie,
    'valor_actual': valorActual,
  };

  Color get estadoColor {
    switch (estado.toLowerCase()) {
      case 'disponible': return const Color(0xFF198754);
      case 'en_uso': return const Color(0xFF0D6EFD);
      case 'mantenimiento': return const Color(0xFFFFC107);
      case 'baja': return const Color(0xFFDC3545);
      default: return const Color(0xFF6C757D);
    }
  }
}

class Material {
  final int id;
  final String codigo;
  final String nombre;
  final String? descripcion;
  final double stock;
  final String? unidad;
  final double? stockMinimo;
  final double? precio;

  Material({
    required this.id, required this.codigo, required this.nombre,
    this.descripcion, required this.stock, this.unidad,
    this.stockMinimo, this.precio,
  });

  factory Material.fromJson(Map<String, dynamic> j) => Material(
    id: j['id'], codigo: j['codigo'] ?? '', nombre: j['nombre'] ?? '',
    descripcion: j['descripcion'],
    stock: (j['stock'] as num?)?.toDouble() ?? 0,
    unidad: j['unidad'],
    stockMinimo: (j['stock_minimo'] as num?)?.toDouble(),
    precio: (j['precio'] as num?)?.toDouble(),
  );

  bool get stockBajo => stockMinimo != null && stock <= stockMinimo!;
}

class Obra {
  final int id;
  final String codigo;
  final String nombre;
  final String estado;
  final String? descripcion;
  final String? responsable;
  final DateTime? fechaInicio;
  final DateTime? fechaFin;

  Obra({
    required this.id, required this.codigo, required this.nombre,
    required this.estado, this.descripcion, this.responsable,
    this.fechaInicio, this.fechaFin,
  });

  factory Obra.fromJson(Map<String, dynamic> j) => Obra(
    id: j['id'], codigo: j['codigo'] ?? '', nombre: j['nombre'] ?? '',
    estado: j['estado'] ?? 'activa', descripcion: j['descripcion'],
    responsable: j['responsable'],
    fechaInicio: j['fecha_inicio'] != null ? DateTime.tryParse(j['fecha_inicio']) : null,
    fechaFin: j['fecha_fin'] != null ? DateTime.tryParse(j['fecha_fin']) : null,
  );
}

class Trabajador {
  final int id;
  final String nombre;
  final String? apellidos;
  final String? dni;
  final String? puesto;
  final String? telefono;
  final String? email;
  final String? foto;
  final bool activo;

  Trabajador({
    required this.id, required this.nombre, this.apellidos, this.dni,
    this.puesto, this.telefono, this.email, this.foto, required this.activo,
  });

  factory Trabajador.fromJson(Map<String, dynamic> j) => Trabajador(
    id: j['id'], nombre: j['nombre'] ?? '',
    apellidos: j['apellidos'], dni: j['dni'],
    puesto: j['puesto'] ?? j['cargo'], telefono: j['telefono'],
    email: j['email'], foto: j['foto'],
    activo: j['activo'] ?? true,
  );

  String get fullName => apellidos != null ? '$nombre $apellidos' : nombre;
}

class Vehiculo {
  final int id;
  final String matricula;
  final String? marca;
  final String? modelo;
  final String estado;
  final String? tipo;
  final DateTime? itvHasta;
  final DateTime? seguroHasta;
  final String? foto;

  Vehiculo({
    required this.id, required this.matricula, this.marca, this.modelo,
    required this.estado, this.tipo, this.itvHasta, this.seguroHasta, this.foto,
  });

  factory Vehiculo.fromJson(Map<String, dynamic> j) => Vehiculo(
    id: j['id'], matricula: j['matricula'] ?? '',
    marca: j['marca'], modelo: j['modelo'],
    estado: j['estado'] ?? 'disponible', tipo: j['tipo'],
    itvHasta: j['itv_hasta'] != null ? DateTime.tryParse(j['itv_hasta']) : null,
    seguroHasta: j['seguro_hasta'] != null ? DateTime.tryParse(j['seguro_hasta']) : null,
    foto: j['foto'],
  );
}

class Epi {
  final int id;
  final String nombre;
  final String? categoria;
  final int stock;
  final int? stockMinimo;
  final String? descripcion;

  Epi({
    required this.id, required this.nombre, this.categoria,
    required this.stock, this.stockMinimo, this.descripcion,
  });

  factory Epi.fromJson(Map<String, dynamic> j) => Epi(
    id: j['id'], nombre: j['nombre'] ?? '',
    categoria: j['categoria'], stock: j['stock'] ?? 0,
    stockMinimo: j['stock_minimo'], descripcion: j['descripcion'],
  );
}

class Incidencia {
  final int id;
  final String titulo;
  final String? descripcion;
  final String estado;
  final String prioridad;
  final DateTime createdAt;
  final String? herramientaNombre;
  final String? reportadoPor;

  Incidencia({
    required this.id, required this.titulo, this.descripcion,
    required this.estado, required this.prioridad, required this.createdAt,
    this.herramientaNombre, this.reportadoPor,
  });

  factory Incidencia.fromJson(Map<String, dynamic> j) => Incidencia(
    id: j['id'], titulo: j['titulo'] ?? '',
    descripcion: j['descripcion'], estado: j['estado'] ?? 'abierta',
    prioridad: j['prioridad'] ?? 'media',
    createdAt: DateTime.tryParse(j['created_at'] ?? '') ?? DateTime.now(),
    herramientaNombre: j['herramienta_nombre'],
    reportadoPor: j['reportado_por'],
  );
}

class SyncQueueItem {
  final int? id;
  final String endpoint;
  final String method;
  final String body;
  final DateTime createdAt;
  int retries;
  bool synced;

  SyncQueueItem({
    this.id, required this.endpoint, required this.method,
    required this.body, required this.createdAt,
    this.retries = 0, this.synced = false,
  });

  Map<String, dynamic> toMap() => {
    'endpoint': endpoint, 'method': method, 'body': body,
    'created_at': createdAt.toIso8601String(),
    'retries': retries, 'synced': synced ? 1 : 0,
  };

  factory SyncQueueItem.fromMap(Map<String, dynamic> m) => SyncQueueItem(
    id: m['id'], endpoint: m['endpoint'], method: m['method'],
    body: m['body'],
    createdAt: DateTime.parse(m['created_at']),
    retries: m['retries'] ?? 0, synced: (m['synced'] ?? 0) == 1,
  );
}

// Flutter import needed in models file
import 'package:flutter/material.dart';
