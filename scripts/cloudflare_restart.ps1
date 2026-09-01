# ══════════════════════════════════════════════════════════════════════════════
# cloudflare_restart.ps1 — Reiniciar el servicio Cloudflare Tunnel
# MRD TOOL CONTROL — IASMRD Deployment
# Requiere ejecutar como Administrador
# ══════════════════════════════════════════════════════════════════════════════

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"
$ServiceName = "cloudflared"

Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  MRD TOOL CONTROL — Reiniciar Cloudflare Tunnel" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

try {
    $svc = Get-Service -Name $ServiceName -ErrorAction Stop

    if ($svc.Status -eq "Running") {
        Write-Host "  Deteniendo $ServiceName..." -ForegroundColor Yellow
        Stop-Service -Name $ServiceName -Force
        Start-Sleep -Seconds 2
    }

    Write-Host "  Iniciando $ServiceName..." -ForegroundColor Yellow
    Start-Service -Name $ServiceName
    Start-Sleep -Seconds 3

    $svc.Refresh()
    if ($svc.Status -eq "Running") {
        Write-Host "  $ServiceName reiniciado correctamente." -ForegroundColor Green
    } else {
        Write-Host "  Estado tras reinicio: $($svc.Status)" -ForegroundColor Red
    }
} catch [Microsoft.PowerShell.Commands.ServiceCommandException] {
    Write-Host "  Servicio '$ServiceName' no encontrado." -ForegroundColor Red
    Write-Host "  Instálalo con: cloudflared service install <TOKEN>" -ForegroundColor Yellow
} catch {
    Write-Host "  Error: $_" -ForegroundColor Red
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
