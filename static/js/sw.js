/* MRD TOOL CONTROL — Service Worker v2.7.50 */
// Incrementar CACHE_NAME al desplegar nueva version invalida la cache antigua.
// El cliente puede forzar actualizacion con: postMessage({type:'SKIP_WAITING'})
const CACHE_NAME = 'mrd-static-v2.7.77';

// Assets estaticos pre-cacheados — NUNCA paginas HTML ni datos de API
const STATIC_ASSETS = [
  '/static/css/bootstrap.min.css',
  '/static/css/bootstrap-icons.min.css',
  '/static/css/mrd.css',
  '/static/css/portal-trabajador.css',
  '/static/css/worker-login.css',
  '/static/js/bootstrap.bundle.min.js',
  '/static/js/scanner_hid.js',
  '/static/js/mrd.js',
  '/static/js/portal-worker.js',
  '/static/js/chart.umd.min.js',
  '/static/js/zxing.min.js',
  '/static/offline.html',
];


// ── Portal del trabajador sin cobertura (mejora 5) ───────────────────────
// La última página del portal se guarda para verla sin red; los envíos (POST)
// del portal que fallan por falta de red se guardan en IndexedDB y se reenvían
// al volver la conexión (Background Sync o mensaje REPLAY desde la página).
const PORTAL_CACHE = CACHE_NAME + '-portal';
const COLA_DB = 'mrd-portal-cola', COLA_STORE = 'envios';

function colaAbrir() {
  return new Promise((res, rej) => {
    const req = indexedDB.open(COLA_DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(COLA_STORE, { keyPath: 'id', autoIncrement: true });
    req.onsuccess = () => res(req.result);
    req.onerror = () => rej(req.error);
  });
}

async function colaGuardar(request) {
  const body = await request.clone().arrayBuffer();
  const headers = [];
  request.headers.forEach((v, k) => headers.push([k, v]));
  const db = await colaAbrir();
  await new Promise((res, rej) => {
    const tx = db.transaction(COLA_STORE, 'readwrite');
    tx.objectStore(COLA_STORE).add({ url: request.url, method: request.method, headers, body, ts: Date.now() });
    tx.oncomplete = res; tx.onerror = () => rej(tx.error);
  });
}

async function colaReenviar() {
  const db = await colaAbrir();
  const items = await new Promise((res, rej) => {
    const req = db.transaction(COLA_STORE, 'readonly').objectStore(COLA_STORE).getAll();
    req.onsuccess = () => res(req.result || []); req.onerror = () => rej(req.error);
  });
  let enviados = 0;
  for (const it of items) {
    try {
      await fetch(it.url, { method: it.method, headers: it.headers, body: it.body, credentials: 'include', redirect: 'follow' });
      await new Promise((res, rej) => {
        const tx = db.transaction(COLA_STORE, 'readwrite');
        tx.objectStore(COLA_STORE).delete(it.id);
        tx.oncomplete = res; tx.onerror = () => rej(tx.error);
      });
      enviados++;
    } catch (e) {
      break;   // sigue sin red: lo intentamos más tarde
    }
  }
  if (enviados) {
    const clients = await self.clients.matchAll({ type: 'window' });
    clients.forEach(c => c.postMessage({ type: 'COLA_ENVIADA', enviados }));
  }
  return enviados;
}

function respuestaEnCola() {
  const html = '<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Guardado sin cobertura</title><style>body{font-family:system-ui,sans-serif;background:#071522;color:#f8fafc;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:24px;text-align:center}a{color:#67e8f9;font-weight:700}</style></head><body><div><h1>Guardado sin cobertura</h1><p>Lo que has enviado se ha guardado en el móvil y se mandará solo cuando vuelva la conexión.</p><p><a href="javascript:history.back()">Volver a mi portal</a></p></div></body></html>';
  return new Response(html, { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
}

self.addEventListener('sync', event => {
  if (event.tag === 'mrd-portal-cola') event.waitUntil(colaReenviar());
});

// ── Instalación: pre-cachear assets estáticos ─────────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS).catch(err => {
        console.warn('[SW] Error pre-cacheando assets:', err);
      });
    }).then(() => self.skipWaiting())
  );
});

// ── Activación: limpiar caches antiguas ──────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME && k !== CACHE_NAME + '-portal').map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Fetch: red primero para no servir CSS/JS antiguos tras una actualización.
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Envíos del portal sin cobertura: a la cola (mejora 5)
  if (event.request.method === 'POST' && url.origin === self.location.origin && url.pathname.startsWith('/portal/')) {
    event.respondWith(
      fetch(event.request.clone()).catch(async () => {
        try { await colaGuardar(event.request); } catch (e) { /* sin IndexedDB: se pierde */ }
        return respuestaEnCola();
      })
    );
    return;
  }

  // Solo interceptar GET del mismo origen
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) {
    return;
  }

  // Página del portal del trabajador: red primero; sin red, la última copia guardada (mejora 5)
  if (event.request.mode === 'navigate' && url.pathname.startsWith('/portal/')) {
    event.respondWith(
      fetch(event.request, {cache: 'no-store'}).then(response => {
        if (response.ok && response.headers.get('content-type') && response.headers.get('content-type').includes('text/html')) {
          const clone = response.clone();
          caches.open(PORTAL_CACHE).then(cache => cache.put(url.pathname, clone));
        }
        return response;
      }).catch(() => caches.open(PORTAL_CACHE).then(cache => cache.match(url.pathname)).then(r => r || caches.match('/static/offline.html')))
    );
    return;
  }

  // Assets estáticos: red primero, caché solo como respaldo sin conexión.
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      fetch(event.request, {cache: 'no-store'}).then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          }
          return response;
      }).catch(() => caches.match(event.request))
    );
    return;
  }

  // Las páginas y API nunca se cachean porque contienen datos y sesiones. Si
  // una navegación falla, solo se muestra el capturador local sin información
  // privada; este guarda códigos para verificarlos cuando vuelva la conexión.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request, {cache: 'no-store'}).catch(() => caches.match('/static/offline.html'))
    );
  }
});

// ── Mensaje para forzar actualización desde el cliente ───────────────────
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  if (event.data && event.data.type === 'REPLAY') {
    event.waitUntil(colaReenviar().catch(() => {}));
  }
});

// ── Notificaciones push (Web Push / VAPID) ────────────────────────────────
self.addEventListener('push', event => {
  let data = { titulo: 'MRD TOOL CONTROL', mensaje: '', enlace: '/' };
  try {
    if (event.data) data = { ...data, ...event.data.json() };
  } catch (e) { /* payload no es JSON, se usa el valor por defecto */ }

  event.waitUntil(
    self.registration.showNotification(data.titulo, {
      body: data.mensaje,
      icon: '/static/icons/icon-192.png',
      badge: '/static/icons/icon-192.png',
      data: { enlace: data.enlace || '/' },
      tag: 'mrd-aviso',
    }).catch(() => {})
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.enlace) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clients => {
      for (const c of clients) {
        if (c.url.includes(self.location.origin) && 'focus' in c) {
          c.navigate(url);
          return c.focus();
        }
      }
      return self.clients.openWindow(url);
    })
  );
});
