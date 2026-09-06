---
name: ventanas-paralelas
description: Coordina varias ventanas de Claude Code trabajando sobre el mismo directorio del proyecto, evitando que se pisen. Usar SIEMPRE al empezar y al cerrar cualquier tanda cuando pueda haber más de una sesión abierta.
---

# Coordinación entre ventanas paralelas

Varias sesiones sobre uno o más checkouts de este proyecto —incluidos
worktrees como Sentinel (`mrd-tool-control-sentinel24x7`)— no se ven entre sí.
El único punto de encuentro es `C:\mrd tool\_coordinacion\VENTANAS.md`,
deliberadamente **fuera de cualquier checkout**: así lo ve cualquier ventana
sin importar en qué carpeta de trabajo esté.

Este `SKILL.md` (el protocolo) va bajo control de versiones en git, en AMBOS
checkouts (`mrd-tool-control-2.5.0` y `mrd-tool-control-sentinel24x7`) —igual
que `baoyu-design` o `web-animation-design`— así cualquier cambio a las reglas
queda en el historial y es auditable con `git log`/`git diff`, en vez de
confiarse a un archivo que nadie puede revisar. `VENTANAS.md` en cambio se
queda deliberadamente fuera de git y fuera de ambos checkouts: es estado vivo
que cada ventana sobrescribe constantemente, no una regla — versionarlo solo
generaría conflictos de merge, y si viviera dentro de un solo checkout sería
invisible para el resto de worktrees (ese fue justo el fallo original).

## Al empezar cualquier tanda

1. Leer `C:\mrd tool\_coordinacion\VENTANAS.md`. Si no existe, crearlo vacío.

2. Determinar el modo de esta tanda:
   - **LECTURA** — solo consulta: grep, graphify, leer archivos, auditar.
     No modifica nada, no arranca la aplicación, no ejecuta pytest.
   - **ESCRITURA** — modifica archivos, crea snapshots, ejecuta pytest,
     reinicia MRD o toca `version.json`.

3. Comprobar compatibilidad con lo ya declarado — **el solapamiento se mide
   por ruta de archivo, no solo por modo**:

   - LECTURA nunca bloquea ni es bloqueada por nada: siempre compatible.
   - ESCRITURA + ESCRITURA sobre listas de `Archivos:` que **no comparten
     ninguna ruta**: compatible, ambas tandas pueden avanzar a la vez.
   - ESCRITURA + ESCRITURA donde **al menos una ruta coincide** entre las dos
     listas de `Archivos:`: **bloqueado** solo para esa ruta compartida.
     Detenerse y avisar al usuario qué ventana tiene tomado ese archivo
     concreto y desde cuándo. No empezar la parte que se solapa igualmente.
   - **Cerrojo global — `version.json` y `static/js/sw.js`**: sin excepción,
     solo una ventana puede declararlos a la vez, sin importar que el resto de
     archivos de cada lista no se solapen entre sí. Si cualquiera de estos dos
     aparece ya en la entrada en curso y también en la tuya, es bloqueo
     automático de esos dos archivos aunque el resto de tu tanda sea
     compatible.

4. Añadir la propia entrada al archivo antes de tocar nada, con este formato
   exacto (sustituir TODO lo que va entre `<>`; no dejar nunca un nombre de
   archivo, hora o tarea reales en este bloque de ejemplo — este SKILL.md está
   versionado en git y lo lee cualquier ventana, así que debe seguir siendo una
   plantilla genérica, nunca el registro de una tanda concreta):

       ## [<LECTURA|ESCRITURA>] <descripción corta de la tarea> — iniciado <YYYY-MM-DD HH:MM>
       Archivos: <ruta1>, <ruta2>
       Reinicia MRD: <sí|no>

## Reglas de exclusividad

- `version.json` y `static/js/sw.js` son **cerrojo global** (ver arriba):
  nunca dos ventanas a la vez, sea cual sea el resto de archivos que cada una
  declare — es como se pierde el rastro de versiones.
- No ejecutar pytest mientras otra ventana tenga una ESCRITURA en curso sobre
  alguno de los mismos archivos: importaría código a medio editar y daría
  resultados falsos. Si las ESCRITURA no comparten ninguna ruta, el pytest de
  cada una es fiable dentro de su propio alcance.
- Reiniciar MRD solo si ninguna otra ventana tiene abierta una ESCRITURA que
  toque los archivos que motivan el reinicio.
- Una tanda de LECTURA nunca crea snapshot: no hay nada que respaldar.

## Al cerrar la tanda

Eliminar la propia entrada de `VENTANAS.md`. Una entrada de más de 2 horas sin
actividad **nunca se declara obsoleta por cuenta propia**: preguntar siempre
al usuario qué ventana la tiene tomada y desde cuándo, y esperar su respuesta
antes de tocarla, ignorarla o borrarla.
