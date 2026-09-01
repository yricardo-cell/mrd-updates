<#
.SYNOPSIS
    Genera configuración de seguridad para MRD TOOL CONTROL.
    Sprint 5.2 — Security Hardening

.DESCRIPTION
    Crea config/local.env con:
      - MRD_SECRET_KEY criptográficamente segura (32 bytes / 64 hex)
      - MRD_ADMIN_PASSWORD aleatoria y robusta

    Si config/local.env ya existe NO lo sobrescribe (salvo -Force).

.PARAMETER Force
    Sobrescribe config/local.env existente.

.EXAMPLE
    .\generate_secrets.ps1
    .\generate_secrets.ps1 -Force
#>
param(
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigDir = Join-Path $ScriptDir "config"
$EnvFile   = Join-Path $ConfigDir "local.env"

# ── Crear directorio config/ si no existe ─────────────────────────────────────
if (-not (Test-Path $ConfigDir)) {
    New-Item -ItemType Directory -Path $ConfigDir | Out-Null
    Write-Host "  Creado directorio: config/" -ForegroundColor Cyan
}

# ── Comprobar si ya existe ────────────────────────────────────────────────────
if ((Test-Path $EnvFile) -and -not $Force) {
    Write-Host ""
    Write-Host "  ⚠️  config/local.env ya existe." -ForegroundColor Yellow
    Write-Host "     Usa -Force para sobreescribir:" -ForegroundColor Yellow
    Write-Host "       .\generate_secrets.ps1 -Force" -ForegroundColor White
    Write-Host ""

    # Comprobar si ya tiene MRD_SECRET_KEY
    $existing = Get-Content $EnvFile -Raw
    if ($existing -match "MRD_SECRET_KEY=\w{16,}") {
        Write-Host "  ✅  El archivo ya contiene MRD_SECRET_KEY." -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  MRD_SECRET_KEY no encontrada o vacía. Usa -Force para regenerar." -ForegroundColor Yellow
    }
    exit 0
}

# ── Generar claves ────────────────────────────────────────────────────────────
function New-SecureHex([int]$bytes) {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $buf = New-Object byte[] $bytes
    $rng.GetBytes($buf)
    return ($buf | ForEach-Object { $_.ToString("x2") }) -join ""
}

function New-SecurePassword {
    # Genera una contraseña de 16 caracteres con mayúscula, minúscula, dígito y especial
    $upper   = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    $lower   = "abcdefghjkmnpqrstuvwxyz"
    $digits  = "23456789"
    $special = "!@#%^&*-_=+"

    $all = $upper + $lower + $digits + $special
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $buf = New-Object byte[] 16
    $rng.GetBytes($buf)

    $chars = New-Object char[] 16
    # Asegurar al menos uno de cada tipo
    $chars[0]  = $upper[$buf[0]  % $upper.Length]
    $chars[1]  = $lower[$buf[1]  % $lower.Length]
    $chars[2]  = $digits[$buf[2] % $digits.Length]
    $chars[3]  = $special[$buf[3] % $special.Length]
    for ($i = 4; $i -lt 16; $i++) {
        $chars[$i] = $all[$buf[$i] % $all.Length]
    }

    # Mezclar (Fisher-Yates con RNG)
    $rng.GetBytes($buf)
    for ($i = 15; $i -gt 0; $i--) {
        $j = $buf[$i] % ($i + 1)
        $tmp = $chars[$i]; $chars[$i] = $chars[$j]; $chars[$j] = $tmp
    }

    return -join $chars
}

Write-Host ""
Write-Host "  🔐  Generando configuración de seguridad MRD TOOL CONTROL" -ForegroundColor Cyan
Write-Host ""

$secretKey   = New-SecureHex 32
$adminPwd    = New-SecurePassword

# ── Escribir config/local.env ─────────────────────────────────────────────────
$content = @"
# MRD TOOL CONTROL — Configuración de seguridad
# Generado por generate_secrets.ps1 el $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
# MANTENER ESTE ARCHIVO PRIVADO — NO SUBIR AL REPOSITORIO

MRD_ENV=development
MRD_SECRET_KEY=$secretKey
MRD_ADMIN_PASSWORD=$adminPwd
MRD_PASSWORD_MIN_LENGTH=10
MRD_MAX_UPLOAD_MB=10
MRD_SESSION_MAX_AGE=480
MRD_HOST=127.0.0.1
MRD_PORT=8000
MRD_LOG_LEVEL=info
"@

$content | Out-File -FilePath $EnvFile -Encoding UTF8 -NoNewline

# ── Permisos: solo el usuario actual puede leer (solo Windows NTFS) ───────────
try {
    $acl = Get-Acl $EnvFile
    $acl.SetAccessRuleProtection($true, $false)
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
        "FullControl",
        "Allow"
    )
    $acl.AddAccessRule($rule)
    Set-Acl $EnvFile $acl
} catch {
    # No crítico si falla en algunos entornos
}

# ── Resumen ───────────────────────────────────────────────────────────────────
Write-Host "  ✅  config/local.env creado correctamente." -ForegroundColor Green
Write-Host ""
Write-Host "  📋  Credenciales de primer arranque:" -ForegroundColor White
Write-Host "       Usuario:     admin" -ForegroundColor White
Write-Host "       Contraseña:  $adminPwd" -ForegroundColor Yellow
Write-Host ""
Write-Host "  ⚠️   IMPORTANTE:" -ForegroundColor Yellow
Write-Host "       1. Guarda esta contraseña en un lugar seguro." -ForegroundColor White
Write-Host "       2. Cambia la contraseña en el primer inicio de sesión." -ForegroundColor White
Write-Host "       3. NUNCA compartas ni subas config/local.env." -ForegroundColor White
Write-Host ""
Write-Host "  ▶   Ahora puedes arrancar la aplicación:" -ForegroundColor Cyan
Write-Host "       .\INICIAR_MRD.bat" -ForegroundColor White
Write-Host ""
