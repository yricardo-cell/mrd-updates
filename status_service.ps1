# =============================================================
# MRD TOOL CONTROL — Estado del Servicio
# Sprint 5.3 — v1.9.3-alpha
# =============================================================
$ErrorActionPreference = "SilentlyContinue"
$SERVICE = "MRDToolControl"
$ROOT    = $PSScriptRoot

Write-Host ""
Write-Host "  ================================================================" -ForegroundColor White
Write-Host "   MRD TOOL CONTROL — Estado del Servicio" -ForegroundColor White
Write-Host "  ================================================================" -ForegroundColor White
Write-Host ""

# ─── Estado del servicio Windows ─────────────────────────────────────────────
$svc = Get-Service -Name $SERVICE -ErrorAction SilentlyContinue
if ($svc) {
    $color = if ($svc.Status -eq "Running") { "Green" } else { "Red" }
    Write-Host "  Servicio Windows:" -NoNewline
    Write-Host "  $($svc.Status.ToString().ToUpper())" -ForegroundColor $color
    Write-Host "  Nombre:            $($svc.Name)"
    Write-Host "  Nombre visible:    $($svc.DisplayName)"

    # Tipo de inicio
    try {
        $wmi = Get-WmiObject Win32_Service -Filter "Name='$SERVICE'" -ErrorAction SilentlyContinue
        if ($wmi) {
            Write-Host "  Inicio:            $($wmi.StartMode)"
        }
    } catch {}
} else {
    Write-Host "  Servicio Windows:  " -NoNewline
    Write-Host "NO INSTALADO" -ForegroundColor Yellow
}

# ─── Estado del runner (desde archivo de estado) ──────────────────────────────
$statusFile = Join-Path $ROOT ".service_status"
if (Test-Path $statusFile) {
    try {
        $data = Get-Content $statusFile -Raw | ConvertFrom-Json
        Write-Host ""
        Write-Host "  Runner uvicorn:"
        Write-Host "  PID:               $($data.pid)"
        Write-Host "  Puerto:            $($data.port)"
        Write-Host "  Versión:           $($data.version)"
        Write-Host "  Reinicios (auto):  $($data.restart_count)"

        if ($data.uptime_seconds) {
            $uptime = [int]$data.uptime_seconds
            $h = [math]::Floor($uptime / 3600)
            $m = [math]::Floor(($uptime % 3600) / 60)
            $s = $uptime % 60
            Write-Host "  Uptime:            ${h}h ${m}m ${s}s"
        }
        if ($data.start_time) {
            Write-Host "  Iniciado:          $($data.start_time)"
        }
    } catch {
        Write-Host "  (archivo de estado no legible)"
    }
} else {
    Write-Host ""
    Write-Host "  Runner:            sin datos (servicio posiblemente detenido)"
}

# ─── Logs recientes ───────────────────────────────────────────────────────────
$svcLog = Join-Path $ROOT "logs\service.log"
if (Test-Path $svcLog) {
    Write-Host ""
    Write-Host "  Últimas líneas de service.log:" -ForegroundColor Gray
    Get-Content $svcLog -Tail 5 | ForEach-Object {
        Write-Host "    $_" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "  ================================================================" -ForegroundColor Gray
Write-Host "  Gestión: start_service.ps1 | stop_service.ps1 | restart_service.ps1" -ForegroundColor Gray
Write-Host ""
