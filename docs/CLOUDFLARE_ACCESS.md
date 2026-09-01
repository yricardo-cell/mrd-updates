# Cloudflare Access — Control de acceso adicional (opcional)

Cloudflare Access permite añadir una capa de autenticación delante de `https://app.iasmrd.com`, antes de que la petición llegue a la aplicación. Es opcional pero recomendado para entornos con alta seguridad.

---

## ¿Qué hace Cloudflare Access?

Cuando está activo, cualquier usuario que visite `https://app.iasmrd.com` verá primero una pantalla de Cloudflare que le pedirá autenticarse (por email OTP, Google, Microsoft, etc.). Solo tras superar esa pantalla llega a la aplicación MRD.

Esto añade una segunda capa de seguridad: aunque alguien obtuviera credenciales de MRD, necesitaría también superar Cloudflare Access.

---

## Configuración en el panel de Cloudflare

1. Panel Cloudflare → **Zero Trust** → **Access** → **Applications**
2. Click **Add an application** → **Self-hosted**
3. Rellena:
   - **Application name:** MRD Tool Control
   - **Session duration:** 8 hours
   - **Application domain:** `app.iasmrd.com`
4. En **Policies**, crea una regla `Allow`:
   - **Rule name:** Equipo autorizado
   - **Include:** Email → añade los correos del equipo autorizado
   - O usa **IP ranges** si los accesos son desde IPs fijas
5. Guarda y despliega

---

## Bypass para la ruta /scan (operarios sin cuenta)

Si los operarios usan `/scan` sin credenciales de Cloudflare Access, añade una política de **bypass** solo para esa ruta:

1. En la misma aplicación → **Policies** → **Add a policy**
2. **Action:** Bypass
3. **Path:** `/scan`
4. Guarda

Esto permite el acceso libre a `/scan` sin afectar al resto de la aplicación.

---

## Modo sin Cloudflare Access

Si no necesitas esta capa adicional, no es necesario configurar nada. La aplicación MRD ya tiene su propio sistema de login con JWT. Cloudflare Access es un extra opcional.

---

## Documentación oficial

https://developers.cloudflare.com/cloudflare-one/applications/configure-apps/self-hosted-apps/
