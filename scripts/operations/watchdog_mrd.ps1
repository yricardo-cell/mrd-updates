param(
    [string]$RepositoryRoot = "C:\mrd tool\mrd-tool-control-2.5.0",
    [string]$AppServiceName = "MRDToolControl",
    [string]$AppTaskName = "MRD Tool Control",
    [string]$TunnelServiceName = "Cloudflared",
    [string]$HealthUrl = "http://127.0.0.1:8000/health",
    [string]$PublicHealthUrl = "",
    [string]$StateRoot = "$env:ProgramData\MRDToolControl\watchdog",
    [string]$MaintenanceMarker = "C:\mrd tool\mrd-tool-control-2.5.0\.maintenance_mode",
    [int]$FailureThreshold = 3,
    [int]$CooldownSeconds = 300,
    [int]$MaxRestartsPerHour = 3,
    [int]$HealthTimeoutSeconds = 5,
    [string]$RepairPython = "",
    [string]$RepairScript = "",
    [string]$RepairStateRoot = "$env:ProgramData\MRDToolControl\repair-center",
    [switch]$EnableDR4,
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

function Get-AppTarget {
    if (Get-ServiceSafely $AppServiceName) { return "service" }
    if (Get-ScheduledTask -TaskName $AppTaskName -ErrorAction SilentlyContinue) { return "task" }
    return $null
}

function Test-AppRunning {
    param([string]$Target)
    if ($Target -eq "service") {
        $service = Get-ServiceSafely $AppServiceName
        return $service -and $service.Status -eq "Running"
    }
    $task = Get-ScheduledTask -TaskName $AppTaskName -ErrorAction SilentlyContinue
    return $task -and $task.State -eq "Running"
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

function Start-AppSafely {
    param([string]$Target, [string]$Reason)
    if ($DryRun) { Write-WatchdogLog "DRY-RUN: se iniciaria MRD mediante $Target. Motivo: $Reason" "WARN"; return }
    if ($Target -eq "service") { Start-Service -Name $AppServiceName }
    else { Start-ScheduledTask -TaskName $AppTaskName }
    Write-WatchdogLog "MRD iniciado mediante $Target. Motivo: $Reason" "WARN"
}

function Stop-AppSafely {
    param([string]$Target)
    if ($Target -eq "service") { Stop-Service -Name $AppServiceName -Force }
    else { Stop-ScheduledTask -TaskName $AppTaskName }
}

function Restart-AppSafely {
    param([string]$Target, [string]$Reason)
    if ($DryRun) {
        Write-WatchdogLog "DRY-RUN: se reiniciaria MRD mediante $Target. Motivo: $Reason" "WARN"
        return
    }
    if ($Target -eq "service") { Restart-Service -Name $AppServiceName -Force }
    else {
        Stop-ScheduledTask -TaskName $AppTaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Start-ScheduledTask -TaskName $AppTaskName
    }
    Write-WatchdogLog "MRD reiniciado mediante $Target. Motivo: $Reason" "WARN"
}

function Test-RestartAllowed {
    param([System.Collections.IDictionary]$State, [datetime]$Now)
    $cutoff = $Now.AddHours(-1)
    $recent = @($State.restart_times | Where-Object {
        try { [datetime]$_ -ge $cutoff } catch { $false }
    })
    $State.restart_times = $recent
    if ($recent.Count -ge $MaxRestartsPerHour) {
        Write-WatchdogLog "Limite de reinicios alcanzado; se evita un bucle." "ERROR"
        return $false
    }
    if ($State.last_restart) {
        try {
            if (($Now - [datetime]$State.last_restart).TotalSeconds -lt $CooldownSeconds) {
                Write-WatchdogLog "Reinicio omitido durante el periodo de enfriamiento." "WARN"
                return $false
            }
        }
        catch { }
    }
    return $true
}

function Register-Restart {
    param([System.Collections.IDictionary]$State, [datetime]$Now)
    $State.last_restart = $Now.ToString("o")
    $State.restart_times = @($State.restart_times) + $State.last_restart
    $State.consecutive_failures = 0
    $State.incident_open = $true
}

function Invoke-RepairCenter {
    param([switch]$Apply, [switch]$AllowDR4, [switch]$ServiceConfirmedStopped)
    if (-not $RepairPython) { $script:RepairPython = Join-Path $RepositoryRoot "venv\Scripts\python.exe" }
    if (-not $RepairScript) { $script:RepairScript = Join-Path $RepositoryRoot "scripts\operations\repair_center.py" }
    if (-not (Test-Path -LiteralPath $RepairPython -PathType Leaf) -or
        -not (Test-Path -LiteralPath $RepairScript -PathType Leaf)) {
        Write-WatchdogLog "Centro de reparacion no instalado; continua el watchdog clasico." "WARN"
        return $null
    }
    $repairMode = if ($Apply) { "repair" } else { "check" }
    $arguments = @(
        $RepairScript, "--root", $RepositoryRoot,
        "--state-root", $RepairStateRoot, "--mode", $repairMode, "--json",
        "--local-health-url", $HealthUrl
    )
    if ($PublicHealthUrl) { $arguments += @("--public-health-url", $PublicHealthUrl) }
    if ($AllowDR4) { $arguments += "--allow-dr4" }
    if ($ServiceConfirmedStopped) { $arguments += "--service-confirmed-stopped" }
    try {
        $raw = @(& $RepairPython @arguments 2>&1)
        $jsonLine = $raw | Where-Object { $_ -is [string] -and $_.Trim().StartsWith("{") } | Select-Object -Last 1
        if (-not $jsonLine) {
            Write-WatchdogLog "Centro de reparacion no devolvio estado JSON." "ERROR"
            return $null
        }
        return ($jsonLine | ConvertFrom-Json)
    }
    catch {
        Write-WatchdogLog ("Centro de reparacion fallo: " + $_.Exception.Message) "ERROR"
        return $null
    }
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

    # Orden de recuperacion seguro: primero MRD, despues Cloudflare. Si ambos
    # servicios estan caidos, restaurar el tunel antes que la app expondria
    # temporalmente una aplicacion que aun no esta lista para recibir trafico.
    $appTarget = Get-AppTarget
    if ($null -eq $appTarget) {
        Write-WatchdogLog "No se encontro ni el servicio $AppServiceName ni la tarea $AppTaskName." "ERROR"
        exit 2
    }

    if (-not (Test-AppRunning $appTarget)) {
        # Misma regla anti-bucle que el resto de reinicios: un crash al
        # arrancar no debe reiniciarse sin limite ni consumir el presupuesto
        # horario a espaldas de Test-RestartAllowed.
        if (Test-RestartAllowed $state $now) {
            Start-AppSafely $appTarget "aplicacion detenida"
            Register-Restart $state $now
        }
        else {
            $state.incident_open = $true
        }
        Save-WatchdogState $state
        exit 1
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

    # El centro externo revisa cada componente por separado. Primero solo
    # diagnostica (--mode check): repair_center.py no muta database_failures
    # ni escribe state.json/status.json en ese modo, así que llamarlo aquí no
    # cuenta como un fallo real. Solo se pasa a --mode repair si el
    # diagnóstico encuentra remaining_errors; y repair_center.py, dentro de
    # ese modo, solo restaura ficheros ante un fallo real corroborado
    # (fichero ausente, o BD/health local caídos) — un hash distinto con la
    # app sana puede ser una edición manual sin resellar y no se revierte.
    $repair = Invoke-RepairCenter
    if ($repair -and $repair.remaining_errors.Count -gt 0) {
        $repair = Invoke-RepairCenter -Apply
    }
    if ($repair -and $repair.repaired_files.Count -gt 0) {
        $detail = ($repair.repaired_files -join ", ")
        Write-WatchdogLog "Componentes restaurados: $detail" "RECOVERY"
        if (Test-RestartAllowed $state $now) {
            Restart-AppSafely $appTarget "el centro 24x7 restauró componentes concretos"
            Register-Restart $state $now
            Save-WatchdogState $state
            exit 1
        }
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
            if ($EnableDR4 -and $repair -and $repair.dr4_ready -and (Test-RestartAllowed $state $now)) {
                if ($DryRun) {
                    Write-WatchdogLog "DRY-RUN: DR4 restauraria SQLite con MRD detenido." "WARN"
                }
                else {
                    Write-WatchdogLog "DR4 confirmado: se detiene MRD para restaurar una copia SQLite verificada." "ERROR"
                    $dr4 = $null
                    try {
                        Stop-AppSafely $appTarget
                        for ($attempt = 0; $attempt -lt 20; $attempt++) {
                            if (-not (Test-AppRunning $appTarget) -and -not (Test-HttpHealth $HealthUrl)) { break }
                            Start-Sleep -Milliseconds 500
                        }
                        if ((Test-AppRunning $appTarget) -or (Test-HttpHealth $HealthUrl)) {
                            throw "MRD no confirmo la parada; DR4 cancelada."
                        }
                        $dr4 = Invoke-RepairCenter -Apply -AllowDR4 -ServiceConfirmedStopped
                    }
                    catch {
                        # Sin este catch la excepcion saltaba al catch global
                        # (exit 2) antes de Save-WatchdogState y el reinicio
                        # no quedaba registrado: bucle de paradas sin limite.
                        Write-WatchdogLog "DR4 cancelada: $_" "ERROR"
                    }
                    finally {
                        if (-not (Test-AppRunning $appTarget)) { Start-AppSafely $appTarget "fin de DR4" }
                        Register-Restart $state $now
                        Save-WatchdogState $state
                    }
                    if ($dr4 -and $dr4.dr4.ok) {
                        Write-WatchdogLog "DR4 completo; base dañada conservada en cuarentena." "RECOVERY"
                    }
                    else {
                        Write-WatchdogLog "DR4 no pudo restaurar SQLite; MRD se volvió a iniciar sin borrar la base." "ERROR"
                    }
                }
            }
            elseif (Test-RestartAllowed $state $now) {
                Restart-AppSafely $appTarget "health local fallo $($state.consecutive_failures) veces"
                Register-Restart $state $now
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
