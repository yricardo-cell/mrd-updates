param(
    [string]$AppServiceName = "MRDToolControl",
    [string]$TunnelServiceName = "CloudflaredMRD",
    [string]$HealthUrl = "http://127.0.0.1:8000/health",
    [string]$PublicHealthUrl = "",
    [string]$StateRoot = "$env:ProgramData\MRDToolControl\watchdog",
    [string]$MaintenanceMarker = "C:\mrd_tool_control\.maintenance_mode",
    [int]$FailureThreshold = 3,
    [int]$CooldownSeconds = 300,
    [int]$MaxRestartsPerHour = 3,
    [int]$HealthTimeoutSeconds = 5,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$mutex = $null
$hasMutex = $false

function Write-WatchdogLog {
    param([string]$Message, [string]$Level = "INFO")
    $logDir = Join-Path $StateRoot "logs"
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $logPath = Join-Path $logDir ("watchdog-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))
    $safeMessage = $Message -replace '(?i)(token|password|secret|authorization)\s*[=:]\s*\S+', '$1=[REDACTED]'
    "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $safeMessage |
        Add-Content -LiteralPath $logPath -Encoding UTF8
}

function New-DefaultState {
    return [ordered]@{
        consecutive_failures = 0
        last_health_ok = $null
        last_failure = $null
        last_restart = $null
        restart_times = @()
        incident_open = $false
        last_public_check = $null
        last_public_ok = $null
    }
}

function Read-WatchdogState {
    $statePath = Join-Path $StateRoot "state.json"
    if (-not (Test-Path -LiteralPath $statePath)) {
        return New-DefaultState
    }
    try {
        $loaded = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $state = New-DefaultState
        # Copiar las claves antes de actualizar valores. En Windows PowerShell
        # enumerar directamente OrderedDictionary.Keys y asignar valores lanza
        # "Collection was modified" aunque no cambien las claves.
        foreach ($property in @($state.Keys)) {
            if ($null -ne $loaded.$property) {
                $state[$property] = $loaded.$property
            }
        }
        return $state
    }
    catch {
        Write-WatchdogLog "Estado ilegible; se inicia uno nuevo." "WARN"
        return New-DefaultState
    }
}

function Save-WatchdogState {
    param([System.Collections.IDictionary]$State)
    New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
    $statePath = Join-Path $StateRoot "state.json"
    $tmpPath = "$statePath.tmp"
    $State | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $tmpPath -Encoding UTF8
    Move-Item -LiteralPath $tmpPath -Destination $statePath -Force
}

function Test-HttpHealth {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -TimeoutSec $HealthTimeoutSeconds -UseBasicParsing
        if ($response.StatusCode -ne 200) { return $false }
        try {
            $payload = $response.Content | ConvertFrom-Json
            return $payload.status -eq "ok"
        }
        catch {
            return $true
        }
    }
    catch {
        return $false
    }
}

function Get-ServiceSafely {
    param([string]$Name)
    return Get-Service -Name $Name -ErrorAction SilentlyContinue
}

function Start-ServiceSafely {
    param([string]$Name, [string]$Reason)
    if ($DryRun) {
        Write-WatchdogLog "DRY-RUN: se iniciaria $Name. Motivo: $Reason" "WARN"
        return
    }
    Start-Service -Name $Name
    Write-WatchdogLog "Servicio $Name iniciado. Motivo: $Reason" "WARN"
}

function Restart-AppSafely {
    param([string]$Reason)
    if ($DryRun) {
        Write-WatchdogLog "DRY-RUN: se reiniciaria $AppServiceName. Motivo: $Reason" "WARN"
        return
    }
    Restart-Service -Name $AppServiceName -Force
    Write-WatchdogLog "Servicio $AppServiceName reiniciado. Motivo: $Reason" "WARN"
}

try {
    if ($FailureThreshold -lt 2) { throw "FailureThreshold debe ser al menos 2." }
    if ($MaxRestartsPerHour -lt 1) { throw "MaxRestartsPerHour debe ser al menos 1." }

    New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
    $mutex = [Threading.Mutex]::new($false, "Global\MRDToolControlWatchdog")
    $hasMutex = $mutex.WaitOne(0)
    if (-not $hasMutex) {
        Write-WatchdogLog "Otra comprobacion sigue en curso; esta ejecucion termina." "WARN"
        exit 0
    }

    $state = Read-WatchdogState
    $now = Get-Date

    if (Test-Path -LiteralPath $MaintenanceMarker) {
        Write-WatchdogLog "Modo mantenimiento activo; no se realizan reinicios."
        $state.consecutive_failures = 0
        Save-WatchdogState $state
        exit 0
    }

    # El tunel solo se inicia si el servicio esta detenido. Un fallo de Internet
    # nunca provoca el reinicio de un tunel que continua ejecutandose.
    $tunnel = Get-ServiceSafely $TunnelServiceName
    if ($null -eq $tunnel) {
        Write-WatchdogLog "Servicio $TunnelServiceName no encontrado." "ERROR"
    }
    elseif ($tunnel.Status -ne "Running") {
        Start-ServiceSafely $TunnelServiceName "servicio detenido"
    }

    $app = Get-ServiceSafely $AppServiceName
    if ($null -eq $app) {
        Write-WatchdogLog "Servicio $AppServiceName no encontrado." "ERROR"
        exit 2
    }

    if ($app.Status -ne "Running") {
        Start-ServiceSafely $AppServiceName "servicio detenido"
        $state.last_restart = $now.ToString("o")
        $state.restart_times = @($state.restart_times) + $state.last_restart
        $state.consecutive_failures = 0
        $state.incident_open = $true
        Save-WatchdogState $state
        exit 1
    }

    if (Test-HttpHealth $HealthUrl) {
        if ($state.incident_open) {
            Write-WatchdogLog "Aplicacion recuperada y saludable." "RECOVERY"
        }
        $state.consecutive_failures = 0
        $state.last_health_ok = $now.ToString("o")
        $state.incident_open = $false
    }
    else {
        $state.consecutive_failures = [int]$state.consecutive_failures + 1
        $state.last_failure = $now.ToString("o")
        $state.incident_open = $true
        Write-WatchdogLog ("Health local fallo {0}/{1}." -f $state.consecutive_failures, $FailureThreshold) "WARN"

        if ($state.consecutive_failures -ge $FailureThreshold) {
            $cutoff = $now.AddHours(-1)
            $recentRestarts = @($state.restart_times | Where-Object {
                try { [datetime]$_ -ge $cutoff } catch { $false }
            })
            $state.restart_times = $recentRestarts

            $cooldownPassed = $true
            if ($state.last_restart) {
                try {
                    $cooldownPassed = (($now - [datetime]$state.last_restart).TotalSeconds -ge $CooldownSeconds)
                }
                catch { $cooldownPassed = $true }
            }

            if ($recentRestarts.Count -ge $MaxRestartsPerHour) {
                Write-WatchdogLog "Limite de reinicios alcanzado; se evita un bucle." "ERROR"
            }
            elseif (-not $cooldownPassed) {
                Write-WatchdogLog "Reinicio omitido durante el periodo de enfriamiento." "WARN"
            }
            else {
                Restart-AppSafely "health local fallo $($state.consecutive_failures) veces"
                $state.last_restart = $now.ToString("o")
                $state.restart_times = @($recentRestarts) + $state.last_restart
                $state.consecutive_failures = 0
            }
        }
    }

    if ($PublicHealthUrl) {
        $state.last_public_check = $now.ToString("o")
        $state.last_public_ok = Test-HttpHealth $PublicHealthUrl
        if (-not $state.last_public_ok) {
            Write-WatchdogLog "Health publico no disponible; no se reinicia un servicio sano por este motivo." "WARN"
        }
    }

    Save-WatchdogState $state

    $logDir = Join-Path $StateRoot "logs"
    Get-ChildItem -LiteralPath $logDir -File -Filter "watchdog-*.log" -ErrorAction SilentlyContinue |
        Where-Object LastWriteTime -lt $now.AddDays(-30) |
        Remove-Item -Force -ErrorAction SilentlyContinue

    if ($state.incident_open) { exit 1 }
    exit 0
}
catch {
    try { Write-WatchdogLog $_.Exception.Message "ERROR" } catch { }
    exit 2
}
finally {
    if ($hasMutex -and $mutex) { $mutex.ReleaseMutex() }
    if ($mutex) { $mutex.Dispose() }
}
