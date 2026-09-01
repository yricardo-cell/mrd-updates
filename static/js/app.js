/**
 * MRD TOOL CONTROL — app.js
 * Funciones globales de la interfaz
 */

document.addEventListener('DOMContentLoaded', () => {
  initSidebar();
  initFormProtection();
  checkUpdateBanner();
});

// ── Sidebar móvil ────────────────────────────────────────────────────────────
function initSidebar() {
  const btn = document.getElementById('sidebarToggle');
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebarOverlay');
  if (!btn || !sidebar) return;

  btn.addEventListener('click', () => {
    sidebar.classList.toggle('open');
    overlay.classList.toggle('active');
  });
  overlay.addEventListener('click', () => {
    sidebar.classList.remove('open');
    overlay.classList.remove('active');
  });
}

// ── Toasts ───────────────────────────────────────────────────────────────────
function mostrarToast(mensaje, tipo = 'info', duracion = 3500) {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `mrd-toast ${tipo}`;
  const iconos = { success: 'bi-check-circle', error: 'bi-exclamation-triangle', info: 'bi-info-circle' };
  toast.innerHTML = `<i class="bi ${iconos[tipo] || 'bi-info-circle'} me-2"></i>${mensaje}`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'slideInRight 0.25s ease reverse';
    setTimeout(() => toast.remove(), 250);
  }, duracion);
}

// ── Proteger formularios de doble submit ─────────────────────────────────────
function initFormProtection() {
  document.querySelectorAll('form').forEach(form => {
    form.addEventListener('submit', function() {
      const btn = this.querySelector('[type=submit]');
      if (btn && !btn.disabled) {
        setTimeout(() => {
          btn.disabled = true;
          const orig = btn.innerHTML;
          btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Procesando...';
          setTimeout(() => { btn.disabled = false; btn.innerHTML = orig; }, 8000);
        }, 10);
      }
    });
  });
}

// ── Banner de actualización ───────────────────────────────────────────────────
function checkUpdateBanner() {
  const banner = document.getElementById('update-banner');
  if (!banner) return;
  if (sessionStorage.getItem('mrd_update_checked')) return;

  fetch('/api/version/check')
    .then(r => r.json())
    .then(data => {
      sessionStorage.setItem('mrd_update_checked', '1');
      if (data.actualizacion_disponible) {
        banner.querySelector('span').textContent = `Nueva versión v${data.nueva_version} disponible — `;
        banner.classList.remove('d-none');
      }
    })
    .catch(() => {});
}

function mostrarBannerActualizacion(version) {
  const banner = document.getElementById('update-banner');
  if (banner) {
    banner.querySelector('span').textContent = `Nueva versión v${version} disponible — `;
    banner.classList.remove('d-none');
  }
}

// ── Autocompletado con debounce ───────────────────────────────────────────────
function debounce(fn, delay) {
  let timer;
  return function(...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

function initAutocompletado(inputId, url, onSelect) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const buscar = debounce((q) => {
    if (q.length < 2) return;
    fetch(`${url}?q=${encodeURIComponent(q)}`)
      .then(r => r.json())
      .then(datos => onSelect(datos))
      .catch(() => {});
  }, 280);
  input.addEventListener('input', () => buscar(input.value));
}
