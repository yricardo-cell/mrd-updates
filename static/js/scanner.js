/**
 * MRD TOOL CONTROL — scanner.js
 * Captura de pistola lectora USB/Bluetooth (emula teclado)
 * Detecta secuencias rápidas y consulta la API
 */
(function() {
  'use strict';

  const SCAN_TIMEOUT = 80;   // ms entre teclas para considerar escáner
  const MIN_CODE_LENGTH = 4;

  let buffer = '';
  let lastKeyTime = 0;
  let timer = null;

  function procesarCodigo(codigo) {
    codigo = codigo.trim();
    if (codigo.length < MIN_CODE_LENGTH) return;

    fetch(`/api/herramientas/codigo/${encodeURIComponent(codigo)}`)
      .then(r => {
        if (!r.ok) throw new Error('No encontrada');
        return r.json();
      })
      .then(herramienta => {
        mostrarFlash(herramienta);
        // Si el modal de escáner está abierto, actualizar
        const scanCode = document.getElementById('scanCode');
        const scanResult = document.getElementById('scanResult');
        if (scanCode && scanResult) {
          scanCode.textContent = codigo;
          scanResult.classList.remove('d-none');
        }
        // Navegar a la herramienta
        setTimeout(() => {
          window.location.href = herramienta.url;
        }, 800);
      })
      .catch(() => {
        mostrarFlashError(codigo);
      });
  }

  function mostrarFlash(herramienta) {
    if (typeof mostrarToast === 'function') {
      mostrarToast(`🔍 ${herramienta.nombre} — ${herramienta.estado}`, 'info', 2000);
    }
  }

  function mostrarFlashError(codigo) {
    if (typeof mostrarToast === 'function') {
      mostrarToast(`Código no encontrado: ${codigo}`, 'error', 2000);
    }
  }

  function onKeyDown(e) {
    const now = Date.now();
    const target = e.target;

    // Ignorar si el foco está en un input/textarea normal
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') {
      return;
    }

    const elapsed = now - lastKeyTime;
    lastKeyTime = now;

    if (e.key === 'Enter') {
      clearTimeout(timer);
      if (buffer.length >= MIN_CODE_LENGTH) {
        procesarCodigo(buffer);
      }
      buffer = '';
      return;
    }

    // Carácter imprimible de un solo caracter
    if (e.key.length === 1) {
      if (elapsed > 500) {
        buffer = '';
      }
      buffer += e.key;
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (buffer.length >= MIN_CODE_LENGTH && elapsed < SCAN_TIMEOUT * 3) {
          procesarCodigo(buffer);
        }
        buffer = '';
      }, SCAN_TIMEOUT * 5);
    }
  }

  document.addEventListener('keydown', onKeyDown);
})();
