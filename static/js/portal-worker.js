(() => {
  let installPrompt = null;
  const button = () => document.getElementById('install-app');

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
    });
  }

  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    installPrompt = event;
    if (button()) button().hidden = false;
  });

  window.addEventListener('appinstalled', () => {
    installPrompt = null;
    if (button()) button().hidden = true;
  });

  window.addEventListener('DOMContentLoaded', () => {
    if (!button()) return;
    button().addEventListener('click', async () => {
      if (!installPrompt) return;
      await installPrompt.prompt();
      await installPrompt.userChoice;
      installPrompt = null;
      button().hidden = true;
    });
  });
})();

// Avisos push del portal (2.7.48): el trabajador activa los avisos en su móvil
// y recibe al instante "pedido listo", "entregado" o "te falta kit".
(() => {
  const token = document.body && document.body.dataset.portalToken;
  const button = document.getElementById('activar-avisos');
  if (!token || !button || !('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) return;
  const csrf = () => (document.cookie.split('; ').find(v => v.startsWith('mrd_csrf=')) || '').split('=').slice(1).join('');
  const b64 = value => {
    const padding = '='.repeat((4 - value.length % 4) % 4);
    const raw = atob((value + padding).replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
  };
  const enviar = sub => fetch('/portal/' + token + '/push/suscribirse', {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf() },
    body: JSON.stringify(sub.toJSON ? sub.toJSON() : sub),
  });
  navigator.serviceWorker.ready.then(async reg => {
    const actual = await reg.pushManager.getSubscription();
    if (actual) { enviar(actual).catch(() => {}); return; }
    if (Notification.permission !== 'denied') button.hidden = false;
  }).catch(() => {});
  button.addEventListener('click', async () => {
    try {
      const permiso = await Notification.requestPermission();
      if (permiso !== 'granted') { button.textContent = 'Avisos bloqueados en este móvil'; return; }
      const reg = await navigator.serviceWorker.ready;
      const r = await fetch('/portal/' + token + '/push/clave', { credentials: 'same-origin' });
      const { public_key } = await r.json();
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(public_key) });
      const res = await enviar(sub);
      button.textContent = res.ok ? 'Avisos activados' : 'No se pudo activar';
      if (res.ok) setTimeout(() => { button.hidden = true; }, 2500);
    } catch (err) {
      button.textContent = 'No se pudo activar';
    }
  });
})();
