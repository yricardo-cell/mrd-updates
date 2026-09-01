# =============================================================================
# MRD TOOL CONTROL — Instalador de Cloudflare Named Tunnel
# Sprint 5.4 — v1.9.4-alpha
# =============================================================================
# Uso:
#   .\install_cloudflared.ps1
#   .\install_cloudflared.ps1 -TunnelName "mrd-tool" -Hostname "herramientas.midominio.com"
#   .\install_cloudflared.ps1 -ConfigOnly     # Solo actualiza configuración del túnel
#   .\install_cloudflared.ps1 -UninstallOnly  # Desinstala el servicio
# =============================================================================

param(
    [string]$TunnelName  = "mrd-tool",
    [string]$Hostname    = "",
    [string]$Port        = "8000",
    [switch]$ConfigOnly,
    [switch]$UninstallOnly,
    [switch]$SkipDownload,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ROOT = $PSScriptRoot

# ─── Verificar Administrador ──────────────────────────────────────────────────
function Require-Admin {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]$current
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host ""
        Write-Host "  ERROR: Este script debe ejecutarse como Administrador." -ForegroundColor Red
        Write-Host "  Haz clic derecho en PowerShell → 'Ejecutar como administrador'" -ForegroundColor Yellow
        Write-Host ""
        exit 1
    }
}

Require-Admin

Write-Host ""
Write-Host "  ================================================================" -ForegroundColor Cyan
Write-Host "   MRD TOOL CONTROL — Cloudflare Named Tunnel" -ForegroundColor Cyan
Write-Host "   Sprint 5.4 — v1.9.4-alpha" -ForegroundColor Gray
Write-Host "  ================================================================" -ForegroundColor Cyan
Write-Host ""

# ─── Desinstalación ──────────────────────────────────────────────────────────
if ($UninstallOnly) {
    Write-Host "  Desinstalando servicio cloudflared..." -ForegroundColor Yellow
    try {
        $svc = Get-Service -Name "cloudflared" -ErrorAction SilentlyContinue
        if ($svc) {
            if ($svc.Status -eq "Running") {
                Stop-Service -Name "cloudflared" -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 3
            }
            & cloudflared service uninstall 2>&1 | Out-Null
            Write-Host "  OK: Servicio cloudflared eliminado." -ForegroundColor Green
        } else {
            Write-Host "  INFO: Servicio cloudflared no estaba instalado." -ForegroundColor Gray
        }
    } catch {
        Write-Host "  AVISO: $($_.Exception.Message)" -ForegroundColor Yellow
    }
    Write-Host ""
    exit 0
}

# ─── Buscar o descargar cloudflared ──────────────────────────────────────────
$cfExe = $null
$cfDir = Join-Path $ROOT "tools\cloudflared"

# Buscar en ubicaciones conocidas
$searchPaths = @(
    (Join-Path $cfDir "cloudflared.exe"),
    (Join-Path $ROOT "cloudflared.exe"),
    "C:\cloudflared\cloudflared.exe",
    "C:\Program Files\cloudflared\cloudflared.exe"
)
foreach ($p in $searchPaths) {
    if (Test-Path $p) { $cfExe = $p; break }
}

# Buscar en PATH
if (-not $cfExe) {
    try {
        $found = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
        if ($found) { $cfExe = $found.Source }
    } catch {}
}

if (-not $cfExe -and -not $SkipDownload) {
    Write-Host "  cloudflared.exe no encontrado. Descargando..." -ForegroundColor Yellow

    New-Item -ItemType Directory -Path $cfDir -Force | Out-Null
    $cfExe = Join-Path $cfDir "cloudflared.exe"

    # URL oficial de Cloudflare (siempre HTTPS)
    $downloadUrl = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"

    try {
        Write-Host "  Descargando desde: $downloadUrl" -ForegroundColor Gray
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $webClient = New-Object System.Net.WebClient
        $webClient.Headers.Add("User-Agent", "MRD-TOOL-CONTROL/1.9.4")
        $webClient.DownloadFile($downloadUrl, $cfExe)
        Write-Host "  OK: cloudflared descargado." -ForegroundColor Green
    } catch {
        Write-Host "  ERROR: No se pudo descargar cloudflared." -ForegroundColor Red
        Write-Host "  Descarga manualmente desde: https://github.com/cloudflare/cloudflared/releases" -ForegroundColor Yellow
        Write-Host "  y coloca cloudflared.exe en: $cfDir" -ForegroundColor Yellow
        exit 1
    }
} elseif (-not $cfExe) {
    Write-Host "  ERROR: cloudflared.exe no encontrado y -SkipDownload activo." -ForegroundColor Red
    exit 1
}

# Verificar versión
$version = & $cfExe --version 2>&1
Write-Host "  cloudflared: $version" -ForegroundColor Gray
Write-Host "  Ejecutable:  $cfExe" -ForegroundColor Gray

# ─── Solo configuración ───────────────────────────────────────────────────────
if ($ConfigOnly) {
    Write-Host ""
    Write-Host "  Modo -ConfigOnly: actualiza el túnel existente." -ForegroundColor Yellow
    Write-Host "  Ejecuta manualmente:" -ForegroundColor Gray
    Write-Host "    $cfExe tunnel route dns $TunnelName $Hostname" -ForegroundColor White
    Write-Host ""
    exit 0
}

# ─── Login en Cloudflare (si no hay certificado) ──────────────────────────────
$cfHome = "$env:USERPROFILE\.cloudflared"
$certFile = Join-Path $cfHome "cert.pem"

if (-not (Test-Path $certFile)) {
    Write-Host ""
    Write-Host "  PASO 1: Login en Cloudflare" -ForegroundColor Cyan
    Write-Host "  Se abrirá el navegador para autenticarte con tu cuenta Cloudflare." -ForegroundColor Gray
    Write-Host "  Presiona Enter cuando estés listo..." -ForegroundColor Yellow
    Read-Host

    & $cfExe tunnel login

    if (-not (Test-Path $certFile)) {
        Write-Host "  ERROR: Login no completado. Vuelve a ejecutar el script." -ForegroundColor Red
        exit 1
    }
    Write-Host "  OK: Autenticación completada." -ForegroundColor Green
} else {
    Write-Host "  OK: Certificado Cloudflare encontrado." -ForegroundColor Green
}

# ─── Crear o verificar Named Tunnel ───────────────────────────────────────────
Write-Host ""
Write-Host "  PASO 2: Verificar Named Tunnel '$TunnelName'" -ForegroundColor Cyan

$tunnelsList = & $cfExe tunnel list 2>&1
$tunnelExists = $tunnelsList | Select-String -Pattern $TunnelName -Quiet

if (-not $tunnelExists) {
    Write-Host "  Creando Named Tunnel: $TunnelName" -ForegroundColor Yellow
    & $cfExe tunnel create $TunnelName
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ERROR: No se pudo crear el túnel." -ForegroundColor Red
        exit 1
    }
    Write-Host "  OK: Túnel '$TunnelName' creado." -ForegroundColor Green
} else {
    Write-Host "  OK: Túnel '$TunnelName' ya existe." -ForegroundColor Green
}

# Obtener UUID del túnel
$tunnelInfo = & $cfExe tunnel info $TunnelName 2>&1
$tunnelId = ($tunnelInfo | Select-String -Pattern '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}') |
            ForEach-Object { $_.Matches[0].Value } | Select-Object -First 1

Write-Host "  Tunnel ID: $tunnelId" -ForegroundColor Gray

# Buscar archivo de credenciales
$credFile = ""
if ($tunnelId) {
    $credFile = Join-Path $cfHome "$tunnelId.json"
}

# ─── Generar config.yml ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  PASO 3: Generar configuración del túnel" -ForegroundColor Cyan

$configFile = Join-Path $cfHome "config.yml"
$ingressHostname = if ($Hostname) { $Hostname } else { "localhost" }

$configContent = @"
tunnel: $TunnelName
credentials-file: $credFile

ingress:
  - hostname: $ingressHostname
    service: http://localhost:$Port
  - service: http_status:404
"@

Set-Content -Path $configFile -Value $configContent -Encoding UTF8
Write-Host "  OK: config.yml generado en $configFile" -ForegroundColor Green

# ─── Configurar DNS (si se especificó hostname) ───────────────────────────────
if ($Hostname) {
    Write-Host ""
    Write-Host "  PASO 4: Configurar DNS CNAME para '$Hostname'" -ForegroundColor Cyan
    Write-Host "  (Requiere que '$Hostname' pertenezca a tu zona de Cloudflare)" -ForegroundColor Gray

    & $cfExe tunnel route dns $TunnelName $Hostname
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  OK: DNS CNAME configurado: $Hostname → $TunnelName.cfargotunnel.com" -ForegroundColor Green
    } else {
        Write-Host "  AVISO: DNS no configurado automáticamente." -ForegroundColor Yellow
        Write-Host "  Añade manualmente en Cloudflare Dashboard un CNAME:" -ForegroundColor Gray
        Write-Host "    $Hostname → $TunnelName.cfargotunnel.com (Proxied)" -ForegroundColor White
    }
}

# ─── Instalar como servicio Windows ──────────────────────────────────────────
Write-Host ""
Write-Host "  PASO 5: Instalar cloudflared como servicio Windows" -ForegroundColor Cyan

$existingSvc = Get-Service -Name "cloudflared" -ErrorAction SilentlyContinue
if ($existingSvc) {
    if (-not $Force) {
        Write-Host "  AVISO: El servicio 'cloudflared' ya existe." -ForegroundColor Yellow
        $resp = Read-Host "  ¿Reinstalar? (s/N)"
        if ($resp -notmatch '^[sS]') {
            Write-Host "  Omitiendo reinstalación del servicio." -ForegroundColor Gray
        } else {
            if ($existingSvc.Status -eq "Running") {
                Stop-Service -Name "cloudflared" -Force
                Start-Sleep -Seconds 3
            }
            & $cfExe service uninstall 2>&1 | Out-Null
            Start-Sleep -Seconds 2
            & $cfExe --config $configFile service install
        }
    } else {
        if ($existingSvc.Status -eq "Running") {
            Stop-Service -Name "cloudflared" -Force
            Start-Sleep -Seconds 3
        }
        & $cfExe service uninstall 2>&1 | Out-Null
        Start-Sleep -Seconds 2
        & $cfExe --config $configFile service install
    }
} else {
    & $cfExe --config $configFile service install
}

# Configurar inicio automático y recuperación
Start-Sleep -Seconds 2
try {
    & sc.exe config cloudflared start= auto | Out-Null
    & sc.exe failure cloudflared reset= 86400 actions= restart/30000/restart/30000/restart/30000 | Out-Null
    Write-Host "  OK: Servicio configurado con inicio automático y recuperación." -ForegroundColor Green
} catch {
    Write-Host "  AVISO: No se pudo configurar recuperación automática." -ForegroundColor Yellow
}

# ─── Iniciar servicio ────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  PASO 6: Iniciando servicio cloudflared..." -ForegroundColor Cyan

try {
    Start-Service -Name "cloudflared" -ErrorAction Stop
    Start-Sleep -Seconds 3
    $svc = Get-Service -Name "cloudflared"
    if ($svc.Status -eq "Running") {
        Write-Host "  OK: cloudflared en ejecución." -ForegroundColor Green
    } else {
        Write-Host "  AVISO: El servicio arrancó pero el estado es: $($svc.Status)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  AVISO: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "  Inicia manualmente: Start-Service cloudflared" -ForegroundColor Gray
}

# ─── Guardar configuración en MRD TOOL CONTROL ───────────────────────────────
$mrdConfig = Join-Path $ROOT "data\remote_access_config.json"
if (Test-Path $mrdConfig) {
    try {
        $cfg = Get-Content $mrdConfig -Raw | ConvertFrom-Json
        $pub = if ($Hostname) { "https://$Hostname" } else { "" }
        $cfg | Add-Member -NotePropertyName "cf_tunnel_name" -NotePropertyValue $TunnelName -Force
        $cfg | Add-Member -NotePropertyName "cf_tunnel_id"   -NotePropertyValue $tunnelId -Force
        $cfg | Add-Member -NotePropertyName "cf_hostname"    -NotePropertyValue $ingressHostname -Force
        $cfg | Add-Member -NotePropertyName "cf_public_url"  -NotePropertyValue $pub -Force
        $cfg | Add-Member -NotePropertyName "cf_config_file" -NotePropertyValue $configFile -Force
        $cfg | Add-Member -NotePropertyName "cf_exe_path"    -NotePropertyValue $cfExe -Force
        $cfg | Add-Member -NotePropertyName "cloudflared_service" -NotePropertyValue "cloudflared" -Force
        $cfg | Add-Member -NotePropertyName "cf_force_https" -NotePropertyValue $true -Force
        if ($Hostname) {
            $parts = $Hostname.Split(".")
            if ($parts.Count -ge 2) {
                $cfg | Add-Member -NotePropertyName "cf_domain"    -NotePropertyValue ($parts[-2..(-1)] -join ".") -Force
                $cfg | Add-Member -NotePropertyName "cf_subdomain" -NotePropertyValue ($parts[0..($parts.Count-3)] -join ".") -Force
            }
            $cfg | Add-Member -NotePropertyName "manual_url" -NotePropertyValue $pub -Force
        }
        $cfg | ConvertTo-Json -Depth 5 | Set-Content -Path $mrdConfig -Encoding UTF8
        Write-Host "  OK: Configuración guardada en MRD TOOL CONTROL." -ForegroundColor Green
    } catch {
        Write-Host "  AVISO: No se pudo actualizar la config de MRD TOOL CONTROL." -ForegroundColor Yellow
    }
}

# ─── Resumen ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ================================================================" -ForegroundColor Cyan
Write-Host "   CLOUDFLARE NAMED TUNNEL — INSTALADO" -ForegroundColor Green
Write-Host "  ================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Túnel:       $TunnelName"
if ($tunnelId) { Write-Host "  ID:          $tunnelId" }
if ($Hostname)  {
    Write-Host "  Hostname:    $Hostname"
    Write-Host "  URL pública: https://$Hostname"
}
Write-Host "  Config:      $configFile"
Write-Host "  Servicio:    cloudflared (Windows Service)"
Write-Host ""
Write-Host "  Gestión del servicio:" -ForegroundColor Gray
Write-Host "    Start-Service cloudflared" -ForegroundColor White
Write-Host "    Stop-Service cloudflared" -ForegroundColor White
Write-Host "    Restart-Service cloudflared" -ForegroundColor White
Write-Host ""
Write-Host "  Panel de acceso remoto: http://localhost:8000/acceso-remoto" -ForegroundColor Cyan
Write-Host ""
