# MRD TOOL - Publicar actualizacion via GitHub (subida automatica)
# Funciona desde cualquier PC - usa rutas relativas al script

param(
    [string]$Version = "",
    [string]$Descripcion = "",
    [switch]$NoPause
)

$host.UI.RawUI.WindowTitle = "MRD TOOL - Publicar actualizacion"

$raiz   = $PSScriptRoot
$parent = Split-Path $raiz -Parent
$OWNER  = "yricardo-cell"
$REPO   = "mrd-updates"

function Pausar($msg) {
    Write-Host ""
    Write-Host "  $msg" -ForegroundColor Red
    Write-Host ""
    if (-not $NoPause) { Read-Host "  Pulsa Enter para cerrar" }
    exit 1
}

function Write-Utf8NoBom($Path, $Text) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, $Text, $utf8NoBom)
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
    # Windows PowerShell 5 puede enviar los strings como ANSI y romper el JSON
    # cuando el mensaje contiene acentos. Forzar bytes UTF-8 evita el HTTP 400.
    $jsonBytes = [Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Compress))
    $r = Invoke-RestMethod -Uri $url -Method Put -Headers $h `
         -Body $jsonBytes -ContentType "application/json; charset=utf-8"
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
    $localJson = Get-Content "$raiz\version.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    $versionActual = $localJson.version_actual
} catch { }
Write-Host "  Version actual: $versionActual" -ForegroundColor Yellow
Write-Host ""

$versionNueva = if ($Version) { $Version } else { Read-Host "  Nueva version (ej: 2.1.2)" }
$versionNueva = $versionNueva.Trim()
if (-not $versionNueva) { Pausar "ERROR: la version no puede estar vacia." }

Write-Host ""
$cambiosDesc = if ($Descripcion) {
    $Descripcion.Trim()
} else {
    (Read-Host "  Descripcion del cambio (Enter = Mejoras y correcciones)").Trim()
}
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
    "/XD", "venv", "__pycache__", ".git", ".claude", ".agents", "logs", "temp",
           "cache", "releases", "backups", "updates", ".mypy_cache",
           ".pytest_cache", "para_subir_github", "data", "uploads",
           "private_config", "graphify-out", "repair_stage", ".ruff_cache",
    "/XF", "*.log", "*.bak", "*.bak_edit", "desktop.ini", "*.pyc",
           "*.exe", "*.db", "*.db-wal", "*.db-shm",
           "local.env", "*.token", "vapid_keys.json", ".service_restart",
           ".recovery_history.json", "secret.key", "users.json", "*.pem", "cpu_excluir.txt",
           # Estado local de la instalacion (2.7.76): no viaja en el paquete
           "etiquetas.json", "ensayo_restauracion.json", "backup_externo.json",
           "resumen_diario_estado.json", "limpieza_estado.json", "ultima_version_comprobada.json",
           "consumo_obras_estado.json", "errores_avisados.json", "drive_estado.json", "vigilante_estado.json",
    "/NFL", "/NDL", "/NJH", "/NJS"
)
& robocopy @robocopyArgs | Out-Null

# Verificacion de seguridad: ningun *.token (ni otro secreto conocido) debe
# llegar al paquete publico. robocopy copia del disco, no de git, asi que
# .gitignore no protege aqui - esta es la unica red de seguridad real.
$secretosEncontrados = Get-ChildItem -Path $destino -Recurse -File -Include "*.token","local.env","vapid_keys.json","secret.key","users.json","*.pem",".recovery_history.json" -ErrorAction SilentlyContinue
# Segunda red: ningun fichero que git ignore (secretos autogenerados, datos
# locales) debe viajar en el paquete publico aunque nadie lo haya listado.
# Se pasan como argumentos por lotes: por stdin, Windows anade CR y git no
# reconoce las rutas.
$ignorados = @()
try {
    $relativos = @(Get-ChildItem -Path $destino -Recurse -File | ForEach-Object { $_.FullName.Substring($destino.Length + 1).Replace([char]92, '/') })
    for ($i = 0; $i -lt $relativos.Count; $i += 100) {
        $lote = $relativos[$i..([Math]::Min($i + 99, $relativos.Count - 1))]
        $ignorados += @(& git -C $raiz check-ignore --no-index -- @lote 2>$null | Where-Object { $_ -and ($_ -notlike '*.gitkeep') })
    }
} catch { $ignorados = @() }
if ($ignorados.Count -gt 0) {
    $lista = $ignorados -join "`n    "
    Pausar "ERROR: el paquete contiene ficheros ignorados por git (posibles secretos), publicacion abortada:`n    $lista"
}
if ($secretosEncontrados) {
    $lista = ($secretosEncontrados | ForEach-Object { $_.FullName.Substring($destino.Length) }) -join "`n    "
    Pausar "ERROR: se encontraron archivos secretos en el paquete, publicacion abortada:`n    $lista"
}

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
Write-Utf8NoBom $versionJsonPath ($obj | ConvertTo-Json -Depth 3)
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
    if ($versionNueva -ne $localJson.version_actual) {
        $localJson.version_anterior = $localJson.version_actual
    }
    $localJson.version_actual   = $versionNueva
    $localJson.fecha            = (Get-Date -Format "yyyy-MM-dd")
    Write-Utf8NoBom "$raiz\version.json" ($localJson | ConvertTo-Json -Depth 8)
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
if (-not $NoPause) { Read-Host "  Pulsa Enter para cerrar" }
