# setup_cloudflare_tunnel.ps1
# MRD TOOL CONTROL - Configurador Cloudflare Named Tunnel
# USO: Ejecutar como Administrador desde la carpeta del proyecto

#Requires -RunAsAdministrator

$ErrorActionPreference = "Continue"
$ProgressPreference    = "SilentlyContinue"

$InternalUrl = "http://127.0.0.1:8000"
$TunnelName  = "MRD-TOOL-CONTROL"
$AppUrl      = "https://app.iasmrd.com"
$CloudflaredUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
$InstallPath = "C:\Program Files\cloudflared"
$CfExe       = Join-Path $InstallPath "cloudflared.exe"

function Sep  { Write-Host ("  " + ("-" * 60)) -ForegroundColor DarkGray }
function OK   { param($t) Write-Host "  [OK]  $t" -ForegroundColor Green }
function FAIL { param($t) Write-Host "  [ERR] $t" -ForegroundColor Red }
function INFO { param($t) Write-Host "  [-->] $t" -ForegroundColor Yellow }
function STEP { param($n,$t) Write-Host ""; Write-Host "  [$n] $t" -ForegroundColor Cyan; Sep }
function BOX  { param($t) Write-Host "  >>> $t" -ForegroundColor Magenta }

Clear-Host
Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "  MRD TOOL CONTROL - Configurador Cloudflare Named Tunnel" -ForegroundColor Cyan
Write-Host "  Tunel: $TunnelName" -ForegroundColor Cyan
Write-Host "  URL:   $AppUrl" -ForegroundColor Cyan
Write-Host "  ============================================================" -ForegroundColor Cyan

# ---------------------------------------------------------------
# PASO 1: Comprobar que la app responde en localhost:8000
# ---------------------------------------------------------------
STEP "1/5" "Comprobando MRD Tool Control en localhost:8000..."

$appOk = $false
try {
    $r = Invoke-WebRequest -Uri "$InternalUrl/health" -TimeoutSec 5 -UseBasicParsing
    if ($r.StatusCode -eq 200) {
        OK "MRD Tool Control responde en $InternalUrl/health"
        $appOk = $true
    } else {
        FAIL "Estado inesperado: $($r.StatusCode)"
    }
} catch {
    FAIL "No responde en $InternalUrl"
}

if (-not $appOk) {
    Write-Host ""
    INFO "La aplicacion no esta en ejecucion. Iniciala antes de continuar:"
    Write-Host "      Haz doble clic en INICIAR_MRD.bat" -ForegroundColor White
    Write-Host "      o bien ejecuta: python main.py" -ForegroundColor White
    Write-Host ""
    Write-Host "  Cuando la aplicacion este en marcha, vuelve a ejecutar este script." -ForegroundColor Yellow
    pause
    exit 1
}

$svcMrd = Get-Service -Name "MRDToolControl" -ErrorAction SilentlyContinue
if ($svcMrd -and $svcMrd.Status -eq "Running") {
    OK "Servicio MRDToolControl: EN EJECUCION"
} elseif ($svcMrd) {
    INFO "Servicio MRDToolControl instalado pero detenido"
} else {
    INFO "Servicio MRDToolControl no instalado (la app corre manualmente, esta bien)"
}

# ---------------------------------------------------------------
# PASO 2: Comprobar cloudflared.exe
# ---------------------------------------------------------------
STEP "2/5" "Comprobando cloudflared.exe..."

$cfCmd = Get-Command "cloudflared" -ErrorAction SilentlyContinue
if (-not $cfCmd) { $cfCmd = Get-Command $CfExe -ErrorAction SilentlyContinue }

if ($cfCmd) {
    $cfVer = & cloudflared version 2>&1 | Select-Object -First 1
    OK "cloudflared instalado: $cfVer"
} else {
    INFO "cloudflared no encontrado. Descargando..."
    try {
        if (-not (Test-Path $InstallPath)) {
            New-Item -ItemType Directory -Path $InstallPath -Force | Out-Null
        }
        Invoke-WebRequest -Uri $CloudflaredUrl -OutFile $CfExe -UseBasicParsing
        $sysPath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
        if ($sysPath -notlike "*$InstallPath*") {
            [System.Environment]::SetEnvironmentVariable("Path", "$sysPath;$InstallPath", "Machine")
            $env:Path = "$env:Path;$InstallPath"
        }
        $cfVer = & $CfExe version 2>&1 | Select-Object -First 1
        OK "cloudflared instalado: $cfVer"
    } catch {
        FAIL "Error descargando cloudflared: $_"
        INFO "Descargalo manualmente desde:"
        Write-Host "  https://github.com/cloudflare/cloudflared/releases/latest" -ForegroundColor White
        pause
        exit 1
    }
}

# ---------------------------------------------------------------
# PASO 3: Verificar PATH
# ---------------------------------------------------------------
STEP "3/5" "Verificando PATH..."

try {
    $v = & cloudflared version 2>&1 | Select-Object -First 1
    OK "cloudflared accesible en PATH: $v"
} catch {
    try {
        $v = & $CfExe version 2>&1 | Select-Object -First 1
        OK "cloudflared accesible en ruta directa: $v"
        $env:Path = "$env:Path;$InstallPath"
    } catch {
        FAIL "cloudflared no accesible. Cierra y abre PowerShell como Admin e intenta de nuevo."
        pause
        exit 1
    }
}

# ---------------------------------------------------------------
# PASO 4: INSTRUCCIONES PARA EL PANEL DE CLOUDFLARE
# ---------------------------------------------------------------
STEP "4/5" "ACCION REQUERIDA EN EL PANEL DE CLOUDFLARE"

Write-Host ""
Write-Host "  +----------------------------------------------------------+" -ForegroundColor Magenta
Write-Host "  |  PARA AQUI - Sigue estos pasos en tu navegador          |" -ForegroundColor Magenta
Write-Host "  +----------------------------------------------------------+" -ForegroundColor Magenta
Write-Host ""
Write-Host "  Abre en tu navegador:" -ForegroundColor White
Write-Host "  https://one.dash.cloudflare.com/" -ForegroundColor Cyan
Write-Host ""
BOX "1. Menu izquierdo: Networks > Tunnels"
BOX "2. Click en: + Create a tunnel"
BOX "3. Tipo: Cloudflared  (no WARP Connector)"
BOX "4. Click: Next"
BOX "5. Nombre del tunel: MRD-TOOL-CONTROL"
BOX "6. Click: Save tunnel"
BOX "7. En la pagina siguiente, seccion Install connector:"
BOX "   - Sistema operativo: Windows"
BOX "   - Copia el comando que aparece. Empieza asi:"
Write-Host ""
Write-Host "      cloudflared.exe service install eyJh..." -ForegroundColor Yellow
Write-Host ""
BOX "   El token es muy largo y empieza por eyJ"
BOX "8. NO hagas click en Next todavia"
BOX "9. Vuelve a esta ventana y ejecuta el comando copiado"
Write-Host ""
Write-Host "  ------------------------------------------------------------" -ForegroundColor DarkGray
Write-Host "  Comando a ejecutar en ESTA ventana:" -ForegroundColor White
Write-Host ""
Write-Host "      cloudflared.exe service install  [PEGA-AQUI-EL-TOKEN]" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Sustituye [PEGA-AQUI-EL-TOKEN] por el token real de Cloudflare." -ForegroundColor DarkGray
Write-Host "  ------------------------------------------------------------" -ForegroundColor DarkGray

# ---------------------------------------------------------------
# PASO 5: Verificar si el servicio cloudflared esta instalado
# ---------------------------------------------------------------
STEP "5/5" "Verificando servicio cloudflared..."

$cfSvc = Get-Service -Name "cloudflared" -ErrorAction SilentlyContinue
if ($cfSvc -and $cfSvc.Status -eq "Running") {
    OK "Servicio cloudflared: EN EJECUCION"
    Write-Host ""
    Write-Host "  El tunel esta activo. Ahora en el panel de Cloudflare:" -ForegroundColor Green
    BOX "1. Haz click en Next"
    BOX "2. En Public hostname rellena:"
    Write-Host "      Subdomain : app" -ForegroundColor White
    Write-Host "      Domain    : iasmrd.com" -ForegroundColor White
    Write-Host "      Type      : HTTP" -ForegroundColor White
    Write-Host "      URL       : 127.0.0.1:8000" -ForegroundColor White
    BOX "3. Click: Save tunnel"
    Write-Host ""
    Write-Host "  En 2-3 minutos https://app.iasmrd.com estara activo." -ForegroundColor Green
    Write-Host ""
    Write-Host "  Para verificar ejecuta:" -ForegroundColor Cyan
    Write-Host "      .\scripts\cloudflare_test.ps1" -ForegroundColor White
} elseif ($cfSvc) {
    INFO "Servicio cloudflared instalado pero no iniciado. Estado: $($cfSvc.Status)"
    INFO "Inicia con: net start cloudflared"
} else {
    INFO "El servicio cloudflared no esta instalado todavia."
    INFO "Sigue las instrucciones del PASO 4 para obtener el token e instalarlo."
}

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host "  Script completado." -ForegroundColor Cyan
Write-Host "  ============================================================" -ForegroundColor Cyan
Write-Host ""
pause
