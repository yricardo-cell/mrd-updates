# INFORME DE AUDITORÍA — MRD TOOL CONTROL
# FASE 2 — REVISIÓN Y ESTABILIZACIÓN DEL NÚCLEO

**Fecha:** 2026-07-12  
**Versión auditada:** 1.1.2  
**Auditor:** Claude (Cowork)  
**Alcance:** Proyecto completo — Python, HTML, CSS, JS, BD, seguridad, rendimiento

---

## 1. ESTADO GENERAL POR ÁREA

| Área | Estado | % | Justificación |
|------|--------|---|---------------|
| Arquitectura | Funciona parcialmente | 60% | main.py monolítico de 2004 líneas; services/ existe pero no se usa |
| Backend | Funciona correctamente | 75% | CRUD completo y funcional; faltan errores 500 globales y health endpoint |
| Frontend | Funciona parcialmente | 65% | Dos sistemas JS duplicados; styles.css solo en login; sin responsive audit |
| Base de datos | Funciona correctamente | 80% | WAL mode activo; migraciones seguras; índices añadidos en Fase 2a |
| Seguridad | Riesgo alto | 45% | Path traversal backup; sin rate limit; cookie no secure; secret en código |
| Actualizador | Funciona parcialmente | 55% | Sin verificación de integridad; sin rollback; sin estados de progreso |
| Backups | Funciona parcialmente | 65% | Manual OK; restauración OK; sin backup automático en código; path traversal |
| Logs | No funciona | 0% | No existe ningún sistema de logging en el proyecto |
| Acceso remoto | Funciona correctamente | 80% | Detección multi-proveedor sólida; caché con background refresh |
| Escaneo / QR | Funciona correctamente | 75% | ZXing lazy-loaded; /scan público; falta modo offline |
| Etiquetas | Funciona correctamente | 70% | PDF + ZPL operativos; diseño no configurable aún |
| Zebra | Simulado/incompleto | 50% | ZPL generado pero sin prueba real de impresión desde UI |
| PWA | No funciona | 0% | No existe manifest.json ni service worker |
| Rendimiento | Funciona parcialmente | 70% | GZip + índices añadidos; /api/stats sin optimizar; Excel sin streaming |
| Estabilidad | Riesgo medio | 65% | psutil no instalado causa error en /api/system/stats; sin manejo 500 global |
| Preparación producción | Riesgo alto | 40% | Secret hardcoded; sin .env cargado; sin HTTPS forzado; sin logs |

---

## 2. HALLAZGOS CRÍTICOS

### C1 — Path Traversal en descarga de backup
**Archivo:** main.py línea 1311  
**Riesgo:** CRÍTICO  
**Descripción:** `ruta = BACKUPS_DIR / nombre` — si `nombre` contiene `../data/mrd_tool_control.db`, un administrador podría descargar la base de datos activa o cualquier archivo del servidor.  
**Fix requerido:** Sanitizar el nombre — solo permitir `backup_*.db` y `pre_update_*.db`.

### C2 — Sin protección contra fuerza bruta en /login
**Archivo:** main.py línea 226  
**Riesgo:** CRÍTICO  
**Descripción:** No hay limitación de intentos de login. Un atacante puede probar contraseñas indefinidamente sin ser bloqueado.  
**Fix requerido:** Contador de intentos fallidos en memoria o BD; bloqueo temporal tras 5 intentos.

### C3 — SECRET_KEY hardcodeada con valor por defecto débil
**Archivo:** config.py línea 27  
**Riesgo:** CRÍTICO (en producción)  
**Descripción:** Si `MRD_SECRET_KEY` no está en el entorno, se usa `"mrd-tool-control-clave-secreta-2024-cambiar-en-produccion"`. Cualquier instalación sin configurar expone todos los tokens JWT.  
**Fix requerido:** Cargar `.env` automáticamente; generar key aleatoria si no existe; advertir en arranque.

### C4 — psutil no instalado — /api/system/stats falla en producción
**Archivo:** remote_access.py / requirements.txt  
**Riesgo:** ALTO  
**Descripción:** `psutil` está en `requirements.txt` pero `pip list` muestra que no está instalado. La función `get_server_stats()` falla silenciosamente (devuelve campos vacíos), pero el endpoint `/api/system/stats` puede devolver errores.  
**Fix requerido:** Instalar psutil: `pip install psutil --break-system-packages` o en venv.

---

## 3. HALLAZGOS ALTOS

### A1 — No existe sistema de logging
**Riesgo:** ALTO  
**Descripción:** Ningún archivo Python del proyecto usa `import logging`. Los errores son completamente silenciosos. Imposible diagnosticar problemas en producción.  
**Fix requerido:** Sistema de logging rotativo con niveles, separado por categoría (app, seguridad, backups, acceso remoto).

### A2 — Cookie sin `secure=True`
**Archivo:** main.py línea 247  
**Riesgo:** ALTO (cuando se usa con HTTPS via ngrok/Cloudflare)  
**Descripción:** `set_cookie("mrd_token", ..., httponly=True, samesite="lax")` — falta `secure=True`. Cuando la app se accede via HTTPS tunnel, la cookie puede transmitirse también por HTTP inseguro.  
**Fix requerido:** Detectar entorno HTTPS y añadir `secure=True` dinámicamente.

### A3 — No existe endpoint /health
**Riesgo:** ALTO  
**Descripción:** Existe `/api/system/stats` pero no es un health check estándar. No comprueba BD, disco, memoria ni estado de servicios. No sirve para monitoring.  
**Fix requerido:** Crear `GET /health` público con respuesta rápida y `GET /api/system/health` completo para admins.

### A4 — No existe PWA
**Riesgo:** ALTO (para uso móvil)  
**Descripción:** Sin `manifest.json` ni service worker. La app no se puede instalar en móvil, no funciona offline, y no tiene iconos de app. El escáner QR depende de conexión.  
**Fix requerido:** Crear `static/manifest.json`, `static/js/sw.js`, meta tags en base.html.

### A5 — No hay manejo global de errores 500
**Riesgo:** ALTO  
**Descripción:** FastAPI devuelve stack traces técnicos al usuario si hay un error no capturado. Expone rutas internas, versiones de librerías y estructura del código.  
**Fix requerido:** `@app.exception_handler(Exception)` global + páginas de error personalizadas.

---

## 4. HALLAZGOS MEDIOS

### M1 — JWT sub inconsistente
**Archivo:** main.py línea 213 vs auth.py línea 52  
**Descripción:** `crear_token({"sub": user.username})` guarda el username como string. Pero `login_get()` hace `int(payload.get("sub", 0))` — falla silenciosamente (try/except lo captura). `auth.py` lo lee correctamente como string. Inconsistencia entre dos partes del mismo sistema.  
**Fix requerido:** Eliminar `int(payload.get("sub", 0))` de login_get — usar la misma lógica que auth.py.

### M2 — app.js y mrd.js duplicados
**Archivos:** static/js/app.js (107 líneas), static/js/mrd.js (326 líneas)  
**Descripción:** Ambos archivos definen Toast, Sidebar, e inicialización. `app.js` tiene `mostrarToast()` y `mrd.js` tiene `Toast.show()` — dos sistemas paralelos. `app.js` también tiene `checkUpdateBanner()` y `initAutocompletado()` que pueden o no estar activos.  
**Fix requerido:** Auditar qué templates usan cada uno; consolidar o eliminar el duplicado.

### M3 — static/css/styles.css solo en login.html
**Descripción:** `styles.css` (13KB) solo es referenciado por `login.html`. El resto del proyecto usa `mrd.css`. Carga duplicada de estilos en login.  
**Fix requerido:** Integrar los estilos de login en `mrd.css` o en `base.html`; eliminar `styles.css`.

### M4 — VERSION en config.py ≠ version.json
**Archivo:** config.py línea 34  
**Descripción:** `VERSION = "1.0.0"` en config.py pero `version.json` dice `"1.1.2"`. El footer y el ctx_base muestran "1.0.0" en toda la app.  
**Fix requerido:** Leer VERSION desde version.json en config.py o en startup.

### M5 — Fonts duplicados
**Descripción:** `static/fonts/` y `static/css/fonts/` contienen los mismos archivos woff/woff2 de Bootstrap Icons (306KB duplicados). `bootstrap-icons.min.css` referencia la ruta relativa `fonts/` desde `static/css/`, por eso existen en ambos sitios.  
**Fix requerido:** Eliminar `static/fonts/` si `static/css/fonts/` es la ruta correcta; verificar que CSS la encuentra.

### M6 — services/motor_auditoria.py y motor_movimientos.py — código muerto
**Descripción:** Existen módulos de servicios avanzados (auditoria, movimientos) pero no se importan ni usan en main.py. Son código huérfano de una refactorización incompleta.  
**Fix requerido:** Decidir si integrarlos o documentarlos como futura Fase 3.

### M7 — /api/stats sin optimizar
**Archivo:** main.py línea 1488  
**Descripción:** 4 COUNT queries separadas en lugar de 1 GROUP BY (igual que el dashboard antes de la corrección de Fase 2a).  
**Fix requerido:** Aplicar el mismo patrón GROUP BY que se aplicó al dashboard.

### M8 — Import de `verificar_password` dentro de perfil_post
**Archivo:** main.py línea 278  
**Descripción:** `from auth import verificar_password` dentro de una función — ya está importado en el top level. Import redundante y lento.  
**Fix requerido:** Eliminar el import interno.

### M9 — Backup download sin validación de nombre
**Ya listado como C1 — se repite aquí porque también es bypass de permisos si se escala.**

### M10 — Excel de movimientos sin streaming
**Archivo:** main.py línea 1271  
**Descripción:** `limit(5000)` hardcoded en movimientos Excel. Con 5000 movimientos, openpyxl puede usar 200-500MB de RAM.  
**Fix requerido:** Mover a background task o añadir streaming/paginación.

---

## 5. HALLAZGOS BAJOS

### B1 — Imports dentro de funciones
**Descripción:** `import threading`, `from jose import jwt`, `import zipfile`, `import time`, `from auth import verificar_password` dentro de cuerpos de función. Añaden latencia mínima pero indican código no revisado.  

### B2 — Scripts de utilidad sin limpiar
**Descripción:** `fix_admin_ghost.py`, `fix_usuarios.py`, `ver_usuarios.py`, `reset_admin.py` — scripts de mantenimiento de desarrollo. No deben estar en producción.  

### B3 — cloudflared.exe en directorio raíz (204MB)
**Descripción:** El ejecutable de 204MB está en la raíz del proyecto. No debe incluirse en releases ni backups de código. Pertenece a `tools/` o similar.  

### B4 — INICIAR.vbs sin documentar
**Descripción:** Existe pero no está en ningún README ni documentado.  

### B5 — create_release.bat
**Descripción:** Script que crea el ZIP de release pero no actualiza la versión automáticamente.  

### B6 — .fuse_hidden files en data/
**Descripción:** Artefactos del sistema de archivos de la sesión de desarrollo. No aparecerán en Windows real.  

---

## 6. CHECKLIST DE CRITERIOS FASE 2

| Criterio | Estado actual |
|----------|---------------|
| Arranca sin errores | ✅ Sí |
| No depende de PowerShell abierto | ✅ Tiene SERVICIO_MRD.ps1 |
| Se reinicia automáticamente | ✅ Via INSTALAR_SERVICIO.bat |
| Login funciona | ✅ Sí |
| Permisos funcionan | ✅ Sí (4 roles) |
| Cloudflare funciona | ✅ Detecta y muestra URL |
| QR usa URL correcta | ✅ Via /api/remote-access/qr |
| Backups funcionan | ✅ Manual OK |
| Restauración probada | ⚠️ Código OK — no probada en sesión |
| Actualizador reversible | ❌ Sin rollback automático |
| Logs funcionan | ❌ No existen |
| Health endpoint | ❌ No existe /health |
| Sin botones principales sin función | ⚠️ Pendiente auditoría frontend |
| Sin errores 500 conocidos en flujos principales | ⚠️ psutil falta → posible 500 en stats |
| PWA funciona | ❌ No existe |
| Funciona en PC y móvil | ⚠️ PC sí; móvil no auditado |
| Pruebas críticas pasan | ❌ No hay tests |
| Copia base estable | ✅ MRD_TOOL_CONTROL_BASE_ESTABLE_v1.1.2.zip |
| Documentación instalación | ⚠️ Parcial (install.ps1 existe) |
| Documentación recuperación | ❌ No existe |

**Criterios cumplidos: 9/20 (45%)**

---

## 7. PLAN DE CORRECCIONES PRIORITARIO (FASE 2 — Acciones)

### PRIORIDAD 1 — Seguridad crítica (hacer ya)
1. **Sanitizar nombre en descarga de backup** — 5 min
2. **Rate limiting en /login** — 20 min  
3. **Cargar .env automáticamente** — 10 min
4. **VERSION desde version.json** — 5 min
5. **Fix JWT sub en login_get** — 5 min

### PRIORIDAD 2 — Estabilidad (esta semana)
6. **Instalar psutil en venv**
7. **Sistema de logging rotativo** — nuevo módulo `core/logging.py`
8. **Manejador global de errores 500** — páginas de error personalizadas
9. **Endpoint /health**
10. **Eliminar imports dentro de funciones**
11. **Optimizar /api/stats** — mismo patrón que dashboard

### PRIORIDAD 3 — Completitud (antes de v1.2.0)
12. **PWA básica** — manifest.json + service worker simple
13. **cookie secure=True en HTTPS**
14. **Consolidar app.js vs mrd.js**
15. **Eliminar fonts duplicados**
16. **Integrar styles.css en mrd.css o base.html**
17. **Tests mínimos** — pytest básico para login, health, backup

### PRIORIDAD 4 — Limpieza
18. **Mover cloudflared.exe** a tools/ o directorio separado
19. **Documentar scripts de mantenimiento** o moverlos a tools/
20. **Actualizar VERSION en config.py** para que lea de version.json

---

## 8. ARQUITECTURA ACTUAL vs RECOMENDADA

**Estado actual:** Monolito en main.py (2004 líneas)  
**Riesgo:** Bajo si se mantiene documentado  
**Recomendación para Fase 2:** NO reorganizar estructura ahora — el riesgo de romper rutas supera el beneficio. En cambio:

- Extraer solo `core/logging.py` (nuevo, sin impacto)
- Extraer solo `core/health.py` (nuevo, sin impacto)  
- Extraer solo `core/errors.py` (nuevos handlers, sin impacto)
- El resto espera a Fase 3

---

## 9. DEPENDENCIAS — ESTADO

| Paquete | Versión instalada | Estado |
|---------|------------------|--------|
| fastapi | 0.139.0 | ✅ OK |
| sqlalchemy | 2.0.51 | ✅ OK |
| uvicorn | instalado | ✅ OK |
| bcrypt | 5.0.0 | ✅ OK |
| python-jose | 3.3.0 | ✅ OK |
| jinja2 | 3.1.4 | ✅ OK |
| qrcode | instalado | ✅ OK |
| reportlab | instalado | ✅ OK |
| openpyxl | instalado | ✅ OK |
| pillow | instalado | ✅ OK |
| **psutil** | **NO INSTALADO** | ❌ FALTA |
| python-dotenv | instalado | ✅ OK |

---

## 10. RESUMEN EJECUTIVO

El proyecto **funciona y es usable** en su estado actual. Los flujos principales (login, inventario, movimientos, backups, acceso remoto) están operativos. Sin embargo, **no está listo para producción** por tres razones principales:

1. **Seguridad:** Path traversal en backup, sin rate limiting en login, secret key sin protección
2. **Observabilidad:** Sin logs, sin health endpoint — imposible diagnosticar fallos
3. **Completitud:** Sin PWA, sin tests, sin manejo global de errores

La Fase 2 requiere corregir las 5 acciones de Prioridad 1 y las 6 de Prioridad 2 como mínimo antes de declararse completa.

---

*Informe generado automáticamente. Baseline congelado en: `MRD_TOOL_CONTROL_BASE_ESTABLE_v1.1.2.zip`*
