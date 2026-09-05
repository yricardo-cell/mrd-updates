# MRD Sentinel 24x7 — instalacion recomendada mediante Tarea Programada.
# Evita la dependencia de pythonservice.exe/pywin32 y mantiene el proceso
# supervisado al arrancar Windows.

param(
    [string]$RepositoryRoot = "",
    [string]$PythonExe = "",
    [string]$TaskName = "MRD Sentinel 24x7",
    [switch]$Apply,
    [switch]$NoStart,
    [switch]$CurrentUser
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
} else {
    $RepositoryRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
}

if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $parentRoot = Split-Path -Parent $RepositoryRoot
    $pythonCandidates = @(
        (Join-Path $RepositoryRoot "venv\Scripts\python.exe"),
        (Join-Path $RepositoryRoot ".venv\Scripts\python.exe"),
        (Join-Path $parentRoot "mrd-tool-control-2.5.0\venv\Scripts\python.exe"),
        (Join-Path $parentRoot "mrd-tool-control-AI\venv\Scripts\python.exe")
    )
    $PythonExe = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
} elseif (Test-Path -LiteralPath $PythonExe) {
    $PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
} else {
    throw "No existe el Python indicado: $PythonExe"
}
if (-not $PythonExe) {
    throw "No se encontro un entorno Python compatible para Sentinel."
}

$configPath = Join-Path $RepositoryRoot "sentinel\config\apps.yaml"
if (-not (Test-Path -LiteralPath $configPath)) {
    throw "No se encontro la configuracion de Sentinel: $configPath"
}

Push-Location $RepositoryRoot
try {
    & $PythonExe -c "from sentinel.config import load_config; from sentinel.app import create_app; c=load_config(); print(f'{len(c.apps)} app(s), puerto {c.port}')" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "La aplicacion Sentinel no se puede cargar." }
} finally {
    Pop-Location
}

Write-Host "Plan de instalacion de MRD Sentinel 24x7:" -ForegroundColor Cyan
Write-Host "- Crear o actualizar la tarea '$TaskName'"
if ($CurrentUser) {
    Write-Host "- Ejecutarla con la cuenta actual al iniciar sesion (no requiere administrador)"
} else {
    Write-Host "- Ejecutarla como SYSTEM al arrancar Windows"
}
Write-Host "- Mantenerla activa con bateria y reiniciarla si se cierra"
Write-Host "- Iniciar el panel local en http://127.0.0.1:9100"
Write-Host "- No modificar MRD Tool Control, Cloudflare ni sus datos"
Write-Host "- Python verificado: $PythonExe"

if (-not $Apply) {
    if ($CurrentUser) {
        Write-Host "Modo vista previa. Use -Apply para instalar con la cuenta actual." -ForegroundColor Yellow
    } else {
        Write-Host "Modo vista previa. Use -Apply como Administrador para aplicar." -ForegroundColor Yellow
    }
    exit 0
}
if (-not $CurrentUser -and -not (Test-IsAdministrator)) {
    throw "Ejecute PowerShell como Administrador."
}

$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "-m sentinel.service run" `
    -WorkingDirectory $RepositoryRoot
if ($CurrentUser) {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $startupTrigger = New-ScheduledTaskTrigger -AtLogOn -User $currentIdentity
    $principal = New-ScheduledTaskPrincipal `
        -UserId $currentIdentity `
        -LogonType Interactive `
        -RunLevel Limited
} else {
    $startupTrigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal `
        -UserId "SYSTEM" `
        -LogonType ServiceAccount `
        -RunLevel Highest
}
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 50 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $startupTrigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Panel y supervisor independiente MRD Sentinel 24x7." `
    -Force | Out-Null

if (-not $NoStart) {
    Start-ScheduledTask -TaskName $TaskName
}

Write-Host "MRD Sentinel 24x7 instalado correctamente." -ForegroundColor Green
Write-Host "Panel local: http://127.0.0.1:9100"
Write-Host "Primera apertura: cree su cuenta desde este mismo equipo."
