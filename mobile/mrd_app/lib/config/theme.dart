import 'package:flutter/material.dart';

class MrdTheme {
  // ── Colores MRD ───────────────────────────────────────────────────────────────
  static const Color primary     = Color(0xFF1E3A5F);  // Azul marino
  static const Color secondary   = Color(0xFFE07B00);  // Naranja
  static const Color accent      = Color(0xFF2D6DA8);  // Azul claro
  static const Color danger      = Color(0xFFDC3545);
  static const Color success     = Color(0xFF198754);
  static const Color warning     = Color(0xFFFFC107);

  // Dark
  static const Color bgDark      = Color(0xFF0F1923);
  static const Color surfaceDark = Color(0xFF1A2840);
  static const Color cardDark    = Color(0xFF1E3050);

  // Light
  static const Color bgLight     = Color(0xFFF5F7FA);
  static const Color surfaceLight= Color(0xFFFFFFFF);
  static const Color cardLight   = Color(0xFFFFFFFF);

  static ThemeData dark() => ThemeData(
    useMaterial3: true,
    brightness: Brightness.dark,
    scaffoldBackgroundColor: bgDark,
    colorScheme: const ColorScheme.dark(
      primary: primary,
      secondary: secondary,
      surface: surfaceDark,
      error: danger,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: surfaceDark,
      foregroundColor: Colors.white,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        fontFamily: 'Inter', fontWeight: FontWeight.w600,
        fontSize: 18, color: Colors.white,
      ),
    ),
    cardTheme: CardThemeData(
      color: cardDark,
      elevation: 0,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      margin: const EdgeInsets.symmetric(horizontal: 0, vertical: 4),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: cardDark,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(10), borderSide: BorderSide.none),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: secondary, width: 2),
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: secondary,
        foregroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        textStyle: const TextStyle(fontFamily: 'Inter', fontWeight: FontWeight.w600, fontSize: 15),
      ),
    ),
    textTheme: const TextTheme(
      bodyLarge: TextStyle(fontFamily: 'Inter', color: Colors.white),
      bodyMedium: TextStyle(fontFamily: 'Inter', color: Color(0xFFBDC3CD)),
      titleLarge: TextStyle(fontFamily: 'Inter', fontWeight: FontWeight.w700, color: Colors.white),
      titleMedium: TextStyle(fontFamily: 'Inter', fontWeight: FontWeight.w600, color: Colors.white),
      labelLarge: TextStyle(fontFamily: 'Inter', fontWeight: FontWeight.w600),
    ),
    bottomNavigationBarTheme: const BottomNavigationBarThemeData(
      backgroundColor: surfaceDark,
      selectedItemColor: secondary,
      unselectedItemColor: Color(0xFF6B7280),
      type: BottomNavigationBarType.fixed,
      elevation: 8,
    ),
    chipTheme: ChipThemeData(
      backgroundColor: cardDark,
      selectedColor: secondary.withOpacity(0.2),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
    ),
    dividerColor: const Color(0xFF2A3F5C),
    fontFamily: 'Inter',
  );

  static ThemeData light() => ThemeData(
    useMaterial3: true,
    brightness: Brightness.light,
    scaffoldBackgroundColor: bgLight,
    colorScheme: const ColorScheme.light(
      primary: primary,
      secondary: secondary,
      surface: surfaceLight,
      error: danger,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: primary,
      foregroundColor: Colors.white,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        fontFamily: 'Inter', fontWeight: FontWeight.w600,
        fontSize: 18, color: Colors.white,
      ),
    ),
    cardTheme: CardThemeData(
      color: cardLight,
      elevation: 1,
      shadowColor: Colors.black12,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      margin: const EdgeInsets.symmetric(horizontal: 0, vertical: 4),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: Color(0xFFDDE3EC)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: secondary, width: 2),
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: secondary,
        foregroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        textStyle: const TextStyle(fontFamily: 'Inter', fontWeight: FontWeight.w600, fontSize: 15),
      ),
    ),
    fontFamily: 'Inter',
  );
}
