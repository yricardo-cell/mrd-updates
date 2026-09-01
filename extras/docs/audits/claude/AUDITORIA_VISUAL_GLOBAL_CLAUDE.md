# AUDITORÍA VISUAL GLOBAL — MRD Tool Control
**Alcance:** templates/*.html + static/css/mrd.css | **Modo:** solo lectura | **Máx. 1500 palabras**

---

## 1. Los 15 Problemas Visuales Más Importantes

**[P-01] URGENTE — Clases MRD fantasma en epis.html y trabajadores.html**
`mrd-page-header`, `mrd-card`, `mrd-btn`, `mrd-input`, `mrd-worker-card`, `mrd-worker-avatar`, `mrd-worker-name`, `mrd-worker-role`, `mrd-worker-inactive`, `kpi-val` — ninguna existe en mrd.css. Estas pantallas se renderizan sin estilo propio; dependen del CSS base del navegador.

**[P-02] URGENTE — Doble definición de `.firma-canvas-wrap` con valores contradictorios**
mrd.css líneas 1092 y 1205: alturas 140px vs 120px, colores de borde distintos. El navegador aplica la última definición; la primera es letra muerta. Puede romper el canvas de firma dependiendo del orden de carga.

**[P-03] URGENTE — Bloque de código huérfano (error de sintaxis CSS)**
mrd.css líneas 1121-1123: `color: var(--text); text-decoration: none !important; transition: background .1s;` flotando fuera de cualquier selector. Esto aplica a TODOS los elementos del documento en navegadores permisivos, con efecto impredecible sobre links y transiciones.

**[P-04] URGENTE — `var(--secondary)` referenciado pero no definido**
herramientas.html línea 52 usa `var(--secondary)` que no existe en mrd.css. Resultado: el color cae a `initial` (negro en fondo oscuro, blanco en claro) según el tema del navegador.

**[P-05] URGENTE — Chart.js cargado en `extra_css` en lugar de `extra_js`**
informes.html inyecta el `<script>` de Chart.js dentro del bloque `extra_css`. Según cómo base.html construya el head/body, el script puede ejecutarse antes del DOM o nunca. Los gráficos pueden fallar silenciosamente.

**[P-06] MEJORABLE — Dos sistemas de login en paralelo**
mrd.css define `.login-card`/`.login-brand` (líneas 939-969) Y `.mrd-login-page`/`.mrd-login-card` (líneas 1017-1061). Si login.html usa el primer sistema, el segundo es peso muerto; si usa el segundo, el primero es basura. Duplica ~120 líneas de CSS.

**[P-07] MEJORABLE — Hero del dashboard con ~15 `style=` inline y JS inline**
dashboard.html concentra toda su lógica visual en atributos `style=""` y manejadores `onmouseover`/`onmouseout` directamente en el HTML. Imposible mantener en modo oscuro; duplica lógica con el KPI grid debajo.

**[P-08] MEJORABLE — KPIs duplicados en dashboard.html**
Mini KPIs dentro del hero banner + bloque `.kpi-grid` separado muestran los mismos datos. En pantallas pequeñas ambos son visibles al mismo tiempo, confundiendo la jerarquía visual.

**[P-09] MEJORABLE — Clases `search-drop-*` sin selector de contexto**
mrd.css líneas 1124-1147: `.search-drop-item`, `.search-drop-item:hover`, etc. sin selector padre. Cualquier elemento con esa clase en cualquier parte del DOM hereda los estilos, incluyendo páginas donde no hay buscador.

**[P-10] MEJORABLE — Sidebar con 25+ ítems sin agrupación visual clara**
base.html lista 6 secciones y más de 25 nav-items en un sidebar sin separadores visuales consistentes. En viewport < 1200px, la densidad provoca clics erróneos y scroll excesivo.

**[P-11] MEJORABLE — Badge de avisos con 6 propiedades inline en base.html**
El contador de notificaciones usa `style="..."` completo en lugar de una clase `.badge-notification` en mrd.css. Reutilizar ese patrón en otra pantalla requiere copiar el string de estilos.

**[P-12] MEJORABLE — movimiento_entregar.html construido 100% con inline styles**
Las tarjetas de selección de herramienta, la barra de selección y el layout de dos columnas usan exclusivamente `display:grid` y propiedades inline. Ninguna clase MRD. El modo oscuro no tiene efecto.

**[P-13] MEJORABLE — informes.html con KPI cards y alertas 100% inline**
Mismo patrón que movimiento_entregar.html pero en la pantalla de informes. Los bloques de alerta ignoran completamente las variables CSS del sistema de diseño.

**[P-14] MEJORABLE — Enlace "¿Qué está fuera?" con gradient inline hardcoded**
base.html tiene `background:linear-gradient(90deg,rgba(255,193,7,.15),transparent)` directamente en el atributo `style`. En tema oscuro, el amarillo puede no tener suficiente contraste.

**[P-15] CORRECTA (riesgo latente) — Mezcla Bootstrap nativo + MRD en epis/trabajadores**
Ambas plantillas usan `badge bg-success`, `badge bg-secondary`, `badge bg-warning text-dark` (Bootstrap puro) y `table table-hover` en lugar de las clases MRD equivalentes. Si se actualiza Bootstrap, los colores cambiarán independientemente del Design System.

---

## 2. Las 10 Pantallas a Modernizar Primero

| Prioridad | Pantalla | Razón |
|-----------|----------|-------|
| 1 | **epis.html** | Todas las clases MRD son fantasma; render roto |
| 2 | **trabajadores.html** | Mismo problema; clases de avatar/rol inexistentes |
| 3 | **informes.html** | Script en bloque CSS + todo inline; gráficos en riesgo |
| 4 | **movimiento_entregar.html** | 0% clases MRD; modo oscuro no funciona |
| 5 | **dashboard.html** | 15+ inline styles + JS inline + KPIs duplicados |
| 6 | **herramientas.html** | `var(--secondary)` no definida; KPI inline parcial |
| 7 | **login.html** | Sistema de login duplicado; peso muerto en CSS |
| 8 | **historial.html** | No auditada; probable mezcla de sistemas por patrón visto |
| 9 | **mantenimiento.html** | No auditada; alta complejidad de estados visuales |
| 10 | **scan.html** | No auditada; pantalla PWA crítica para uso móvil |

`nueva_herramienta.html` es la referencia de buena práctica — úsala como plantilla base para el resto.

---

## 3. Sistema Visual Recomendado

### Variables CSS (ya definidas — estandarizar uso)
```
--primary    → acciones principales, CTA
--surface    → fondos de tarjeta
--bg         → fondo de página
--text       → texto base
--border     → separadores
```
**Añadir obligatoriamente:** `--secondary` (actualmente ausente; referenciada en código).

### Tipografía
Inter (ya cargada desde Google Fonts). Jerarquía: `1.125rem/600` para títulos de sección, `0.875rem/400` para datos de tabla, `0.75rem` para etiquetas y badges.

### Tarjetas
Usar exclusivamente `.card` + `.card-header` + `.card-body` de mrd.css. Eliminar cualquier `<div style="border-radius:...background:...">` en HTML.

### Botones
Consolidar en `.btn-primary`, `.btn-secondary`, `.btn-danger` de mrd.css. Eliminar variantes `mrd-btn` y cualquier `<button style="...">`.

### Tablas
Migrar todas las tablas a `.smart-table` de mrd.css. Eliminar `table-hover align-middle` de Bootstrap donde Bootstrap no es la fuente de verdad.

### Estados y Badges
Definir en mrd.css: `.badge-activo`, `.badge-inactivo`, `.badge-pendiente`, `.badge-alerta`. Eliminar dependencia directa de `bg-success`, `bg-warning`, `bg-secondary` de Bootstrap.

### KPIs
Usar siempre `.kpi-card` + `.kpi-icon` + `.kpi-value` + `.kpi-label`. Nunca duplicar KPIs en la misma pantalla.

---

## 4. Plan de Sprints Visuales

### Sprint Visual 1 — Correcciones de emergencia (CSS puro, sin tocar lógica)
1. Eliminar bloque huérfano líneas 1121-1123 de mrd.css
2. Deduplicar `.firma-canvas-wrap` (conservar una definición, la mayor)
3. Deduplicar sistema de login (conservar `.mrd-login-page`, eliminar `.login-card`)
4. Añadir `--secondary` a las variables CSS raíz
5. Añadir las clases ausentes usadas en epis/trabajadores: `mrd-page-header`, `mrd-card`, badges de estado
6. Mover Chart.js a bloque `extra_js` en informes.html

**Riesgo:** Bajo. Solo mrd.css y bloques de script. Cero cambios de lógica.

### Sprint Visual 2 — Migración de inline styles (pantallas críticas)
1. **epis.html + trabajadores.html:** Sustituir clases fantasma por equivalentes MRD reales
2. **informes.html:** Convertir KPI cards y alertas a clases MRD
3. **movimiento_entregar.html:** Extraer layout a clases CSS; mantener JS intacto
4. **dashboard.html:** Eliminar inline styles del hero; eliminar KPI duplicado; llevar hover a CSS

**Riesgo:** Medio. Requiere verificar que las nuevas clases CSS no rompan breakpoints existentes. Probar en resolución 768px y 1440px.

### Sprint Visual 3 — Consistencia global y optimización
1. Auditar historial.html, mantenimiento.html, scan.html, incidencias.html, portal_trabajador.html, albaran_detalle.html
2. Migrar todos los badges Bootstrap restantes a clases MRD
3. Consolidar `search-drop-*` bajo selector de contexto (`.sidebar .search-drop-item`)
4. Revisar sidebar: añadir separadores visuales, posible colapsado por sección
5. Reemplazar gradient inline del enlace "¿Qué está fuera?" con clase `.nav-highlight`
6. Reemplazar badge de avisos inline con clase `.badge-notification`

**Riesgo:** Bajo-medio. El sidebar afecta todas las pantallas autenticadas.

---

## 5. Riesgos de Romper Funcionalidad

| Riesgo | Pantalla | Descripción |
|--------|----------|-------------|
| **Alto** | informes.html | Chart.js en bloque `extra_css` puede no ejecutarse; corregir con cuidado de orden de carga |
| **Alto** | Formularios de firma | Deduplicar `.firma-canvas-wrap` puede cambiar el alto del canvas activo; verificar JS que dependa de `offsetHeight` |
| **Medio** | movimiento_entregar.html | La barra de selección usa `display:none` inline + JS toggle; al migrar a clase CSS, el toggle JS debe apuntar a la clase, no al atributo `style` |
| **Medio** | base.html sidebar | Cualquier cambio estructural en nav-items puede romper el JS de detección de ruta activa |
| **Bajo** | epis.html / trabajadores.html | Añadir clases MRD reales no rompe lógica; solo añade estilos que antes faltaban |
| **Bajo** | dashboard.html hero | Eliminar `onmouseover`/`onmouseout` y mover a CSS `:hover` es seguro; verificar que no haya JS externo que llame a esos handlers |

---

## 6. Resumen Final

mrd.css tiene tres bugs activos: código huérfano, doble definición de canvas y variable `--secondary` ausente. Epis y trabajadores renderizan sin estilo MRD real. Informes carga Chart.js en el bloque incorrecto. La mitad de las plantillas ignoran el Design System y usan inline styles incompatibles con el tema oscuro. `nueva_herramienta.html` es la única plantilla ejemplar. Sprint 1 es CSS puro de bajo riesgo y resuelve los bugs críticos. Sprints 2 y 3 son migración progresiva sin tocar lógica de negocio.
