class AppConfig {
  // ── API ──────────────────────────────────────────────────────────────────────
  static const String baseUrl = 'https://app.iasmrd.com';
  static const String apiVersion = 'v1';
  static const int connectTimeout = 15; // segundos
  static const int receiveTimeout = 30;

  // ── App ──────────────────────────────────────────────────────────────────────
  static const String appName = 'MRD TOOL CONTROL';
  static const String appVersion = '2.1.0';
  static const String companyName = 'MRD Estructuras';

  // ── Offline ───────────────────────────────────────────────────────────────────
  static const int maxSyncRetries = 3;
  static const int syncIntervalMinutes = 5;
  static const int maxOfflineDays = 30;

  // ── Secure storage keys ───────────────────────────────────────────────────────
  static const String keyAccessToken = 'mrd_access_token';
  static const String keyRefreshToken = 'mrd_refresh_token';
  static const String keyUserData = 'mrd_user_data';
  static const String keyBiometricEnabled = 'mrd_biometric_enabled';
  static const String keyEncryptionKey = 'mrd_enc_key';
  static const String keyLastSync = 'mrd_last_sync';

  // ── Endpoints ─────────────────────────────────────────────────────────────────
  static String get apiBase => '$baseUrl/api/$apiVersion';

  static String ep(String path) => '$baseUrl$path';
  static String api(String path) => '$apiBase$path';
}
