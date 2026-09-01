# PAQUETE OPERATIVO DE ALMACÉN — MRD TOOL CONTROL
**Versión:** 1.0 · **Fecha:** 2026-08-20  
**Para:** Encargado de Patio y equipo de implantación · **Sprint:** 5.4

---

## 1. Flujo Diario del Encargado de Patio

### 1.1 Recepción de suministros (llegada de pedido)

1. Abrir **Almacén → Recepción** en el panel.
2. Buscar el pedido por número o proveedor.
3. Comprobar físicamente las unidades recibidas versus las esperadas.
4. Si todo cuadra → **Confirmar recepción completa**.  
   Si hay diferencia → registrar cantidad real y marcar la línea como **recepción parcial con incidencia**.
5. El sistema suma el stock automáticamente al confirmar.
6. Imprimir etiquetas para los artículos nuevos (ver sección 5).
7. Colocar los artículos en su ubicación y pegar la etiqueta en el lugar visible.

**Resultado esperado:** El stock queda actualizado; el pedido aparece como "Recibido" o "Recibido parcial".

---

### 1.2 Alta de artículo nuevo o entrada de artículo existente

**Artículo que ya existe en el sistema:**
1. Ir a **Almacén → Entradas**.
2. Escanear el QR del artículo o buscarlo por nombre.
3. Introducir la cantidad recibida.
4. Confirmar → stock actualizado.

**Artículo nuevo (primera vez):**
1. Ir a **Almacén → Catálogo → Nuevo artículo**.
2. Rellenar: nombre, categoría, talla (si aplica), referencia del proveedor.
3. Guardar → el sistema genera el código interno y el QR.
4. Imprimir la etiqueta antes de colocar el artículo.

**Ropa y consumibles con talla:** crear una variante por cada combinación de modelo + color + talla. El sistema no permite duplicados.

---

### 1.3 Impresión y colocación de etiquetas

**Cuándo imprimir:**
- Artículo nuevo que llega sin etiqueta.
- Etiqueta dañada o ilegible.
- Reimpresión por cambio de ubicación (registrar motivo obligatorio).

**Cómo imprimir:**
1. Abrir el artículo o la variante en el sistema.
2. Pulsar **Imprimir etiqueta**.
3. Seleccionar el formato (ver sección 5 para tamaños).
4. Confirmar en la Zebra ZT231.

**Dónde pegar:**
- Ropa y consumibles: en la estantería o caja, no en la prenda.
- Herramientas: superficie plana visible (mango, carcasa).
- Maquinaria: chasis, zona sin temperatura ni rozamiento.
- Arnés: en la bolsa de almacenaje, **nunca en las cintas del arnés**.
- Ubicaciones de almacén: en la balda o el panel vertical.

---

### 1.4 Inventario por zonas

1. Ir a **Inventario → Nueva sesión de conteo**.
2. Seleccionar la zona o familia a contar (ej.: "Zona A — Herramientas eléctricas").
3. El sistema muestra la lista de artículos esperados con la cantidad que debería haber.
4. Escanear cada artículo o introducir la cantidad manualmente.
5. Cuando una línea no cuadra → el sistema la marca en rojo; anotarla como incidencia.
6. Al terminar la zona → **Cerrar sesión parcial**. Se puede retomar sin perder lo ya contado.
7. Al terminar todas las zonas → **Cerrar inventario completo**. El sistema calcula las diferencias y genera el informe.

**Regla clave:** No cerrar el inventario si quedan líneas sin contar. Las líneas sin contar deben marcarse explícitamente como "no accesible hoy" con motivo.

---

### 1.5 Entrega de ropa y EPIs a trabajador nuevo

1. Ir a **Patio → Dotaciones → Trabajador**.
2. Comprobar que el trabajador tiene la talla de ropa y calzado en su ficha. Si no → rellenarlas antes.
3. Pulsar **Generar dotación**. El sistema crea la lista según la plantilla del rol.
4. Para cada línea → escanear el QR del artículo físico → el sistema lo reserva.
5. Cuando todo está preparado → ir a **Modo Entrega**.
6. Escanear de nuevo cada artículo delante del trabajador (confirmación).
7. Recoger la firma del trabajador (pantalla o papel).
8. Confirmar → el stock se descuenta y queda registrado quién entregó, a quién y cuándo.

**Si un artículo no hay en stock:** la línea queda como "Pendiente de stock". La entrega del resto continúa con normalidad.

---

### 1.6 Asignación de arnés y absorbedor individual

1. Ir a **Patio → Dotaciones** del trabajador → línea de arnés.
2. El sistema solo admite unidades en estado **disponible**, sin trabajador asignado y con la revisión vigente.
3. Escanear el QR de la bolsa del arnés (no las cintas).
4. El sistema muestra el número de serie, la fecha de última revisión y cuándo vence.
5. Si la revisión está vencida → el sistema rechaza el escaneo y pide otra unidad.
6. Confirmar → la unidad queda asignada al trabajador; aparece su nombre en la ficha del arnés.

**Al devolver el arnés:**
1. Abrir la línea de dotación → **Devolver**.
2. Escanear el QR de la bolsa.
3. El sistema libera la unidad y la vuelve a poner como disponible.
4. Si el arnés tiene daños → marcar como "En revisión" para que no vuelva a estar disponible hasta inspeccionarlo.

---

### 1.7 Entrega y devolución de herramientas

**Entrega:**
1. Ir a **Herramientas → Entregar**.
2. Escanear el QR de la herramienta.
3. Seleccionar el trabajador o la obra destinataria.
4. Confirmar → herramienta pasa a estado "Entregada".

**Devolución:**
1. Ir a **Herramientas → Devolver** o escanear el QR desde el panel principal.
2. El sistema muestra a quién estaba asignada.
3. Confirmar el estado al devolver: "Correcta", "Requiere revisión", "Averiada".
4. Si está averiada → se abre automáticamente un parte de avería.

**Si una herramienta no aparece al escanear:** buscar por nombre y comprobar su estado. Si el QR está dañado → reimprimirlo desde la ficha de la herramienta.

---

### 1.8 Control de maquinaria

**Ver estado actual:**
1. Ir a **Maquinaria → Pasaporte** de cada máquina.
2. Ver estado: Operativa / En observación / Averiada / En reparación.
3. Ver la próxima revisión ITV o inspección reglamentaria.

**Registrar avería:**
1. Escanear el QR de la máquina o buscarla por nombre.
2. Pulsar **Registrar avería**.
3. Describir brevemente el problema.
4. El sistema cambia el estado a "Averiada" y avisa al responsable.

**Registrar reparación completada:**
1. Ir a la avería abierta → **Marcar como reparada**.
2. Añadir descripción de la reparación y quién la realizó.
3. El sistema vuelve la máquina a "Operativa" o "Pendiente de prueba" según corresponda.

**AirTag (si la máquina lo tiene):**
- En la ficha de la máquina aparece el campo "Última ubicación verificada" y la fecha de comprobación.
- No es automático: el encargado actualiza la ubicación manualmente tras verla físicamente.
- El QR del AirTag está vinculado a la ficha de la máquina como dato adicional.

---

### 1.9 Cierre diario y revisión de pendientes

Al final de cada jornada:
1. Ir a **Patio → Resumen del día**.
2. Comprobar la lista de alertas activas:
   - Dotaciones pendientes de entregar
   - Herramientas no devueltas con más de X días
   - Artículos con stock bajo mínimo
   - Arneses con revisión próxima a vencer
   - Averías abiertas sin asignar
3. Resolver las que se pueda o anotar en las incidencias del día.
4. El sistema guarda automáticamente; no hay botón de "cierre" manual.

---

## 2. Criterios de Aceptación por Mejora

### 2.1 Recepción de suministros

| | Detalle |
|-|---------|
| **Debe funcionar** | Confirmar recepción aumenta el stock. Recepción parcial deja la diferencia como pendiente. Las líneas sin recibir no desaparecen. |
| **Debe quedar bloqueado** | No se puede confirmar una recepción con cantidad 0. No se puede recibir más de lo pedido sin alerta. |
| **Prueba manual** | Crear un pedido de 10 unidades. Confirmar recepción de 7. Verificar: stock +7, pedido en "Recibido parcial", 3 unidades pendientes visibles. |
| **Resultado esperado** | Stock correcto, trazabilidad del pedido intacta. |
| **Riesgo si falla** | Stock inflado o deflado; pérdida de trazabilidad con el proveedor. |

### 2.2 Inventario operativo

| | Detalle |
|-|---------|
| **Debe funcionar** | Contar por zonas sin perder lo ya contado. Cerrar inventario genera informe de diferencias. Las diferencias negativas generan alerta. |
| **Debe quedar bloqueado** | No se puede cerrar el inventario con líneas en estado "sin contar" (sin marcar explícitamente). No se puede reabrir una sesión cerrada. |
| **Prueba manual** | Crear sesión de inventario de 5 artículos. Contar 4 correctamente y uno con diferencia de -2. Cerrar. Verificar: informe muestra exactamente 1 diferencia, el stock del artículo corregido, y el resto sin cambios. |
| **Resultado esperado** | Diferencias reflejadas, stock ajustado, alerta generada para el artículo con diferencia negativa. |
| **Riesgo si falla** | Stock incorrecto que genera falsos pedidos o falsa disponibilidad. |

### 2.3 Dotaciones escaneadas

| | Detalle |
|-|---------|
| **Debe funcionar** | Generación automática desde plantilla. Preparar sin descontar stock. Descontar solo al escanear en entrega. Entrega parcial permitida. Firma obligatoria. |
| **Debe quedar bloqueado** | Sin tallas del trabajador no se genera dotación. Sin escaneo de QR no se confirma entrega. Sin firma no se cierra ninguna línea. Doble escaneo del mismo código devuelve respuesta idempotente, no doble descuento. |
| **Prueba manual** | Dar de alta trabajador con tallas. Generar dotación. Preparar 3 de 5 artículos. Confirmar entrega de los 3 con firma. Verificar: stock -3 exacto, 2 líneas en "pendiente de stock", dotación en "entregada parcial". |
| **Resultado esperado** | Solo se descuenta lo realmente escaneado y firmado. |
| **Riesgo si falla** | Descuento de stock sin entrega real, o entrega sin registro → pérdida de trazabilidad legal de EPIs. |

### 2.4 Arneses y absorbedores individuales

| | Detalle |
|-|---------|
| **Debe funcionar** | Solo se puede asignar una unidad disponible, sin trabajador y con revisión vigente. La asignación vincula la unidad al trabajador. La devolución libera la unidad. |
| **Debe quedar bloqueado** | Unidad con revisión vencida: escaneo rechazado. Unidad ya asignada a otro: escaneo rechazado. Misma unidad en dos dotaciones simultáneas: la segunda recibe error de carrera concurrente. |
| **Prueba manual** | Tomar la unidad de arnés real. Verificar que la revisión está vigente en el sistema. Asignarla a un trabajador de prueba. Intentar asignarla a un segundo trabajador → debe rechazar. Devolver la primera asignación → verificar que vuelve a disponible. |
| **Resultado esperado** | Trazabilidad 1:1 entre arnés físico y trabajador en todo momento. |
| **Riesgo si falla** | Dos trabajadores con el mismo arnés registrado en el sistema → riesgo legal en caso de accidente. |

### 2.5 Fichas de ropa y consumibles

| | Detalle |
|-|---------|
| **Debe funcionar** | Una variante por cada combinación modelo+color+talla+almacén. QR generado solo por el sistema. Stock por variante. Reset controlado de ropa con preview y backup previo. |
| **Debe quedar bloqueado** | No se pueden crear dos variantes idénticas. El QR de una variante no puede usarse para otra. El reset de ropa requiere confirmación de admin con motivo. |
| **Prueba manual** | Crear variante Chaleco L Naranja. Intentar crear otra Chaleco L Naranja en el mismo almacén → debe rechazar con "variante ya existe". Crear entrada de 10 unidades. Verificar stock = 10. |
| **Resultado esperado** | Sin duplicados, stock exacto por talla. |
| **Riesgo si falla** | Entregas de talla incorrecta no detectadas, stock contable erróneo. |

### 2.6 Pasaporte digital de maquinaria

| | Detalle |
|-|---------|
| **Debe funcionar** | Ficha con estado, historial de averías, revisiones e ITV. Escanear QR lleva directamente al pasaporte. Cambio de estado queda registrado con quién lo cambió y cuándo. AirTag como metadato manual con fecha de última verificación. |
| **Debe quedar bloqueado** | No se puede cambiar estado de "Averiada" a "Operativa" sin registrar la reparación. No se puede introducir fecha de ITV futura como "pasada". |
| **Prueba manual** | Escanear QR del Alimak (o de la maquinaria a registrar primero). Registrar una avería. Verificar que el estado cambia en el panel del Encargado. Resolver la avería. Verificar que el historial muestra los dos eventos con timestamps. |
| **Resultado esperado** | Historial de vida de la máquina completo y trazable. |
| **Riesgo si falla** | Máquina averiada utilizada por desconocimiento → accidente laboral. |

### 2.7 Panel del Encargado de Patio

| | Detalle |
|-|---------|
| **Debe funcionar** | Vista de resumen actualizada cada 60 segundos. Alertas activas por prioridad. Acceso directo a las acciones más frecuentes. Funciona desde el móvil del encargado. |
| **Debe quedar bloqueado** | Las alertas resueltas desaparecen del panel. Un observador no puede actuar, solo ver. |
| **Prueba manual** | Generar una dotación pendiente y una alerta de stock bajo. Abrir el panel en el móvil del encargado. Verificar que ambas alertas aparecen. Resolver la dotación. Verificar que la alerta de dotación desaparece en el siguiente refresco (máx. 60s). |
| **Resultado esperado** | Información en tiempo real sin necesidad de navegar por menús. |
| **Riesgo si falla** | El encargado pierde alertas críticas → entregas olvidadas, stock agotado sin aviso. |

---

## 3. Plan Real de Puesta en Marcha

### Semana 1 — Solo suministros nuevos que lleguen esta semana

**Objetivo:** El equipo aprende el flujo de recepción con artículos reales sin presión de inventario.

- Activar los roles: crear el usuario del Encargado de Patio y asignarle el rol.
- Configurar el almacén principal: nombre, ubicaciones básicas (Zona A, Zona B, etc.).
- Probar la pistola USB: conectar, abrir el campo de código, escanear. Debe escribir el código como si fuera un teclado.
- Cuando llegue cualquier pedido esta semana → recibirlo por el sistema en lugar de anotarlo en papel.
- Imprimir las etiquetas de los artículos nuevos y colocarlas.
- No tocar el stock existente todavía.

**Hito de validación:** Al final de la semana, el stock de los artículos nuevos en el sistema coincide con lo físico.

---

### Semana 2 — Ropa existente + inventario inicial

**Objetivo:** Registrar la ropa actual en el sistema con su stock real.

- Crear las variantes de ropa: por cada prenda, crear una variante por talla disponible.
- No usar el reset masivo todavía. Introducir el stock mediante "Entrada de almacén" con motivo "Inventario inicial".
- Contar físicamente prenda por prenda y zona por zona. Una zona al día para no paralizar el almacén.
- Imprimir etiquetas para cada variante y colocarlas en la estantería (no en la prenda).
- Al terminar: comparar el sistema con el conteo físico. Ajustar diferencias.

**Hito de validación:** El stock de ropa en el sistema coincide con el recuento físico en todas las zonas.

---

### Semana 3 — Arneses y absorbedores reales

**Objetivo:** Registrar las dos unidades reales de arnés y absorbedor.

- Crear en el sistema los dos arneses como "Unidades individuales EPI".
- Datos obligatorios: número de serie (del fabricante), fecha de fabricación, fecha de última revisión, próxima revisión.
- Imprimir etiqueta para la bolsa de cada arnés (no para las cintas).
- Verificar físicamente que los datos coinciden con la etiqueta del fabricante.
- Asignar temporalmente a un trabajador ficticio de prueba → verificar que el sistema bloquea una segunda asignación.
- Devolver la asignación de prueba → verificar que vuelve a disponible.

**Hito de validación:** Los dos arneses están en el sistema con estado "Disponible" y se puede asignar/devolver correctamente.

---

### Semana 4 — Maquinaria prioritaria

**Orden recomendado:** primero las máquinas más usadas y con mayor riesgo de avería.

1. **Alimak** (plataforma de elevación de personal) — prioridad máxima por normativa de seguridad.
2. **Maquinillos** — alta rotación, frecuentes averías.
3. **Transpaletas** — uso diario, fácil de inventariar.

Por cada máquina:
1. Crear la ficha en **Maquinaria → Nueva**.
2. Datos mínimos: nombre, número de serie, año de fabricación, fecha de última ITV/inspección, próxima ITV.
3. Estado inicial: "Operativa" si está en uso sin incidencias, o el estado real.
4. Imprimir etiqueta de maquinaria (formato grande, resistente al exterior).
5. Pegar en el chasis, zona visible desde el suelo.
6. Si tiene AirTag → anotar el ID del AirTag en la ficha (campo metadato). La ubicación se actualiza manualmente.

**Hito de validación:** Al escanear el QR de cada máquina desde el móvil, aparece su pasaporte digital con el estado actual y la próxima revisión.

---

### Semana 5 en adelante — Expansión y dotaciones de nuevos trabajadores

- Configurar las plantillas de dotación por rol (cuántos cascos, chalecos, botas, etc. corresponden a cada puesto).
- El próximo trabajador que se incorpore → generarle la dotación desde el sistema.
- Continuar incorporando el resto del catálogo de herramientas y consumibles a medida que se necesiten (no de golpe).

**Regla de expansión:** Mejor añadir un artículo bien que añadir diez artículos mal. Un QR ilegible o un dato incorrecto genera más trabajo que no haberlo añadido.

---

## 4. Datos Mínimos Obligatorios por Tipo

### Ropa (variante)
- Nombre del artículo (ej.: "Chaleco reflectante")
- Categoría ("Ropa de trabajo" o "EPI")
- Modelo (ej.: "Alta visibilidad clase 2")
- Color
- Talla (S / M / L / XL / XXL para ropa; número para calzado)
- Almacén y ubicación
- Stock inicial (puede ser 0)

### Consumible
- Nombre
- Categoría ("Material consumible")
- Referencia del proveedor (para reposición)
- Unidad de medida (unidad, caja, metro, kg)
- Stock mínimo (para alertas de reposición)
- Almacén y ubicación

### Herramienta
- Nombre (ej.: "Taladro percutor")
- Marca y modelo
- Número de serie (si lo tiene)
- Estado inicial (Nueva / Disponible)
- Categoría (eléctrica / manual / neumática)
- El código QR e interno los genera el sistema

### Arnés / Absorbedor (unidad individual)
- Nombre ("Arnés anticaída" / "Absorbedor de energía")
- Marca y modelo
- Número de serie **del fabricante** (obligatorio, es el identificador legal)
- Fecha de fabricación
- Fecha de última revisión/inspección
- Fecha de próxima revisión
- Estado inicial ("Disponible")
- El QR lo genera el sistema; pegarlo en la bolsa de almacenaje

### Maquinaria
- Nombre (ej.: "Alimak plataforma 1")
- Tipo (elevación / transporte / perforación...)
- Marca y modelo
- Número de serie / matrícula
- Año de fabricación
- Fecha de última ITV o inspección reglamentaria
- Fecha de próxima ITV
- Estado inicial
- Ubicación habitual (obra, almacén central...)
- ID del AirTag (si lo tiene) — solo como texto informativo

### Localizador AirTag (metadato en la ficha de máquina)
- ID del AirTag (se lee en la app Encontrar del iPhone)
- Descripción ("AirTag en Alimak plataforma 1")
- Fecha de última verificación manual de ubicación
- Ubicación verificada (texto libre: "Almacén central, puerta norte")

No hay integración automática. La actualización es manual.

---

## 5. Etiquetas Necesarias

### Formatos por tipo de artículo

| Tipo | Tamaño | Formato Zebra | Qué lleva visible |
|------|--------|---------------|-------------------|
| Ropa / EPI variante | 102×51 mm | ZPL 102×51 | QR + código interno + nombre + talla |
| Herramienta | 50×25 mm | ZPL 50×25 | QR + código interno + nombre corto |
| Maquinaria / Vehículo | 70×40 mm | ZPL 70×40 | QR + código interno + nombre + tipo |
| Arnés / Absorbedor (bolsa) | 102×51 mm | ZPL 102×51 | QR + número de serie + próxima revisión |
| Ubicación de estantería | 102×51 mm | ZPL 102×51 | QR + código de ubicación + zona |
| Tarjeta de identificación de arnés | 102×152 mm | ZPL 102×152 | QR grande + nº serie + fecha revisiones |

### Material recomendado para comprar

**Etiquetas para herramientas y maquinaria:**
- Poliéster blanco resistente a la intemperie, con adhesivo permanente de alta resistencia.
- Resistente a: aceite, polvo, temperatura (-20°C a +80°C), rozamiento moderado.
- No usar papel estándar en zonas expuestas a la humedad o al sol directo.
- Para superficies curvas (mangos de herramienta): etiquetas de poliéster flexible.

**Etiquetas para ropa y estanterías:**
- Papel térmico estándar es suficiente en interior.
- Si la estantería está en exterior o zona húmeda → usar poliéster.

**Qué debe contener el QR (datos codificados):**
El QR codifica únicamente el código interno del artículo (ej.: `HER-2024-0045`).  
El sistema resuelve el resto (nombre, estado, historial) con ese código como clave.  
No se codifica información personal ni precios.

### Cantidades iniciales recomendadas para comprar

Estas cantidades cubren la puesta en marcha descrita en el plan de 5 semanas:

| Formato | Cantidad recomendada |
|---------|----------------------|
| Etiquetas 50×25 mm (herramientas) | 200 unidades |
| Etiquetas 70×40 mm (maquinaria) | 50 unidades |
| Etiquetas 102×51 mm (ropa, arneses, ubicaciones) | 300 unidades |
| Etiquetas 102×152 mm (tarjetas arnés) | 10 unidades |
| Ribbon de resina para poliéster (si la Zebra usa transferencia térmica) | 1 rollo adicional |

Todos los formatos son compatibles con la **Zebra ZT231** (203 DPI, ancho máximo de impresión 104 mm).

---

## 6. Lista de Comprobación para el Primer Día

### Sistema y accesos
- [ ] El usuario del Encargado de Patio está creado con rol correcto
- [ ] El encargado puede entrar al sistema desde su PC y desde el móvil/tableta
- [ ] El almacén principal está configurado con nombre y al menos 2 ubicaciones (Zona A, Zona B)
- [ ] Las categorías básicas de artículos están configuradas (ropa, herramienta, consumible, EPI)
- [ ] La plantilla de dotación para el rol más común está configurada con al menos 3 artículos

### Hardware
- [ ] Pistola USB conectada al PC del encargado → abrir el campo de código del sistema → escanear un QR de prueba → el código aparece escrito en el campo
- [ ] Zebra ZT231 encendida y conectada → imprimir una etiqueta de prueba → el QR es legible con la pistola y con el móvil
- [ ] El móvil o tableta del encargado accede al sistema por la red local o por Cloudflare → la cámara abre al pulsar el botón de escaneo

### Etiquetas
- [ ] Hay stock suficiente de etiquetas en los formatos necesarios (ver sección 5)
- [ ] El material de las etiquetas es adecuado para las zonas de uso (exterior vs. interior)

### Datos iniciales
- [ ] El inventario inicial de ropa está a cero o ya cargado (no mezclar: elegir uno)
- [ ] Los dos arneses reales están registrados con número de serie y fecha de revisión
- [ ] La próxima revisión de los arneses está visible en el sistema y es correcta

### Seguridad de datos
- [ ] Se ha hecho una copia de seguridad manual antes de empezar: `backup_manager.py` o el botón de backup en el panel de admin
- [ ] El sistema arranca correctamente tras un reinicio del servicio: verificar `/health` → todos los checks en verde

### Prueba de caída y recuperación
- [ ] Detener el servicio desde Servicios de Windows → esperar 35 segundos → verificar que vuelve a arrancar solo (watchdog + Windows Service)
- [ ] Abrir el panel del sistema desde el móvil tras el reinicio → debe estar disponible sin intervención manual

---

## 7. Manual del Encargado de Patio (15 pasos, sin tecnicismos)

**Lee esto cuando empieces cada jornada. Guárdalo en papel en el almacén.**

---

**1. Enciende el ordenador y abre el programa MRD Tool Control.**  
Entra con tu usuario y contraseña. Si no recuerdas la contraseña, avisa al responsable de oficina.

**2. Mira las alertas del día en el panel de inicio.**  
Aparecen en rojo las urgentes y en amarillo las que puedes ver más tarde. Empieza por las rojas.

**3. Si llega un pedido, ve a "Almacén → Recepción".**  
Busca el pedido, cuenta lo que ha llegado e introduce la cantidad. Si falta algo, ponlo como diferencia. Confirma al terminar.

**4. Si un artículo es nuevo y no tiene etiqueta, imprímela antes de colocarlo.**  
Búscalo en el catálogo, pulsa "Imprimir etiqueta" y manda a la Zebra. Pégala en el artículo o en la estantería.

**5. Si un trabajador nuevo llega, ve a su ficha y comprueba que tiene las tallas apuntadas.**  
Sin tallas no puedes preparar su dotación. Si faltan, pídelas antes de seguir.

**6. Para preparar la dotación de un trabajador, ve a "Patio → Dotaciones".**  
Pulsa "Generar dotación". El programa te muestra la lista de artículos que le corresponden.

**7. Para cada artículo de la lista, escanea su QR con la pistola.**  
El programa comprueba que el artículo está disponible. Si no hay stock, aparece en naranja como "Sin stock": déjalo así y sigue con los demás.

**8. Cuando tengas todo preparado, ve a "Modo Entrega".**  
Delante del trabajador, escanea de nuevo cada artículo. Pide la firma al trabajador. Pulsa "Confirmar entrega". El stock baja en ese momento, no antes.

**9. Si el arnés o absorbedor no pasa el escáner, busca otra unidad.**  
El programa rechaza el arnés si su revisión está vencida. No intentes saltarte este paso.

**10. Si una herramienta sale de obra, ve a "Herramientas → Devolver".**  
Escanea su QR. Di si vuelve bien, necesita revisión o está avería. Si está avería, se abrirá un parte solo.

**11. Si una máquina falla, ve a su ficha y registra la avería.**  
Escanea el QR de la máquina o búscala por nombre. Pulsa "Registrar avería" y describe qué pasó. Cambia el estado a "Averiada".

**12. Para contar el almacén, ve a "Inventario → Nueva sesión".**  
Elige la zona. Escanea o cuenta artículo por artículo. Si no coincide con lo que pone el programa, apunta la diferencia en el campo de incidencias. Cierra la sesión cuando termines esa zona.

**13. Si algo no cuadra al escanear, para y avisa.**  
No fuerces el escáner ni introduzcas números a mano si el artículo debería escanearse. Podría ser un QR dañado (reimprimir la etiqueta) o un artículo que no está registrado aún (darlo de alta primero).

**14. Si el programa no responde o da error, espera 30 segundos y recarga la página.**  
El sistema se recupera solo. Si en 2 minutos sigue sin funcionar, avisa al responsable informático.

**15. Al terminar la jornada, revisa los pendientes del panel.**  
Anota en papel o en el campo de notas cualquier incidencia que no hayas podido resolver. El programa guarda todo automáticamente; no hay que cerrar sesión manualmente.

---

*Documento generado por Claude (Cowork) · Solo diseño y operativa · Sin modificaciones en código ni producción · 2026-08-20*
