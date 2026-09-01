import 'dart:convert';
import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart';
import '../models/models.dart';
import '../config/app_config.dart';

class LocalDatabase {
  static final LocalDatabase _i = LocalDatabase._();
  static LocalDatabase get instance => _i;
  LocalDatabase._();

  Database? _db;

  Future<Database> get db async {
    _db ??= await _open();
    return _db!;
  }

  Future<Database> _open() async {
    final path = join(await getDatabasesPath(), 'mrd_tool_control.db');
    return openDatabase(path, version: 1, onCreate: _onCreate);
  }

  Future<void> _onCreate(Database db, int version) async {
    // Cola de sincronización offline
    await db.execute('''
      CREATE TABLE sync_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        endpoint TEXT NOT NULL,
        method TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        retries INTEGER DEFAULT 0,
        synced INTEGER DEFAULT 0
      )''');

    // Cache de herramientas
    await db.execute('''
      CREATE TABLE herramientas (
        id INTEGER PRIMARY KEY,
        codigo TEXT,
        nombre TEXT,
        descripcion TEXT,
        estado TEXT,
        categoria TEXT,
        ubicacion TEXT,
        foto TEXT,
        numero_serie TEXT,
        valor_actual REAL,
        cached_at TEXT
      )''');

    // Cache de obras
    await db.execute('''
      CREATE TABLE obras (
        id INTEGER PRIMARY KEY,
        codigo TEXT,
        nombre TEXT,
        estado TEXT,
        descripcion TEXT,
        cached_at TEXT
      )''');

    // Cache de trabajadores
    await db.execute('''
      CREATE TABLE trabajadores (
        id INTEGER PRIMARY KEY,
        nombre TEXT,
        apellidos TEXT,
        puesto TEXT,
        telefono TEXT,
        foto TEXT,
        activo INTEGER,
        cached_at TEXT
      )''');

    // Cache de incidencias creadas offline
    await db.execute('''
      CREATE TABLE incidencias_local (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titulo TEXT,
        descripcion TEXT,
        prioridad TEXT,
        herramienta_id INTEGER,
        foto_path TEXT,
        firma_path TEXT,
        created_at TEXT,
        synced INTEGER DEFAULT 0
      )''');

    // Fotos pendientes de subir
    await db.execute('''
      CREATE TABLE photos_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        local_path TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        field_name TEXT NOT NULL,
        extra_data TEXT,
        created_at TEXT,
        synced INTEGER DEFAULT 0
      )''');
  }

  // ── Cola de sincronización ────────────────────────────────────────────────────
  Future<void> enqueue(String endpoint, String method, Map<String, dynamic> data) async {
    final d = await db;
    await d.insert('sync_queue', {
      'endpoint': endpoint,
      'method': method,
      'body': jsonEncode(data),
      'created_at': DateTime.now().toIso8601String(),
      'retries': 0,
      'synced': 0,
    });
  }

  Future<List<SyncQueueItem>> getPendingQueue() async {
    final d = await db;
    final rows = await d.query('sync_queue', where: 'synced = 0', orderBy: 'created_at ASC');
    return rows.map((r) => SyncQueueItem.fromMap(r)).toList();
  }

  Future<void> markSynced(int id) async {
    final d = await db;
    await d.update('sync_queue', {'synced': 1}, where: 'id = ?', whereArgs: [id]);
  }

  Future<void> incrementRetry(int id) async {
    final d = await db;
    await d.rawUpdate('UPDATE sync_queue SET retries = retries + 1 WHERE id = ?', [id]);
  }

  Future<void> processQueue() async {
    final pending = await getPendingQueue();
    for (final item in pending) {
      if (item.retries >= AppConfig.maxSyncRetries) continue;
      try {
        // Procesado por SyncService
        await _processItem(item);
        await markSynced(item.id!);
      } catch (_) {
        await incrementRetry(item.id!);
      }
    }
  }

  Future<void> _processItem(SyncQueueItem item) async {
    final data = jsonDecode(item.body) as Map<String, dynamic>;
    if (item.method == 'POST') {
      await ApiService.instance.post(item.endpoint, data);
    } else if (item.method == 'PUT') {
      await ApiService.instance.put(item.endpoint, data);
    }
  }

  // ── Cache de herramientas ─────────────────────────────────────────────────────
  Future<void> cacheHerramientas(List<Herramienta> items) async {
    final d = await db;
    final batch = d.batch();
    batch.delete('herramientas');
    for (final h in items) {
      batch.insert('herramientas', {
        'id': h.id, 'codigo': h.codigo, 'nombre': h.nombre,
        'descripcion': h.descripcion, 'estado': h.estado,
        'categoria': h.categoria, 'ubicacion': h.ubicacion,
        'foto': h.foto, 'numero_serie': h.numeroSerie,
        'valor_actual': h.valorActual,
        'cached_at': DateTime.now().toIso8601String(),
      });
    }
    await batch.commit();
  }

  Future<List<Herramienta>> getCachedHerramientas({String? query}) async {
    final d = await db;
    final rows = query != null
      ? await d.query('herramientas',
          where: 'nombre LIKE ? OR codigo LIKE ?',
          whereArgs: ['%$query%', '%$query%'])
      : await d.query('herramientas');
    return rows.map((r) => Herramienta.fromJson(r)).toList();
  }

  // ── Cache de obras ─────────────────────────────────────────────────────────────
  Future<void> cacheObras(List<Obra> items) async {
    final d = await db;
    final batch = d.batch();
    batch.delete('obras');
    for (final o in items) {
      batch.insert('obras', {
        'id': o.id, 'codigo': o.codigo, 'nombre': o.nombre,
        'estado': o.estado, 'descripcion': o.descripcion,
        'cached_at': DateTime.now().toIso8601String(),
      });
    }
    await batch.commit();
  }

  Future<List<Obra>> getCachedObras() async {
    final d = await db;
    final rows = await d.query('obras');
    return rows.map((r) => Obra.fromJson(r)).toList();
  }

  // ── Cola de fotos ─────────────────────────────────────────────────────────────
  Future<void> enqueuePhoto(String path, String endpoint, String field,
      {Map<String, dynamic>? extra}) async {
    final d = await db;
    await d.insert('photos_queue', {
      'local_path': path,
      'endpoint': endpoint,
      'field_name': field,
      'extra_data': extra != null ? jsonEncode(extra) : null,
      'created_at': DateTime.now().toIso8601String(),
      'synced': 0,
    });
  }

  Future<int> pendingCount() async {
    final d = await db;
    final r = await d.rawQuery('SELECT COUNT(*) as c FROM sync_queue WHERE synced = 0');
    return (r.first['c'] as int? ?? 0);
  }
}

import 'api_service.dart';
