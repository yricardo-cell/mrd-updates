# =============================================================
# MRD FAILOVER WATCHDOG — Instalador del Servicio Windows (Fase 1)
# Continuidad 24x7 — app.iasmrd.com
#
# Ejecutar como Administrador:
#   powershell -ExecutionPolicy Bypass -File install_failover_service.ps1
#
# Requiere: config/cloudflare_dns.token ya creado con el API Token de
# Cloudflare (Zone:DNS:Edit, solo zona iasmrd.com). El script no continua
# sin ese archivo, para no instalar un servicio que fallaria de inmediato.
# =============================================================

param(
    [switch]$ForceReinstall,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"

$ROOT        = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$SERVICE     = "MRDFailoverWatchdog"
$SVC_SCRIPT  = Join-Path $PSScriptRoot "failover_service.py"
$TOKEN_FILE  = Join-Path $ROOT "config\cloudflare_dns.token"

function Write-Step { param($msg) Write-Host "  [->] $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-WARN { param($msg) Write-Host "  [!]  $msg" -ForegroundColor Yellow }
function Write-ERR  { param($msg) Write-Host "  [X]  $msg" -ForegroundColor Red }

function Require-Admin {
    $identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]$identity
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]"Administrator")) {
        Write-ERR "Este script debe ejecutarse como Administrador."
        exit 1
    }
}

function Find-Python {
    $candidates = @(
        (Join-Path $ROOT "venv\Scripts\python.exe"),
        (Join-Path $ROOT ".venv\Scripts\python.exe")
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) { return $p }
    }
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) { return $py.Path }
    return $null
}

Write-Host ""
Write-Host "  ================================================================" -ForegroundColor White
Write-Host "   MRD FAILOVER WATCHDOG — Instalacion del Servicio Windows" -ForegroundColor White
Write-Host "  ================================================================" -ForegroundColor White
Write-Host ""

Require-Admin

# ─── 1. Verificar Python y pywin32 ────────────────────────────────────────────
Write-Step "Buscando Python..."
$PYTHON = Find-Python
if (-not $PYTHON) {
    Write-ERR "Python no encontrado (venv o PATH)."
    exit 1
}
Write-OK "Python: $PYTHON"

Write-Step "Verificando pywin32..."
$checkWin32 = & $PYTHON -c "import win32serviceutil; print('ok')" 2>&1
if ($checkWin32 -ne "ok") {
    Write-ERR "pywin32 no instalado en este interprete. Instala con: $PYTHON -m pip install pywin32"
    exit 1
}
Write-OK "pywin32: disponible."

# ─── 2. Verificar el token de Cloudflare ANTES de instalar ───────────────────
Write-Step "Verificando token de Cloudflare..."
if (-not (Test-Path $TOKEN_FILE)) {
    Write-ERR "No existe $TOKEN_FILE."
    Write-Host "  Crea un API Token de Cloudflare (Zone:DNS:Edit, solo zona iasmrd.com)" -ForegroundColor Yellow
    Write-Host "  y guardalo en ese archivo (solo el token, una linea)." -ForegroundColor Yellow
    exit 1
}
Write-OK "Token encontrado."

Write-Step "Validando token contra la API de Cloudflare (solo lectura)..."
& $PYTHON (Join-Path $PSScriptRoot "failover.py") --verify-token
if ($LASTEXITCODE -ne 0) {
    Write-ERR "El token no pudo validarse. Revisa el mensaje anterior antes de continuar."
    exit 1
}
Write-OK "Token valido: zone_id y record_id resueltos."

# ─── 3. Verificar si el servicio ya existe ────────────────────────────────────
Write-Step "Comprobando servicio existente..."
$existing = Get-Service -Name $SERVICE -ErrorAction SilentlyContinue

if ($existing) {
    if (-not $ForceReinstall) {
        Write-WARN "El servicio '$SERVICE' ya existe."
        $resp = Read-Host "  ¿Desinstalar e instalar de nuevo? (s/N)"
        if ($resp -notmatch "^[sS]$") {
            Write-Host "  Instalacion cancelada." -ForegroundColor Yellow
            exit 0
        }
    }
    Write-Step "Deteniendo servicio existente..."
    try { Stop-Service -Name $SERVICE -Force -ErrorAction SilentlyContinue } catch {}
    Start-Sleep 3
    Write-Step "Desinstalando servicio existente..."
    & $PYTHON $SVC_SCRIPT remove 2>&1 | Out-Null
    Start-Sleep 2
}

# ─── 4. Registrar el servicio Windows ─────────────────────────────────────────
Write-Step "Registrando servicio Windows '$SERVICE'..."
try {
    & $PYTHON $SVC_SCRIPT install
    if ($LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }
} catch {
    Write-ERR "Error al registrar el servicio: $_"
    exit 1
}
Write-OK "Servicio registrado."

# ─── 5. Inicio automatico y recuperacion ante fallos ──────────────────────────
# sc.exe es un binario nativo: un exit code distinto de 0 NO dispara
# $ErrorActionPreference="Stop" (eso solo aplica a cmdlets de PowerShell), asi
# que cada llamada se valida a mano para no dejar el servicio registrado pero
# a medio configurar sin que nadie se entere.
function Invoke-ScOrFail {
    param([string]$StepLabel, [string[]]$ScArgs)
    & sc.exe @ScArgs | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-ERR "$StepLabel fallo (sc.exe exit code $LASTEXITCODE)."
        Write-Host "  El servicio '$SERVICE' quedo registrado pero incompleto. Revisa con: sc.exe qc $SERVICE" -ForegroundColor Yellow
        exit 1
    }
}

Write-Step "Configurando inicio automatico y recuperacion..."
Invoke-ScOrFail "Inicio automatico" @("config", $SERVICE, "start=", "auto")
Invoke-ScOrFail "Descripcion del servicio" @("description", $SERVICE, "Vigila app.iasmrd.com y conmuta el tunel Cloudflare activo si el tunel principal pierde conexion.")
# 3 fallos -> reiniciar con 30s de espera; resetear contador cada 24h (mismo
# patron que install_service.ps1 usa para el servicio principal MRDToolControl).
Invoke-ScOrFail "Recuperacion ante fallos" @("failure", $SERVICE, "reset=", "86400", "actions=", "restart/30000/restart/30000/restart/30000")
Write-OK "Inicio automatico y recuperacion configurados."

# ─── 6. Iniciar el servicio ───────────────────────────────────────────────────
if (-not $NoStart) {
    Write-Step "Iniciando servicio '$SERVICE'..."
    try {
        Start-Service -Name $SERVICE
        Start-Sleep 3
        $svc = Get-Service -Name $SERVICE
        if ($svc.Status -eq "Running") {
            Write-OK "Servicio iniciado — estado: RUNNING"
        } else {
            Write-WARN "Servicio en estado: $($svc.Status)"
        }
    } catch {
        Write-ERR "Error al iniciar el servicio: $_"
    }
}

Write-Host ""
Write-Host "  ================================================================" -ForegroundColor Green
Write-Host "   Instalacion completada" -ForegroundColor Green
Write-Host "  ================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Servicio:      $SERVICE" -ForegroundColor White
Write-Host "  Estado log:    %ProgramData%\MRDToolControl\failover\logs\failover.log" -ForegroundColor White
Write-Host "  Historial:     %ProgramData%\MRDToolControl\failover\history.jsonl" -ForegroundColor White
Write-Host ""
$failoverScript = Join-Path $PSScriptRoot "failover.py"
Write-Host "  Prueba en seco (sin instalar servicio):" -ForegroundColor Gray
Write-Host "    & '$PYTHON' '$failoverScript' --dry-run --once" -ForegroundColor Gray
Write-Host ""
