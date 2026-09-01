@echo off
cd /d "%~dp0mrd_app"

echo.
echo  ============================================================
echo  MRD TOOL CONTROL - Compilar App Android
echo  ============================================================
echo.

echo [1/4] Comprobando Flutter...
flutter --version
if errorlevel 1 (
    echo  ERROR: Flutter no encontrado. Ejecuta INSTALAR_FLUTTER.ps1 primero.
    pause
    exit /b 1
)

echo [2/4] Instalando dependencias...
flutter pub get
if errorlevel 1 ( echo  ERROR en pub get. & pause & exit /b 1 )

echo [3/4] Compilando APK release...
flutter build apk --release --target-platform android-arm64
if errorlevel 1 ( echo  ERROR compilando APK. & pause & exit /b 1 )

echo [4/4] APK generado:
echo  build\app\outputs\flutter-apk\app-release.apk
echo.
echo  Copia el APK a tu telefono e instalalo.
echo  (Activa "Fuentes desconocidas" en Ajustes del telefono)
echo.
pause
