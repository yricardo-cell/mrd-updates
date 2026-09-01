# MRD TOOL - Publicar actualizacion via GitHub (subida automatica)
# Funciona desde cualquier PC - usa rutas relativas al script

$host.UI.RawUI.WindowTitle = "MRD TOOL - Publicar actualizacion"

$raiz   = $PSScriptRoot
$parent = Split-Path $raiz -Parent
$OWNER  = "yricardo-cell"
$REPO   = "mrd-updates"

function Pausar($msg) {
    Write-Host ""
    Write-Host "  $msg" -ForegroundColor Red
    Write-Host ""
    Read-Host "  Pulsa Enter para cerrar"
    exit 1
}

function Get-GitHubToken {
    $tokenFile = "$raiz\config\github.token"
    if (Test-Path $tokenFile) {
        $token = (Get-Content $tokenFile -Raw).Trim()
        if ($token) { return $token }
    }
    Write-Host ""
    Write-Host "  TOKEN DE GITHUB" -ForegroundColor Yellow
    Write-Host "  Ve a: github.com/settings/tokens -> Generate new token (classic)" -ForegroundColor Gray
    Write-Host "  Permisos necesarios: repo (contents write)" -ForegroundColor Gray
    Write-Host ""
    $token = (Read-Host "  Pega el token aqui").Trim()
    if (-not $token) { return $null }
    $guardar = Read-Host "  Guardar token para proximas veces? (s/n)"
    if ($guardar -eq "s") {
        $token | Set-Content $tokenFile -Encoding UTF8
        Write-Host "  Token guardado en config\github.token" -ForegroundColor Gray
    }
    return $token
}

function Get-GitHubSHA($token, $nombre) {
    try {
        $url = "https://api.github.com/repos/$OWNER/$REPO/contents/$nombre"
        $h = @{ Authorization = "token $token"; "User-Agent" = "MRD-TOOL" }
        $r = Invoke-RestMethod -Uri $url -Headers $h -Method Get
        return $r.sha
    } catch { return $null }
}

function Subir-Archivo($token, $rutaLocal, $nombreRemoto, $mensajeCommit) {
    $contenido = [Convert]::ToBase64String([IO.File]::ReadAllBytes($rutaLocal))
    $sha = Get-GitHubSHA $token $nombreRemoto
    $body = [ordered]@{ message = $mensajeCommit; content = $contenido }
    if ($sha) { $body.sha = $sha }
    $url = "https://api.github.com/repos/$OWNER/$REPO/contents/$nombreRemoto"
    $h = @{
        Authorization = "token $token"
        "User-Agent"  = "MRD-TOOL"
        Accept        = "application/vnd.github.v3+json"
    }
    $r = Invoke-RestMethod -Uri $url -Method Put -Headers $h `
         -Body ($body | ConvertTo-Json -Compress) -ContentType "application/json"
    return $r.content.name
}

try {

Set-Location $raiz

Write-Host ""
Write-Host "  =====================================================" -ForegroundColor Cyan
Write-Host "   MRD TOOL - Publicar actualizacion via GitHub" -ForegroundColor Cyan
Write-Host "  =====================================================" -ForegroundColor Cyan
Write-Host "  Carpeta: $raiz" -ForegroundColor DarkGray
Write-Host ""

$versionActual = "desconocida"
$localJson = $null
try {
    $localJson = Get-Content "$raiz\version.json" -Raw | ConvertFrom-Json
    $versionActual = $localJson.version_actual
} catch { }
Write-Host "  Version actual: $versionActual" -ForegroundColor Yellow
Write-Host ""

$versionNueva = Read-Host "  Nueva version (ej: 2.1.2)"
$versionNueva = $versionNueva.Trim()
if (-not $versionNueva) { Pausar "ERROR: la version no puede estar vacia." }

Write-Host ""
$cambiosDesc = (Read-Host "  Descripcion del cambio (Enter = Mejoras y correcciones)").Trim()
if (-not $cambiosDesc) { $cambiosDesc = "Mejoras y correcciones" }

# 1. Empaquetar
Write-Host ""
Write-Host "  [1/6] Empaquetando..." -ForegroundColor Green

$zipNombre = "mrd_v$versionNueva.zip"
$zipTmp    = "$parent\MRD_Tool_Control_INSTALABLE.zip"
$destino   = "$parent\MRD_PAQUETE"

if (Test-Path $destino) { Remove-Item $destino -Recurse -Force }
if (Test-Path $zipTmp)  { Remove-Item $zipTmp  -Force }

$robocopyArgs = @(
    $raiz, $destino, "/E",
    "/XD", "venv", "__pycache__", ".git", "logs", "temp",
           "cache", "releases", "backups", "updates", ".mypy_cache",
           ".pytest_cache", "para_subir_github", "data", "uploads",
    "/XF", "*.log", "*.bak", "*.bak_edit", "desktop.ini", "*.pyc",
           "*.exe", "*.db", "*.db-wal", "*.db-shm",
           "local.env", "github.token", ".service_restart",
    "/NFL", "/NDL", "/NJH", "/NJS"
)
& robocopy @robocopyArgs | Out-Null

Compress-Archive -Path "$destino\*" -DestinationPath $zipTmp -Force

if (-not (Test-Path $zipTmp)) { Pausar "ERROR: no se pudo crear el ZIP." }
Remove-Item $destino -Recurse -Force

$sizeKB = [math]::Round((Get-Item $zipTmp).Length / 1KB)
Write-Host "  ZIP OK: $sizeKB KB" -ForegroundColor Gray

# 2. SHA256
Write-Host ""
Write-Host "  [2/6] Calculando SHA256..." -ForegroundColor Green
$sha256 = (Get-FileHash $zipTmp -Algorithm SHA256).Hash.ToLower()
Write-Host "  $sha256" -ForegroundColor Gray

# 3. Carpeta de subida
Write-Host ""
Write-Host "  [3/6] Preparando archivos..." -ForegroundColor Green
$carpeta = "$parent\para_subir_github"
if (Test-Path $carpeta) { Remove-Item $carpeta -Recurse -Force }
New-Item -ItemType Directory -Path $carpeta | Out-Null
Copy-Item $zipTmp "$carpeta\$zipNombre"
Remove-Item $zipTmp -Force

# 4. version.json
Write-Host ""
Write-Host "  [4/6] Generando version.json..." -ForegroundColor Green
$downloadUrl = "https://raw.githubusercontent.com/$OWNER/$REPO/main/$zipNombre"
$obj = [ordered]@{
    version_actual = $versionNueva
    nombre         = "MRD TOOL CONTROL -- $cambiosDesc"
    fecha          = (Get-Date -Format "yyyy-MM-dd")
    cambios        = @($cambiosDesc)
    notas          = "Instala desde Configuracion > Actualizaciones."
    download_url   = $downloadUrl
    sha256         = $sha256
}
$versionJsonPath = "$carpeta\version.json"
$obj | ConvertTo-Json -Depth 3 | Set-Content $versionJsonPath -Encoding UTF8
Write-Host "  version.json OK" -ForegroundColor Gray

# 5. Subir a GitHub
Write-Host ""
Write-Host "  [5/6] Subiendo a GitHub..." -ForegroundColor Green

$token = Get-GitHubToken
if (-not $token) { Pausar "ERROR: sin token no se puede subir a GitHub." }

$commitMsg = "Release v$versionNueva - $cambiosDesc"

Write-Host "  Subiendo $zipNombre ..." -ForegroundColor Gray
Subir-Archivo $token "$carpeta\$zipNombre" $zipNombre $commitMsg | Out-Null
Write-Host "  Subiendo version.json ..." -ForegroundColor Gray
Subir-Archivo $token $versionJsonPath "version.json" $commitMsg | Out-Null
Write-Host "  GitHub OK" -ForegroundColor Green

# 6. Actualizar version local
Write-Host ""
Write-Host "  [6/6] Actualizando version local..." -ForegroundColor Green
if ($localJson) {
    $localJson.version_anterior = $localJson.version_actual
    $localJson.version_actual   = $versionNueva
    $localJson.fecha            = (Get-Date -Format "yyyy-MM-dd")
    $localJson | ConvertTo-Json -Depth 5 | Set-Content "$raiz\version.json" -Encoding UTF8
}
Write-Host "  version.json local -> $versionNueva" -ForegroundColor Gray

Write-Host ""
Write-Host "  =====================================================" -ForegroundColor Cyan
Write-Host "   LISTO - v$versionNueva publicada en GitHub" -ForegroundColor Cyan
Write-Host "  =====================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  En app.iasmrd.com:" -ForegroundColor White
Write-Host "    Configuracion > Actualizaciones > Comprobar > Instalar" -ForegroundColor Gray
Write-Host ""

} catch {
    Write-Host ""
    Write-Host "  ===== ERROR =====" -ForegroundColor Red
    Write-Host "  $_" -ForegroundColor Red
    Write-Host "  =================" -ForegroundColor Red
}

Write-Host ""
Read-Host "  Pulsa Enter para cerrar"
