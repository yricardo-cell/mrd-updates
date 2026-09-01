# CLOUDFLARE SETUP — MRD TOOL CONTROL
# Guia completa de configuracion del Named Tunnel para app.iasmrd.com

Version: 1.9.9-alpha | Fecha: 2026-07-13

---

## QUE HACE ESTE SISTEMA

Conecta el servidor MRD Tool Control (en tu ordenador) con Internet de forma segura usando
Cloudflare Zero Trust. El resultado es que cualquier movil con Internet puede acceder a
https://app.iasmrd.com sin abrir puertos del router ni exponer la IP publica.

Arquitectura:
  Movil  <-->  Cloudflare  <-->  cloudflared (Windows service)  <-->  FastAPI (localhost:8000)

---

## ANTES DE EMPEZAR

### Requisitos obligatorios

- La aplicacion MRD Tool Control debe estar en marcha en localhost:8000
  Para verificarlo, abre en el mismo ordenador: http://localhost:8000/health
  Debe responder {"status": "ok"}

- Debes tener acceso a la cuenta de Cloudflare donde esta el dominio iasmrd.com
  Panel: https://one.dash.cloudflare.com/

- El ordenador donde corre MRD Tool Control debe tener conexion a Internet

- No hace falta abrir ningun puerto en el router (esa es la ventaja del Named Tunnel)

### Script automatico (PASO 1)

Abre PowerShell como Administrador y ejecuta:

    cd "C:\mrd tool\mrd_tool_control"
    .\scripts\setup_cloudflare_tunnel.ps1

El script verifica que la aplicacion responde y descarga cloudflared.exe si no esta instalado.
Cuando el script se detiene en el PASO 4, pasa a la siguiente seccion.

---

## PASO 2 — CREAR EL TUNEL EN EL PANEL DE CLOUDFLARE

IMPORTANTE: NO INVENTES NI COPIES TOKENS DE NINGUN LADO. Cloudflare genera el tuyo.

1. Abre en el navegador: https://one.dash.cloudflare.com/

2. En el menu izquierdo, ve a: Networks > Tunnels

3. Haz clic en el boton: + Create a tunnel

4. Selecciona el tipo: Cloudflared
   (NO selecciones "WARP Connector" ni "Remote Network")

5. Haz clic: Next

6. Nombre del tunel: MRD-TOOL-CONTROL
   (puedes usar este nombre exacto o el que prefieras)

7. Haz clic: Save tunnel

8. En la pagina siguiente, en el apartado "Install connector":
   - Selecciona el sistema operativo: Windows
   - Cloudflare te mostrara un comando completo con este aspecto:
       cloudflared.exe service install eyJhXXXXXXXXXXXXXXXXXXXXXXXXX...
   - Copia ese comando completo (el token empieza por "eyJ" y es muy largo)

9. NO hagas clic en "Next" todavia
   Vuelve a PowerShell y ejecuta el comando que acabas de copiar:

       cloudflared.exe service install <pega-aqui-el-token-que-copiaste>

   Cuando finalice sin errores, vuelve al panel de Cloudflare.

---

## PASO 3 — CONFIGURAR EL HOSTNAME (donde apunta el tunel)

De vuelta en el panel de Cloudflare, despues de instalar el servicio:

1. Haz clic en Next

2. En la seccion "Public Hostnames", rellena exactamente asi:

   Subdomain:  app
   Domain:     iasmrd.com
   Type:       HTTP
   URL:        127.0.0.1:8000

   No uses HTTPS en el campo URL — Cloudflare gestiona el HTTPS externamente.

3. Haz clic: Save tunnel

4. Espera 2-3 minutos. Cloudflare propaga la configuracion automaticamente.

---

## PASO 4 — VERIFICAR QUE TODO FUNCIONA

### Verificacion rapida desde PowerShell

    cd "C:\mrd tool\mrd_tool_control"
    .\scripts\cloudflare_test.ps1

Debe mostrar OK en todas las comprobaciones.

### Verificacion manual

1. Desde el mismo ordenador, abre: https://app.iasmrd.com
   Debe cargar la pantalla de login de MRD Tool Control.
   El candado del navegador debe estar verde (HTTPS valido).

2. Desde un movil con datos moviles (NO wifi del mismo router):
   Abre https://app.iasmrd.com
   Debe funcionar exactamente igual.

3. QR del escaner:
   Ve a Acceso remoto en la aplicacion.
   El codigo QR debe apuntar a https://app.iasmrd.com/scan
   Escanea con el movil — debe abrir la camara de escaneo.

### Verificacion desde la aplicacion

Entra en la aplicacion como admin > Acceso remoto.
Pulsa el boton "Probar conexion". Deben aparecer 12 comprobaciones en verde.

---

## PASO 5 — CONFIGURAR INICIO AUTOMATICO

El servicio cloudflared ya se instala con inicio automatico (AUTO_START).
Cuando el ordenador se reinicie, el tunel se conectara solo.

Para verificar:

    sc query cloudflared

Debe mostrar: STATE: 4 RUNNING

Para ver el inicio configurado:

    sc qc cloudflared

Debe mostrar: START_TYPE: 2 AUTO_START

---

## DIAGNOSTICO Y SOLUCION DE PROBLEMAS

### El tunel no conecta

    # Ver estado del servicio
    .\scripts\cloudflare_status.ps1

    # Ver logs del servicio
    .\scripts\cloudflare_logs.ps1

    # Reiniciar el servicio
    .\scripts\cloudflare_restart.ps1  (requiere Administrador)

### La URL no responde desde Internet

Posibles causas:
1. El servicio cloudflared no esta en ejecucion -> sc start cloudflared
2. MRD Tool Control no esta en ejecucion -> net start MRDToolControl
3. El tunel no tiene el hostname configurado -> revisar Paso 3
4. El DNS de iasmrd.com no apunta a Cloudflare -> verificar en Cloudflare DNS

### Error "Too many redirects"

La configuracion de Cloudflare SSL debe estar en modo "Flexible" o "Full",
NO en "Full (Strict)" para una conexion HTTP interna.
Ve a: Cloudflare > iasmrd.com > SSL/TLS > Overview > selecciona "Flexible"

### El QR apunta a localhost

La variable MRD_SCAN_URL no esta configurada correctamente.
Verifica en config/local.env que existe la linea:
    MRD_SCAN_URL=https://app.iasmrd.com/scan

Despues reinicia el servicio: net restart MRDToolControl

---

## GUIA DE PRUEBA DESDE MOVIL (FASE 9)

### Requisitos del movil

- Cualquier smartphone con navegador moderno (Chrome, Safari, Firefox)
- Datos moviles o wifi diferente al del servidor
- Camara funcional para el escaner

### Prueba paso a paso

1. ACCESO BASICO
   Abre Chrome o Safari en el movil.
   Escribe: https://app.iasmrd.com
   Debe aparecer la pantalla de login con candado verde.

2. LOGIN
   Usuario: yusniel (o el que uses)
   Contrasena: tu contrasena
   Debe entrar correctamente.

3. NAVEGACION
   Prueba navegar por el menu: Herramientas, EPIs, Acceso remoto.
   Las paginas deben cargar rapido (< 3 segundos desde cualquier lugar).

4. ESCANER QR
   Ve a Acceso remoto en el movil.
   Pulsa "Abrir escaner".
   Debe pedir permiso para usar la camara.
   Acepta y apunta a un codigo QR de herramienta.
   Debe mostrar la ficha de la herramienta.

5. INSTALAR COMO APP (PWA)
   En Chrome Android: menu de tres puntos > "Anadir a pantalla de inicio"
   En Safari iOS: boton compartir > "Anadir a pantalla de inicio"
   Se instalara como una app nativa sin icono de navegador.

6. DIAGNOSTICO COMPLETO
   Entra como admin > Acceso remoto > "Probar conexion"
   Deben aparecer 12 comprobaciones. Los checks de SSL y DNS
   solo seran verdes si el tunel esta correctamente configurado.

---

## RECUPERAR EL TUNEL SI SE PIERDE LA CONEXION

Ver: docs/RECUPERAR_TUNEL.md

Resumen rapido:
1. Verificar que MRD Tool Control responde: http://localhost:8000/health
2. Verificar que cloudflared esta en marcha: sc query cloudflared
3. Si el servicio esta parado: sc start cloudflared
4. Si el token expiro o el tunel se elimino: repetir desde el Paso 2 de esta guia
5. Nunca reinstales cloudflared si el servicio ya funciona — solo reinicialo

---

## SEGURIDAD

- El token del tunel se almacena SOLO en el registro de Windows del servicio.
  NO esta en ningun archivo de texto, log, Git ni en esta documentacion.

- Cloudflare cifra todo el trafico con TLS 1.3. No hay datos en claro.

- La IP publica del servidor nunca se expone a Internet.

- Puedes anadir Cloudflare Access (autenticacion adicional) para proteger
  el acceso incluso si alguien tiene la URL. Ver: docs/CLOUDFLARE_ACCESS.md

---

## ARCHIVOS RELEVANTES

    config/local.env                    Variables de produccion (SECRET_KEY, URLs)
    scripts/setup_cloudflare_tunnel.ps1 Wizard de configuracion inicial
    scripts/cloudflare_status.ps1       Estado del tunel y servicios
    scripts/cloudflare_test.ps1         8 pruebas de conectividad
    scripts/cloudflare_restart.ps1      Reiniciar cloudflared (requiere Admin)
    scripts/cloudflare_logs.ps1         Ver logs de cloudflared
    docs/RECUPERAR_TUNEL.md             Guia de recuperacion ante incidencias
    docs/CLOUDFLARE_ACCESS.md           Proteccion adicional con Cloudflare Access
    docs/CLOUDFLARE_SECURITY.md         Buenas practicas de seguridad

