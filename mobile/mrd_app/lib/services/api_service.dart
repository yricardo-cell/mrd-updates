import 'package:dio/dio.dart';
import 'package:connectivity_plus/connectivity_plus.dart';
import '../config/app_config.dart';
import 'auth_service.dart';
import 'local_database.dart';

class ApiService {
  static final ApiService _i = ApiService._();
  static ApiService get instance => _i;
  ApiService._() { _init(); }

  late final Dio _dio;
  bool _isOnline = true;

  bool get isOnline => _isOnline;

  void _init() {
    _dio = Dio(BaseOptions(
      baseUrl: AppConfig.baseUrl,
      connectTimeout: Duration(seconds: AppConfig.connectTimeout),
      receiveTimeout: Duration(seconds: AppConfig.receiveTimeout),
      headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
    ));

    // Auth interceptor
    _dio.interceptors.add(InterceptorsWrapper(
      onRequest: (opts, handler) async {
        if (opts.extra['authenticated'] != false) {
          final token = await AuthService.instance.getToken();
          if (token != null) opts.headers['Authorization'] = 'Bearer $token';
        }
        handler.next(opts);
      },
      onError: (DioException e, handler) async {
        if (e.response?.statusCode == 401) {
          final refreshed = await AuthService.instance.refreshToken();
          if (refreshed) {
            final token = await AuthService.instance.getToken();
            final opts = e.requestOptions;
            opts.headers['Authorization'] = 'Bearer $token';
            final retry = await _dio.fetch(opts);
            return handler.resolve(retry);
          }
          await AuthService.instance.logout();
        }
        handler.next(e);
      },
    ));

    // Connectivity monitor
    Connectivity().onConnectivityChanged.listen((results) {
      _isOnline = results.any((r) => r != ConnectivityResult.none);
      if (_isOnline) LocalDatabase.instance.processQueue();
    });
  }

  Future<Response> get(String path, {Map<String, dynamic>? params, bool authenticated = true}) async {
    return _dio.get(path, queryParameters: params, options: Options(extra: {'authenticated': authenticated}));
  }

  Future<Response> post(String path, Map<String, dynamic> data, {bool authenticated = true}) async {
    return _dio.post(path, data: data, options: Options(extra: {'authenticated': authenticated}));
  }

  Future<Response> put(String path, Map<String, dynamic> data) async {
    return _dio.put(path, data: data);
  }

  Future<Response> patch(String path, Map<String, dynamic> data) async {
    return _dio.patch(path, data: data);
  }

  Future<Response> delete(String path) async {
    return _dio.delete(path);
  }

  Future<Response> upload(String path, FormData formData) async {
    return _dio.post(path, data: formData,
      options: Options(
        headers: {'Content-Type': 'multipart/form-data'},
        extra: {'authenticated': true},
      ));
  }

  // ── Offline-safe POST (encola si no hay conexión) ─────────────────────────────
  Future<Map<String, dynamic>> safePost(String path, Map<String, dynamic> data) async {
    if (!_isOnline) {
      await LocalDatabase.instance.enqueue(path, 'POST', data);
      return {'queued': true, 'offline': true};
    }
    try {
      final r = await post(path, data);
      return r.data as Map<String, dynamic>;
    } catch (e) {
      await LocalDatabase.instance.enqueue(path, 'POST', data);
      return {'queued': true, 'offline': true, 'error': e.toString()};
    }
  }
}
