# Probar la Aplicación desde el Móvil

## Requisitos previos

- El servicio `cloudflared` debe estar en ejecución en el PC servidor
- La app MRD debe estar en ejecución (`net start MRDToolControl`)
- El PC debe tener conexión a internet

---

## Opción A — Escanear el código QR

1. Inicia sesión en la aplicación desde el PC
2. Ve a **Acceso Remoto** (menú lateral)
3. Verás el código QR en pantalla
4. Abre la **cámara del móvil** y apunta al QR
5. Toca el enlace que aparece en pantalla
6. Se abrirá `https://app.iasmrd.com/scan` en el navegador del móvil

---

## Opción B — Escribir la URL directamente

Abre el navegador del móvil y escribe:

```
https://app.iasmrd.com
```

---

## Opción C — Desde otra red (datos móviles)

La URL pública funciona desde cualquier conexión a internet, incluidos datos móviles. No es necesario estar conectado a la misma WiFi que el servidor.

---

## Pantalla de escaneo (operarios)

La ruta `https://app.iasmrd.com/scan` está optimizada para móvil. Permite a los operarios:
- Buscar herramientas por código QR de la etiqueta
- Registrar préstamos y devoluciones sin iniciar sesión (si está habilitado)

---

## Verificar que funciona

Desde el PC, ejecuta:

```powershell
.\scripts\cloudflare_test.ps1
```

Si todas las pruebas pasan (especialmente "URL pública accesible" y "Ruta /scan disponible"), el acceso desde móvil funcionará correctamente.

---

## Solución de problemas en el móvil

| Problema | Causa probable | Solución |
|---|---|---|
| "No se puede conectar" | Túnel caído | `.\scripts\cloudflare_restart.ps1` |
| "502 Bad Gateway" | App MRD parada | `net start MRDToolControl` |
| QR no se escanea | QR desactualizado | Refresca el panel Acceso Remoto |
| Certificado no válido | Sin internet en PC | Verificar conexión del servidor |
