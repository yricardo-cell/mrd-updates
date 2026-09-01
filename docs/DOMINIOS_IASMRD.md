# Dominios y DNS — IASMRD

## Estructura de dominios

| Registro | Tipo | Destino |
|---|---|---|
| `iasmrd.com` | NS / raíz | Gestionado por Cloudflare |
| `app.iasmrd.com` | CNAME | `<UUID>.cfargotunnel.com` (creado por cloudflared) |

## URL de la aplicación

La única URL de acceso a la aplicación en producción es:

```
https://app.iasmrd.com
```

Esta URL siempre usa HTTPS (gestionado por Cloudflare). No se expone ningún puerto HTTP público.

## Registro CNAME

El registro CNAME `app.iasmrd.com` apunta al túnel de Cloudflare. Se crea automáticamente con:

```powershell
cloudflared tunnel route dns MRD-TOOL-CONTROL app.iasmrd.com
```

Para verificarlo desde PowerShell:
```powershell
Resolve-DnsName app.iasmrd.com
```

El resultado debe mostrar un CNAME a `<UUID>.cfargotunnel.com`.

## SSL/TLS

Cloudflare gestiona el certificado TLS para `*.iasmrd.com`. No es necesario instalar ningún certificado en el servidor Windows.

Configuración recomendada en el panel de Cloudflare:
- **SSL/TLS → Modo de cifrado:** Full (strict) o Full
- **SSL/TLS → HSTS:** Activar con `max-age=31536000`
- **Reglas de página:** Redirigir todo HTTP a HTTPS

## Seguridad DNS

Con Cloudflare activado:
- La IP del servidor Windows nunca queda expuesta en el DNS
- Todo el tráfico pasa por los proxies de Cloudflare
- Se puede activar Cloudflare WAF (Web Application Firewall) para protección adicional
