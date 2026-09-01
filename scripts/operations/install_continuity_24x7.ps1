param(
    [string]$RepositoryRoot = "C:\mrd_tool_control",
    [string]$AppServiceName = "MRDToolControl",
    [string]$TunnelServiceName = "CloudflaredMRD",
    [string]$TaskName = "MRD Tool Control - Watchdog 24x7",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$watchdog = Join-Path $RepositoryRoot "scripts\operations\watchdog_mrd.ps1"
if (-not (Test-Path -LiteralPath $watchdog)) {
    throw "No se encontro el watchdog en $watchdog"
}

foreach ($serviceName in @($AppServiceName, $TunnelServiceName)) {
    if (-not (Get-Service -Name $serviceName -ErrorAction SilentlyContinue)) {
        throw "No existe el servicio $serviceName"
    }
}

Write-Host "Plan de continuidad 24x7:" -ForegroundColor Cyan
Write-Host "- Configurar recuperacion de Windows para $AppServiceName"
Write-Host "- Configurar recuperacion de Windows para $TunnelServiceName"
Write-Host "- Crear tarea $TaskName cada minuto y al arrancar"
Write-Host "- No reiniciar ningun servicio durante la instalacion"

if (-not $Apply) {
    Write-Host "Modo vista previa. Use -Apply como Administrador para aplicar." -ForegroundColor Yellow
    exit 0
}

if (-not (Test-IsAdministrator)) {
    throw "Ejecute PowerShell como Administrador."
}

foreach ($serviceName in @($AppServiceName, $TunnelServiceName)) {
    & sc.exe config $serviceName start= auto | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudo configurar inicio automatico para $serviceName" }
    & sc.exe failure $serviceName reset= 86400 actions= restart/5000/restart/15000/restart/60000 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudo configurar recovery para $serviceName" }
    & sc.exe failureflag $serviceName 1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "No se pudo activar failureflag para $serviceName" }
}

$quotedScript = '"{0}"' -f $watchdog
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $quotedScript"
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
    -Description "Vigila MRD Tool Control con umbral, cooldown y proteccion anti-bucle." `
    -Force | Out-Null

Write-Host "Continuidad 24x7 configurada sin reiniciar servicios." -ForegroundColor Green
Write-Host "Revise con: sc.exe qfailure $AppServiceName"
Write-Host "Revise con: Get-ScheduledTask -TaskName '$TaskName'"
