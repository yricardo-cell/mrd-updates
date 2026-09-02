/* ============================================================
   MRD TOOL CONTROL — App JS v2
   ============================================================ */

function mrdEscapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

function mrdSafeId(value) {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? String(parsed) : '0';
}

// ── Theme ─────────────────────────────────────────────────────
const Theme = (() => {
  const KEY = 'mrd_theme';
  const root = document.documentElement;

  function apply(t) {
    root.setAttribute('data-theme', t);
    localStorage.setItem(KEY, t);
    const icon = document.getElementById('theme-icon');
    if (icon) icon.className = t === 'dark' ? 'bi bi-sun' : 'bi bi-moon';
  }

  function toggle() {
    apply(current() === 'dark' ? 'light' : 'dark');
  }

  function current() {
    return localStorage.getItem(KEY) || 'light';
  }

  function init() {
    apply(current());
  }

  return { init, toggle, current };
})();

// ── Sidebar ───────────────────────────────────────────────────
const Sidebar = (() => {
  const KEY = 'mrd_sidebar';
  let sidebar, main;

  function init() {
    sidebar = document.getElementById('app-sidebar');
    main = document.getElementById('app-main');
    if (!sidebar) return;
    const mini = localStorage.getItem(KEY) === 'mini';
    if (mini) setMini(true);
  }

  function toggle() {
    const isMini = sidebar.classList.contains('mini');
    setMini(!isMini);
  }

  function setMini(mini) {
    sidebar.classList.toggle('mini', mini);
    if (main) main.classList.toggle('expanded', mini);
    localStorage.setItem(KEY, mini ? 'mini' : 'full');
  }

  return { init, toggle };
})();

// ── Toast ──────────────────────────────────────────────────────
const Toast = (() => {
  let container;

  const ICONS = {
    success: 'bi-check-circle-fill',
    error:   'bi-x-circle-fill',
    warning: 'bi-exclamation-triangle-fill',
    info:    'bi-info-circle-fill',
  };

  function show(msg, type = 'info', dur = 3500) {
    if (!container) {
      container = document.getElementById('toast-container');
      if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        document.body.appendChild(container);
      }
    }
    const t = document.createElement('div');
    t.className = `toast toast-${type}`;
    const icon = document.createElement('i');
    icon.className = `bi ${ICONS[type] || ICONS.info} toast-icon`;
    const message = document.createElement('span');
    message.className = 'toast-msg';
    message.textContent = String(msg ?? '');
    const close = document.createElement('button');
    close.className = 'toast-close'; close.type = 'button'; close.setAttribute('aria-label', 'Cerrar');
    close.innerHTML = '<i class="bi bi-x"></i>';
    close.addEventListener('click', () => t.remove());
    t.append(icon, message, close);
    container.appendChild(t);
    setTimeout(() => {
      t.classList.add('removing');
      setTimeout(() => t.remove(), 200);
    }, dur);
  }

  return { show, success: m => show(m,'success'), error: m => show(m,'error',5000),
           warning: m => show(m,'warning'), info: m => show(m,'info') };
})();

// ── Confirm dialog ────────────────────────────────────────────
function mrdConfirm(msg, onConfirm, opts = {}) {
  const {
    title = 'Confirmar acción',
    btnOk = 'Confirmar',
    btnCancel = 'Cancelar',
    danger = false,
  } = opts;

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal" style="max-width:400px">
      <div class="modal-header">
        <span class="modal-title">${mrdEscapeHtml(title)}</span>
        <button class="modal-close" onclick="this.closest('.modal-overlay').remove()"><i class="bi bi-x"></i></button>
      </div>
      <div class="modal-body" style="padding:20px">
        <p style="color:var(--text-2)">${mrdEscapeHtml(msg)}</p>
      </div>
      <div class="modal-footer">
        <button class="btn btn-outline btn-sm" onclick="this.closest('.modal-overlay').remove()">${mrdEscapeHtml(btnCancel)}</button>
        <button class="btn ${danger ? 'btn-danger' : 'btn-primary'} btn-sm confirm-ok">${mrdEscapeHtml(btnOk)}</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  requestAnimationFrame(() => overlay.classList.add('open'));

  overlay.querySelector('.confirm-ok').addEventListener('click', () => {
    overlay.remove();
    onConfirm();
  });
  overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
}

// ── Modal helpers ─────────────────────────────────────────────
function openModal(id) {
  const m = document.getElementById(id);
  if (m) {
    m.classList.add('open');
    m.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';
    const focusable = m.querySelector('input:not([type="hidden"]), select, textarea, button');
    if (focusable) requestAnimationFrame(() => focusable.focus({preventScroll:true}));
  }
}
function closeModal(id) {
  const m = document.getElementById(id);
  if (m) {
    m.classList.remove('open');
    m.setAttribute('aria-hidden', 'true');
  }
  if (!document.querySelector('.modal-overlay.open')) document.body.style.overflow = '';
}

document.addEventListener('click', e => {
  if (e.target.classList.contains('modal-overlay')) {
    e.target.classList.remove('open');
    e.target.setAttribute('aria-hidden', 'true');
    if (!document.querySelector('.modal-overlay.open')) document.body.style.overflow = '';
  }
});

// Evita que una navegación atrás/recarga restaurada deje la página bloqueada.
window.addEventListener('pageshow', () => {
  if (!document.querySelector('.modal-overlay.open')) document.body.style.overflow = '';
});

// ── Tabs ───────────────────────────────────────────────────────
function initTabs(container) {
  const ctx = container || document;
  ctx.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.tab;
      const parent = btn.closest('[data-tabs]') || btn.closest('.card') || document;
      parent.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      parent.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      btn.classList.add('active');
      const content = parent.querySelector(`.tab-content[data-tab="${target}"]`);
      if (content) content.classList.add('active');
    });
  });
}

// ── Smart Table ────────────────────────────────────────────────
function initSmartTable(tableId) {
  const table = document.getElementById(tableId);
  if (!table) return;

  // Sort
  table.querySelectorAll('th[data-sort]').forEach(th => {
    th.style.cursor = 'pointer';
    th.addEventListener('click', () => {
      const col = th.dataset.sort;
      const asc = !th.classList.contains('sorted-asc');
      table.querySelectorAll('th').forEach(h => h.classList.remove('sorted-asc','sorted-desc'));
      th.classList.add(asc ? 'sorted-asc' : 'sorted-desc');
      sortTable(table, col, asc);
    });
  });

  // Row checkbox
  const selectAll = table.querySelector('.select-all');
  if (selectAll) {
    selectAll.addEventListener('change', () => {
      table.querySelectorAll('.row-check').forEach(cb => {
        cb.checked = selectAll.checked;
        cb.closest('tr').classList.toggle('selected', selectAll.checked);
      });
      updateBulkBar(table);
    });
  }

  table.querySelectorAll('.row-check').forEach(cb => {
    cb.addEventListener('change', () => {
      cb.closest('tr').classList.toggle('selected', cb.checked);
      updateBulkBar(table);
    });
  });
}

function sortTable(table, col, asc) {
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  rows.sort((a, b) => {
    const aVal = a.querySelector(`td[data-col="${col}"]`)?.textContent.trim() || '';
    const bVal = b.querySelector(`td[data-col="${col}"]`)?.textContent.trim() || '';
    return asc ? aVal.localeCompare(bVal, 'es', { numeric: true })
               : bVal.localeCompare(aVal, 'es', { numeric: true });
  });
  rows.forEach(r => tbody.appendChild(r));
}

function updateBulkBar(table) {
  const selected = table.querySelectorAll('.row-check:checked').length;
  const bar = document.getElementById('bulk-bar');
  if (bar) {
    bar.classList.toggle('visible', selected > 0);
    const cnt = bar.querySelector('.bulk-count');
    if (cnt) cnt.textContent = selected;
  }
}

// ── Live search (filtro instantáneo sobre tabla) ───────────────
function initLiveSearch(inputId, tableId, cols) {
  const input = document.getElementById(inputId);
  const table = document.getElementById(tableId);
  if (!input || !table) return;

  input.addEventListener('input', () => {
    const q = input.value.toLowerCase().trim();
    table.querySelectorAll('tbody tr').forEach(row => {
      const text = (cols
        ? cols.map(c => row.querySelector(`td[data-col="${c}"]`)?.textContent || '').join(' ')
        : row.textContent
      ).toLowerCase();
      row.style.display = text.includes(q) ? '' : 'none';
    });
  });
}

// ── Buscador global (Ctrl+K + dropdown) ──────────────────────
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault();
    const s = document.getElementById('global-search');
    if (s) { s.focus(); s.select(); }
  }
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay.open').forEach(m => {
      m.classList.remove('open');
      document.body.style.overflow = '';
    });
  }
});

function initGlobalSearch() {
  const input = document.getElementById('global-search');
  if (!input) return;
  const wrap = input.closest('.search-input-wrap');
  if (!wrap) return;

  let drop = document.createElement('div');
  drop.className = 'search-dropdown';
  wrap.appendChild(drop);

  let timer;

  function closeDrop() { drop.classList.remove('open'); }

  function renderDrop(data) {
    const { herramientas = [], trabajadores = [], obras = [], maquinaria = [], albaranes = [] } = data;
    const total = herramientas.length + trabajadores.length + obras.length + maquinaria.length + albaranes.length;
    if (total === 0) {
      drop.innerHTML = '<div class="search-drop-empty"><i class="bi bi-search"></i> Sin resultados para "<strong>' + mrdEscapeHtml(input.value) + '</strong>"</div>';
    } else {
      let html = '';
      if (herramientas.length) {
        html += '<div class="search-drop-section">Herramientas</div>';
        herramientas.forEach(h => {
          const est = (h.estado || '').replace(/_/g, ' ');
          html += `<a href="/herramientas/${mrdSafeId(h.id)}" class="search-drop-item">
            <div class="search-drop-icon" style="background:var(--primary-light);color:var(--primary)"><i class="bi bi-wrench-adjustable"></i></div>
            <div><div class="search-drop-name">${mrdEscapeHtml(h.codigo)} — ${mrdEscapeHtml(h.nombre)}</div><div class="search-drop-sub">${mrdEscapeHtml(est)}</div></div>
          </a>`;
        });
      }
      if (trabajadores.length) {
        html += '<div class="search-drop-section">Trabajadores</div>';
        trabajadores.forEach(t => {
          html += `<a href="/trabajadores" class="search-drop-item">
            <div class="search-drop-icon" style="background:var(--success-light);color:var(--success)"><i class="bi bi-person"></i></div>
            <div><div class="search-drop-name">${mrdEscapeHtml(t.nombre)}</div><div class="search-drop-sub">${mrdEscapeHtml(t.cargo || '')}</div></div>
          </a>`;
        });
      }
      if (obras.length) {
        html += '<div class="search-drop-section">Obras</div>';
        obras.forEach(o => {
          html += `<a href="/obras/${mrdSafeId(o.id)}" class="search-drop-item">
            <div class="search-drop-icon" style="background:var(--info-light);color:var(--info)"><i class="bi bi-building"></i></div>
            <div><div class="search-drop-name">${mrdEscapeHtml(o.nombre)}</div><div class="search-drop-sub">${mrdEscapeHtml(o.numero || '')}</div></div>
          </a>`;
        });
      }
      if (maquinaria.length) {
        html += '<div class="search-drop-section">Maquinaria</div>';
        maquinaria.forEach(m => {
          html += `<a href="/maquinaria/${mrdSafeId(m.id)}" class="search-drop-item">
            <div class="search-drop-icon" style="background:var(--orange-light);color:var(--orange)"><i class="bi bi-truck-front"></i></div>
            <div><div class="search-drop-name">${mrdEscapeHtml(m.nombre)}</div><div class="search-drop-sub">${mrdEscapeHtml(m.matricula || '')}</div></div>
          </a>`;
        });
      }
      if (albaranes.length) {
        html += '<div class="search-drop-section">Albaranes</div>';
        albaranes.forEach(a => {
          html += `<a href="/albaranes-salida/${mrdSafeId(a.id)}" class="search-drop-item">
            <div class="search-drop-icon" style="background:var(--gray-light);color:var(--text-2)"><i class="bi bi-file-earmark-text"></i></div>
            <div><div class="search-drop-name">${mrdEscapeHtml(a.numero)}</div><div class="search-drop-sub">${mrdEscapeHtml((a.estado || '').replace(/_/g, ' '))}</div></div>
          </a>`;
        });
      }
      const q = encodeURIComponent(input.value.trim());
      html += `<a href="/buscar?q=${q}" class="search-drop-footer"><i class="bi bi-arrow-right-circle"></i> Ver todos los resultados</a>`;
      drop.innerHTML = html;
    }
    drop.classList.add('open');
  }

  input.addEventListener('input', () => {
    const q = input.value.trim();
    clearTimeout(timer);
    if (q.length < 2) { closeDrop(); return; }
    timer = setTimeout(() => {
      fetch(`/api/buscar?q=${encodeURIComponent(q)}`)
        .then(r => r.json())
        .then(renderDrop)
        .catch(() => closeDrop());
    }, 220);
  });

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && input.value.trim()) {
      e.preventDefault();
      closeDrop();
      window.location.href = `/buscar?q=${encodeURIComponent(input.value.trim())}`;
    }
    if (e.key === 'Escape') closeDrop();
  });

  document.addEventListener('click', e => {
    if (!wrap.contains(e.target)) closeDrop();
  });
}

// ── Firma digital (canvas) ────────────────────────────────────
function initFirmaCanvas(canvasId, inputId) {
  const canvas = document.getElementById(canvasId);
  const input  = document.getElementById(inputId);
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  const ph  = canvas.parentElement.querySelector('.firma-canvas-placeholder');
  const clr = canvas.parentElement.querySelector('.firma-clear-btn');

  let drawing = false;
  let hasStrokes = false;

  function getPos(e) {
    const r = canvas.getBoundingClientRect();
    const src = e.touches ? e.touches[0] : e;
    return { x: (src.clientX - r.left) * (canvas.width / r.width),
             y: (src.clientY - r.top)  * (canvas.height / r.height) };
  }

  function startDraw(e) {
    e.preventDefault();
    drawing = true;
    const p = getPos(e);
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
    if (ph) ph.classList.add('hidden');
    if (clr) clr.classList.add('visible');
  }

  function draw(e) {
    if (!drawing) return;
    e.preventDefault();
    const p = getPos(e);
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';
    ctx.strokeStyle = '#1a202c';
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    hasStrokes = true;
  }

  function endDraw() {
    if (!drawing) return;
    drawing = false;
    if (hasStrokes && input) {
      input.value = canvas.toDataURL('image/png');
    }
  }

  canvas.addEventListener('mousedown', startDraw);
  canvas.addEventListener('mousemove', draw);
  canvas.addEventListener('mouseup', endDraw);
  canvas.addEventListener('mouseleave', endDraw);
  canvas.addEventListener('touchstart', startDraw, { passive: false });
  canvas.addEventListener('touchmove', draw, { passive: false });
  canvas.addEventListener('touchend', endDraw);

  if (clr) {
    clr.addEventListener('click', () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (input) input.value = '';
      if (ph) ph.classList.remove('hidden');
      clr.classList.remove('visible');
      hasStrokes = false;
    });
  }
}

function clearFirmaCanvas(canvasId, inputId, phId) {
  const canvas = document.getElementById(canvasId);
  const input  = document.getElementById(inputId);
  const ph     = document.getElementById(phId);
  const clr    = canvas && canvas.parentElement.querySelector('.firma-clear-btn');
  if (canvas) canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
  if (input)  input.value = '';
  if (ph)     ph.classList.remove('hidden');
  if (clr)    clr.classList.remove('visible');
}

// ── Foto preview ───────────────────────────────────────────────
function initPhotoPreview(inputId, previewId) {
  const input = document.getElementById(inputId);
  const preview = document.getElementById(previewId);
  if (!input || !preview) return;

  input.addEventListener('change', () => {
    const file = input.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = e => {
      preview.src = e.target.result;
      preview.style.display = 'block';
    };
    reader.readAsDataURL(file);
  });
}

// ── Form validation ────────────────────────────────────────────
function validateRequired(formId) {
  const form = document.getElementById(formId);
  if (!form) return true;
  let ok = true;
  form.querySelectorAll('[required]').forEach(field => {
    const empty = !field.value.trim();
    field.classList.toggle('error', empty);
    if (empty) ok = false;
  });
  return ok;
}

// ── Submitting state ───────────────────────────────────────────
function setSubmitting(btn, loading = true) {
  if (loading) {
    btn._origText = btn.innerHTML;
    btn.innerHTML = '<i class="bi bi-arrow-clockwise spin"></i> Guardando...';
    btn.disabled = true;
  } else {
    btn.innerHTML = btn._origText || 'Guardar';
    btn.disabled = false;
  }
}

// Spinner style
const spin = document.createElement('style');
spin.textContent = '.spin { animation: spin .6s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }';
document.head.appendChild(spin);

// ── Form protection (doble submit) ───────────────────────────
function restoreSubmitButtons(root = document) {
  root.querySelectorAll('button[data-mrd-submit-locked="1"]').forEach(btn => {
    btn.disabled = false;
    if (btn._mrdOriginalHtml) btn.innerHTML = btn._mrdOriginalHtml;
    delete btn.dataset.mrdSubmitLocked;
  });
}

function initFormProtection() {
  document.querySelectorAll('form').forEach(form => {
    if (form.matches('[data-managed-submit]')) return;
    form.addEventListener('submit', function(event) {
      const btn = this.querySelector('[type=submit]');
      if (btn && !btn.disabled) {
        queueMicrotask(() => {
          if (event.defaultPrevented) return;
          btn._mrdOriginalHtml = btn.innerHTML;
          btn.dataset.mrdSubmitLocked = '1';
          btn.disabled = true;
          btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Procesando...';
        });
      }
    });
  });
}
window.addEventListener('pageshow', () => restoreSubmitButtons());

// ── Debounce + autocompletado ─────────────────────────────────
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

// ── Banner de actualizacion ───────────────────────────────────
function checkUpdateBanner() {
  const banner = document.getElementById('update-banner');
  if (!banner) return;
  if (sessionStorage.getItem('mrd_update_checked')) return;
  fetch('/api/version/check')
    .then(r => r.json())
    .then(data => {
      sessionStorage.setItem('mrd_update_checked', '1');
      if (data.actualizacion_disponible) {
        const span = banner.querySelector('span');
        if (span) span.textContent = 'Nueva version v' + data.nueva_version + ' disponible - ';
        banner.classList.remove('d-none');
      }
    })
    .catch(() => {});
}

// ── CSRF helpers (Sprint 5.2) ────────────────────────────────
function getCsrfToken() {
  const m = document.cookie.match(/(?:^|; )mrd_csrf=([^;]*)/);
  return m ? decodeURIComponent(m[1]) : '';
}

// fetchCsrf: wrapper para peticiones mutantes que añade X-CSRF-Token
// (complementa el patch global de base.html para mayor compatibilidad)
function fetchCsrf(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    const headers = new Headers(options.headers || {});
    if (!headers.has('X-CSRF-Token')) {
      headers.set('X-CSRF-Token', getCsrfToken());
    }
    options = { ...options, headers };
  }
  return fetch(url, options);
}

// ── Pistola QR global ─────────────────────────────────────────
// Los lectores HID escriben el código muy deprisa y terminan con Enter/Tab.
// Esta detección funciona en cualquier pantalla sin confundir escritura normal.
const GlobalScanner = (() => {
  let resetTimer = null;
  let detector = null;
  let capturedField = null;
  let capturedValue = '';
  let capturedSelection = null;

  function profile() {
    const defaults = {
      minLength: 3, maxAverageMs: 220, resetMs: 5000, fastRatio: 0.6, dedupeMs: 900,
      pacedMaxCv: 0.25, pacedMaxAverageMs: 400,
    };
    try { return { ...defaults, ...JSON.parse(localStorage.getItem('mrd_scanner_profile') || '{}') }; }
    catch (_) { return defaults; }
  }

  function normalize(value) {
    let code = String(value || '').replace(/[´’`]/g, "'").normalize('NFKC')
      .replace(/[\uFEFF\u200B\u2060]/g, '')
      .replace(/[‐‑‒–—−]/g, '-').replace(/^\][A-Za-z]\d/, '')
      .replace(/^(?:CODIGO|CÓDIGO|CODE|QR|REF)\s*[:=]\s*/i, '')
      .replace(/[\x00-\x1F\x7F]/g, '').trim();
    if (/^[A-Za-z0-9]+(?:['´’`][A-Za-z0-9]+)+$/.test(code)) {
      code = code.replace(/['´’`]/g, '-');
    }
    return code;
  }

  function clear() {
    if (detector) detector.clear();
    clearTimeout(resetTimer);
  }

  function captureField(target) {
    if (capturedField || !target?.matches?.('input:not([type="password"]), textarea')) return;
    capturedField = target;
    capturedValue = target.value;
    capturedSelection = Number.isInteger(target.selectionStart)
      ? [target.selectionStart, target.selectionEnd] : null;
  }

  function releaseField(restore) {
    if (restore && capturedField?.isConnected) {
      capturedField.value = capturedValue;
      if (capturedSelection && capturedField.setSelectionRange) {
        capturedField.setSelectionRange(capturedSelection[0], capturedSelection[1]);
      }
      capturedField.dispatchEvent(new Event('input', {bubbles: true}));
    }
    capturedField = null;
    capturedValue = '';
    capturedSelection = null;
  }

  function onKey(event) {
    if (['/scan', '/login', '/cambiar-contrasena'].includes(location.pathname) || event.ctrlKey || event.altKey || event.metaKey || event.isComposing) return;
    if (event.target?.matches?.('input[type="password"]')) { clear(); return; }
    const cfg = profile();
    const now = performance.now();
    if (!detector) detector = new MRDScannerHID.Detector({
      minLength: cfg.minLength, fastKeyMs: cfg.maxAverageMs,
      resetMs: cfg.resetMs, fastRatio: cfg.fastRatio, dedupeMs: cfg.dedupeMs,
      pacedMaxCv: cfg.pacedMaxCv, pacedMaxAverageMs: cfg.pacedMaxAverageMs,
    });
    if (event.key.length === 1 && !detector.buffer) captureField(event.target);
    // En campos de trabajo usamos su valor completo, igual que /scan. Esto
    // conserva el prefijo aunque Android trate el separador como tecla muerta.
    const completeValue = capturedField?.isConnected ? capturedField.value : undefined;
    const result = detector.feed(event.key, now, completeValue);
    if (result.terminated) {
      const code = normalize(result.code);
      const localInput = event.target?.matches?.(
        '#counter-scan,#inventory-scan-input,#line-filter,#receipt-code,#transfer-scan,#prep-scan,#purchase-code'
      );
      // Dentro de un flujo de escaneo explícito, Enter/Tab confirma siempre el
      // valor completo. Así una pistola Bluetooth con pausas funciona igual
      // que en /scan, sin depender de su velocidad de escritura.
      if ((result.scannerLike || localInput) && code) {
        event.preventDefault();
        event.stopImmediatePropagation();
        releaseField(true);
        clear();
        if (result.duplicate) return;
        try {
          const scannedUrl = new URL(code, location.origin);
          if (scannedUrl.origin === location.origin && scannedUrl.pathname.startsWith('/preparaciones-entrega/qr/')) {
            location.assign(scannedUrl.pathname);
            return;
          }
        } catch (_) { /* el código no era una URL; continúa como artículo */ }
        const scanEvent = new CustomEvent('mrd:scanner-code', {
          detail: { code, source: 'hid', fastRatio: result.fastRatio }, cancelable: true,
        });
        document.dispatchEvent(scanEvent);
        const localWorkflow = document.querySelector(
          '#counter-scan,#inventory-scan-input,#line-filter,#receipt-code,#transfer-scan,#prep-scan,#purchase-code'
        );
        if (!scanEvent.defaultPrevented && !localWorkflow) {
          location.assign('/scan?codigo=' + encodeURIComponent(code) + '&origen=pistola');
        }
        return;
      }
      releaseField(false);
      clear();
      return;
    }
    if (event.key.length !== 1) return;
    clearTimeout(resetTimer);
    resetTimer = setTimeout(() => { clear(); releaseField(false); }, cfg.resetMs);
  }

  function init() {
    document.addEventListener('keydown', onKey, true);
  }
  return { init, normalize, profile };
})();
window.MRDGlobalScanner = GlobalScanner;

// Reinicio administrativo + renovación de la caché PWA. No reinicia Windows
// ni toca la base de datos; espera a que MRD vuelva antes de recargar la vista.
async function reiniciarYCargarCambios(button, statusElement, confirmado) {
  if (!confirmado && !confirm('¿Reiniciar MRD TOOL CONTROL y cargar la última versión?\n\nLos datos no se borrarán. La aplicación estará unos segundos sin responder.')) return;
  const status = statusElement || document.getElementById('reinicio-countdown');
  if (button) { button.disabled = true; button.innerHTML = '<i class="bi bi-hourglass-split"></i> Aplicando cambios…'; }
  if (status) { status.classList.add('is-visible'); status.textContent = 'Preparando actualización segura…'; }
  try {
    if ('caches' in window) {
      const keys = await caches.keys();
      await Promise.all(keys.map(key => caches.delete(key)));
    }
    if ('serviceWorker' in navigator) {
      const registrations = await navigator.serviceWorker.getRegistrations();
      await Promise.all(registrations.map(registration => registration.update().catch(() => null)));
    }
    const response = await fetchCsrf('/admin/reiniciar', {method: 'POST', cache: 'no-store'});
    if (!response.ok) throw new Error(response.status === 403 ? 'Solo un administrador puede reiniciar el sistema.' : 'No se pudo iniciar el reinicio.');
    if (status) status.textContent = 'Reiniciando MRD…';
    await new Promise(resolve => setTimeout(resolve, 2500));
    let online = false;
    for (let attempt = 0; attempt < 35; attempt += 1) {
      try {
        const health = await fetch('/health?actualizacion=' + Date.now(), {cache: 'no-store'});
        if (health.ok) { online = true; break; }
      } catch (_) {}
      if (status) status.textContent = 'Esperando a que el sistema vuelva… ' + (attempt + 1) + ' s';
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    if (!online) throw new Error('El reinicio tarda más de lo normal. Espera unos segundos y recarga la página.');
    if ('caches' in window) {
      const keys = await caches.keys();
      await Promise.all(keys.map(key => caches.delete(key)));
    }
    if (status) status.textContent = 'Actualización cargada. Abriendo la aplicación…';
    location.replace('/?actualizado=' + Date.now());
  } catch (error) {
    if (status) status.textContent = error.message;
    if (button) { button.disabled = false; button.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Reintentar'; }
  }
}

// ── Init ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  Theme.init();
  Sidebar.init();
  initTabs();
  GlobalScanner.init();
  document.querySelectorAll('.smart-table').forEach(t => initSmartTable(t.id));
  document.querySelectorAll('[data-live-search]').forEach(el => {
    initLiveSearch(el.dataset.input, el.dataset.table);
  });

  // Barras proporcionales (ej. Top obras del dashboard): ancho calculado en
  // servidor vía data-pct, aplicado aquí para no usar CSS inline en las plantillas.
  document.querySelectorAll('[data-pct]').forEach(el => {
    el.style.width = el.dataset.pct + '%';
  });

  // Theme toggle button
  const themeBtn = document.getElementById('btn-theme');
  if (themeBtn) themeBtn.addEventListener('click', Theme.toggle);

  // Sidebar toggle button
  const sidebarBtn = document.getElementById('btn-sidebar');
  if (sidebarBtn) sidebarBtn.addEventListener('click', Sidebar.toggle);

  // Alert close auto-dismiss
  document.querySelectorAll('.alert-dismissible').forEach(a => {
    setTimeout(() => a.remove(), 5000);
  });

  // Form double-submit protection
  initFormProtection();

  // Update banner check
  checkUpdateBanner();

  // Global search dropdown
  initGlobalSearch();

  // Notificaciones push
  initPushNotifications();
});

// ── Notificaciones push (Web Push / VAPID) ────────────────────
function _urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  return Uint8Array.from([...raw].map(c => c.charCodeAt(0)));
}

async function initPushNotifications() {
  const btn = document.getElementById('btn-push');
  if (!btn || !('serviceWorker' in navigator) || !('PushManager' in window)) {
    if (btn) btn.style.display = 'none';
    return;
  }
  const icon = document.getElementById('push-icon');

  async function refrescarEstado() {
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      const activo = !!sub && Notification.permission === 'granted';
      btn.classList.toggle('active', activo);
      btn.title = activo ? 'Notificaciones push activadas (clic para desactivar)'
                          : 'Activar notificaciones push';
      if (icon) icon.className = activo ? 'bi bi-bell-fill' : 'bi bi-bell-slash';
      return sub;
    } catch (e) {
      return null;
    }
  }

  btn.addEventListener('click', async () => {
    const reg = await navigator.serviceWorker.ready;
    const subActual = await reg.pushManager.getSubscription();

    if (subActual) {
      try {
        await fetch('/api/push/desuscribirse', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ endpoint: subActual.endpoint }),
        });
        await subActual.unsubscribe();
        if (window.Toast) Toast.success('Notificaciones push desactivadas.');
      } catch (e) {
        if (window.Toast) Toast.error('No se pudieron desactivar las notificaciones.');
      }
      await refrescarEstado();
      return;
    }

    try {
      const permiso = await Notification.requestPermission();
      if (permiso !== 'granted') {
        if (window.Toast) Toast.error('Permiso de notificaciones denegado.');
        return;
      }
      const r = await fetch('/api/push/vapid-public-key');
      const { public_key } = await r.json();
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: _urlBase64ToUint8Array(public_key),
      });
      const subJson = sub.toJSON();
      await fetch('/api/push/suscribirse', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          endpoint: subJson.endpoint,
          keys: subJson.keys,
        }),
      });
      if (window.Toast) Toast.success('Notificaciones push activadas.');
    } catch (e) {
      if (window.Toast) Toast.error('No se pudo activar las notificaciones push.');
    }
    await refrescarEstado();
  });

  refrescarEstado();
}

