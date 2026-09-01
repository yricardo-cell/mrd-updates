# DISEÑO — SPRINT ESCÁNER 1 (V2): PISTOLAS UNIVERSALES Y USO SIMULTÁNEO
**MRD TOOL CONTROL · Solo lectura · No implementar hasta aprobación**
**v2 — incorpora correcciones obligatorias tras revisión**

---

## 1. ESTADO ACTUAL — RESUMEN DE AUDITORÍA

*(Sin cambios respecto a V1. Ver hallazgos RC-01…RC-05.)*

Puntos críticos confirmados:
- **RC-01**: read-check-write no atómico en `movimiento_entregar_post` y `movimiento_devolver_post`. El commit `29fc53f` solo corrige serialización JSON, **no resuelve la carrera**.
- **RC-02**: sin `scan_event_id`; doble POST puede duplicar operaciones.
- **RC-03**: `client_key` = solo IP; sin identidad de puesto.
- **RC-04**: navegador no distingue varias pistolas HID en el mismo PC.
- **RC-05**: sin notificación en tiempo real entre puestos.

---

## 2. CORRECCIONES V2 — ÍNDICE

| # | Corrección |
|---|---|
| C-01 | Servicio transaccional común reutilizado por rutas actuales y `/scan/operar` |
| C-02 | Idempotencia por inserción atómica, no por consulta previa |
| C-03 | Nuevas tablas en el migrador SQLite existente (`apply_migrations` + `models.py`) |
| C-04 | Polling SQLite en vez de SSE en memoria |
| C-05 | WebSocket Bridge: Origin + auth + expiración + revocación + HTTPS |
| C-06 | Token Bridge con Windows DPAPI, sin texto plano |
| C-07 | Bridge en `%LocalAppData%`, sin permisos administrativos |
| C-08 | Solo registrar operaciones autenticadas; retención 90 días |
| C-09 | Plan de pruebas completo incluyendo dos pistolas físicas simultáneas |
| C-10 | Visibilidad de cámara solo en móvil/tablet |

---

## 3. C-01 — SERVICIO TRANSACCIONAL COMÚN

### Problema V1
`/scan/operar` replicaba lógica de permisos, estado y movimientos ya existente en `movimiento_entregar_post` y `_aplicar_devolucion`. Cualquier cambio a las reglas de negocio requeriría actualizar dos sitios.

### Solución

Extraer **dos funciones de servicio** que encapsulan toda la lógica de negocio. Las rutas HTTP existentes y `/scan/operar` llaman a las mismas funciones. No se modifica el comportamiento externo de ninguna ruta existente.

```python
# ── Servicio entrega ─────────────────────────────────────────────────────────
def servicio_entregar_herramienta(
    db: Session,
    herramienta_id: int,
    usuario: Usuario,
    trabajador_id: Optional[int] = None,
    obra_id: Optional[int] = None,
    observaciones: str = "",
    firma_datos: str = "",
    firma_nombre: str = "",
) -> Movimiento:
    """
    Entrega atómica. Lanza HTTPException si:
    - herramienta no existe o está inactiva (404)
    - usuario sin permiso 'entregar' (403)
    - herramienta no disponible (409)
    - trabajador/obra inválidos (400)
    Llamado por: movimiento_entregar_post() y scan_operar()
    """
    if not tiene_permiso(usuario, "entregar"):
        raise HTTPException(403, "Sin permiso")

    # UPDATE condicional atómico — fix RC-01
    result = db.execute(
        text("UPDATE herramientas SET estado='entregada' "
             "WHERE id=:hid AND activa=1 AND estado='disponible'"),
        {"hid": herramienta_id}
    )
    db.flush()
    if result.rowcount == 0:
        h = db.query(Herramienta).filter(Herramienta.id == herramienta_id).first()
        if not h or not h.activa:
            raise HTTPException(404, "Herramienta no encontrada o inactiva")
        raise HTTPException(409, f"La herramienta no está disponible (estado actual: {h.estado})")

    h = db.query(Herramienta).filter(Herramienta.id == herramienta_id).first()

    t_id = int(trabajador_id) if trabajador_id else None
    o_id = int(obra_id) if obra_id else None
    trabajador = db.query(Trabajador).filter(
        Trabajador.id == t_id, Trabajador.activo == True
    ).first() if t_id else None
    if t_id and not trabajador:
        db.rollback()
        raise HTTPException(400, "Trabajador no válido o inactivo")
    obra = db.query(Obra).filter(Obra.id == o_id, Obra.activa == True).first() if o_id else None
    if o_id and not obra:
        db.rollback()
        raise HTTPException(400, "Obra no válida o inactiva")

    destino = trabajador.nombre_completo if trabajador else (obra.nombre if obra else "Entregada")
    h.responsable_id = t_id
    h.obra_id = o_id
    h.almacen_id = None
    h.ubicacion_texto = destino
    mov = registrar_movimiento(db, h, "entrega", "entregada", usuario, t_id, o_id,
                               destino=destino, observaciones=observaciones)
    if firma_datos and mov:
        mov.firma_datos = firma_datos
        mov.firma_nombre = firma_nombre or None
    return mov


# ── Servicio devolución ──────────────────────────────────────────────────────
# _aplicar_devolucion() ya existe y encapsula la lógica.
# Se reutiliza directamente desde scan_operar(). Sin cambios a su firma.
# El UPDATE atómico se añade ANTES de llamarla:
#
#   result = db.execute(
#       text("UPDATE herramientas SET estado='pendiente' "   # estado temporal no válido
#            "... "),  ← ver sección 4 para la técnica exacta
```

**Regla:** cualquier cambio futuro a condiciones de entrega/devolución se hace **solo** en `servicio_entregar_herramienta()` y `_aplicar_devolucion()`. Las rutas solo validan formulario y llaman al servicio.

### Adaptación de rutas existentes

`movimiento_entregar_post()` se convierte en:
```python
@app.post("/movimientos/entregar")
def movimiento_entregar_post(...):
    try:
        mov = servicio_entregar_herramienta(db, h_id, user, t_id, o_id, observaciones, firma_datos, firma_nombre)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return RedirectResponse(f"/herramientas/{h_id}", status_code=303)
```

La respuesta externa (RedirectResponse 303) no cambia. La lógica interna es idéntica a hoy pero atómica.

---

## 4. C-02 — IDEMPOTENCIA ATÓMICA CON `scan_event_id`

### Problema V1
"Consultar antes de insertar no garantiza idempotencia" — si dos requests con el mismo `scan_event_id` llegan simultáneamente, ambos pasan la consulta de verificación.

### Solución: inserción atómica con UNIQUE constraint

```sql
-- En scan_eventos: índice UNIQUE sobre scan_event_id
CREATE UNIQUE INDEX IF NOT EXISTS uix_scan_event_id
    ON scan_eventos(scan_event_id);
```

Flujo en `scan_operar()`:

```python
async def scan_operar(body: ScanOperarBody, user: Usuario, db: Session):
    # 1. Intentar insertar el evento ANTES de cualquier operación
    try:
        db.execute(text(
            "INSERT INTO scan_eventos "
            "(scan_event_id, puesto_id, pistola_id, pistola_nombre, "
            " codigo, accion, usuario_id, created_at) "
            "VALUES (:eid, :pid, :gid, :gname, :cod, :acc, :uid, datetime('now'))"
        ), {
            "eid": body.scan_event_id,
            "pid": body.puesto_id or "",
            "gid": body.pistola_id or None,
            "gname": body.pistola_nombre or None,
            "cod": body.codigo or "",
            "acc": body.accion,
            "uid": user.id,
        })
        db.flush()
    except IntegrityError:
        db.rollback()
        # El evento ya existe → idempotencia
        fila = db.execute(
            text("SELECT resultado, movimiento_id FROM scan_eventos "
                 "WHERE scan_event_id=:eid"), {"eid": body.scan_event_id}
        ).first()
        return JSONResponse({"resultado": "ya_procesado",
                             "movimiento_id": fila.movimiento_id if fila else None},
                            status_code=200)

    # 2. Ejecutar operación (servicio transaccional)
    try:
        if body.accion == "entregar":
            mov = servicio_entregar_herramienta(db, body.herramienta_id, user,
                                                body.trabajador_id, body.obra_id,
                                                body.observaciones or "")
        elif body.accion == "devolver":
            h = db.query(Herramienta).filter(Herramienta.id == body.herramienta_id,
                                             Herramienta.activa == True).first()
            if not h:
                raise HTTPException(404)
            almacen = _primer_almacen_activo(db)
            _aplicar_devolucion(db, h, user, almacen, body.condicion or "buena",
                                body.observaciones or "")
            mov = db.query(Movimiento).filter(
                Movimiento.herramienta_id == body.herramienta_id
            ).order_by(Movimiento.id.desc()).first()
        else:
            raise HTTPException(400, "Acción no válida")

        # 3. Actualizar el evento con el resultado
        db.execute(text(
            "UPDATE scan_eventos SET resultado='ok', movimiento_id=:mid, "
            "procesado_en=datetime('now') WHERE scan_event_id=:eid"
        ), {"mid": mov.id if mov else None, "eid": body.scan_event_id})
        db.commit()
        # 4. Notificar cambio en tabla scan_notificaciones (ver C-04)
        _publicar_cambio_estado(db, body.herramienta_id)
        return JSONResponse({"resultado": "ok", "movimiento_id": mov.id if mov else None})

    except HTTPException as e:
        db.execute(text(
            "UPDATE scan_eventos SET resultado='conflicto', "
            "procesado_en=datetime('now') WHERE scan_event_id=:eid"
        ), {"eid": body.scan_event_id})
        db.commit()
        return JSONResponse({"resultado": "conflicto", "detalle": e.detail},
                            status_code=e.status_code)
    except Exception:
        db.execute(text(
            "UPDATE scan_eventos SET resultado='error', "
            "procesado_en=datetime('now') WHERE scan_event_id=:eid"
        ), {"eid": body.scan_event_id})
        db.commit()
        raise
```

**Garantías:**
- `IntegrityError` en la inserción = única fuente de verdad para idempotencia.
- El servicio transaccional solo se ejecuta si la inserción triunfó.
- Un error en el servicio marca el evento como `'conflicto'`/`'error'`; una segunda llamada con el mismo `scan_event_id` devuelve `ya_procesado` inmediatamente.
- **No se consulta antes de insertar.** La unicidad la garantiza SQLite.

---

## 5. C-03 — INTEGRACIÓN EN EL MIGRADOR EXISTENTE

### Regla
No hay segundo migrador. No hay script SQL suelto. Todo va en `database.py` tal como hacen los demás sprints.

### Nuevas tablas → `models.py` + `Base.metadata.create_all()`

```python
# models.py — añadir al final

class PuestoEscaner(Base):
    __tablename__ = "puestos_escaner"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    puesto_id     = Column(String(36), unique=True, nullable=False, index=True)
    nombre        = Column(String(100), nullable=False)
    token_hash    = Column(String(64), nullable=False)   # SHA-256(token)
    activo        = Column(Boolean, nullable=False, default=True)
    ultimo_visto  = Column(DateTime, nullable=True)
    created_at    = Column(DateTime, server_default=func.now())
    created_by_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)


class ScanEvento(Base):
    __tablename__ = "scan_eventos"
    id             = Column(Integer, primary_key=True, autoincrement=True)
    scan_event_id  = Column(String(36), unique=True, nullable=False, index=True)
    puesto_id      = Column(String(36), nullable=False, index=True)
    pistola_id     = Column(String(200), nullable=True)
    pistola_nombre = Column(String(100), nullable=True)
    codigo         = Column(String(200), nullable=False)
    accion         = Column(String(30), nullable=True)   # 'entregar'|'devolver'
    resultado      = Column(String(30), nullable=True)   # 'ok'|'conflicto'|'error'|'ya_procesado'
    herramienta_id = Column(Integer, ForeignKey("herramientas.id"), nullable=True)
    movimiento_id  = Column(Integer, ForeignKey("movimientos.id"), nullable=True)
    usuario_id     = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    created_at     = Column(DateTime, server_default=func.now(), index=True)
    procesado_en   = Column(DateTime, nullable=True)


class ScanNotificacion(Base):
    """Tabla de polling para notificaciones entre puestos. Ver C-04."""
    __tablename__ = "scan_notificaciones"
    id             = Column(Integer, primary_key=True, autoincrement=True)
    herramienta_id = Column(Integer, ForeignKey("herramientas.id"), nullable=False, index=True)
    estado_nuevo   = Column(String(50), nullable=False)
    puesto_origen  = Column(String(100), nullable=True)
    created_at     = Column(DateTime, server_default=func.now(), index=True)
```

`Base.metadata.create_all(engine)` (ya llamado en el arranque) crea estas tablas con `IF NOT EXISTS` implícito. Idempotente.

### Nuevas columnas → lista `migrations` en `apply_migrations()`

Si en el futuro se necesita añadir columnas a estas tablas nuevas, se añade una tupla a la lista `migrations` exactamente como todos los sprints anteriores. Por ahora no hay columnas que añadir en la migración inicial (las tablas son nuevas).

### Índice con restricción UNIQUE

`models.py` define `unique=True` en `scan_event_id`. SQLAlchemy genera el índice UNIQUE en el `create_all()`. No es necesario DDL adicional.

---

## 6. C-04 — POLLING SQLite EN LUGAR DE SSE EN MEMORIA

### Problema V1
`asyncio.Queue` en memoria: no funciona con múltiples procesos uvicorn (o tras reinicio NSSM). Inútil en producción con más de un worker.

### Solución: tabla `scan_notificaciones` + polling cliente

**Servidor — `_publicar_cambio_estado()`:**
```python
def _publicar_cambio_estado(db: Session, herramienta_id: int,
                             puesto_origen: str = ""):
    """Inserta fila en scan_notificaciones tras una operación exitosa."""
    h = db.query(Herramienta).filter(Herramienta.id == herramienta_id).first()
    if not h:
        return
    db.execute(text(
        "INSERT INTO scan_notificaciones (herramienta_id, estado_nuevo, puesto_origen) "
        "VALUES (:hid, :est, :po)"
    ), {"hid": herramienta_id, "est": h.estado, "po": puesto_origen})
    # No hace commit aquí — lo hace scan_operar() tras flush
```

**Endpoint de polling:**
```
GET /scan/cambios?desde=<iso_datetime>&herramienta_ids=42,57
Auth: requiere_login
```
Devuelve:
```json
[{"herramienta_id":42,"estado_nuevo":"entregada","puesto_origen":"Mostrador 1","ts":"..."}]
```

**Cliente — polling cada 4 segundos (solo si hay herramienta escaneada activa):**
```javascript
var _pollInterval = null;
function iniciarPolling(herramienta_id) {
  if (_pollInterval) clearInterval(_pollInterval);
  var desde = new Date().toISOString();
  _pollInterval = setInterval(async function() {
    try {
      var r = await fetch('/scan/cambios?desde=' + encodeURIComponent(desde)
                          + '&herramienta_ids=' + herramienta_id);
      if (!r.ok) return;
      var items = await r.json();
      items.forEach(function(ev) {
        if (ev.herramienta_id == _currentTool?.id) {
          _currentTool.estado = ev.estado_nuevo;
          mostrarResultado(_currentTool);
          desde = ev.ts;
        }
      });
    } catch(_) {}
  }, 4000);
}
function detenerPolling() {
  if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
}
```

**Limpieza automática de `scan_notificaciones`:** registros con `created_at < now - 5 minutos` eliminados por la tarea de automatizaciones existente. No es audit trail — es señal de transporte.

**Ventaja sobre SSE:** funciona con N workers, N procesos, reinicios NSSM, Cloudflare. Un único SELECT sin estado en servidor.

---

## 7. C-05 — WEBSOCKET LOCAL: SEGURIDAD COMPLETA

### Restricciones del entorno

Una página HTTPS no puede abrir `ws://` (mixed content bloqueado). El Bridge escucha en `localhost`. Dos opciones:

| Opción | Pros | Contras |
|---|---|---|
| **A) HTTP polling local** (Bridge expone `http://localhost:9421/poll`) | Sin problemas mixed-content desde HTTPS | Latencia ~500ms |
| B) WSS con cert autofirmado | Tiempo real | Requiere instalar cert en sistema; UX compleja |

**Decisión: Opción A — HTTP polling local.** Más simple, sin cert management, latencia aceptable para pistola física.

### Protocolo Bridge → navegador

```
GET http://localhost:9421/poll
Headers: Authorization: Bearer <token_sesion_bridge>
         Origin: https://mrd.empresa.com  (o el dominio configurado)
```

El Bridge valida:
1. **Origin**: solo acepta el dominio configurado en `config.json` (`allowed_origin`). Si el Origin no coincide → 403.
2. **Token de sesión**: token de corta vida (10 minutos) que el navegador obtiene al cargar `scan.html` mediante un intercambio con el servidor MRD:
   ```
   POST /scan/bridge-token
   Auth: cookie de sesión
   → {bridge_token: "hex32", expires_in: 600}
   ```
   El servidor genera el `bridge_token`, lo almacena en `scan_eventos` o una tabla auxiliar con TTL. El Bridge verifica el `bridge_token` contra el servidor MRD en la primera conexión y lo cachea por su TTL.
3. **Expiración**: `bridge_token` expira a los 10 minutos. El navegador renueva silenciosamente antes de expirar.
4. **Revocación**: revocar el `puesto_escaner` invalida todos los `bridge_token` asociados. El servidor responde 401 al Bridge en la verificación siguiente.

### Respuesta del poll

```json
{
  "scans": [
    {
      "scan_event_id": "uuid",
      "pistola_id": "HID\\VID_05E0...",
      "pistola_nombre": "Mostrador 1-A",
      "codigo": "HT-0042",
      "ts": "2026-08-20T10:32:00.123Z"
    }
  ],
  "next_poll_ms": 300
}
```

Si no hay lecturas nuevas: `{"scans": [], "next_poll_ms": 500}`.

### Tabla auxiliar `bridge_tokens`

```python
class BridgeToken(Base):
    __tablename__ = "bridge_tokens"
    id         = Column(Integer, primary_key=True)
    token_hash = Column(String(64), unique=True, nullable=False)
    puesto_id  = Column(String(36), ForeignKey("puestos_escaner.puesto_id"), nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
```

Limpieza: eliminar filas con `expires_at < now` en la tarea de automatizaciones.

---

## 8. C-06 — TOKEN BRIDGE CON WINDOWS DPAPI

### Problema V1
`config.json` con token en texto plano. Cualquier usuario con acceso al filesystem puede leerlo.

### Solución: Windows DPAPI

```python
# scanner_bridge/dpapi.py
import ctypes, ctypes.wintypes

def encrypt(plaintext: str) -> bytes:
    """Cifra con DPAPI (scope: usuario actual, sin contraseña adicional)."""
    DATA_BLOB = type('DATA_BLOB', (ctypes.Structure,), {
        '_fields_': [('cbData', ctypes.wintypes.DWORD),
                     ('pbData', ctypes.POINTER(ctypes.c_char))]
    })
    data = plaintext.encode()
    input_blob = DATA_BLOB(len(data), ctypes.cast(ctypes.c_char_p(data), ctypes.POINTER(ctypes.c_char)))
    output_blob = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)):
        raise OSError("DPAPI CryptProtectData falló")
    result = bytes(ctypes.string_at(output_blob.pbData, output_blob.cbData))
    ctypes.windll.kernel32.LocalFree(output_blob.pbData)
    return result

def decrypt(ciphertext: bytes) -> str:
    # Análogo con CryptUnprotectData
    ...
```

`config.json` almacena:
```json
{
  "puesto_id": "uuid-claro",
  "token_encrypted_b64": "base64(DPAPI(token))",
  "allowed_origin": "https://mrd.empresa.com",
  "server_url": "https://mrd.empresa.com"
}
```

El token en texto plano solo existe en memoria durante la ejecución del Bridge. Si el archivo es copiado a otro PC o a otro usuario Windows, `CryptUnprotectData` falla (DPAPI es scope de usuario+máquina).

**Fallback en tests:** variable de entorno `MRD_BRIDGE_TOKEN_PLAINTEXT=1` omite DPAPI. Solo activa si se ejecuta con `--test-mode`. Nunca en producción.

---

## 9. C-07 — INSTALACIÓN SIN PERMISOS ADMINISTRATIVOS

### Ubicación

```
%LocalAppData%\MRD\ScannerBridge\
├── bridge.exe
├── config.json
├── bridge.log
└── bridge_tokens_cache.db   (SQLite local, TTL de bridge_tokens)
```

No escribe en `C:\Program Files\`, `HKLM` ni `System32`.

### Arranque automático sin admin

```powershell
# install.ps1 — solo escribe en HKCU (usuario actual)
$regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$exePath = "$env:LocalAppData\MRD\ScannerBridge\bridge.exe"
Set-ItemProperty -Path $regPath -Name "MRDScannerBridge" -Value "`"$exePath`" --minimized"
```

`HKCU\...\Run` no requiere privilegios. El proceso arranca al iniciar sesión del usuario actual.

### Desinstalación limpia

```powershell
# uninstall.ps1
Remove-ItemProperty -Path $regPath -Name "MRDScannerBridge" -ErrorAction SilentlyContinue
Stop-Process -Name "bridge" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$env:LocalAppData\MRD\ScannerBridge\"
```

### Sin MSI, sin UAC

El instalador es el propio `bridge.exe --install` ejecutado una vez. Extrae sus archivos en `%LocalAppData%`, escribe `HKCU\Run` y lanza la UI de configuración.

---

## 10. C-08 — POLÍTICA DE REGISTRO Y RETENCIÓN

### Qué se registra en `scan_eventos`

| Operación | Se registra | Condición |
|---|---|---|
| `/scan/buscar` (búsqueda pública) | **NO** | Pública, sin auth, sin implicación operativa |
| `/scan/operar` con resultado OK | **SÍ** | Operación autenticada con movimiento |
| `/scan/operar` con conflicto | **SÍ** | Evidencia de intento concurrente |
| `/scan/operar` con error | **SÍ** | Evidencia de fallo |
| Duplicado (`ya_procesado`) | **NO** | El evento original ya consta; no aporta información nueva |

El rate limiting de `/scan/buscar` sigue siendo en memoria (`_scan_attempts`). No se persiste.

### Retención

| Tabla | Retención | Criterio |
|---|---|---|
| `scan_eventos` | 90 días | `created_at < now - 90d` |
| `scan_notificaciones` | 5 minutos | `created_at < now - 5m` |
| `bridge_tokens` | Al expirar + 1h | `expires_at < now - 1h` |

**Limpieza:** añadir tres `DELETE` a la tarea de automatizaciones programadas existente. Sin nuevo módulo.

---

## 11. C-09 — PLAN DE PRUEBAS COMPLETO

### Pruebas de concurrencia

| ID | Mecanismo | Criterio |
|---|---|---|
| T-CON-01 | `threading.Thread` × 2, mismo `herramienta_id`, `scan_event_id` distintos | Exactamente 1 `rowcount==1`; el otro recibe 409 |
| T-CON-02 | Mismo `scan_event_id`, dos threads | Exactamente 1 INSERT en `scan_eventos`; el otro recibe `ya_procesado` |
| T-CON-03 | 10 threads paralelos, herramientas distintas | Todos completan OK; 10 movimientos creados |

### Pruebas de sesión

| ID | Caso | Criterio |
|---|---|---|
| T-SES-01 | Cookie caducada → POST `/scan/operar` | HTTP 401; cero movimientos creados; `scan_eventos.resultado='error'` |
| T-SES-02 | Usuario activo, cookie válida → operación | 200 OK |
| T-SES-03 | Cookie válida, usuario desactivado entre escaneo y confirm | 401 o 403 |

### Pruebas de permisos

| ID | Caso | Criterio |
|---|---|---|
| T-PER-01 | Usuario sin permiso `entregar` | HTTP 403; sin movimiento |
| T-PER-02 | Usuario sin permiso `devolver` | HTTP 403; sin movimiento |
| T-PER-03 | Admin registra puesto | 200 OK, token devuelto |
| T-PER-04 | No-admin intenta registrar puesto | 403 |

### Pruebas de duplicados e idempotencia

| ID | Caso | Criterio |
|---|---|---|
| T-IDP-01 | Mismo `scan_event_id` enviado 2 veces (secuencial) | Segunda llamada: `ya_procesado`; 1 solo movimiento |
| T-IDP-02 | Mismo `scan_event_id` enviado 2 veces (concurrente) | Una INSERT triunfa; la otra recibe `IntegrityError` → `ya_procesado` |
| T-IDP-03 | Herramienta entregada → intentar entregar otra vez con nuevo `scan_event_id` | 409 conflicto; sin segundo movimiento |

### Pruebas de rollback

| ID | Caso | Criterio |
|---|---|---|
| T-ROL-01 | Error forzado tras UPDATE atómico, antes de commit | Estado herramienta = original; sin movimiento; `scan_eventos.resultado='error'` |
| T-ROL-02 | Trabajador inválido tras UPDATE atómico | Rollback; herramienta vuelve a 'disponible' |

### Pruebas de Bridge

| ID | Caso | Criterio |
|---|---|---|
| T-BRI-01 | Origin incorrecto en poll | 403 del Bridge |
| T-BRI-02 | `bridge_token` expirado | Bridge renueva; operación continúa |
| T-BRI-03 | Puesto revocado desde web | Bridge recibe 401; UI muestra "token revocado" |
| T-BRI-04 | Bridge reinicia | `puesto_id` persiste; lectura siguiente funciona |
| T-BRI-05 | Pistola desconectada y reconectada | Raw Input re-detecta dispositivo |

### Pruebas de cámara y visibilidad (ver C-10)

| ID | Caso | Criterio |
|---|---|---|
| T-CAM-01 | Desktop (puntero mouse, pantalla ≥1200px) | Sección cámara oculta; solo input pistola |
| T-CAM-02 | Mobile (touch, pantalla <600px) | Sección cámara visible |
| T-CAM-03 | Tablet (touch, pantalla 768-1199px) | Sección cámara visible |
| T-CAM-04 | Desktop: pistola escanea código | Resultado en < 500ms |
| T-CAM-05 | Móvil: cámara deniega permiso | Mensaje claro; input manual disponible |

### **PRUEBA FINAL OBLIGATORIA: DOS PISTOLAS FÍSICAS SIMULTÁNEAS**

| ID | Procedimiento | Criterio de éxito |
|---|---|---|
| T-FIS-01 | Bridge ejecutándose con Pistola A (USB) y Pistola B (USB o BT) conectadas | Ambas aparecen en la UI con nombres distintos |
| T-FIS-02 | Pistola A escanea HT-001; Pistola B escanea HT-002 simultáneamente | Dos resultados distintos; cada uno muestra `pistola_nombre` correcto |
| T-FIS-03 | Pistola A y Pistola B escanean HT-001 simultáneamente | Una operación OK; la otra recibe conflicto con mensaje claro en pantalla |
| T-FIS-04 | Pistola A lee rápido × 5 (doble-beep simulado) | Cada código llega completo sin mezcla de caracteres |
| T-FIS-05 | Pistola A desconectada; Pistola B sigue leyendo | Pistola B continúa operativa; UI no se bloquea |

---

## 12. C-10 — VISIBILIDAD DE CÁMARA SOLO EN MÓVIL/TABLET

### Problema
En PC la cámara es innecesaria (pistola HID). Mostrarla confunde y puede provocar activación accidental.

### Detección — combinación de tres señales (no solo User-Agent)

```javascript
function _esMobileOTablet() {
  // 1. Puntero: coarse = táctil; fine = mouse
  var esCoarse = window.matchMedia('(pointer: coarse)').matches;
  // 2. Tamaño: < 1100px de ancho
  var esPequeno = window.innerWidth < 1100;
  // 3. Touch disponible
  var esTouch = navigator.maxTouchPoints > 0;
  // Móvil/tablet si al menos 2 de 3 señales son positivas
  return (esCoarse ? 1 : 0) + (esPequeno ? 1 : 0) + (esTouch ? 1 : 0) >= 2;
}
```

### Comportamiento

```javascript
var _mostrarCamara = _esMobileOTablet();
var _camPanel = document.getElementById('panel-camara');
if (_camPanel) {
  _camPanel.style.display = _mostrarCamara ? '' : 'none';
}
```

- **Desktop (PC):** sección cámara oculta completamente. Sin botón "Activar cámara". Sin solicitud de permiso automática. Input de pistola en primer plano.
- **Móvil/tablet:** sección cámara visible, pero el botón "Activar cámara" sigue siendo manual — nunca auto-activa ni solicita permiso automáticamente.
- **Dispositivo sin cámara o permiso denegado:** mensaje claro: `"No hay cámara disponible. Usa la pistola o introduce el código manualmente."`. El input de código permanece funcional.
- **Redimensionado de ventana:** la detección se reevalúa en `window.addEventListener('resize', ...)` con debounce de 300ms para cubrir el caso de DevTools mobile emulation.

---

## 13. ARQUITECTURA FINAL — RESUMEN

```
┌── Pistola HID (USB/BT) ────── Modo A: navegador captura keystrokes ──────────────┐
│                                                                                    │
│   scan.html                                                                        │
│   ├── input#scan-input: detección HID (timing < 80ms)                             │
│   ├── puesto_id: sessionStorage (UUID por tab)                                    │
│   ├── scan_event_id: crypto.randomUUID() por operación                            │
│   ├── polling /scan/cambios cada 4s (si hay herramienta activa)                   │
│   └── poll a http://localhost:9421/poll (Bridge, opcional)                         │
│                                                                                    │
│── Bridge (Modo B) ───────────────────────────────────────────────────────────────│
│   Pistola A ──Raw Input──┐                                                        │
│   Pistola B ──Raw Input──┤── bridge.exe (DPAPI, %LocalAppData%, HKCU\Run)        │
│   Pistola C ──COM/serie──┘      │                                                 │
│                          POST http://localhost:9421/poll                           │
│                          Auth: bridge_token (TTL 10min, renovable)                │
│                          Origin: validado                                          │
│                                                                                    │
│── FastAPI ───────────────────────────────────────────────────────────────────────│
│   POST /scan/operar            ← JSON, requiere_login                             │
│     ├── INSERT scan_eventos (UNIQUE → IntegrityError = idempotencia)              │
│     ├── servicio_entregar_herramienta() o _aplicar_devolucion()                   │
│     │     └── UPDATE atómico WHERE estado='disponible' → rowcount check           │
│     ├── UPDATE scan_eventos.resultado                                              │
│     ├── INSERT scan_notificaciones                                                 │
│     └── db.commit()                                                                │
│                                                                                    │
│   GET /scan/cambios            ← polling desde clientes autenticados              │
│   POST /scan/bridge-token      ← genera bridge_token con TTL                      │
│   POST /scan/puestos/registrar ← admin only                                       │
│   POST /scan/puestos/{id}/revocar ← admin only                                   │
│                                                                                    │
│── SQLite WAL ────────────────────────────────────────────────────────────────────│
│   scan_eventos         (UNIQUE scan_event_id, retención 90d)                     │
│   scan_notificaciones  (retención 5min)                                           │
│   puestos_escaner                                                                 │
│   bridge_tokens        (TTL 10min, limpieza en automatizaciones)                  │
└───────────────────────────────────────────────────────────────────────────────────┘
```

---

## 14. BLOQUES DE IMPLEMENTACIÓN SEGUROS

Cada bloque es independiente y no toca producción hasta el merge.

| Bloque | Contenido | Prerequisito | Toca producción |
|---|---|---|---|
| **B-1** | `models.py`: añadir 4 clases nuevas | Ninguno | No |
| **B-2** | `servicio_entregar_herramienta()` en `main.py` (solo función, sin reemplazar rutas) | B-1 | No |
| **B-3** | Adaptar `movimiento_entregar_post()` para llamar al servicio | B-2 | Solo en merge |
| **B-4** | `/scan/operar` + `/scan/cambios` + `/scan/bridge-token` | B-1, B-2 | No (rutas nuevas) |
| **B-5** | Actualizar `scan.html`: puesto_id, scan_event_id, polling, Bridge poll, cámara condicional | B-4 | No |
| **B-6** | `scanner_bridge/`: bridge.exe + DPAPI + UI | B-4 | No |
| **B-7** | Limpieza en automatizaciones existente | B-1 | Solo en merge |
| **B-8** | Pruebas `tests/test_scan_sprint1.py` | Todos | No |
| **B-9** | **Prueba física T-FIS-01..T-FIS-05** | B-5, B-6 | No (entorno test) |
| **B-10** | **Merge a main + commit final** | B-8, B-9 aprobados | Sí |

**B-1..B-4 no requieren tocar las rutas activas.** Las rutas nuevas son adiciones puras. El riesgo de regresión en producción es nulo hasta B-3 y B-10.

---

## 15. ARCHIVOS PREVISTOS

### Modificados
| Archivo | Cambio | Método |
|---|---|---|
| `models.py` | +4 clases: `PuestoEscaner`, `ScanEvento`, `ScanNotificacion`, `BridgeToken` | Append al final |
| `main.py` | +`servicio_entregar_herramienta()`, +4 rutas `/scan/*`, adaptar `movimiento_entregar_post()` | Script ast.parse() |
| `templates/scan.html` | +puesto_id, +scan_event_id, +polling, +Bridge poll, +cámara condicional | Edit preservando compatibilidad |
| `automatizaciones.py` | +3 DELETE de limpieza en tarea programada existente | Append a función existente |

### Creados
| Archivo | Contenido |
|---|---|
| `scanner_bridge/__init__.py` | (vacío) |
| `scanner_bridge/bridge.py` | Proceso principal + HTTP server local |
| `scanner_bridge/rawinput.py` | ctypes Windows Raw Input |
| `scanner_bridge/serial_reader.py` | COM/serie opcional |
| `scanner_bridge/dpapi.py` | DPAPI encrypt/decrypt |
| `scanner_bridge/ui.py` | tkinter diagnóstico |
| `scanner_bridge/config.json` | Plantilla (token_encrypted_b64 vacío) |
| `scanner_bridge/install.ps1` | Instalador HKCU\Run |
| `scanner_bridge/uninstall.ps1` | Desinstalador |
| `scanner_bridge/bridge.spec` | PyInstaller --onefile |
| `tests/test_scan_sprint1.py` | T-CON-*, T-SES-*, T-PER-*, T-IDP-*, T-ROL-*, T-BRI-*, T-CAM-* |

### NO modificados
- `/movimientos/devolver` — gestionado por Codex
- Cualquier ruta de reservas, kits, fotografías, inventario
- `database.py` — solo `models.py` y `apply_migrations` son el contrato

---

## 16. CRITERIOS DE ACEPTACIÓN

1. **T-CON-01**: una sola entrega por herramienta en concurrencia; conflicto claro al segundo.
2. **T-IDP-01/T-IDP-02**: `scan_event_id` duplicado → `ya_procesado`; cero movimientos extra.
3. **T-SES-01**: sesión caducada → 401; sin operación registrada.
4. **T-BRI-01**: Origin incorrecto → 403 del Bridge; sin lectura procesada.
5. **T-BRI-03**: token revocado → Bridge bloqueado; UI informa.
6. **T-CAM-01**: panel de cámara oculto en desktop; sin solicitud de permiso.
7. **T-FIS-03**: dos pistolas físicas, misma herramienta → una OK, otra conflicto visible.
8. Todos los endpoints nuevos responden JSON (nunca RedirectResponse).
9. `movimiento_entregar_post()` sigue devolviendo `RedirectResponse 303` externamente.
10. Cero cambios a rutas de Codex (`/movimientos/devolver`, reservas, kits).

---

## 17. DECISIONES PENDIENTES (requieren confirmación)

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| D-1 | Nombre del `puesto_id` para tabs sin Bridge | UUID por sessionStorage (actual propuesta) vs. UUID fijo por usuario+dispositivo en cookie | sessionStorage — más simple, privacidad preservada |
| D-2 | Nivel de log para `scan_eventos.resultado='conflicto'` | Solo BD vs. también `mrd_logging` | Solo BD — evita ruido en logs de producción |
| D-3 | Reintentos de renovación de `bridge_token` | 1 reintento silencioso vs. mostrar error en UI Bridge | 1 reintento silencioso; error si falla el segundo |

---

## 18. RIESGOS PENDIENTES

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| `CryptProtectData` falla si el perfil de usuario itinerante cambia | Baja | Medio | `--reset-token` en CLI del Bridge; re-registro desde la web |
| Raw Input bloqueado por antivirus | Media | Alto | Modo A como fallback automático; Bridge informa en UI |
| Pistola COM sin terminador conocido | Baja | Medio | `serial_reader.py` configurable: `terminator`, `timeout_ms` |
| `scan_notificaciones` crece si la limpieza falla | Certeza sin limpieza | Bajo | Limpieza en dos capas: automatizaciones + al inicio del proceso |
| Codex modifica `_aplicar_devolucion` durante el Sprint | Media | Bajo | Interfaces separadas; `/scan/operar` llama la función, no la duplica |
| Bridge.exe detectado por Windows Defender (heurística) | Media | Alto | Excluir `%LocalAppData%\MRD\` en política AV de empresa |
