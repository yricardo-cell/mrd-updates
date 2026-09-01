# ══════════════════════════════════════════════════════════════════════════════
# cloudflare_test.ps1 — Prueba completa de conectividad IASMRD
# MRD TOOL CONTROL — IASMRD Deployment
# ══════════════════════════════════════════════════════════════════════════════

$ErrorActionPreference = "SilentlyContinue"
$PublicUrl  = "https://app.iasmrd.com"
$LocalUrl   = "http://127.0.0.1:8000"
$Passed = 0
$Failed = 0

function Test-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail = "")
    if ($Ok) {
        Write-Host "  [OK] $Name" -ForegroundColor Green
        $script:Passed++
    } else {
        Write-Host "  [FAIL] $Name" -ForegroundColor Red
        if ($Detail) { Write-Host "       $Detail" -ForegroundColor DarkGray }
        $script:Failed++
    }
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  MRD TOOL CONTROL — Test de Conectividad IASMRD" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# 1. cloudflared en PATH
$cfPath = Get-Command "cloudflared" -ErrorAction SilentlyContinue
Test-Check "cloudflared.exe en PATH" ($null -ne $cfPath)

# 2. Servicio cloudflared
$svc = Get-Service -Name "cloudflared" -ErrorAction SilentlyContinue
Test-Check "Servicio cloudflared instalado" ($null -ne $svc)
Test-Check "Servicio cloudflared en ejecución" ($svc -and $svc.Status -eq "Running")

# 3. Proceso cloudflared
$proc = Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue
Test-Check "Proceso cloudflared activo" ($null -ne $proc)

# 4. App MRD local
try {
    $r = Invoke-WebRequest -Uri "$LocalUrl/health" -TimeoutSec 5 -UseBasicParsing
    Test-Check "App MRD responde en localhost:8000" ($r.StatusCode -eq 200)
} catch {
    Test-Check "App MRD responde en localhost:8000" $false "No se pudo conectar a $LocalUrl/health"
}

# 5. URL pública accesible
try {
    $r = Invoke-WebRequest -Uri "$PublicUrl/health" -TimeoutSec 15 -UseBasicParsing
    Test-Check "URL pública accesible ($PublicUrl)" ($r.StatusCode -eq 200)
} catch {
    Test-Check "URL pública accesible ($PublicUrl)" $false $_
}

# 6. HTTPS
try {
    $r = Invoke-WebRequest -Uri "$PublicUrl" -TimeoutSec 10 -UseBasicParsing -MaximumRedirection 5
    Test-Check "HTTPS activo en $PublicUrl" ($r.BaseResponse.ResponseUri.Scheme -eq "https")
} catch {
    Test-Check "HTTPS activo en $PublicUrl" $false
}

# 7. Ruta /scan disponible
try {
    $r = Invoke-WebRequest -Uri "$PublicUrl/scan" -TimeoutSec 10 -UseBasicParsing -MaximumRedirection 5
    Test-Check "Ruta /scan disponible" ($r.StatusCode -lt 500)
} catch {
    Test-Check "Ruta /scan disponible" $false
}

# 8. Cabecera CF-Ray presente (confirma paso por Cloudflare)
try {
    $r = Invoke-WebRequest -Uri "$PublicUrl/health" -TimeoutSec 10 -UseBasicParsing
    $cfRay = $r.Headers["CF-Ray"]
    Test-Check "Cabecera CF-Ray presente (tráfico via Cloudflare)" ($null -ne $cfRay) $cfRay
} catch {
    Test-Check "Cabecera CF-Ray presente" $false
}

# Resumen
Write-Host ""
Write-Host "───────────────────────────────────────────────────" -ForegroundColor DarkGray
$total = $Passed + $Failed
$color = if ($Failed -eq 0) { "Green" } else { "Yellow" }
Write-Host "  Resultado: $Passed/$total pruebas correctas" -ForegroundColor $color
if ($Failed -gt 0) {
    Write-Host "  $Failed prueba(s) fallida(s). Revisa los puntos marcados con [FAIL]." -ForegroundColor Red
}
Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
