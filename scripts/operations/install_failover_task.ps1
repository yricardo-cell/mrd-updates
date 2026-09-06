# MRD Failover Watchdog 24x7 — instalacion recomendada mediante Tarea Programada.
#
# El servicio pywin32 MRDFailoverWatchdog no arranca en esta maquina (el SCM
# agota el tiempo de espera en cada arranque de Windows, igual que le pasaba a
# MRDSentinel). Este instalador registra el mismo vigilante
# (scripts/operations/failover_service.py run) como tarea programada nativa,
# siguiendo el patron de install_sentinel_task.ps1: arranca con Windows (o al
# iniciar sesion con -CurrentUser), se reinicia sola si el proceso termina y no
# depende de pythonservice.exe.
#
# Vista previa (sin cambios):
#   powershell -ExecutionPolicy Bypass -File scripts\operations\install_failover_task.ps1
# Instalacion como SYSTEM (PowerShell de administrador):
#   powershell -ExecutionPolicy Bypass -File scripts\operations\install_failover_task.ps1 -Apply
# Instalacion con la cuenta actual (sin administrador):
#   powershell -ExecutionPolicy Bypass -File scripts\operations\install_failover_task.ps1 -Apply -CurrentUser

param(
    [string]$RepositoryRoot = "",
    [string]$PythonExe = "",
    [string]$TaskName = "MRD Failover Watchdog 24x7",
    [string]$LegacyServiceName = "MRDFailoverWatchdog",
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
        (Join-Path $parentRoot "mrd-tool-control-2.5.0\venv\Scripts\python.exe")
    )
    $PythonExe = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
} elseif (Test-Path -LiteralPath $PythonExe) {
    $PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
} else {
    throw "No existe el Python indicado: $PythonExe"
}
if (-not $PythonExe) {
    throw "No se encontro el entorno Python de MRD (venv\Scripts\python.exe)."
}

$serviceScript = Join-Path $RepositoryRoot "scripts\operations\failover_service.py"
$failoverScript = Join-Path $RepositoryRoot "scripts\operations\failover.py"
$tokenFile = Join-Path $RepositoryRoot "config\cloudflare_dns.token"
foreach ($required in @($serviceScript, $failoverScript)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "No se encontro $required"
    }
}
if (-not (Test-Path -LiteralPath $tokenFile -PathType Leaf)) {
    throw "Falta $tokenFile. Crea un API Token de Cloudflare (Zone:DNS:Edit, solo zona iasmrd.com) y guardalo ahi en una linea."
}

# Verificacion de solo lectura del token (GET a la API; nunca cambia el DNS).
# Se usa un state-root temporal para no competir por el lock del vigilante real.
$verifyRoot = Join-Path $env:TEMP ("mrd-failover-verify-" + [guid]::NewGuid().ToString("N"))
try {
    & $PythonExe $failoverScript --verify-token --state-root $verifyRoot | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "El token de $tokenFile no es valido para la zona iasmrd.com (ver salida anterior)."
    }
} finally {
    if (Test-Path -LiteralPath $verifyRoot) { Remove-Item -LiteralPath $verifyRoot -Recurse -Force -ErrorAction SilentlyContinue }
}

$legacyService = Get-Service -Name $LegacyServiceName -ErrorAction SilentlyContinue

# El vigilante escribe estado, lock y logs en ProgramData. Si ya los creo el
# servicio SYSTEM, pertenecen a Administradores y una tarea con la cuenta
# actual no podria abrirlos: moriria nada mas arrancar sin dejar rastro.
$stateRoot = Join-Path $env:ProgramData "MRDToolControl\failover"
if ($CurrentUser) {
    $probeTargets = @(
        (Join-Path $stateRoot "logs\failover.log"),
        (Join-Path $stateRoot "state.json"),
        (Join-Path $stateRoot "failover.lock")
    )
    foreach ($target in $probeTargets) {
        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { continue }
        try {
            $stream = [System.IO.File]::Open($target, 'Open', 'ReadWrite', 'ReadWrite')
            $stream.Close()
        } catch {
            throw "La cuenta actual no puede escribir $target (lo creo el servicio SYSTEM). Instale como Administrador sin -CurrentUser, o corrija los permisos con: icacls `"$stateRoot`" /grant `"$env:USERNAME`":(OI)(CI)F /T"
        }
    }
}

Write-Host "Plan de instalacion de $TaskName`:" -ForegroundColor Cyan
Write-Host "- Crear o actualizar la tarea '$TaskName'"
if ($CurrentUser) {
    Write-Host "- Ejecutarla con la cuenta actual al iniciar sesion (no requiere administrador)"
} else {
    Write-Host "- Ejecutarla como SYSTEM al arrancar Windows"
}
Write-Host "- Mantenerla activa con bateria y reiniciarla si se cierra"
Write-Host "- Vigilante: $PythonExe `"$serviceScript`" run"
Write-Host "- Token verificado (solo lectura): $tokenFile"
if ($legacyService) {
    if ($CurrentUser) {
        Write-Host "- El servicio pywin32 '$LegacyServiceName' sigue existiendo (estado: $($legacyService.Status)); desactivalo como administrador con:"
        Write-Host "    sc.exe stop $LegacyServiceName; sc.exe config $LegacyServiceName start= disabled" -ForegroundColor Yellow
    } else {
        Write-Host "- Detener y desactivar el servicio pywin32 '$LegacyServiceName' (estado: $($legacyService.Status)) para que no compita por el lock"
    }
}
Write-Host "- No modificar MRD Tool Control, los tuneles Cloudflare ni el DNS"

if (-not $Apply) {
    if ($CurrentUser) {
        Write-Host "Modo vista previa. Use -Apply para instalar con la cuenta actual." -ForegroundColor Yellow
    } else {
        Write-Host "Modo vista previa. Use -Apply como Administrador para aplicar." -ForegroundColor Yellow
    }
    exit 0
}
if (-not $CurrentUser -and -not (Test-IsAdministrator)) {
    throw "Ejecute PowerShell como Administrador (o use -CurrentUser)."
}

$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument ('"{0}" run' -f $serviceScript) `
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

if ($legacyService -and -not $CurrentUser) {
    if ($legacyService.Status -ne 'Stopped') {
        Stop-Service -Name $LegacyServiceName -Force -ErrorAction SilentlyContinue
    }
    & sc.exe config $LegacyServiceName start= disabled | Out-Null
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $startupTrigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Vigilante de failover de tunel Cloudflare (A/B) para app.iasmrd.com." `
    -Force | Out-Null

if (-not $NoStart) {
    Start-ScheduledTask -TaskName $TaskName
}

Write-Host "$TaskName instalado correctamente." -ForegroundColor Green
Write-Host "Estado: Get-ScheduledTask -TaskName '$TaskName' ; logs en $env:ProgramData\MRDToolControl\failover\logs"
