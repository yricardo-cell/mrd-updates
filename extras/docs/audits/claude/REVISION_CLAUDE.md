# Revisión Claude — MRD Tool Control
**Fecha:** 2026-08-19 · **Auditor:** Claude (solo lectura, sin modificaciones)
**Alcance:** templates, navegación, UX móvil, formularios, accesibilidad, flujos

---

## 🔴 CRÍTICO — Errores que pueden perder datos o bloquear el trabajo

---

### C-1 · `incidencias.html` — Mismatch de estado en filtros KPI
**Pantalla:** `/incidencias`
**Problema:** Los KPI cards llaman a `filtrarEstado('en_proceso')` (línea 34) pero el `<select>` de filtro tiene `value="en_curso"`. Cuando el responsable hace clic en "En proceso" para ver incidencias activas, el filtro JS compara `row.dataset.estado === 'en_proceso'` pero el select busca `en_curso`. El resultado: el filtro no muestra nada aunque haya registros.
**Efecto:** El responsable cree que no hay incidencias en proceso → puede dejar incidencias críticas sin atender.
**Solución:** Unificar el valor de estado: cambiar el `<option value="en_curso">` a `value="en_proceso"` o viceversa, asegurándose de que coincida con lo que guarda el backend.

---

### C-2 · `scan.html` — Select de trabajadores vacío si el servicio no se ha reiniciado
**Pantalla:** `/scan` — Modal de entrega rápida
**Problema:** Se añadió `trabajadores` al route `/scan` en `main.py` (parche reciente de Claude). Si el servicio **no se ha reiniciado** desde ese parche, el template recibe `trabajadores=undefined` y el `<select>` del modal aparece vacío. Una entrega enviada sin trabajador seleccionado puede grabarse con `responsable_id=None` o causar un 422 del backend.
**Efecto:** El responsable hace una entrega, parece que funciona (toast verde), pero el movimiento queda sin asignar o no se graba.
**Solución:** Reiniciar el servicio MRDToolControl después del parche. Verificar en la BD que los últimos movimientos tienen `responsable_id` correcto.

---

### C-3 · `trabajadores.html` — Sin paginación ni búsqueda; carga masiva sin límite
**Pantalla:** `/trabajadores`
**Problema:** El template muestra **todos** los trabajadores en tarjetas sin paginación, sin búsqueda y sin límite. El backend ejecuta `db.query(Trabajador).order_by(Trabajador.nombre).all()`. En empresas con 100+ trabajadores, la página carga todo en memoria y puede tardar varios segundos o agotar la sesión SQLite.
**Efecto:** Página lenta o inaccesible en empresas medianas. En móvil con conexión 4G, puede time-out.
**Solución:** Añadir `<input>` de búsqueda JS en el lado cliente (inmediato, sin backend), y opcionalmente paginación server-side. Mínimo: filtro JS por nombre.

---

### C-4 · `nueva_herramienta.html` — Grid de 4 columnas sin breakpoint móvil
**Pantalla:** `/herramientas/nueva`
**Problema:** La sección "Datos técnicos" usa `grid-template-columns:repeat(4,1fr)` (línea 128) sin `@media` query. En pantallas de menos de 600px los inputs de Potencia, Voltaje, Peso y Color quedan con ~60px de ancho — ilegibles e inutilizables. El campo queda tan estrecho que el placeholder no cabe.
**Efecto:** En móvil el formulario de creación de herramientas es inutilizable en la sección técnica. Los datos se introducen mal o no se introducen.
**Solución:** Cambiar a `repeat(2,1fr)` en mobile: `@media(max-width:600px){ grid-template-columns:1fr 1fr; }` o usar `repeat(auto-fit,minmax(120px,1fr))`.

---

## 🟠 IMPORTANTE — Problemas claros de funcionamiento o usabilidad

---

### I-1 · `herramientas.html` — Búsqueda en tiempo real engañosa (solo página actual)
**Pantalla:** `/herramientas`
**Problema:** Al escribir en el buscador, el JS filtra **solo las filas de la página actual** al instante; tras 600ms sin escribir hace un `form.submit()` al servidor. Si hay 300 herramientas y se muestra la página 1 (25 filas), el usuario busca "taladro" y ve 2 resultados inmediatos → cree que solo hay 2 → los 45 restantes en otras páginas no aparecen hasta que el servidor responde.
**Efecto:** El responsable puede creer que una herramienta "no existe" y registrarla duplicada.
**Solución:** Eliminar el filtro JS instantáneo o añadir un aviso "Buscando en página actual... espera..." + lanzar el submit del servidor inmediatamente al escribir (con debounce de 300ms).

---

### I-2 · `trabajadores.html` — Sin enlace desde el badge de herramientas
**Pantalla:** `/trabajadores`
**Problema:** Cada tarjeta muestra `<span class="badge bg-warning">3 herramientas</span>` pero no es clicable. Para saber qué herramientas tiene un trabajador hay que ir a `/herramientas?responsable=X` manualmente o a la ficha del trabajador si existe.
**Efecto:** El almacenero no puede ver en un clic qué lleva un trabajador. Flujo lento para control de préstamos.
**Solución:** Hacer el badge un enlace: `<a href="/herramientas?trabajador={{ t.id }}">{{ cnt }} herramienta(s)</a>`.

---

### I-3 · `portal_trabajador.html` — CDN externo sin fallback
**Pantalla:** `/portal-trabajador/{token}`
**Problema:** El portal del trabajador carga Bootstrap 5.3 y Bootstrap Icons desde `cdn.jsdelivr.net` (líneas 7-8). El resto del sistema usa archivos **locales** en `/static/css/`. Si el servidor Windows no tiene salida a internet (frecuente en instalaciones de taller), el portal queda sin estilos ni iconos.
**Efecto:** El trabajador ve su portal sin formato. Texto plano sin layout.
**Solución:** Cambiar las URLs de CDN a rutas locales: `/static/css/bootstrap.min.css` y `/static/css/bootstrap-icons.min.css`.

---

### I-4 · `portal_trabajador.html` — Sin herramientas asignadas
**Pantalla:** `/portal-trabajador/{token}`
**Problema:** El portal muestra EPIs, formación y reconocimiento médico pero **no muestra las herramientas** que tiene el trabajador en préstamo. El trabajador no puede saber qué lleva registrado a su nombre.
**Efecto:** Discrepancias no detectadas entre lo que el trabajador cree que lleva y lo que el sistema registra. No hay forma de que el trabajador confirme su inventario.
**Solución:** Añadir sección "Herramientas a mi cargo" en el portal mostrando código, nombre y estado de cada herramienta asignada.

---

### I-5 · `movimiento_entregar.html` — Entrega en batch sin confirmación
**Pantalla:** `/movimientos/entregar`
**Problema:** Al seleccionar múltiples herramientas y pulsar "Entregar X herramientas", el JS ejecuta un `fetch()` loop sin modal de confirmación. No hay "¿Estás seguro?" ni vista previa del lote.
**Efecto:** Un clic accidental con 20 herramientas seleccionadas registra todas como entregadas. No hay forma de deshacer desde la interfaz.
**Solución:** Mostrar un modal de confirmación con la lista de herramientas seleccionadas antes de ejecutar el batch.

---

### I-6 · `incidencias.html` — Sin vista de detalle de incidencia
**Pantalla:** `/incidencias`
**Problema:** La lista de incidencias tiene botón "Editar" (modal inline) y "Cerrar", pero no hay enlace a una ficha completa de la incidencia. La descripción se trunca a 60 caracteres (línea 95). No hay historial de cambios visible.
**Efecto:** Si una incidencia tiene una descripción larga o historial de actuaciones, el responsable no puede leerla completa desde esta pantalla.
**Solución:** Añadir enlace a `/incidencias/{id}` para ver ficha completa con historial.

---

### I-7 · `base.html` — Sidebar de 30+ ítems sin agrupación colapsable en móvil
**Pantalla:** Todas (sidebar)
**Problema:** El sidebar tiene 30 enlaces en 6 secciones. En móvil (si el sidebar es un overlay), el usuario tiene que hacer scroll significativo para llegar a "Mantenimiento" o "Notificaciones". No hay secciones colapsables.
**Efecto:** En móvil, navegar a funciones de la parte inferior requiere scroll largo. Usuarios que no conocen la app pueden no encontrar funciones.
**Solución:** En pantallas <768px, colapsar las secciones menos usadas (Automatización, Sistema) por defecto. O reducir los ítems visibles añadiendo una sección "Más".

---

### I-8 · `herramientas.html` — Tabla de 10 columnas inutilizable en móvil
**Pantalla:** `/herramientas`
**Problema:** La tabla tiene 10 columnas (checkbox, foto, código, nombre, categoría, marca/modelo, estado, ubicación, responsable, acciones). Con `overflow-x:auto` es desplazable pero no usable con el pulgar en móvil. Las columnas más importantes (código, nombre, estado) no tienen prioridad visual.
**Efecto:** El almacenero en móvil tiene que hacer scroll horizontal para ver el estado o el responsable. Muy lento en el día a día.
**Solución:** En móvil, ocultar columnas no esenciales (categoría, marca/modelo, ubicación) y mostrar un layout de tarjeta por fila o 4-5 columnas prioritarias.

---

## 🟡 MEJORA — Diseño, facilidad de uso y productividad

---

### M-1 · `login.html` — Sin "Recordar usuario"
**Pantalla:** `/login`
**Problema:** No hay opción de recordar el usuario. En móvil, el teclado virtual hace el login tedioso si se repite varias veces al día.
**Solución:** Añadir `<input type="checkbox" name="remember">` para mantener la sesión por más tiempo (ej. 30 días). Requiere cambio en backend.

---

### M-2 · `dashboard.html` — KPIs duplicados entre hero y grid
**Pantalla:** `/`
**Problema:** El hero banner muestra Total, Disponibles, En obra y Extraviados. El grid de KPIs justo debajo repite Total, Disponibles, En obra, En reparación, Furgoneta. Los primeros 3 KPIs están duplicados.
**Solución:** En el hero, mostrar solo los datos de bienvenida (empresa, hora). En el grid, los KPIs operativos. Eliminar los mini-KPIs del hero o mostrar solo incidencias y alertas (datos únicos).

---

### M-3 · `nueva_herramienta.html` — Formulario con demasiados campos opcionales visibles
**Pantalla:** `/herramientas/nueva`
**Problema:** El formulario muestra 20+ campos opcionales desde el principio: subcategoría, familia, fabricante, potencia, voltaje, peso, color, dimensiones, activo fijo, vida útil. Para el 80% de los registros solo se necesitan código, nombre, categoría, marca y modelo.
**Solución:** Colapsar la sección "Datos técnicos" (potencia, voltaje, peso, color, dimensiones) y "Datos contables" (activo fijo, vida útil, número de factura) en un acordeón "Datos avanzados (opcional)" cerrado por defecto.

---

### M-4 · `base.html` — Hint "Ctrl K" no tiene sentido en móvil
**Pantalla:** Todas (header)
**Problema:** El buscador global muestra `<span class="search-kbd">Ctrl K</span>`. En móvil no hay teclado físico y el shortcut no funciona.
**Solución:** Ocultar el hint en móvil: `@media(max-width:768px){ .search-kbd{ display:none; } }`.

---

### M-5 · `trabajadores.html` — Diseño visual inconsistente con el resto
**Pantalla:** `/trabajadores`
**Problema:** Esta pantalla usa clases Bootstrap antiguas (`d-flex`, `col-sm-6`, `col-lg-4`, `gap-2`, `btn-warning`, `mrd-card`, `mrd-worker-card`) mientras el resto del sistema usa el design system MRD (`btn btn-primary`, `page-header-row`, `card`, etc.). El botón "Nuevo trabajador" es amarillo (Bootstrap warning) en lugar de azul primario.
**Solución:** Rediseñar la pantalla con el design system MRD: usar `page-header-row`, `card`, `btn btn-primary`, y el grid system propio en lugar del grid Bootstrap.

---

### M-6 · `scan.html` — Torch no soportado en iOS sin aviso claro
**Pantalla:** `/scan`
**Problema:** La API `applyConstraints({advanced:[{torch:true}]})` no está soportada en Safari/iOS. El botón de linterna solo se muestra si `caps.torch` es verdadero, pero en iOS `caps.torch` puede devolver `undefined` o `false` sin mensaje de error al usuario.
**Solución:** Cuando el dispositivo no soporta torch, mostrar un mensaje: "Linterna no disponible en este dispositivo. Usa la linterna nativa del teléfono."

---

### M-7 · `incidencias.html` — Sin filtro por herramienta o trabajador
**Pantalla:** `/incidencias`
**Problema:** Solo hay filtros por estado, prioridad y búsqueda de texto. No hay filtro por herramienta específica ni por responsable. Para ver todas las incidencias de un taladro concreto hay que buscar su nombre en el buscador de texto.
**Solución:** Añadir `<select>` de herramienta (con datalist si son muchas) y filtro por responsable/trabajador.

---

### M-8 · `portal_trabajador.html` — Sin acceso a QR del trabajador desde el portal
**Pantalla:** `/portal-trabajador/{token}`
**Problema:** El portal muestra información personal pero no ofrece el QR del trabajador para que pueda identificarse en el almacén sin necesitar al administrador.
**Solución:** Mostrar el QR de identificación del trabajador al inicio del portal, bajo el avatar, para que lo pueda presentar directamente.

---

### M-9 · `movimiento_devolver.html` — Condición de herramienta no recordada entre sesiones
**Pantalla:** `/movimientos/devolver`
**Problema:** El selector de condición (buena/requiere revisión/dañada) se resetea con cada devolución en batch. Si se devuelven 5 herramientas en condición "requiere revisión", el responsable tiene que seleccionar la condición en cada modal o en el formulario de cada herramienta.
**Solución:** Recordar la última condición seleccionada en la sesión (localStorage o variable JS) para agilizar las devoluciones repetitivas.

---

### M-10 · General — Falta botón "Volver arriba" en páginas largas
**Pantalla:** `/herramientas`, `/trabajadores`, `/historial`, `/incidencias`
**Problema:** En páginas con tablas o listados largos no hay botón "volver arriba". En móvil, el usuario debe hacer scroll largo para volver al filtro o al header.
**Solución:** Añadir en `base.html` un botón flotante `↑` que aparece al hacer scroll >300px.

---

## Resumen ejecutivo

| Prioridad | Nº | Acción inmediata |
|---|---|---|
| 🔴 CRÍTICO | 4 | Mismatch estado incidencias, select vacío en scan, sin búsqueda en trabajadores, grid 4col en móvil |
| 🟠 IMPORTANTE | 8 | CDN externo portal, sin herramientas en portal, sin confirmación batch, tabla móvil, sidebar largo |
| 🟡 MEJORA | 10 | Diseño trabajadores, campos ocultos nueva herramienta, KPIs duplicados, torch iOS, filtros incidencias |

**Pantallas que más urgen rediseño:**
1. `trabajadores.html` — Diseño Bootstrap legacy + sin búsqueda
2. `incidencias.html` — Bug de filtro estado + sin ficha detalle
3. `nueva_herramienta.html` — Formulario abrumador en móvil
4. `portal_trabajador.html` — CDN externo + sin herramientas

**Pantallas en buen estado (recién rediseñadas):**
- `scan.html` ✅, `mantenimiento.html` ✅, `informes.html` ✅, `historial.html` ✅, `movimiento_entregar.html` ✅, `movimiento_devolver.html` ✅

---
*Generado por Claude — revisión de lectura sin modificaciones al código.*
