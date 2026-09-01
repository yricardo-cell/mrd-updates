# INSTALAR_FLUTTER.ps1
# Instala Flutter SDK en Windows para compilar MRD TOOL CONTROL App

$FlutterVersion = "3.22.3"
$FlutterUrl = "https://storage.googleapis.com/flutter_infra_release/releases/stable/windows/flutter_windows_${FlutterVersion}-stable.zip"
$InstallPath = "C:\flutter"
$ZipPath = "$env:TEMP\flutter_windows.zip"

function Write-Step { param($n,$t) Write-Host ""; Write-Host "  [$n] $t" -ForegroundColor Cyan }
function Write-OK   { param($t) Write-Host "  [OK] $t" -ForegroundColor Green }
function Write-Info { param($t) Write-Host "  [-->] $t" -ForegroundColor Yellow }

Clear-Host
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "  MRD TOOL CONTROL - Instalador Flutter SDK" -ForegroundColor Cyan
Write-Host "  Version: $FlutterVersion" -ForegroundColor Cyan
Write-Host "  ============================================================" -ForegroundColor Cyan

# Paso 1: Comprobar si Flutter ya esta instalado
Write-Step "1/5" "Comprobando instalacion existente..."
$existing = Get-Command flutter -ErrorAction SilentlyContinue
if ($existing) {
    $ver = & flutter --version 2>&1 | Select-Object -First 1
    Write-OK "Flutter ya instalado: $ver"
    Write-Host "  Si quieres reinstalar, elimina C:\flutter y vuelve a ejecutar." -ForegroundColor Yellow
    pause
    exit 0
}

# Paso 2: Descargar Flutter
Write-Step "2/5" "Descargando Flutter $FlutterVersion (puede tardar varios minutos)..."
Write-Info "URL: $FlutterUrl"
try {
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -Uri $FlutterUrl -OutFile $ZipPath -UseBasicParsing
    Write-OK "Descarga completada: $ZipPath"
} catch {
    Write-Host "  [ERR] Error descargando Flutter: $_" -ForegroundColor Red
    Write-Info "Descarga manual: https://flutter.dev/docs/get-started/install/windows"
    pause; exit 1
}

# Paso 3: Extraer
Write-Step "3/5" "Extrayendo Flutter en $InstallPath..."
if (Test-Path $InstallPath) { Remove-Item $InstallPath -Recurse -Force }
try {
    Expand-Archive -Path $ZipPath -DestinationPath "C:\" -Force
    Write-OK "Extraido en $InstallPath"
} catch {
    Write-Host "  [ERR] Error extrayendo: $_" -ForegroundColor Red
    pause; exit 1
}

# Paso 4: Agregar al PATH
Write-Step "4/5" "Configurando PATH del sistema..."
$flutterBin = "$InstallPath\bin"
$currentPath = [Environment]::GetEnvironmentVariable("Path", "Machine")
if ($currentPath -notlike "*$flutterBin*") {
    [Environment]::SetEnvironmentVariable("Path", "$currentPath;$flutterBin", "Machine")
    $env:Path = "$env:Path;$flutterBin"
    Write-OK "PATH actualizado"
} else {
    Write-OK "Ya estaba en PATH"
}

# Paso 5: Verificar y flutter doctor
Write-Step "5/5" "Verificando instalacion..."
try {
    $ver = & "$InstallPath\bin\flutter.bat" --version 2>&1 | Select-Object -First 1
    Write-OK "Flutter instalado: $ver"
    Write-Host ""
    Write-Host "  Ejecutando flutter doctor..." -ForegroundColor Cyan
    & "$InstallPath\bin\flutter.bat" doctor
} catch {
    Write-Host "  [ERR] Error verificando Flutter: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Green
Write-Host "  Flutter instalado. Siguientes pasos:" -ForegroundColor Green
Write-Host "  1. Instala Android Studio: https://developer.android.com/studio" -ForegroundColor White
Write-Host "  2. En Android Studio instala Flutter y Dart plugins" -ForegroundColor White
Write-Host "  3. Acepta licencias: flutter doctor --android-licenses" -ForegroundColor White
Write-Host "  4. Ejecuta COMPILAR_APP.bat para generar el APK" -ForegroundColor White
Write-Host "  ============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  IMPORTANTE: Cierra y abre una nueva ventana de PowerShell/CMD" -ForegroundColor Yellow
Write-Host "  para que los cambios de PATH surtan efecto." -ForegroundColor Yellow
Write-Host ""
pause
