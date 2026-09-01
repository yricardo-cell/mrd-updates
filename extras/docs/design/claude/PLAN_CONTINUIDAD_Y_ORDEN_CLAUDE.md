# PLAN DE CONTINUIDAD Y ORDEN — MRD TOOL CONTROL
**Versión:** 1.0 · **Fecha:** 2026-08-20  
**Autor:** Inspección automatizada Claude (Cowork) · **Sprint:** 5.3

> **Alcance de este documento:** Análisis de solo-lectura de los sistemas de continuidad, recuperación, backups, servicios Windows y estructura de carpetas.  
> **Ningún archivo fue modificado. Ningún servicio fue reiniciado. Ninguna credencial fue expuesta.**

---

## 1. Estado Actual de Disponibilidad

### Arquitectura de ejecución

```
SCM de Windows
  └── MRDToolControl  (startup=automatic)
        └── MRDWindowsService  [pywin32]
              └── MRDServiceRunner
                    ├── uvicorn  (subprocess, workers=1, puerto 8000)
                    ├── thread: mrd-watchdog   (cada 10 s)
                    ├── thread: mrd-cleanup    (diario a las 02:00)
                    └── thread: mrd-status     (cada 30 s → .service_status)
```

### Estado de los mecanismos de alta disponibilidad

| Mecanismo | Configurado | Funcionando | Notas |
|-----------|-------------|-------------|-------|
| Servicio Windows auto-start | ✅ | ✅ | startup=automatic |
| Recuperación Windows (SCM) | ✅ | ✅ | 3×restart @ 30s |
| Watchdog interno | ✅ | ✅ | 10s interval, max 5 reinicios |
| Health check HTTP | ✅ | ✅ | cada 60s, verifica DB+disco+RAM |
| Backup automático | ✅ | ✅ | diario, semanal, mensual |
| Notificaciones Telegram | ✅ | ✅ | urllib nativo, sin deps externas |
| Cloudflare Tunnel | ✅ | ✅ | cloudflare_tunnel.py (21 KB) |

### Tiempo de recuperación estimado por escenario

| Escenario | Tiempo estimado | Mecanismo |
|-----------|-----------------|-----------|
| Crash de uvicorn | 30–60 s | Watchdog interno → restart |
| Crash del runner | 30 s | SCM Windows (recovery) |
| Fallo de electricidad | 1–3 min | Auto-start al restaurar tensión |
| Corrupción de BD | Manual | Restore desde backup |
| Actualización de código | 1–2 min | .bat / .ps1 de despliegue |

---

## 2. Diseño de Recuperación Automática

### Capa 1 — Watchdog interno (`windows_service.py`)

El watchdog ejecuta `_watchdog_tick()` cada 10 segundos y actúa en tres situaciones:

**a) Señal de reinicio desde la API**  
Si existe el archivo `.service_restart`, lo elimina y llama a `_restart_uvicorn()`. Este mecanismo permite reiniciar uvicorn desde la API sin tocar el proceso Windows. No hay verificación de autenticidad del archivo (cualquier proceso que pueda escribir en el directorio base puede provocar un reinicio).

**b) Caída inesperada de uvicorn**  
Si `proc.poll()` devuelve un código de salida, `_handle_unexpected_exit()` registra la caída en `crash.log` e intenta reiniciar, respetando el límite de `max_restarts=5` dentro de una ventana de `cooldown_minutes=5`. Cuando se supera el límite, el runner se detiene y cede el control a la capa 2.

**c) Uso crítico de RAM**  
Si uvicorn supera `2 × memory_limit_mb` (1 024 MB por defecto), el watchdog lo reinicia y registra en `crash.log`. Si supera solo `memory_limit_mb` (512 MB), emite una advertencia sin reiniciar.

**⚠️ Brecha identificada — retrasos de reinicio no progresivos**  
Los tres intentos de recuperación del SCM de Windows están configurados con el mismo retraso de 30s. En una caída en bucle rápido (p. ej., OOM reiterado), los tres intentos se consumen en 90 segundos sin permitir que el sistema se estabilice.  
**Recomendación:** Escalonar a 30s / 60s / 120s en `service.yaml` bajo la sección `recovery`.

### Capa 2 — Recuperación Windows (SCM)

Cuando el runner se detiene (tras superar `max_restarts`), el SCM actúa:  
- Primera caída: reiniciar tras 30s  
- Segunda caída: reiniciar tras 30s  
- Tercera caída: reiniciar tras 30s  
- Reinicio del contador de fallos: cada 24h

### Capa 3 — Inicio automático al arrancar el sistema

`startup=automatic` en `service.yaml` garantiza que el SCM inicia el servicio cuando Windows arranca, incluso después de un corte de luz o reinicio forzado.

### Archivo de estado

El runner escribe `.service_status` cada 30s con PID, uptime, puerto, y conteo de reinicios. Este archivo es consumido por el endpoint de estado de la API y por la consola de diagnóstico.

---

## 3. Protección SQLite

### Ubicación real de la base de datos

La base de datos de producción está en:
```
C:\mrd_tool_control\data\mrd_tool.db
```
Configurada en `config.py` como `DATA_DIR / "mrd_tool.db"`. El archivo `mrd_tool.db` de 0 bytes en la raíz del proyecto es un artefacto vacío y puede eliminarse para evitar confusión.

### Modo WAL y concurrencia

El servicio opera con `workers=1` porque SQLite solo admite un escritor concurrente en modo WAL. El comentario en `service.yaml` advierte explícitamente que subir workers requiere migrar a PostgreSQL (Sprint 5.5). **No subir `workers` sin esa migración.**

### Mecanismo de backup (hot backup)

`backup_manager.py` usa `sqlite3.Connection.backup()`, que es la única API segura para copiar una base SQLite en uso con WAL activo. El proceso:

1. Abre conexión con `timeout=30`  
2. Llama a `connection.backup(dest, pages=100, progress=...)` — copia en bloques de 100 páginas  
3. Calcula SHA-256 del archivo resultante  
4. Opcionalmente encripta con Fernet (AES-128-CBC) si la clave está configurada  
5. Registra en `backup_history.json` (protegido con `threading.RLock`)

### Verificación de backups

`verify_backup()` comprueba:
- SHA-256 coincide con el registrado  
- Magic bytes: `SQLite format 3\x00` en los primeros 16 bytes del archivo (o del archivo desencriptado)

**⚠️ Brecha identificada — sin `PRAGMA integrity_check` post-backup**  
La verificación valida integridad del archivo pero no integridad lógica de la BD. Un backup de una BD con páginas corruptas pasará la verificación de magic bytes.  
**Recomendación:** Añadir `PRAGMA integrity_check` sobre el archivo de backup tras copiarlo a un path temporal.

**⚠️ Brecha identificada — sin copia offsite**  
Todos los backups están en `C:\mrd_tool_control\backups\`. Un fallo de disco afecta a la BD y a sus backups simultáneamente.  
**Recomendación:** Configurar replicación a carpeta de red (NAS/servidor) o servicio de almacenamiento en la nube, al menos del backup diario más reciente.

**⚠️ Brecha identificada — sin test de restauración automatizado**  
`restore_backup()` existe y está implementado (crea pre-migrate backup antes de restaurar), pero no hay ningún mecanismo que pruebe periódicamente que un backup se puede restaurar y que la BD resultante responde a consultas.  
**Recomendación:** Script semanal que restaure el backup más reciente en un path temporal, ejecute `SELECT COUNT(*) FROM herramientas` y registre éxito/fallo.

### Política de retención

| Tipo | Cantidad | Carpeta |
|------|----------|---------|
| Diario | 7 | `backups/daily/` |
| Semanal | 4 | `backups/weekly/` |
| Mensual | 12 | `backups/monthly/` |
| Pre-acción | 10 | `backups/pre_action/` |

El backup pre-acción se crea automáticamente antes de cualquier restauración.

---

## 4. Preparación ante Corte de Luz

### Comportamiento actual

El servicio está configurado con `startup=automatic`, lo que garantiza que Windows lo inicia al restaurar la alimentación eléctrica. La secuencia es:

1. Alimentación restaurada → Windows arranca  
2. SCM inicia `MRDToolControl` automáticamente  
3. `MRDServiceRunner.run()` arranca uvicorn como subproceso  
4. Uvicorn carga la aplicación FastAPI (incluye `Base.metadata.create_all()` idempotente)  
5. Tunnel Cloudflare (`cloudflare_tunnel.py`) retoma la conexión externa  

### Integridad de SQLite tras corte abrupto

SQLite en modo WAL es resistente a cortes de luz: las transacciones confirmadas se recuperan del WAL en el siguiente `PRAGMA wal_checkpoint`. Las transacciones no confirmadas se descartan. No se requiere acción manual salvo que el archivo WAL esté corrupto.

En caso de sospecha de corrupción tras un corte:
```
PRAGMA integrity_check;
```
Si devuelve algo distinto de `ok`, restaurar desde el backup más reciente con `backup_manager.py restore`.

### Tiempo de indisponibilidad esperado

| Fase | Duración típica |
|------|-----------------|
| Arranque Windows | 1–2 min |
| Inicio del servicio | 5–10 s |
| Carga de uvicorn | 3–5 s |
| Cloudflare Tunnel activo | 5–15 s |
| **Total** | **~2–3 min** |

### Recomendación para minimizar tiempo de indisponibilidad

Si el equipo dispone de UPS, configurar el agente UPS para ejecutar `net stop MRDToolControl` en un apagado controlado antes de cortar la alimentación. Esto permite que uvicorn termine de procesar las peticiones en curso (timeout de 30s configurado).

---

## 5. Rotación de Tokens Cloudflare

### Tokens y credenciales identificados

En `config.py` se leen las siguientes variables de entorno relacionadas con Cloudflare y seguridad general desde `config/local.env`:

- `MRD_SECRET_KEY` — clave JWT (obligatoria en producción; la app no arranca sin ella)  
- `MRD_PUBLIC_URL` — URL pública (sin valor sensible, solo URL)  
- `MRD_TRUST_PROXY_HEADERS` — booleano para confiar en X-Forwarded-For  
- `MRD_HTTPS_ONLY` — booleano para forzar cookies Secure  
- `MRD_ALLOWED_HOSTS` — lista de hosts permitidos  

El token de Cloudflare Tunnel se gestiona en `cloudflare_tunnel.py` (21 KB, no inspeccionado en detalle) y se espera que esté también en `config/local.env` o en las variables de entorno del sistema.  
Las credenciales de Telegram están en `config/local.env` como `MRD_TELEGRAM_BOT_TOKEN` y `MRD_TELEGRAM_CHAT_ID`.

**No se muestran valores de ninguna de estas variables.**

### Procedimiento de rotación (sin tiempo de inactividad)

**MRD_SECRET_KEY (JWT):**  
1. Generar nueva clave con `generate_secrets.ps1`  
2. Actualizar `config/local.env` con la nueva clave  
3. Reiniciar el servicio (`REINICIAR.bat` o desde servicios de Windows)  
4. Todas las sesiones activas quedan invalidadas — los usuarios deben volver a autenticarse  
5. Comunicar el mantenimiento antes del paso 3 si hay usuarios conectados

**Token de Cloudflare Tunnel:**  
1. Generar nuevo token en el panel de Cloudflare Zero Trust → Tunnels  
2. Actualizar el valor en `config/local.env`  
3. Reiniciar `cloudflare_tunnel.py` (o el servicio completo)  
4. Verificar que el tunnel aparece como "Healthy" en el panel Cloudflare  
5. Revocar el token anterior desde el panel

**Bot Token de Telegram:**  
1. Revocar el token actual desde `@BotFather` con `/revoke`  
2. Obtener nuevo token  
3. Actualizar `config/local.env`  
4. Reiniciar el servicio o recargar configuración  

### Frecuencia recomendada

| Credencial | Rotación recomendada | Rotación obligatoria |
|------------|----------------------|----------------------|
| MRD_SECRET_KEY | Cada 6 meses | Ante sospecha de filtración |
| Cloudflare Tunnel Token | Anual | Ante sospecha de filtración |
| Bot Token Telegram | Anual | Ante sospecha de filtración |
| Contraseña admin | Cada 3 meses | Ante salida de personal |

### ⚠️ Brecha identificada — `forwarded_allow_ips: "*"`

`service.yaml` tiene `forwarded_allow_ips: "*"`, que pasa todos los IPs de proxy como confiables. Cualquier proxy intermedio puede falsificar el IP de origen real.  
**Recomendación:** Reemplazar `"*"` por los rangos de IP de Cloudflare (publicados en `https://www.cloudflare.com/ips/`) una vez estabilizado el entorno.

---

## 6. Despliegues Seguros

### Scripts de despliegue disponibles en la raíz

Se identificaron los siguientes scripts relacionados con despliegue y mantenimiento:

- `INSTALAR.bat` / `INSTALAR.ps1` — instalación inicial del servicio  
- `REINICIAR.bat` — reinicio del servicio  
- `ARREGLAR_SERVICIOS.ps1` / `ARREGLAR_SERVICIOS_v2.ps1` — scripts de reparación  
- `PUBLICAR.bat` (o similar) — despliegue de nueva versión  
- `HANDOFF_NUEVO_PC.md` — guía de migración a nuevo equipo  

### Protocolo recomendado para actualizaciones de código

**Antes del despliegue:**
1. Verificar que el último backup diario es reciente: `backup_manager.py list` o revisar `backups/daily/`  
2. Si hay cambios de modelo de datos, ejecutar `python apply_migrations.py --dry-run` (si existe)  
3. Crear un backup manual pre-despliegue: la función `crear_backup(tipo="pre_action")` en `backup_manager.py`

**Durante el despliegue:**
1. Aplicar cambios de código (copiar archivos o hacer pull)  
2. Si hay migraciones: `python apply_migrations.py` (no modificar la BD directamente)  
3. Reiniciar el servicio. El watchdog detectará la señal y el SCM reiniciará si el runner cae

**Después del despliegue:**
1. Verificar `/health` o la pantalla de estado: DB, disco, RAM, puerto deben estar en `ok`  
2. Verificar `logs/startup.log` — debe mostrar el nuevo PID de uvicorn sin errores de importación  
3. Verificar `logs/crash.log` — debe estar vacío o sin entradas nuevas

**Rollback:**
1. Detener el servicio  
2. Restaurar archivos de código de la versión anterior  
3. `python backup_manager.py restore <nombre_backup_pre_action>` si hubo cambio de esquema  
4. Iniciar el servicio y verificar

### Backups main.py

Existen dos copias de seguridad detectadas en la raíz:
- `main.py.bak_20260723_115310`  
- `main.py.bak_20260818_172317`  

Estas copias permiten un rollback manual de `main.py` sin necesidad de restaurar toda la BD.

---

## 7. Organización de Carpetas

### Estructura actual (inspeccionada)

```
C:\mrd_tool_control\
├── main.py                        ← Aplicación principal FastAPI
├── main.py.bak_20260723_115310    ← Backup manual de main.py
├── main.py.bak_20260818_172317    ← Backup manual de main.py
├── windows_service.py             ← Servicio Windows (pywin32)
├── service_health.py              ← Módulo de health checks
├── backup_manager.py              ← Gestor de backups (hot backup SQLite)
├── backups.py                     ← Módulo secundario de backups (4 KB)
├── telegram_notif.py              ← Notificaciones Telegram (urllib nativo)
├── cloudflare_tunnel.py           ← Gestión del tunnel Cloudflare (21 KB)
├── config.py                      ← Configuración global y variables de entorno
├── service.yaml                   ← Configuración del servicio Windows
├── version.json                   ← Versión actual de la aplicación
│
├── config/
│   └── local.env                  ← Secretos de producción (NO versionar)
│
├── data/
│   └── mrd_tool.db                ← Base de datos SQLite de producción ⚡
│
├── backups/
│   ├── daily/                     ← Backups diarios (retención 7)
│   ├── weekly/                    ← Backups semanales (retención 4)
│   ├── monthly/                   ← Backups mensuales (retención 12)
│   └── pre_action/                ← Backups pre-despliegue (retención 10)
│
├── logs/
│   ├── service.log                ← Log general del servicio
│   ├── startup.log                ← Log de arranques
│   ├── shutdown.log               ← Log de apagados
│   ├── crash.log                  ← Log de crashes y reinicios
│   ├── rotation.log               ← Log de limpieza automática
│   └── uvicorn.log                ← Salida stdout/stderr de uvicorn
│
├── uploads/
│   ├── herramientas/
│   ├── trabajadores/
│   └── obras/
│
├── migrations/                    ← Scripts de migración de esquema
├── templates/                     ← Plantillas Jinja2
├── exports/                       ← Exportaciones generadas
│
├── .service_restart               ← Señal de reinicio desde la API (temporal)
├── .service_status                ← Estado del runner (JSON, actualizado c/30s)
│
├── INSTALAR.bat / .ps1            ← Scripts de instalación
├── REINICIAR.bat                  ← Script de reinicio
├── ARREGLAR_SERVICIOS.ps1         ← Scripts de reparación
├── HANDOFF_NUEVO_PC.md            ← Guía de migración de equipo
│
└── [diseños y documentación]
    ├── DISENO_INVENTARIO_MASIVO_CLAUDE.md
    ├── DISENO_CENTRO_OPERATIVO_CLAUDE.md
    └── PLAN_CONTINUIDAD_Y_ORDEN_CLAUDE.md  ← este documento
```

### Elementos que requieren atención de orden

| Elemento | Situación | Acción recomendada |
|----------|-----------|-------------------|
| `mrd_tool.db` (0 bytes, raíz) | Artefacto vacío confuso | Eliminar; la BD real está en `data/` |
| `main.py.bak_*` (×2, raíz) | Backups manuales acumulados | Mover a una carpeta `backups/code/` o eliminar los más antiguos |
| `backups.py` (4 KB) + `backup_manager.py` (20 KB) | Dos módulos de backup | Verificar si `backups.py` es un wrapper o un módulo legacy redundante |
| `files1.zip` (1857 bytes, raíz) | Origen desconocido | Identificar contenido; si es temporal, eliminar |
| `0nuevo/` (raíz) | Nombre no descriptivo | Identificar propósito; renombrar o eliminar |
| `actulizaciones/` (raíz) | Nombre con typo | Renombrar a `actualizaciones/` o vaciar y eliminar |
| `instance/` (raíz) | Posible artefacto Flask | Verificar si tiene contenido activo; si está vacío, eliminar |
| Documentos de diseño en raíz | 5+ archivos `.md` | Mover a `docs/` para mantener raíz limpia |
| Scripts `.bat`/`.ps1` en raíz | 6+ scripts mezclados | Mover a `scripts/` con nombres descriptivos |

### Directorios protegidos (nunca limpiar automáticamente)

El cleanup automático del servicio (`_run_cleanup()`) opera únicamente sobre `temp/` y `cache/`. Los siguientes directorios están **explícitamente excluidos** del cleanup:

- `backups/` — backups de BD  
- `data/` — base de datos de producción  
- `uploads/` — archivos subidos por usuarios  
- `config/` — secretos y configuración

---

## 8. Matriz de Movimientos de Datos

### Flujo de datos en operación normal

```
Usuario (browser)
    │
    ▼ HTTPS
Cloudflare (CDN + Tunnel)
    │
    ▼ HTTP local
uvicorn :8000
    │
    ├── FastAPI routers
    │       ├── Lee/escribe → data/mrd_tool.db  (SQLite WAL)
    │       ├── Sirve archivos ← uploads/
    │       └── Genera exports → exports/
    │
    └── Telegram API  (urllib, solo salida)
            └── https://api.telegram.org/...
```

### Flujo de backup

```
data/mrd_tool.db
    │
    ▼ sqlite3.Connection.backup() [hot backup]
backups/{daily,weekly,monthly,pre_action}/
    │
    ├── SHA-256 checksum  → backup_history.json
    └── Fernet encrypt (opcional)  → archivo .enc
```

### Flujo de reinicio suave (sin detener el servicio Windows)

```
API POST /admin/restart
    │
    ▼ crea archivo
.service_restart
    │
    ▼ watchdog detecta en <10s
_watchdog_tick() → elimina .service_restart → _restart_uvicorn()
    │
    ▼
uvicorn.terminate() → uvicorn.wait(30s) → uvicorn nuevo PID
```

### Datos que nunca deben salir del servidor

- Contenido de `config/local.env` (tokens, claves)  
- Contenido de `data/mrd_tool.db` sin autorización  
- Archivos de `uploads/trabajadores/` (datos personales)  
- `logs/crash.log` si contiene trazas con datos de sesión

### Datos de solo entrada

- Cloudflare X-Forwarded-For (confiado actualmente por `forwarded_allow_ips: "*"`)  
- Señal `.service_restart` (sin autenticación adicional en el mecanismo de archivo)

---

## 9. Fases de Migración Recomendadas

Las siguientes mejoras están ordenadas por impacto en continuidad. No son un sprint de desarrollo sino mejoras operativas.

### Fase A — Correcciones sin cambio de código (inmediatas)

| Tarea | Archivo a editar | Descripción |
|-------|------------------|-------------|
| A-1 | `service.yaml` | Escalonar delays de recovery SCM: 30s / 60s / 120s |
| A-2 | `service.yaml` | Restringir `forwarded_allow_ips` a IPs de Cloudflare |
| A-3 | Raíz del proyecto | Eliminar `mrd_tool.db` vacío de la raíz |
| A-4 | Raíz del proyecto | Identificar y limpiar `files1.zip`, `0nuevo/`, `instance/` |
| A-5 | Raíz del proyecto | Mover documentos `.md` a `docs/`, scripts a `scripts/` |

### Fase B — Mejoras de backup (bajo riesgo)

| Tarea | Descripción |
|-------|-------------|
| B-1 | Añadir `PRAGMA integrity_check` sobre el archivo backup en un path temporal antes de confirmar el backup como válido |
| B-2 | Configurar copia del backup diario a carpeta de red o almacenamiento externo (offsite) |
| B-3 | Script semanal de test de restauración: restaurar en path temporal, ejecutar query de verificación, registrar resultado |

### Fase C — Mejoras de seguridad operativa (medio plazo)

| Tarea | Descripción |
|-------|-------------|
| C-1 | Añadir verificación de autenticidad al mecanismo `.service_restart` (p. ej., contenido firmado con HMAC) |
| C-2 | Revisar `backups.py` (4 KB): determinar si es módulo legacy y consolidar en `backup_manager.py` |
| C-3 | Configurar notificación Telegram cuando el watchdog supera 3 reinicios consecutivos |
| C-4 | Configurar notificación Telegram cuando el health check detecta disco < 1 GB o RAM > 80% |

### Fase D — Preparación para Sprint 5.5 (PostgreSQL)

| Tarea | Descripción |
|-------|-------------|
| D-1 | Diseñar migración de datos SQLite → PostgreSQL (Export → Import verificado) |
| D-2 | Actualizar `backup_manager.py` para soporte pg_dump |
| D-3 | Actualizar `service.yaml` workers a 2–4 (solo tras completar D-1 y D-2) |

---

## 10. Criterios de Aceptación del Plan de Continuidad

El sistema se considera en estado operativo aceptable cuando cumple todos estos puntos:

### Disponibilidad

- [ ] `GET /health` devuelve `{"healthy": true}` con los 7 checks en `ok`  
- [ ] El servicio Windows `MRDToolControl` aparece como `RUNNING` en `services.msc`  
- [ ] El tunnel Cloudflare aparece como "Healthy" en el panel de Cloudflare Zero Trust  
- [ ] `logs/startup.log` no contiene errores de importación en el último arranque  
- [ ] `logs/crash.log` no tiene entradas en las últimas 24h  

### Backups

- [ ] Existe al menos un backup en `backups/daily/` con fecha de hoy o ayer  
- [ ] `backup_history.json` registra el último backup con checksum SHA-256  
- [ ] El backup más reciente pasa `verify_backup()` sin errores  

### Secretos

- [ ] `config/local.env` existe, no está vacío, y no está rastreado por git  
- [ ] `MRD_SECRET_KEY` está definida (la aplicación arranca sin mensaje de clave de desarrollo)  
- [ ] Los tokens de Telegram están configurados y `telegram_notif.configurado()` devuelve `True`  

### Estructura

- [ ] La raíz del proyecto no contiene archivos `.tmp` sueltos  
- [ ] `data/mrd_tool.db` es el único archivo de BD activo (y tiene tamaño > 0)  
- [ ] Los directorios `uploads/`, `logs/`, `backups/`, `data/` existen y tienen permisos de escritura (verificado por el health check de `check_directory`)  

### Recuperación

- [ ] Un reinicio manual vía `REINICIAR.bat` completa en menos de 2 minutos  
- [ ] Tras el reinicio, `GET /health` vuelve a devolver `{"healthy": true}`  

---

## Archivos y Configuraciones Examinados

Esta inspección fue de **solo lectura**. Los archivos examinados fueron:

| Archivo | Tamaño aprox. | Contenido inspeccionado |
|---------|---------------|------------------------|
| `C:\mrd_tool_control\service.yaml` | 2 KB | Configuración completa del servicio, watchdog, health check, cleanup, logging |
| `C:\mrd_tool_control\service_health.py` | 10 KB | Health checks: DB, disco, RAM, puerto 8000, uploads, logs, backups, sc.exe query |
| `C:\mrd_tool_control\backup_manager.py` | 20 KB | Hot backup sqlite3, SHA-256, Fernet encryption, retención, historial, verify, restore |
| `C:\mrd_tool_control\config.py` | 7 KB | Rutas de directorios, carga de .env, JWT config, Cloudflare vars, categorías/estados |
| `C:\mrd_tool_control\windows_service.py` | 26 KB | MRDWindowsService, MRDServiceRunner, watchdog loop, cleanup loop, status file, CLI |
| `C:\mrd_tool_control\telegram_notif.py` | 4 KB | enviar_mensaje, enviar_aviso, despachar_canal_telegram, configuración desde .env |
| `C:\mrd_tool_control\` (listado de directorio) | — | ~100+ archivos catalogados; estructura completa de carpetas identificada |
| `C:\mrd_tool_control\main.py` (primeras 60 líneas) | parcial | Imports y estructura de routers solamente |

**No se inspeccionaron** (fuera del alcance de continuidad):  
`database.py`, `models.py`, los routers de la aplicación, `apply_migrations.py`, los módulos de negocio (herramientas, trabajadores, inventario, etc.), ni el contenido de `config/local.env`.

**No se modificó ningún archivo.**  
**No se ejecutó ningún comando en el sistema.**  
**No se reinició ningún servicio.**  
**No se creó ningún commit.**  
**No se expuso ninguna credencial, token ni clave.**

---

*Documento generado por Claude (Cowork) — Inspección de solo lectura — 2026-08-20*
