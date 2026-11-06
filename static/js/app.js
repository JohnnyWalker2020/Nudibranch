// Register the PWA service worker from "/" (served by Django) so it controls the whole site.
// The original registered /static/sw.js, which could only control /static/.
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' })
      .catch(err => console.warn('Service worker registration failed:', err));
  });
}

// ---- Timer sound -------------------------------------------------------------
let nudiAudio = null;
function nudiBeep() {
  try {
    nudiAudio = nudiAudio || new (window.AudioContext || window.webkitAudioContext)();
    [0, 0.35, 0.7].forEach(offset => {
      const osc = nudiAudio.createOscillator(), gain = nudiAudio.createGain();
      osc.frequency.value = 880;
      osc.connect(gain); gain.connect(nudiAudio.destination);
      gain.gain.value = 0.2;
      osc.start(nudiAudio.currentTime + offset);
      osc.stop(nudiAudio.currentTime + offset + 0.2);
    });
  } catch (e) { /* sound isn't available */ }
}

// ---- Generic modal helpers --------------------------------------------------
// Modals are `hidden` by default; opening swaps `hidden` for `flex` so they centre.
function openModal(id) {
  const m = document.getElementById(id);
  if (!m) return;
  m.classList.remove('hidden');
  m.classList.add('flex');
  document.body.classList.add('overflow-hidden');
}

function closeModal(id) {
  const m = document.getElementById(id);
  if (!m) return;
  m.classList.add('hidden');
  m.classList.remove('flex');
  if (!document.querySelector('.fixed.inset-0.flex[id$="-modal"]')) {
    document.body.classList.remove('overflow-hidden');
  }
}

// ---- Parameter metadata (decimal places per parameter) ---------------------
window.nudibranchParamTypes = [];

async function initParameterMetadata() {
  try {
    const res = await fetch('/api/parameters/types/');
    if (res.ok) {
      const data = await res.json();
      window.nudibranchParamTypes = data.parameters || [];
      syncModalInputStep();
    }
  } catch (err) {
    console.warn('Could not prefetch parameter metadata:', err);
  }
}

// ---- Quick log modal ---------------------------------------------------------
function openQuickLogModal(paramId = null) {
  const modal = document.getElementById('quick-log-modal');
  if (!modal) return;
  openModal('quick-log-modal');

  const select = modal.querySelector('select[name="parameter_type"]');
  if (select && paramId) select.value = paramId;
  if (window.nudibranchParamTypes.length) syncModalInputStep();
  else initParameterMetadata();  // only needed once someone actually opens this

  setTimeout(() => {
    const valInput = modal.querySelector('input[name="value"]');
    if (valInput) valInput.focus();
  }, 100);
}

function closeQuickLogModal() {
  closeModal('quick-log-modal');
}

function syncModalInputStep() {
  const modal = document.getElementById('quick-log-modal');
  if (!modal) return;
  const select = modal.querySelector('select[name="parameter_type"]');
  const valInput = modal.querySelector('input[name="value"]');
  if (!select || !valInput) return;

  const pt = (window.nudibranchParamTypes || []).find(p => String(p.id) === String(select.value));
  if (!pt) return;
  const d = Number(pt.decimal_places);
  valInput.step = d <= 0 ? '1' : '0.' + '0'.repeat(d - 1) + '1';
}

document.addEventListener('DOMContentLoaded', () => {
  const select = document.querySelector('#quick-log-modal select[name="parameter_type"]');
  if (select) select.addEventListener('change', syncModalInputStep);
});

// Close any open modal on Escape
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  document.querySelectorAll('.fixed.inset-0.flex[id$="-modal"]').forEach(m => closeModal(m.id));
});
