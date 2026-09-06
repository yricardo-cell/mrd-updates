# Tunel B de respaldo (mrd-tool-control-backup) como tarea programada SYSTEM.
#
# Hasta el 06/09/2026 la tarea 'CloudflaredBackup' corria con la cuenta del
# usuario al iniciar sesion: tras un reinicio sin iniciar sesion (o si el
# arranque fallaba, como paso a las 11:21 de ese dia) el tunel B quedaba
# parado durante horas y el failover A->B habria conmutado a un tunel muerto.
# Este instalador registra la misma tarea como SYSTEM al arrancar Windows,
# con reinicio automatico ilimitado, y comprueba que el conector se registra
# de verdad en Cloudflare (metrics 127.0.0.1:20251/ready).
#
# Vista previa (sin cambios):
#   powershell -ExecutionPolicy Bypass -File scripts\operations\install_backup_tunnel_task.ps1
# Aplicar (PowerShell de administrador; usar & si se ejecuta desde una consola):
#   & ".\scripts\operations\install_backup_tunnel_task.ps1" -Apply

param(
    [string]$RepositoryRoot = "",
    [string]$TaskName = "CloudflaredBackup",
    [string]$CloudflaredExe = "C:\Program Files (x86)\cloudflared\cloudflared.exe",
    [string]$ReadyUrl = "http://127.0.0.1:20251/ready",
    [switch]$Apply,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-ReadyConnections {
    param([string]$Url)
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 4 -Uri $Url
        if ($r.StatusCode -eq 200) { return ($r.Content | ConvertFrom-Json).readyConnections }
    } catch {}
    return $null
}

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
} else {
    $RepositoryRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
}
$configFile = Join-Path $RepositoryRoot "config\cloudflared-backup.yml"

if (-not (Test-Path -LiteralPath $CloudflaredExe -PathType Leaf)) { throw "No se encontro cloudflared en $CloudflaredExe" }
if (-not (Test-Path -LiteralPath $configFile -PathType Leaf)) { throw "No se encontro la configuracion del tunel B: $configFile" }

$credLine = Get-Content -LiteralPath $configFile | Where-Object { $_ -match '^\s*credentials-file:\s*(.+)$' } | Select-Object -First 1
$credFile = if ($credLine) { ($credLine -replace '^\s*credentials-file:\s*', '').Trim() } else { $null }
if (-not $credFile -or -not (Test-Path -LiteralPath $credFile -PathType Leaf)) {
    throw "La configuracion no apunta a un archivo de credenciales existente (credentials-file: $credFile)"
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$readyNow = Get-ReadyConnections -Url $ReadyUrl

Write-Host "Plan: tunel B ($TaskName) como tarea SYSTEM" -ForegroundColor Cyan
Write-Host "- Ejecutable: $CloudflaredExe"
Write-Host "- Configuracion: $configFile (credenciales: $credFile)"
if ($existing) {
    Write-Host "- Tarea actual: usuario $($existing.Principal.UserId), estado $($existing.State) -> se sustituye por SYSTEM al arrancar Windows"
} else {
    Write-Host "- No existe la tarea: se crea nueva"
}
Write-Host "- Reinicio automatico cada minuto si el proceso termina, sin limite de tiempo, tambien con bateria"
Write-Host "- Conexiones del tunel B ahora mismo: $(if ($null -ne $readyNow) { $readyNow } else { 'ninguna (sin proceso)' })"
Write-Host "- No se toca el tunel A (servicio Cloudflared), el DNS ni MRD Tool Control"

if (-not $Apply) {
    Write-Host "Modo vista previa. Use -Apply como Administrador para aplicar." -ForegroundColor Yellow
    exit 0
}
if (-not (Test-IsAdministrator)) { throw "Ejecute PowerShell como Administrador." }

$action = New-ScheduledTaskAction `
    -Execute $CloudflaredExe `
    -Argument ('tunnel --config "{0}" --no-autoupdate run' -f $configFile)
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1)

if ($existing -and $existing.State -eq "Running") {
    # Un solo conector por tunel: se para la instancia de usuario antes de
    # arrancar la de SYSTEM (corte de unos segundos solo en el tunel B).
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Tunel Cloudflare B de respaldo (mrd-tool-control-backup) para app.iasmrd.com y sentinel.iasmrd.com." `
    -Force | Out-Null

if (-not $NoStart) {
    Start-ScheduledTask -TaskName $TaskName
    $connections = $null
    for ($i = 0; $i -lt 15 -and $null -eq $connections; $i++) {
        Start-Sleep -Seconds 2
        $connections = Get-ReadyConnections -Url $ReadyUrl
    }
    if ($null -eq $connections) {
        throw "La tarea se registro pero el tunel B no responde en $ReadyUrl tras 30 s. Revise: Get-ScheduledTaskInfo '$TaskName'"
    }
    Write-Host "Tunel B conectado: $connections conexiones registradas en Cloudflare." -ForegroundColor Green
}
Write-Host "$TaskName instalado como SYSTEM al arrancar Windows." -ForegroundColor Green
