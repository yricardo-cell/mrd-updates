# BASELINE — MRD TOOL CONTROL v1.1.2

**Fecha:** 2026-07-12  
**Versión congelada:** v1.1.2-base  
**Estado:** Funcional — en revisión para Fase 2  
**Archivo de restauración:** `MRD_TOOL_CONTROL_BASE_ESTABLE_v1.1.2.zip`

---

## Cómo restaurar esta versión

1. Detener el servidor: cerrar la ventana de INICIAR_MRD.bat o ejecutar `kill_port8000.bat`
2. Hacer backup previo de `data/mrd_tool_control.db`
3. Descomprimir `MRD_TOOL_CONTROL_BASE_ESTABLE_v1.1.2.zip` sobre `C:\mrd tool\mrd_tool_control\`
4. Sobrescribir todos los archivos excepto `data/`, `backups/`, `uploads/`
5. Reiniciar con `INICIAR_MRD.bat`

**NUNCA modificar el archivo ZIP de baseline.**

---

## Funciones existentes en esta versión

### Autenticación
- Login con JWT en cookie httponly, samesite=lax, 8h de sesión
- Logout limpia cookie
- Cambio de contraseña desde perfil
- 4 roles: admin, almacen, encargado, consulta

### Herramientas
- CRUD completo (crear, editar, dar de baja)
- Paginación (25/página), filtros por estado y categoría
- Acciones: entregar, devolver, reparar, mover
- Subida de foto
- Generación de código automático (MRD-YYYYMMDD-NNNN)

### Movimientos
- Historial completo con paginación
- Entrega y devolución desde formularios
- Registro de trabajador, obra, destino, observaciones

### Inventario de apoyo
- Trabajadores, Obras, Almacenes, Vehículos, Proveedores, Materiales
- Incidencias y Reparaciones
- Documentos adjuntos

### Etiquetas
- PDF con Code128 + QR (tamaño 38×25mm)
- ZPL para Zebra ZT231
- Descarga individual o lote

### Acceso remoto
- Panel dedicado en /acceso-remoto
- Detección automática: Cloudflare Tunnel, ngrok, Tailscale, red local
- QR de acceso móvil
- Configuración avanzada por administrador
- Endpoints: /api/remote-access/status|config|test|qr|restart

### Escáner QR
- Página /scan — acceso público (sin login)
- ZXing lazy-loaded (no bloquea página)
- Compatible con cámara de móvil

### Informes
- Excel: inventario y movimientos

### Backups
- Manual desde Configuración
- Descarga del archivo
- Restauración desde panel

### Sistema
- Actualizador desde ZIP en releases/
- Empaquetador de release
- Servicio Windows (INSTALAR_SERVICIO.bat / SERVICIO_MRD.ps1)
- Scripts: inicio, parada, desinstalación

---

## Errores conocidos en esta versión

| # | Severidad | Descripción |
|---|-----------|-------------|
| 1 | CRÍTICO | Path traversal en descarga de backup — `nombre` no sanitizado |
| 2 | CRÍTICO | Sin protección contra fuerza bruta en /login |
| 3 | ALTO | `psutil` en requirements.txt pero no instalado — /api/system/stats falla |
| 4 | ALTO | Sin sistema de logs — errores silenciosos |
| 5 | ALTO | Cookie sin `secure=True` — inseguro sobre HTTPS |
| 6 | ALTO | No existe endpoint /health |
| 7 | ALTO | No existe PWA / manifest / service worker |
| 8 | MEDIO | JWT sub inconsistente: se guarda como username, pero login_get lo parsea como int |
| 9 | MEDIO | app.js y mrd.js con funciones duplicadas (Toast, Sidebar) |
| 10 | MEDIO | static/css/styles.css — solo en login.html, no integrado |
| 11 | MEDIO | VERSION en config.py = "1.0.0" pero version.json = "1.1.2" |
| 12 | MEDIO | fonts duplicados: static/fonts/ y static/css/fonts/ |
| 13 | MEDIO | services/motor_auditoria.py y motor_movimientos.py no usados |
| 14 | MEDIO | Sin manejo global de errores 500 |
| 15 | BAJO | Imports dentro de funciones (threading, jose, zipfile) |
| 16 | BAJO | /api/stats repite 4 COUNT queries sin optimizar |
| 17 | BAJO | movimientos excel sin paginación (limit hardcoded 5000) |

---

## Archivos principales

```
main.py              — 2004 líneas — router principal FastAPI
models.py            — 515 líneas  — modelos SQLAlchemy
database.py          — 162 líneas  — engine + migraciones
auth.py              — 80 líneas   — JWT + permisos
config.py            — 68 líneas   — configuración global
remote_access.py     — 649 líneas  — detección multi-proveedor
backups.py           — 78 líneas   — copia de seguridad
updater.py           — 144 líneas  — actualizador desde ZIP
reports.py           — 229 líneas  — exportación Excel
label_printer.py     — 196 líneas  — PDF + ZPL etiquetas
codigos.py           — 81 líneas   — QR + Code128
```

---

*Esta copia nunca debe modificarse.*
