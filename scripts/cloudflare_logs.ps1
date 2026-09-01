# ══════════════════════════════════════════════════════════════════════════════
# cloudflare_logs.ps1 — Ver logs de Cloudflare Tunnel
# MRD TOOL CONTROL — IASMRD Deployment
# ══════════════════════════════════════════════════════════════════════════════

param(
    [int]$Lines = 50,
    [switch]$Follow
)

$ErrorActionPreference = "SilentlyContinue"

# Rutas candidatas para el log de cloudflared
$LogPaths = @(
    "$env:USERPROFILE\.cloudflared\cloudflared.log",
    "C:\ProgramData\cloudflared\cloudflared.log",
    "$PSScriptRoot\..\data\cloudflared.log"
)

Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  MRD TOOL CONTROL — Logs Cloudflare Tunnel" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

$LogFile = $null
foreach ($p in $LogPaths) {
    if (Test-Path $p) {
        $LogFile = $p
        break
    }
}

if (-not $LogFile) {
    Write-Host "  No se encontró fichero de log de cloudflared." -ForegroundColor Yellow
    Write-Host "  Rutas buscadas:" -ForegroundColor DarkGray
    $LogPaths | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    Write-Host ""
    Write-Host "  Para ver logs en tiempo real usa:" -ForegroundColor Cyan
    Write-Host "  cloudflared tunnel run --loglevel debug MRD-TOOL-CONTROL" -ForegroundColor White
} else {
    Write-Host "  Fichero: $LogFile" -ForegroundColor DarkGray
    Write-Host ""
    if ($Follow) {
        Write-Host "  Mostrando en tiempo real (Ctrl+C para salir)..." -ForegroundColor Yellow
        Get-Content $LogFile -Tail $Lines -Wait
    } else {
        Get-Content $LogFile -Tail $Lines | ForEach-Object {
            if ($_ -match "error|ERR|ERRO") {
                Write-Host $_ -ForegroundColor Red
            } elseif ($_ -match "warn|WARN") {
                Write-Host $_ -ForegroundColor Yellow
            } elseif ($_ -match "info|INF") {
                Write-Host $_ -ForegroundColor Gray
            } else {
                Write-Host $_
            }
        }
    }
}

Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
