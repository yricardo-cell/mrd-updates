# MRD Tool Control 2.5.0 — Instrucciones permanentes

## 1. Exploración de código
Antes de usar grep o leer archivos completos para entender la estructura del código,
funciones o relaciones entre módulos, usar primero:

    graphify query "<pregunta>"

Recurrir a lectura completa de archivos o grep solo si graphify no tiene la respuesta
o el grafo (`graphify-out/graph.json`) no está generado/actualizado.

## 2. Flujo de trabajo para cualquier mejora o cambio
1. Crear un snapshot en `backups/` antes de tocar nada.
2. Para features no triviales, usar `/ecc:plan` antes de implementar.
3. Un cambio a la vez — nunca mezclar varios cambios distintos en la misma tanda.
4. Probar el flujo real afectado antes de dar el trabajo por terminado (no basta con
   que compile o pase los tests unitarios si el flujo tiene un componente end-to-end).
5. Ejecutar `/code-review` después de cada cambio.
6. Al cerrar cada tanda de trabajo, actualizar `version.json` con el changelog
   correspondiente.

## 3. Protección de backups/
Nunca proponer ni aplicar reglas de auto mode que permitan borrar contenido dentro de
`backups/` (por ejemplo `rm` sobre `backups/*` o equivalentes). Los snapshots son la
red de seguridad del proyecto y no deben poder autoeliminarse bajo ninguna circunstancia.

## 4. Trabajo visual / UI
Para cualquier trabajo visual o de interfaz, aplicar:
- Las guías de **UI UX Pro Max** (contraste, espaciado, tipografía, accesibilidad).
- La skill **web-animation-design** (`.agents/skills/web-animation-design/`) para
  animaciones y micro-interacciones sutiles y elegantes.

## 5. Mockups antes de tocar código real
Antes de aplicar cambios visuales grandes al código real, generar primero un mockup
local con la skill **Baoyu Design** (`.agents/skills/baoyu-design/`, servidor local,
nunca un artifact de claude.ai) para que el usuario lo apruebe antes de implementar
en el código de producción.

## 6. Conflictos entre skills
Si varias skills dan sugerencias que entran en conflicto (p. ej. UI UX Pro Max vs.
web-animation-design vs. Baoyu Design), no elegir unilateralmente. Explicar
brevemente el conflicto y las opciones disponibles, y preguntar al usuario cuál
prefiere antes de aplicar nada. Nunca mezclar recomendaciones a medias de varias
skills sin verificar que son coherentes entre sí.
