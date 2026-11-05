// Register PWA Service Worker
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/static/sw.js')
      .then(reg => console.log('Nudibranch PWA Service Worker Registered', reg.scope))
      .catch(err => console.log('Service Worker registration failed: ', err));
  });
}

// Global cache of parameter metadata (unit, decimals, ideal range)
window.nudibranchParamTypes = [];

async function initParameterMetadata() {
  try {
    const res = await fetch('/api/parameters/types/');
    if (res.ok) {
      const data = await res.json();
      window.nudibranchParamTypes = data.parameters || [];
    }
  } catch (err) {
    console.warn('Could not prefetch parameter metadata:', err);
  }
}
document.addEventListener('DOMContentLoaded', initParameterMetadata);

// Modal Toggle Helpers
function openQuickLogModal(paramId = null) {
  const modal = document.getElementById('quick-log-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  
  const select = modal.querySelector('select[name="parameter_type"]');
  if (select && paramId) {
    select.value = paramId;
  }
  
  syncModalInputStep();

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

function syncModalInputStep() {
  const modal = document.getElementById('quick-log-modal');
  if (!modal) return;
  const select = modal.querySelector('select[name="parameter_type"]');
  const valInput = modal.querySelector('input[name="value"]');
  if (!select || !valInput || !window.nudibranchParamTypes) return;

  const currentId = select.value;
  const pt = window.nudibranchParamTypes.find(p => p.id == currentId);
  if (pt) {
    if (pt.decimal_places === 0) {
      valInput.step = "1";
      valInput.placeholder = "420";
    } else if (pt.decimal_places === 1) {
      valInput.step = "0.1";
      valInput.placeholder = "8.4";
    } else if (pt.decimal_places === 2) {
      valInput.step = "0.01";
      valInput.placeholder = "0.03";
    } else if (pt.decimal_places >= 3) {
      valInput.step = "0.001";
      valInput.placeholder = "1.026";
    }
  }
}

// Hook select change in modal
document.addEventListener('DOMContentLoaded', () => {
  const select = document.querySelector('#quick-log-modal select[name="parameter_type"]');
  if (select) {
    select.addEventListener('change', syncModalInputStep);
  }
});

// Close modal on Escape key
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeQuickLogModal();
});
