# Consolidación MRD Tool Control — estado al 06/09/2026

Sesión de consolidación previa a añadir funcionalidad nueva.
Versión al cierre: 2.7.28. Suite: **809 pasan, 10 saltados, 0 fallos**.

---

## Punto de partida

La aplicación tenía 61 archivos de prueba pero nadie sabía si la suite seguía
verde. Resultó que sí (804 pasaban), con 10 *errores de recolección* que llevaban
meses invisibles porque nadie distinguía un error de colección de un fallo.

Principio que guió toda la sesión: **consolidar no es reescribir**. El código que
funciona y no se toca no se rompe. Se construye la red de seguridad y se limpia
solo la superficie donde caerán las funciones nuevas.

---

## Cerrado en esta sesión

**DR4 ya no puede destruir la base de producción.** `repair_center.py` elegía el
`.db` más reciente de `backups/` validándolo solo con `PRAGMA quick_check`, que
comprueba que sea un SQLite sano, no que sea *el nuestro* — y había `.db` de
prueba en esa carpeta. En un failover nocturno podía sobrescribir la base de
Madrid y Barcelona con una de pruebas. Ahora valida la firma del esquema MRD,
pone la BD dañada en cuarentena, **nunca escribe sobre la base viva** y exige
intervención manual.

**Las fotos tienen respaldo por primera vez.** `backup_manager.py` respaldaba
solo la BD. Las fotos de herramientas (`uploads/herramientas/`) y de EPI
(`static/uploads/epis/`, ruta distinta) no entraban en ningún backup, ni en git,
ni en el ZIP de actualización: existían en un único disco. Ahora se empaquetan
junto al backup y la restauración las devuelve a su ruta. Al añadirlo apareció
un fallo previo en `cleanup_old_backups()`, que contaba ficheros en vez de
backups y rompía la retención — corregido.

**La PWA iba dos versiones por detrás.** `CACHE_NAME` en `sw.js` estaba en
2.7.25 con `version.json` en 2.7.27: los navegadores del almacén servían una
versión antigua de la aplicación. Sincronizado. Los tests que comparaban contra
el literal `"2.7.25"` se reescribieron para verificar coherencia entre
`version.json`, `CACHE_NAME` y `config.VERSION` — ya no requieren mantenimiento
en cada bump y detectan el olvido.

**Informes ya no mezcla sedes.** `/informes` llamaba a
`generar_analisis_inteligente(db)` sin `almacen_id`, así que sus tres gráficos
sumaban Madrid y Barcelona (el PDF sí filtraba, de ahí las discrepancias).
Corregido con el patrón de `dashboard()`.

**Auditoría de gráficos:** no hay datos inventados en ninguna pantalla. Ningún
fallback de demo, ningún `Math.random`, ningún array incrustado.

**Sentinel:** `test_sentinel_service.py` describía una arquitectura descartada
que nunca se construyó (servidor HTTP crudo + auth por token + DR4 dentro de
`service.py`). Marcado con `pytest.skip` y el motivo escrito en el archivo. La
implementación vigente sobre FastAPI está cubierta por `test_sentinel_24x7.py`.

---

## Pendiente, por orden

1. **Watchdog — doble conteo.** El modo `check` de `watchdog_mrd.ps1` muta
   estado: `_sqlite_integrity` incrementa `database_failures` en las dos
   llamadas del ciclo `check→apply`, así que el umbral efectivo no es el
   configurado. Corregir la raíz: `check` debe ser inocuo por construcción.
   Severidad baja desde que DR4 no escribe — solo adelanta un aviso.
2. **Etiquetas con prefijo antiguo.** El QR usaba `LA,` por error de origen y se
   corrigió a `MA,`. El software está arreglado, pero las etiquetas ya pegadas
   en las herramientas se imprimieron antes. Hay que localizar cuáles y
   reimprimirlas: ninguna corrección de código las arregla.
3. **Consolidar el rastro de versiones.** 2.7.25 nunca se selló y encima se
   apilaron 2.7.26, 2.7.27 y 2.7.28, escritas por sesiones distintas. Antes de
   publicar hay que fundirlas en entradas que digan de verdad qué llevan dentro;
   hoy no hay un punto de retorno claro.
4. **Verificar en dispositivo real** del almacén que la PWA muestra la versión
   nueva. Varios síntomas sospechados (escáner, fotos) podrían ser clientes con
   la versión cacheada antigua, no bugs.
5. **Fotos: síntoma sin explicar.** Que no hubiera respaldo explica poder
   *perderlas*, no que "no se mantengan" durante el uso. Falta reproducir:
   ¿desaparecen al subirlas, al recargar, tras reiniciar, o solo a algunos
   usuarios? ¿Herramientas, EPI o ambas?
6. **Simulacro de restauración.** Una copia que nadie ha restaurado nunca es una
   hipótesis. Restaurar sobre una copia del proyecto y comprobar que vuelven las
   fotos y la BD.

---

## Diseño aprobado: solicitudes del portal del trabajador

Pendiente de `/ecc:plan` antes de implementar.

- **Un solo flujo de estados**: `recibida → en_preparación → lista → entregada`,
  más `cancelada` y `parcial`. Conviven quien pide y recoge después y quien
  espera en el mostrador (recorre los estados rápido). Extender el esquema
  actual sin romper `test_solicitud_compatibilidad_esquema_antiguo.py`.
- **Entrega parcial desde el diseño inicial**: piden 5, hay 3; se entregan 3 y
  las 2 restantes siguen vivas en la solicitud.
- **Aviso a todos los usuarios de ese almacén**, filtrado por `almacen_id`,
  nunca cruzado entre sedes, y accionable (abre la solicitud). Agrupar si llegan
  varias seguidas. Reutilizar `push_service.py` y `notificaciones.py`.
- **La salida no crea un segundo camino**: la solicitud se precarga en Mostrador
  Único, el almacenero escanea para confirmar lo realmente entregado y el
  albarán sale por la vía existente, conservando la idempotencia por `event_id`.
  Construir una entrega paralela garantiza que ambas diverjan.
- Aviso al trabajador al pasar a `lista`. Vista de pendientes del almacén para
  preparar por lotes. Las partes visuales, con mockup previo (regla 5).

### Comando para arrancarlo

Pegar tal cual en una ventana de Claude Code, en la carpeta del proyecto. Genera
el plan, no toca código. Revisar el plan resultante antes de aprobar nada.

```
/ecc:plan Notificación y salida de solicitudes del portal del trabajador.

Un solo flujo de estados: recibida → en_preparación → lista → entregada, más
cancelada y parcial. Los dos casos conviven: quien pide y recoge después, y
quien espera en el mostrador (recorre los estados rápido). Extender el esquema
actual sin romper test_solicitud_compatibilidad_esquema_antiguo.py.

Al crear una solicitud, emitir evento que notifique por push a todos los
usuarios con acceso a ese almacén, aislado por almacen_id, con enlace que abra
la solicitud. Agrupar avisos si llegan varias seguidas. Reutilizar
push_service.py y notificaciones.py, no crear infraestructura nueva.

La salida NO debe crear un segundo camino de entrega: la solicitud se precarga
en Mostrador Único con sus líneas, el almacenero escanea para confirmar lo
realmente entregado y el albarán se genera por la vía existente, conservando la
idempotencia por event_id. Soportar entrega parcial: lo no entregado sigue
pendiente en la solicitud.

Avisar al trabajador cuando su solicitud pase a "lista". Añadir vista de
solicitudes pendientes del almacén para preparar por lotes.

Divide en tandas pequeñas, una por cambio, cada una con su prueba de regresión.
Las partes visuales, con mockup previo según la regla 5 del CLAUDE.md.
```

---

## Reglas de trabajo que salieron de esta sesión

**Una sola ventana escribe.** Varias ventanas de escritura sobre la misma
carpeta no dan paralelismo: se turnan sobre `version.json` y solo añaden
coordinación. Las ventanas extra rinden para lectura — auditar, buscar,
informar. Ya provocó dos bumps simultáneos y un test roto.

**Una prueba de regresión vale si falla sin el fix.** Verificar siempre
revirtiendo el cambio; si pasa igual, no prueba nada.

**Arreglar la causa, no el número.** El doble conteo no se parchea restando uno:
el fallo es que un modo de comprobación mute estado.

**Cero fallos en la suite, siempre.** Un rojo permanente enseña a ignorar los
rojos, y así estuvieron los 10 errores de Sentinel durante meses.

**Lo que se toca es donde aparecen los fallos viejos.** El bug de retención en
`cleanup_old_backups()` llevaba tiempo ahí y solo se vio al añadirle las fotos.

### Skills creadas en `.agents/skills/`

- `auditoria-regresion` — comprueba si los fixes de `version.json` tienen prueba.
- `auditoria-graficos` — audita el origen de los datos de gráficos y KPIs.
- `ventanas-paralelas` — coordina varias sesiones sobre la misma carpeta
  mediante `TRABAJO_EN_CURSO.md`.
