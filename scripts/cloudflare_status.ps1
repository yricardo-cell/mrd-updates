# ══════════════════════════════════════════════════════════════════════════════
# cloudflare_status.ps1 — Estado del túnel Cloudflare
# MRD TOOL CONTROL — IASMRD Deployment
# ══════════════════════════════════════════════════════════════════════════════

$ErrorActionPreference = "SilentlyContinue"
$PublicUrl = "https://app.iasmrd.com"

Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  MRD TOOL CONTROL — Estado Cloudflare Tunnel" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# 1. Servicio cloudflared
$svc = Get-Service -Name "cloudflared" -ErrorAction SilentlyContinue
if ($svc) {
    $color = if ($svc.Status -eq "Running") { "Green" } else { "Red" }
    Write-Host "  Servicio cloudflared : " -NoNewline
    Write-Host $svc.Status -ForegroundColor $color
} else {
    Write-Host "  Servicio cloudflared : " -NoNewline
    Write-Host "NO INSTALADO" -ForegroundColor Red
}

# 2. Proceso cloudflared.exe
$proc = Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue
if ($proc) {
    Write-Host "  Proceso cloudflared  : " -NoNewline
    Write-Host "En ejecución (PID $($proc.Id))" -ForegroundColor Green
} else {
    Write-Host "  Proceso cloudflared  : " -NoNewline
    Write-Host "No encontrado" -ForegroundColor Yellow
}

# 3. Aplicación MRD en localhost
Write-Host ""
try {
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3 -UseBasicParsing
    Write-Host "  App MRD (local)      : " -NoNewline
    Write-Host "OK ($($resp.StatusCode))" -ForegroundColor Green
} catch {
    Write-Host "  App MRD (local)      : " -NoNewline
    Write-Host "NO RESPONDE" -ForegroundColor Red
}

# 4. URL pública
try {
    $resp = Invoke-WebRequest -Uri "$PublicUrl/health" -TimeoutSec 10 -UseBasicParsing
    Write-Host "  URL pública          : " -NoNewline
    Write-Host "ACCESIBLE ($($resp.StatusCode))" -ForegroundColor Green
} catch {
    Write-Host "  URL pública          : " -NoNewline
    Write-Host "NO ACCESIBLE" -ForegroundColor Red
    Write-Host "  ($PublicUrl/health)" -ForegroundColor DarkGray
}

# 5. Túneles activos
Write-Host ""
Write-Host "  Túneles activos:" -ForegroundColor Cyan
try {
    $tunnels = & cloudflared tunnel list 2>&1
    Write-Host $tunnels -ForegroundColor Gray
} catch {
    Write-Host "  cloudflared no está en el PATH" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
