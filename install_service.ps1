# =============================================================
# MRD TOOL CONTROL — Instalador del Servicio Windows
# Sprint 5.3 — Servicios de Producción
# v1.9.3-alpha
#
# Ejecutar como Administrador:
#   Right-click → "Ejecutar como administrador"
#   O: powershell -ExecutionPolicy Bypass -File install_service.ps1
#
# Requisitos: Windows 10/11 o Server 2016+, Python 3.9+
# =============================================================

param(
    [switch]$ForceReinstall,    # Reinstalar si ya existe
    [switch]$NoStart,           # No iniciar el servicio al terminar
    [string]$ConfigFile = ""    # Ruta a service.yaml alternativo
)

$ErrorActionPreference = "Stop"

# ─── Variables base ────────────────────────────────────────────────────────────
$ROOT        = $PSScriptRoot
$SERVICE     = "MRDToolControl"
$DISPLAY     = "MRD Tool Control"
$DESCRIPTION = "MRD Tool Control Production Service"
$SVC_SCRIPT  = Join-Path $ROOT "windows_service.py"
$SVC_YAML    = if ($ConfigFile) { $ConfigFile } else { Join-Path $ROOT "service.yaml" }
$LOG_DIR     = Join-Path $ROOT "logs"
$TEMP_DIR    = Join-Path $ROOT "temp"
$CACHE_DIR   = Join-Path $ROOT "cache"

# ─── Funciones de utilidad ────────────────────────────────────────────────────
function Write-Step  { param($msg) Write-Host "  [→] $msg" -ForegroundColor Cyan }
function Write-OK    { param($msg) Write-Host "  [✓] $msg" -ForegroundColor Green }
function Write-WARN  { param($msg) Write-Host "  [!] $msg" -ForegroundColor Yellow }
function Write-ERR   { param($msg) Write-Host "  [✗] $msg" -ForegroundColor Red }

function Require-Admin {
    $identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]$identity
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]"Administrator")) {
        Write-ERR "Este script debe ejecutarse como Administrador."
        Write-Host "  Haz clic derecho sobre install_service.ps1 → 'Ejecutar como administrador'"
        exit 1
    }
}

function Find-Python {
    # Buscar Python en venv primero, luego en PATH
    $candidates = @(
        (Join-Path $ROOT "venv\Scripts\python.exe"),
        (Join-Path $ROOT ".venv\Scripts\python.exe")
    )
    foreach ($p in $candidates) {
        if (Test-Path $p) { return $p }
    }
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) { return $py.Path }
    $py3 = Get-Command python3 -ErrorAction SilentlyContinue
    if ($py3) { return $py3.Path }
    return $null
}

function Ensure-Directory { param($path, $label)
    if (-not (Test-Path $path)) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
        Write-OK "Directorio creado: $label"
    }
}

# ─── Inicio ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ================================================================" -ForegroundColor White
Write-Host "   MRD TOOL CONTROL — Instalación del Servicio Windows" -ForegroundColor White
Write-Host "   Sprint 5.3 — Servicios de Producción — v1.9.3-alpha" -ForegroundColor Gray
Write-Host "  ================================================================" -ForegroundColor White
Write-Host ""

Require-Admin

# ─── 1. Verificar Python ──────────────────────────────────────────────────────
Write-Step "Buscando Python..."
$PYTHON = Find-Python
if (-not $PYTHON) {
    Write-ERR "Python no encontrado. Instala Python 3.9+ desde https://python.org"
    exit 1
}
$pyver = & $PYTHON --version 2>&1
Write-OK "Python: $pyver ($PYTHON)"

# ─── 2. Verificar entorno virtual ─────────────────────────────────────────────
Write-Step "Verificando entorno virtual..."
$venv = Join-Path $ROOT "venv\Scripts\activate.ps1"
if (-not (Test-Path $venv)) {
    Write-WARN "venv no encontrado. Creando entorno virtual..."
    & $PYTHON -m venv (Join-Path $ROOT "venv")
    Write-OK "Entorno virtual creado."
}

# ─── 3. Instalar dependencias de servicio ─────────────────────────────────────
Write-Step "Verificando pywin32..."
$pip = Join-Path $ROOT "venv\Scripts\pip.exe"
$checkWin32 = & $PYTHON -c "import win32serviceutil; print('ok')" 2>&1
if ($checkWin32 -ne "ok") {
    Write-Step "Instalando pywin32..."
    & $pip install pywin32 --quiet
    # Post-install hook de pywin32
    $postInstall = Join-Path $ROOT "venv\Scripts\pywin32_postinstall.py"
    if (Test-Path $postInstall) {
        & $PYTHON $postInstall -install
    }
    Write-OK "pywin32 instalado."
} else {
    Write-OK "pywin32: disponible."
}

Write-Step "Verificando pyyaml..."
$checkYaml = & $PYTHON -c "import yaml; print('ok')" 2>&1
if ($checkYaml -ne "ok") {
    & $pip install pyyaml --quiet
    Write-OK "pyyaml instalado."
} else {
    Write-OK "pyyaml: disponible."
}

Write-Step "Verificando psutil..."
$checkPsutil = & $PYTHON -c "import psutil; print('ok')" 2>&1
if ($checkPsutil -ne "ok") {
    & $pip install psutil --quiet
    Write-OK "psutil instalado."
} else {
    Write-OK "psutil: disponible."
}

# ─── 4. Verificar archivos necesarios ─────────────────────────────────────────
Write-Step "Verificando archivos del servicio..."
if (-not (Test-Path $SVC_SCRIPT)) {
    Write-ERR "windows_service.py no encontrado en $ROOT"
    exit 1
}
if (-not (Test-Path $SVC_YAML)) {
    Write-ERR "service.yaml no encontrado en $ROOT"
    exit 1
}
Write-OK "Archivos verificados."

# ─── 5. Verificar config/local.env ────────────────────────────────────────────
$localEnv = Join-Path $ROOT "config\local.env"
if (-not (Test-Path $localEnv)) {
    Write-WARN "config\local.env no encontrado."
    Write-Host "  Ejecuta generate_secrets.ps1 para generar las claves." -ForegroundColor Yellow
    $resp = Read-Host "  ¿Continuar de todas formas? (s/N)"
    if ($resp -notmatch "^[sS]$") { exit 0 }
}

# ─── 6. Crear estructura de directorios ───────────────────────────────────────
Write-Step "Creando estructura de directorios..."
Ensure-Directory $LOG_DIR   "logs"
Ensure-Directory $TEMP_DIR  "temp"
Ensure-Directory $CACHE_DIR "cache"
Ensure-Directory (Join-Path $ROOT "backups")  "backups"
Ensure-Directory (Join-Path $ROOT "uploads")  "uploads"
Ensure-Directory (Join-Path $ROOT "instance") "instance"
Write-OK "Estructura de directorios lista."

# ─── 7. Verificar si el servicio ya existe ────────────────────────────────────
Write-Step "Comprobando servicio existente..."
$existing = Get-Service -Name $SERVICE -ErrorAction SilentlyContinue

if ($existing) {
    if (-not $ForceReinstall) {
        Write-WARN "El servicio '$SERVICE' ya existe."
        $resp = Read-Host "  ¿Desinstalar e instalar de nuevo? (s/N)"
        if ($resp -notmatch "^[sS]$") {
            Write-Host "  Instalación cancelada." -ForegroundColor Yellow
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

# ─── 8. Registrar el servicio Windows ─────────────────────────────────────────
Write-Step "Registrando servicio Windows '$SERVICE'..."
try {
    & $PYTHON $SVC_SCRIPT install
    if ($LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }
} catch {
    Write-ERR "Error al registrar el servicio: $_"
    exit 1
}
Write-OK "Servicio registrado."

# ─── 9. Configurar propiedades del servicio ───────────────────────────────────
Write-Step "Configurando propiedades del servicio..."
# Inicio automático
sc.exe config $SERVICE start= auto | Out-Null
# Descripción
sc.exe description $SERVICE $DESCRIPTION | Out-Null
Write-OK "Inicio automático configurado."

# ─── 10. Configurar recuperación ante fallos ──────────────────────────────────
Write-Step "Configurando recuperación ante fallos..."
# Los 3 fallos → reiniciar el servicio con 30 s de espera; resetear contador cada 24 h
sc.exe failure $SERVICE reset= 86400 actions= restart/30000/restart/30000/restart/30000 | Out-Null
Write-OK "Recuperación configurada: 3 fallos → reiniciar (30 s espera, reset 24 h)."

# ─── 11. Configurar permisos del directorio de logs ──────────────────────────
Write-Step "Ajustando permisos del directorio de logs..."
try {
    $acl = Get-Acl $LOG_DIR
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        "NETWORK SERVICE", "Modify", "ContainerInherit,ObjectInherit", "None", "Allow"
    )
    $acl.SetAccessRule($rule)
    Set-Acl $LOG_DIR $acl
    Write-OK "Permisos de logs ajustados."
} catch {
    Write-WARN "No se pudieron ajustar permisos de logs: $_"
}

# ─── 12. Iniciar el servicio ──────────────────────────────────────────────────
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
        Write-Host "  Revisa logs\startup.log para más detalles." -ForegroundColor Yellow
    }
}

# ─── Resumen ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ================================================================" -ForegroundColor Green
Write-Host "   Instalación completada" -ForegroundColor Green
Write-Host "  ================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Servicio:      $SERVICE" -ForegroundColor White
Write-Host "  Inicio:        Automático con Windows" -ForegroundColor White
Write-Host "  Recuperación:  3 fallos → reiniciar automáticamente" -ForegroundColor White
Write-Host "  Logs:          $LOG_DIR" -ForegroundColor White
Write-Host ""
Write-Host "  Comandos de gestión:" -ForegroundColor Gray
Write-Host "    .\start_service.ps1     — Iniciar" -ForegroundColor Gray
Write-Host "    .\stop_service.ps1      — Detener" -ForegroundColor Gray
Write-Host "    .\restart_service.ps1   — Reiniciar" -ForegroundColor Gray
Write-Host "    .\status_service.ps1    — Ver estado" -ForegroundColor Gray
Write-Host "    .\uninstall_service.ps1 — Desinstalar" -ForegroundColor Gray
Write-Host ""
