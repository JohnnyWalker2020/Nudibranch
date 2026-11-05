// Register PWA Service Worker
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/static/sw.js')
      .then(reg => console.log('Nudibranch PWA Service Worker Registered', reg.scope))
      .catch(err => console.log('Service Worker registration failed: ', err));
  });
}

// Modal Toggle Helpers
function openQuickLogModal(paramId = null) {
  const modal = document.getElementById('quick-log-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  
  if (paramId) {
    const select = modal.querySelector('select[name="parameter_type"]');
    if (select) select.value = paramId;
  }
  
  // Focus value input for immediate mobile entry
  setTimeout(() => {
    const valInput = modal.querySelector('input[name="value"]');
    if (valInput) valInput.focus();
  }, 100);
}

function closeQuickLogModal() {
  const modal = document.getElementById('quick-log-modal');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

// Close modal on Escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeQuickLogModal();
});
