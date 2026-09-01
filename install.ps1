# MRD TOOL CONTROL - Instalador
# Uso: .\install.ps1 [-Puerto 8000] [-Host "0.0.0.0"] [-InstalarServicio]
param(
    [int]$Puerto = 8000,
    [string]$HostAddr = "0.0.0.0",
    [switch]$InstalarServicio
)

$ErrorActionPreference = "Stop"
$ROOT = $PSScriptRoot

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   MRD TOOL CONTROL - Instalador v1.0.0   " -ForegroundColor Cyan
Write-Host "   MRD Estructuras                         " -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Verificar Python 3.10+
Write-Host "[1/7] Verificando Python..." -ForegroundColor Yellow
try {
    $pyVer = python --version 2>&1
    if ($pyVer -match "Python (\d+)\.(\d+)") {
        $maj = [int]$Matches[1]; $min = [int]$Matches[2]
        if ($maj -lt 3 -or ($maj -eq 3 -and $min -lt 10)) {
            Write-Host "ERROR: Se requiere Python 3.10 o superior. Version actual: $pyVer" -ForegroundColor Red
            exit 1
        }
        Write-Host "   OK: $pyVer" -ForegroundColor Green
    }
} catch {
    Write-Host "ERROR: Python no encontrado. Instala Python 3.10+ desde python.org" -ForegroundColor Red
    exit 1
}

# Crear entorno virtual
Write-Host "[2/7] Creando entorno virtual..." -ForegroundColor Yellow
$venvPath = Join-Path $ROOT "venv"
if (!(Test-Path $venvPath)) {
    python -m venv $venvPath
}
Write-Host "   OK: $venvPath" -ForegroundColor Green

# Instalar dependencias
Write-Host "[3/7] Instalando dependencias..." -ForegroundColor Yellow
$pip = Join-Path $venvPath "Scripts\pip.exe"
& $pip install --upgrade pip -q
& $pip install -r (Join-Path $ROOT "requirements.txt") -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR al instalar dependencias" -ForegroundColor Red
    exit 1
}
Write-Host "   OK: todas las dependencias instaladas" -ForegroundColor Green

# Crear carpetas
Write-Host "[4/7] Creando estructura de carpetas..." -ForegroundColor Yellow
$folders = @("data","backups","exports","logs","releases","migrations","uploads","static\css","static\js","templates","config","services")
foreach ($f in $folders) {
    $p = Join-Path $ROOT $f
    if (!(Test-Path $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}
Write-Host "   OK" -ForegroundColor Green

# Inicializar base de datos
Write-Host "[5/7] Inicializando base de datos..." -ForegroundColor Yellow
$python = Join-Path $venvPath "Scripts\python.exe"
$initScript = @"
import sys, os
sys.path.insert(0, r'$ROOT')
os.chdir(r'$ROOT')
from database import engine, Base
from models import *
Base.metadata.create_all(bind=engine)
from database import SessionLocal
from models import Usuario, Almacen
from auth import hash_password
db = SessionLocal()
if not db.query(Usuario).filter_by(username='admin').first():
    db.add(Usuario(username='admin', password_hash=hash_password('mrd2024'), nombre='Administrador', rol='admin', activo=True))
if not db.query(Almacen).first():
    db.add(Almacen(nombre='Almacen Principal', descripcion='Almacen por defecto', activo=True))
db.commit()
db.close()
print('Base de datos lista')
"@
$initScript | & $python -
Write-Host "   OK: base de datos inicializada" -ForegroundColor Green

# Crear archivo de inicio rápido
Write-Host "[6/7] Creando accesos directos..." -ForegroundColor Yellow

$batContent = "@echo off`ntitle MRD TOOL CONTROL`ncd /d `"$ROOT`"`necho Iniciando MRD TOOL CONTROL...`ncall venv\Scripts\activate`nuvicorn main:app --host $HostAddr --port $Puerto --reload`npause"
$batContent | Out-File -FilePath (Join-Path $ROOT "INICIAR_MRD.bat") -Encoding ASCII

# run.ps1
$runContent = @"
param([int]`$Puerto=$Puerto,[string]`$HostAddr='$HostAddr',[switch]`$Produccion,[int]`$Workers=2)
`$ROOT = `$PSScriptRoot
`$python = Join-Path `$ROOT 'venv\Scripts\python.exe'
`$uvicorn = Join-Path `$ROOT 'venv\Scripts\uvicorn.exe'
Set-Location `$ROOT
if (`$Produccion) {
    `$logFile = Join-Path `$ROOT "logs\app_`$(Get-Date -f 'yyyyMMdd_HHmm').log"
    Write-Host 'Modo produccion - log: ' `$logFile -ForegroundColor Cyan
    & `$uvicorn main:app --host `$HostAddr --port `$Puerto --workers `$Workers --log-level warning 2>&1 | Tee-Object -FilePath `$logFile
} else {
    Write-Host "Iniciando en modo desarrollo en http://localhost:`$Puerto" -ForegroundColor Green
    & `$uvicorn main:app --host `$HostAddr --port `$Puerto --reload
}
"@
$runContent | Out-File -FilePath (Join-Path $ROOT "run.ps1") -Encoding UTF8

# Acceso directo en escritorio
try {
    $wsh = New-Object -ComObject WScript.Shell
    $shortcut = $wsh.CreateShortcut("$env:USERPROFILE\Desktop\MRD Tool Control.lnk")
    $shortcut.TargetPath = "powershell.exe"
    $shortcut.Arguments = "-ExecutionPolicy Bypass -File `"$(Join-Path $ROOT 'run.ps1')`""
    $shortcut.WorkingDirectory = $ROOT
    $shortcut.IconLocation = "powershell.exe"
    $shortcut.Description = "MRD Tool Control"
    $shortcut.Save()
    Write-Host "   OK: acceso directo creado en escritorio" -ForegroundColor Green
} catch {
    Write-Host "   (acceso directo no creado: $($_.Exception.Message))" -ForegroundColor Yellow
}

# Tarea programada backup diario
try {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -Command `"cd '$ROOT'; & 'venv\Scripts\python.exe' -c 'from backups import crear_backup; crear_backup()'`""
    $trigger = New-ScheduledTaskTrigger -Daily -At "03:00"
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName "MRDToolControl-Backup" -Action $action -Trigger $trigger -Settings $settings -Description "Backup diario MRD Tool Control" -Force | Out-Null
    Write-Host "   OK: backup diario programado a las 03:00" -ForegroundColor Green
} catch {
    Write-Host "   (tarea programada no creada: requiere permisos de administrador)" -ForegroundColor Yellow
}

# Servicio Windows (opcional)
if ($InstalarServicio) {
    Write-Host "[7/7] Instalando servicio Windows..." -ForegroundColor Yellow
    $nssm = Join-Path $ROOT "services\nssm.exe"
    if (Test-Path $nssm) {
        & $nssm install MRDToolControl (Join-Path $venvPath "Scripts\uvicorn.exe")
        & $nssm set MRDToolControl AppParameters "main:app --host $HostAddr --port $Puerto --workers 2"
        & $nssm set MRDToolControl AppDirectory $ROOT
        & $nssm set MRDToolControl Start SERVICE_AUTO_START
        & $nssm set MRDToolControl AppStdout (Join-Path $ROOT "logs\service_stdout.log")
        & $nssm set MRDToolControl AppStderr (Join-Path $ROOT "logs\service_stderr.log")
        Write-Host "   OK: servicio MRDToolControl instalado" -ForegroundColor Green
    } else {
        Write-Host "   AVISO: nssm.exe no encontrado en services\. Servicio no instalado." -ForegroundColor Yellow
    }
} else {
    Write-Host "[7/7] (Servicio Windows omitido - usa -InstalarServicio para activarlo)" -ForegroundColor Gray
}

# Resumen final
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "   INSTALACION COMPLETADA" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  URL local:    http://localhost:$Puerto" -ForegroundColor White
Write-Host "  URL LAN:      http://<IP-PC>:$Puerto" -ForegroundColor White
Write-Host ""
Write-Host "  Usuario:      admin" -ForegroundColor Yellow
Write-Host "  Contrasena:   mrd2024" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Para iniciar: doble clic en INICIAR_MRD.bat" -ForegroundColor Cyan
Write-Host "  O ejecutar:   .\run.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "  CAMBIA LA CONTRASENA al primer acceso!" -ForegroundColor Red
Write-Host ""
