import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:local_auth/local_auth.dart';
import '../config/app_config.dart';
import '../models/models.dart';

class AuthService extends ChangeNotifier {
  static final AuthService _i = AuthService._();
  static AuthService get instance => _i;
  AuthService._();

  final _storage = const FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
    iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
  );
  final _localAuth = LocalAuthentication();

  UserModel? _user;
  bool _loading = false;
  bool _biometricEnabled = false;

  UserModel? get user => _user;
  bool get isLogged => _user != null;
  bool get loading => _loading;
  bool get biometricEnabled => _biometricEnabled;

  // ── Inicialización ────────────────────────────────────────────────────────────
  Future<bool> init() async {
    try {
      final token = await _storage.read(key: AppConfig.keyAccessToken);
      final userData = await _storage.read(key: AppConfig.keyUserData);
      final bio = await _storage.read(key: AppConfig.keyBiometricEnabled);
      _biometricEnabled = bio == 'true';
      if (token != null && userData != null) {
        _user = UserModel.fromJson(jsonDecode(userData));
        notifyListeners();
        return true;
      }
    } catch (_) {}
    return false;
  }

  // ── Login con usuario/contraseña ──────────────────────────────────────────────
  Future<Map<String, dynamic>> login(String username, String password) async {
    _loading = true; notifyListeners();
    try {
      final response = await ApiService.instance.post('/login', {
        'username': username,
        'password': password,
      }, authenticated: false);
      if (response.statusCode == 200) {
        await _saveSession(response.data);
        return {'ok': true};
      }
      return {'ok': false, 'error': response.data['detail'] ?? 'Error de login'};
    } catch (e) {
      return {'ok': false, 'error': 'Sin conexión al servidor'};
    } finally {
      _loading = false; notifyListeners();
    }
  }

  Future<void> _saveSession(Map<String, dynamic> data) async {
    final token = data['access_token'] as String?;
    final refresh = data['refresh_token'] as String?;
    final userData = data['user'] as Map<String, dynamic>?;
    if (token != null) await _storage.write(key: AppConfig.keyAccessToken, value: token);
    if (refresh != null) await _storage.write(key: AppConfig.keyRefreshToken, value: refresh);
    if (userData != null) {
      _user = UserModel.fromJson(userData);
      await _storage.write(key: AppConfig.keyUserData, value: jsonEncode(userData));
    }
    notifyListeners();
  }

  // ── Autenticación biométrica ──────────────────────────────────────────────────
  Future<bool> biometricAvailable() async {
    try {
      final canCheck = await _localAuth.canCheckBiometrics;
      final isSupported = await _localAuth.isDeviceSupported();
      return canCheck && isSupported;
    } catch (_) {
      return false;
    }
  }

  Future<List<BiometricType>> availableBiometrics() async {
    try {
      return await _localAuth.getAvailableBiometrics();
    } catch (_) {
      return [];
    }
  }

  Future<bool> authenticateWithBiometrics() async {
    try {
      return await _localAuth.authenticate(
        localizedReason: 'Accede a MRD TOOL CONTROL con tu huella o Face ID',
        options: const AuthenticationOptions(
          stickyAuth: true,
          biometricOnly: false,
        ),
      );
    } catch (_) {
      return false;
    }
  }

  Future<void> enableBiometric(bool enabled) async {
    _biometricEnabled = enabled;
    await _storage.write(key: AppConfig.keyBiometricEnabled, value: enabled.toString());
    notifyListeners();
  }

  // ── Token ─────────────────────────────────────────────────────────────────────
  Future<String?> getToken() => _storage.read(key: AppConfig.keyAccessToken);
  Future<String?> getRefreshToken() => _storage.read(key: AppConfig.keyRefreshToken);

  Future<bool> refreshToken() async {
    final refresh = await getRefreshToken();
    if (refresh == null) return false;
    try {
      final response = await ApiService.instance.post('/api/auth/refresh',
        {'refresh_token': refresh}, authenticated: false);
      if (response.statusCode == 200) {
        await _saveSession(response.data);
        return true;
      }
    } catch (_) {}
    return false;
  }

  // ── Logout ────────────────────────────────────────────────────────────────────
  Future<void> logout() async {
    try {
      await ApiService.instance.post('/logout', {});
    } catch (_) {}
    await _storage.delete(key: AppConfig.keyAccessToken);
    await _storage.delete(key: AppConfig.keyRefreshToken);
    await _storage.delete(key: AppConfig.keyUserData);
    _user = null;
    notifyListeners();
  }

  // ── Remote wipe ───────────────────────────────────────────────────────────────
  Future<void> remoteWipe() async {
    await _storage.deleteAll();
    _user = null;
    _biometricEnabled = false;
    notifyListeners();
  }
}

// Circular import prevention — ApiService reference
import 'api_service.dart';
