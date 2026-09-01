# Seguridad con Cloudflare — MRD TOOL CONTROL

## Principios de seguridad aplicados

### 1. Nunca exponer la IP del servidor

El servidor Windows no abre ningún puerto al exterior. Todo el tráfico llega a través de `cloudflared`, que establece una conexión saliente a Cloudflare. La IP pública del servidor permanece oculta.

### 2. HTTPS obligatorio

`MRD_HTTPS_ONLY=true` en `config/local.env` garantiza que:
- Las cookies de sesión solo se envían por HTTPS (`Secure=true`)
- La cabecera HSTS se incluye en las respuestas de producción
- Los clientes sin HTTPS son bloqueados a nivel de aplicación

### 3. Proxy headers de Cloudflare

`MRD_TRUST_PROXY_HEADERS=true` configura la aplicación para leer:
- `X-Forwarded-Proto` → detectar HTTPS aunque la conexión interna sea HTTP
- `X-Forwarded-For` → obtener la IP real del cliente (no la de Cloudflare)
- `CF-Connecting-IP` → IP real del visitante (cabecera de Cloudflare)

**Importante:** Solo confiar en estos headers cuando el tráfico proviene efectivamente de Cloudflare. Si la app se expone directamente sin Cloudflare, desactivar `MRD_TRUST_PROXY_HEADERS`.

### 4. TrustedHost

La aplicación solo acepta peticiones para los hosts configurados en `MRD_ALLOWED_HOSTS`:
```
app.iasmrd.com,localhost,127.0.0.1
```
Peticiones con cabecera `Host:` distinta reciben un error 400.

### 5. Protección CSRF

Todos los formularios y endpoints mutables están protegidos con token CSRF (doble-submit cookie). Las únicas rutas exentas son `/health`, `/login` y `/scan/buscar`.

### 6. Credenciales del túnel

- El token del túnel Cloudflare **nunca** debe escribirse en archivos de código, Git, logs ni documentación
- Se almacena en `%USERPROFILE%\.cloudflared\<UUID>.json` (generado por cloudflared)
- El servicio de Windows lee las credenciales directamente de esa ruta

### 7. Qué NO hacer

- No abrir el puerto 8000 en el firewall de Windows ni en el router
- No usar ngrok como solución permanente
- No exponer la IP pública del servidor en DNS sin proxy de Cloudflare
- No guardar el token del túnel en `config/local.env`, `.env.example` ni en Git
- No desactivar `MRD_TRUST_PROXY_HEADERS` si el tráfico pasa por Cloudflare (rompería la detección de HTTPS y la IP real del cliente)

## Recomendaciones adicionales

- **Cloudflare WAF:** Activar el nivel Free de WAF en el panel de Cloudflare para bloquear ataques comunes
- **Rate limiting de Cloudflare:** Complementa el rate limiting interno de MRD para ataques de fuerza bruta
- **Cloudflare Access:** Ver `docs/CLOUDFLARE_ACCESS.md` para añadir autenticación previa opcional
- **Bot Fight Mode:** Activar en Cloudflare para bloquear bots automáticos
