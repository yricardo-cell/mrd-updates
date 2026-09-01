# ══════════════════════════════════════════════════════════════════════════════
# FINALIZAR_ROTACION_TOKEN.ps1 — Paso final de la rotación del token de Cloudflare Tunnel
# MRD TOOL CONTROL
#
# Qué hace:
#   1. Repunta el DNS de app.iasmrd.com al túnel nuevo (MRD-TOOL-CONTROL-v2)
#   2. Reinicia el servicio "cloudflared" para que cargue el config.yml nuevo
#      (ya apunta al túnel nuevo — ver private_config/cloudflared/config.yml)
#   3. Verifica que la app responde
#
# El túnel viejo (43c8887e-...) NO se borra aquí a propósito: hasta que no
# confirmes que todo funciona, se deja como red de seguridad para poder
# volver atrás. El borrado (que es lo que invalida el token expuesto de
# forma definitiva) se hace después, en un paso separado.
#
# Requiere ejecutar como Administrador.
# ══════════════════════════════════════════════════════════════════════════════

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"
$CfExe      = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$NewTunnel  = "43513dd0-f1b1-4ac6-a10d-23642d9b53b7"
$Hostname   = "app.iasmrd.com"
$ServiceName = "cloudflared"

function OK   { param($t) Write-Host "  [OK]  $t" -ForegroundColor Green }
function FAIL { param($t) Write-Host "  [ERR] $t" -ForegroundColor Red }
function INFO { param($t) Write-Host "  [-->] $t" -ForegroundColor Yellow }

Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  MRD TOOL CONTROL — Finalizar rotación de token Cloudflare" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $CfExe)) {
    $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($cmd) { $CfExe = $cmd.Source } else { FAIL "No se encuentra cloudflared.exe"; exit 1 }
}

INFO "Repuntando DNS de $Hostname al tunel nuevo..."
& $CfExe tunnel route dns --overwrite-dns $NewTunnel $Hostname
if ($LASTEXITCODE -ne 0) { FAIL "Fallo al repuntar el DNS"; exit 1 }
OK "DNS repuntado a $NewTunnel"

INFO "Reiniciando el servicio $ServiceName..."
$svc = Get-Service -Name $ServiceName -ErrorAction Stop
if ($svc.Status -eq "Running") { Stop-Service -Name $ServiceName -Force; Start-Sleep -Seconds 2 }
Start-Service -Name $ServiceName
Start-Sleep -Seconds 5
$svc.Refresh()
if ($svc.Status -eq "Running") { OK "Servicio $ServiceName reiniciado" } else { FAIL "El servicio no quedo en Running (estado: $($svc.Status))" }

INFO "Verificando conectividad local (localhost:8000/health)..."
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 5 -UseBasicParsing
    if ($r.StatusCode -eq 200) { OK "App responde en local" } else { FAIL "Estado inesperado: $($r.StatusCode)" }
} catch { FAIL "La app no responde en local: $_" }

INFO "Verificando conectividad publica (https://$Hostname/health)..."
try {
    Start-Sleep -Seconds 3
    $r = Invoke-WebRequest -Uri "https://$Hostname/health" -TimeoutSec 15 -UseBasicParsing
    if ($r.StatusCode -eq 200) { OK "https://$Hostname responde correctamente" } else { FAIL "Estado inesperado: $($r.StatusCode)" }
} catch { FAIL "https://$Hostname no responde todavia: $_ (puede tardar unos segundos mas en propagar; reintenta en el navegador)" }

Write-Host ""
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Siguiente paso: confirma que app.iasmrd.com funciona bien" -ForegroundColor Yellow
Write-Host "  (login, escaner, portal del trabajador) y avisa para" -ForegroundColor Yellow
Write-Host "  borrar el tunel viejo y dejar el token expuesto inservible." -ForegroundColor Yellow
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
