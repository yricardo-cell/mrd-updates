# MRD TOOL CONTROL — Traspaso al servidor de producción

## El sistema

FastAPI + Jinja2 + SQLite corriendo en Windows.
- **PC viejo** (desarrollo): donde se hacen los cambios
- **PC nuevo** (producción): `app.iasmrd.com` — el que usan los trabajadores

---

## Lo que hay que hacer en el PC nuevo AHORA

### 1. Recibir la actualización v2.1.1

La actualización ya está publicada en GitHub:
`https://github.com/yricardo-cell/mrd-updates`

**En el PC nuevo, ejecuta UNA VEZ:**
```
C:\mrd tool\mrd_tool_control\CONFIGURAR_UPDATE_GITHUB.bat
```
Esto cambia el origen de actualizaciones de `app.iasmrd.com` a GitHub.
Luego **reinicia el servidor**.

Después ve a: `http://localhost:8000/actualizaciones`
→ Comprobar → v2.1.1 disponible → **Instalar**

**Qué incluye v2.1.1:**
- Escáner Bluetooth HID: al escanear desde cualquier página, redirige a `/scan` automáticamente
- Página `/scan` auto-busca el código al llegar con `?q=`
- Rediseño EPIs: modales paso a paso para entrega kit/ropa con artículos adicionales
- EPIs individuales: panel "Revisiones pendientes" con formulario inline
- Scripts de publicación de actualizaciones vía GitHub

---

### 2. Emparejar el escáner Inateck Bluetooth

El escáner ya está soportado en la app (modo HID = teclado).

1. Pon el escáner en modo emparejamiento (mantén el botón ~7 seg hasta LED azul parpadeante)
2. Windows → Configuración → Bluetooth → Agregar dispositivo → selecciona Inateck
3. Queda emparejado como teclado Bluetooth, sin drivers
4. Desde cualquier página de la app: escanea → va a `/scan` con el resultado

---

### 3. Pendiente: rotar token Cloudflare

El token de Cloudflare Tunnel hay que rotarlo y reinstalar el servicio con el nuevo token.
(El PC viejo tenía el token expuesto — no usar ese token en producción)

---

### 4. Pendiente: backup automático de la BD

Crear tarea programada en Windows para copiar `mrd_tool.db` con fecha cada día.
Aún no implementado — pedirlo en la próxima sesión.

---

## Arquitectura técnica (para Claude)

| Elemento | Detalle |
|---|---|
| Framework | FastAPI + Jinja2 (templates recargan solos; Python requiere reinicio) |
| BD | SQLite via SQLAlchemy ORM — archivo `mrd_tool.db` |
| Auth | Cookie-based CSRF (`mrd_csrf` + `_csrf_token`) |
| Frontend | Bootstrap 5 + JS vanilla |
| Updates | `updater.py` lee `MRD_UPDATE_SERVER` de `config/local.env` |
| Versión actual | 2.1.1 |

**REGLA CRÍTICA:** Nunca editar `main.py` con Edit tool — solo con scripts Python que usen `ast.parse()` para verificar. El servidor no puede caerse.

### Modelos clave
- `Herramienta` — herramientas con código/serie, estado, movimientos
- `EPIIndividual` — arneses/absorbedores con revisión periódica (tipos: ARNES, ABSORBEDOR)
- `EntregaEPI` — entregas de EPI/ropa a trabajadores
- `StockEPI` — stock de EPIs genéricos en almacén
- `Material` — materiales en almacenes
- `Ubicacion` — sub-ubicaciones dentro de almacenes

### Rutas importantes
- `/scan` — página de escaneo (HID + cámara)
- `/scan/buscar?codigo=X` — API JSON: busca herramienta/maquinaria/material
- `/epis` — gestión EPIs genéricos + ropa
- `/epis/individuales` — arneses y absorbedores con revisiones
- `/actualizaciones` — panel de actualizaciones automáticas

---

## Cómo publicar futuras actualizaciones (desde el PC viejo)

1. Hacer los cambios en el código
2. Ejecutar `PUBLICAR_ACTUALIZACION.bat` en `C:\mrd tool\mrd_tool_control\`
3. Introducir versión (ej: `2.1.2`) y descripción
4. Subir los 2 archivos generados a `github.com/yricardo-cell/mrd-updates`
5. En el PC nuevo: `/actualizaciones` → Comprobar → Instalar

---

## Estado de tareas completadas

- Módulo almacenes: stock, ubicaciones, QR, alertas, inventario express, exportar Excel
- Módulo EPIs: rediseño completo, revisiones pendientes inline, ropa + artículos sueltos
- Dashboard mejorado con KPIs reales
- CSS profesional unificado
- PWA instalable (service worker)
- Sistema tray (icono en bandeja)
- Canal de actualizaciones GitHub
- Escáner Bluetooth HID global
