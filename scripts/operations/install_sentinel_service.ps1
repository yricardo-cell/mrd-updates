# =============================================================
# MRD SENTINEL — Instalador del Servicio Windows (Fase 2)
# Centro de recuperacion independiente de MRD Tool Control
#
# Ejecutar como Administrador:
#   powershell -ExecutionPolicy Bypass -File install_sentinel_service.ps1
# =============================================================

param(
    [switch]$ForceReinstall,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"

$ROOT       = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$SERVICE    = "MRDSentinel"
$SVC_SCRIPT = Join-Path $ROOT "sentinel\service.py"

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
Write-Host "   MRD SENTINEL — Instalacion del Servicio Windows" -ForegroundColor White
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

# ─── 2. Verificar que la configuracion de Sentinel carga correctamente ───────
Write-Step "Verificando sentinel/config/apps.yaml..."
Push-Location $ROOT
$checkCfg = & $PYTHON -c "from sentinel.config import load_config; c = load_config(); print(f'{len(c.apps)} app(s), puerto {c.port}')" 2>&1
Pop-Location
if ($LASTEXITCODE -ne 0) {
    Write-ERR "No se pudo cargar la configuracion de Sentinel:"
    Write-Host "  $checkCfg" -ForegroundColor Yellow
    exit 1
}
Write-OK "Configuracion valida: $checkCfg"

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

# ─── 5. Fix PYTHONPATH para pywin32 dentro de un venv ─────────────────────────
# pythonservice.exe no procesa los .pth de site-packages (pywin32.pth) ni
# resuelve el resto de site-packages del venv (fastapi, pyyaml, etc.) el
# mismo modo que python.exe -- sin esto el servicio falla al arrancar con
# "No module named 'servicemanager'" (pywin32) o "No module named 'yaml'"
# (cualquier dependencia normal del proyecto).
Write-Step "Configurando PYTHONPATH del servicio (fix pywin32 + site-packages en venv)..."
$venvSitePackages = Join-Path $ROOT "venv\Lib\site-packages"
$pywin32Paths = @(
    $venvSitePackages,
    (Join-Path $venvSitePackages "win32"),
    (Join-Path $venvSitePackages "win32\lib"),
    (Join-Path $venvSitePackages "Pythonwin")
) -join ";"
$envValue = "PYTHONPATH=$pywin32Paths"
try {
    Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\$SERVICE" `
        -Name "Environment" -Value @($envValue) -Type MultiString
    Write-OK "PYTHONPATH configurado para el servicio."
} catch {
    Write-ERR "No se pudo configurar PYTHONPATH del servicio: $_"
    Write-Host "  El servicio quedo registrado pero probablemente fallara al arrancar." -ForegroundColor Yellow
    exit 1
}

# ─── 6. Inicio automatico y recuperacion ante fallos ──────────────────────────
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
Invoke-ScOrFail "Descripcion del servicio" @("description", $SERVICE, "Centro de recuperacion independiente de MRD Tool Control: panel de estado/historial y proxy de emergencia.")
Invoke-ScOrFail "Recuperacion ante fallos" @("failure", $SERVICE, "reset=", "86400", "actions=", "restart/30000/restart/30000/restart/30000")
Write-OK "Inicio automatico y recuperacion configurados."

# ─── 7. Iniciar el servicio ───────────────────────────────────────────────────
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
Write-Host "  Panel local:   http://127.0.0.1:9100" -ForegroundColor White
Write-Host "  Logs:          $ROOT\sentinel\logs\" -ForegroundColor White
Write-Host ""