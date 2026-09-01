/* MRD TOOL CONTROL — Service Worker v2.7.6 */
// Incrementar CACHE_NAME al desplegar nueva version invalida la cache antigua.
// El cliente puede forzar actualizacion con: postMessage({type:'SKIP_WAITING'})
const CACHE_NAME = 'mrd-static-v2.7.6';

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
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Fetch: red primero para no servir CSS/JS antiguos tras una actualización.
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Solo interceptar GET del mismo origen
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) {
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
