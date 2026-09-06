param(
    [string]$RepositoryRoot = "C:\mrd tool\mrd-tool-control-2.5.0",
    [string]$AppServiceName = "MRDToolControl",
    [string]$AppTaskName = "MRD Tool Control",
    [string]$TunnelServiceName = "Cloudflared",
    [string]$HealthUrl = "http://127.0.0.1:8000/health",
    [string]$PublicHealthUrl = "https://app.iasmrd.com/health",
    [string]$TaskName = "MRD Tool Control - Watchdog 24x7",
    [bool]$EnableDR4 = $true,
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$watchdog = Join-Path $RepositoryRoot "scripts\operations\watchdog_mrd.ps1"
$repairScript = Join-Path $RepositoryRoot "scripts\operations\repair_center.py"
$repairPython = Join-Path $RepositoryRoot "venv\Scripts\python.exe"
$repairStateRoot = Join-Path $env:ProgramData "MRDToolControl\repair-center"
$externalWatchdog = Join-Path $repairStateRoot "watchdog_mrd.ps1"
$externalRepairScript = Join-Path $repairStateRoot "repair_center.py"
if (-not (Test-Path -LiteralPath $watchdog)) {
    throw "No se encontro el watchdog en $watchdog"
}
if (-not (Test-Path -LiteralPath $repairScript -PathType Leaf)) {
    throw "No se encontro el centro de reparacion en $repairScript"
}
if (-not (Test-Path -LiteralPath $repairPython -PathType Leaf)) {
    throw "No se encontro Python de MRD en $repairPython"
}

$appService = Get-Service -Name $AppServiceName -ErrorAction SilentlyContinue
$appTask = Get-ScheduledTask -TaskName $AppTaskName -ErrorAction SilentlyContinue
if (-not $appService -and -not $appTask) {
    throw "No existe ni el servicio $AppServiceName ni la tarea $AppTaskName"
}
if (-not (Get-Service -Name $TunnelServiceName -ErrorAction SilentlyContinue)) {
    throw "No existe el servicio $TunnelServiceName"
}

Write-Host "Plan de continuidad 24x7:" -ForegroundColor Cyan
Write-Host "- Supervisar MRD mediante $(if ($appService) { 'servicio' } else { 'tarea programada' })"
Write-Host "- Configurar recuperacion de Windows para $TunnelServiceName"
Write-Host "- Crear tarea $TaskName cada minuto y al arrancar"
Write-Host "- Ejecutar el vigilante desde una copia externa protegida"
Write-Host "- Sellar la version actual como linea base valida para reparacion por componentes"
Write-Host "- DR4 SQLite: $EnableDR4 (solo tras 3 corrupciones confirmadas y con copia valida)"
Write-Host "- No reiniciar ningun servicio durante la instalacion"

if (-not $Apply) {
    Write-Host "Modo vista previa. Use -Apply como Administrador para aplicar." -ForegroundColor Yellow
    exit 0
}

if (-not (Test-IsAdministrator)) {
    throw "Ejecute PowerShell como Administrador."
}

$servicesToConfigure = @($TunnelServiceName)
if ($appService) { $servicesToConfigure += $AppServiceName }
foreach ($serviceName in $servicesToConfigure) {
    & sc.exe config $serviceName start= auto | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudo configurar inicio automatico para $serviceName" }
    & sc.exe failure $serviceName reset= 86400 actions= restart/5000/restart/15000/restart/60000 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudo configurar recovery para $serviceName" }
    & sc.exe failureflag $serviceName 1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudo activar failureflag para $serviceName" }
}

# Las dos piezas de recuperación se ejecutan fuera de la carpeta de la app.
# Así pueden restaurar su copia interna aunque un archivo del despliegue quede
# incompleto. El servicio MRDFailoverWatchdog existente sigue siendo la otra
# cadena independiente de arranque y disponibilidad.
New-Item -ItemType Directory -Path $repairStateRoot -Force | Out-Null
Copy-Item -LiteralPath $watchdog -Destination $externalWatchdog -Force
Copy-Item -LiteralPath $repairScript -Destination $externalRepairScript -Force

# La línea base se sella antes de activar la tarea. Si esta operación falla no
# se registra un vigilante capaz de restaurar desde una referencia incompleta.
& $repairPython $externalRepairScript --root $RepositoryRoot --state-root $repairStateRoot --mode seal --json
if ($LASTEXITCODE -ne 0) { throw "No se pudo sellar la linea base del Centro de Reparacion" }

$maintenanceMarker = Join-Path $RepositoryRoot ".maintenance_mode"
$quotedScript = '"{0}"' -f $externalWatchdog
$taskArgument = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $quotedScript" +
    " -RepositoryRoot `"$RepositoryRoot`"" +
    " -AppServiceName `"$AppServiceName`"" +
    " -AppTaskName `"$AppTaskName`"" +
    " -TunnelServiceName `"$TunnelServiceName`"" +
    " -HealthUrl `"$HealthUrl`"" +
    " -PublicHealthUrl `"$PublicHealthUrl`"" +
    " -RepairPython `"$repairPython`"" +
    " -RepairScript `"$externalRepairScript`"" +
    " -RepairStateRoot `"$repairStateRoot`"" +
    " -MaintenanceMarker `"$maintenanceMarker`""
if ($EnableDR4) { $taskArgument += " -EnableDR4" }
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $taskArgument
$startupTrigger = New-ScheduledTaskTrigger -AtStartup
$minuteTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($startupTrigger, $minuteTrigger) `
    -Principal $principal `
    -Settings $settings `
    -Description "Vigila MRD por componentes, restaura la version sellada y activa DR4 seguro para SQLite." `
    -Force | Out-Null

# El vigilante antiguo apuntaba a otra copia del proyecto. Solo se desactiva
# después de que el nuevo vigilante SYSTEM haya quedado registrado.
$legacyTask = Get-ScheduledTask -TaskName "MRD Watchdog Usuario" -ErrorAction SilentlyContinue
if ($legacyTask) { Disable-ScheduledTask -TaskName "MRD Watchdog Usuario" | Out-Null }

Write-Host "Continuidad 24x7 configurada sin reiniciar servicios." -ForegroundColor Green
if ($appService) { Write-Host "Revise con: sc.exe qfailure $AppServiceName" }
Write-Host "Revise con: Get-ScheduledTask -TaskName '$TaskName'"
