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
