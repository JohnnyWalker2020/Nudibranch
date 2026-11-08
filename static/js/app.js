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
  if (select && paramId) { select.value = paramId; select.dispatchEvent(new Event('change', { bubbles: true })); }
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

  // Readings can be typed in other units now (the unit button), so any precision is allowed.
  valInput.step = 'any';
}

// A parameter dropdown with data-unit-for="value" drives the unit button in that value box: its units, the
// unit shown (the parameter's own), and the example in the box.
document.addEventListener('change', e => {
  const select = e.target;
  if (!select.matches || !select.matches('select[data-unit-for]') || !select.form) return;
  const box = select.form.querySelector(`input[name="${select.dataset.unitFor}"]`);
  const btn = box && box.closest('.unit-field') && box.closest('.unit-field').querySelector('button[data-units]');
  const option = select.selectedOptions[0];
  if (!btn || !option || !option.dataset.units) return;
  btn.dataset.units = option.dataset.units;
  btn.dataset.examples = option.dataset.examples || '';
  btn.disabled = !option.dataset.units.includes(',');
  setUnitButton(btn, option.dataset.units.split(',')[0]);
  btn.dispatchEvent(new Event('change', { bubbles: true }));
});
// A unit button with examples keeps its box's "e.g." in step with the unit.
document.addEventListener('change', e => {
  const btn = e.target;
  if (!btn.matches || !btn.matches('button[data-units][data-examples]')) return;
  const box = btn.closest('.unit-field') && btn.closest('.unit-field').querySelector('input:not([type="hidden"])');
  if (!box) return;
  const example = (btn.dataset.examples || '').split('|')[btn.dataset.units.split(',').indexOf(btn.value)] || '';
  box.placeholder = example ? 'e.g. ' + example : '';
});

document.addEventListener('DOMContentLoaded', () => {
  const select = document.querySelector('#quick-log-modal select[name="parameter_type"]');
  if (select) select.addEventListener('change', syncModalInputStep);
});

// Close any open modal on Escape
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  document.querySelectorAll('.fixed.inset-0.flex[id$="-modal"]').forEach(m => closeModal(m.id));
});

// ---- Unit buttons ------------------------------------------------------------
// A unit shown beside a number is itself the switch: <button data-units="gal,L" value="gal">.
// Tapping it moves to the next unit and fires "change", so code reads button.value like a select.
// data-labels gives display text when it differs from the values, and data-remember keeps the choice.
function setUnitButton(btn, value) {
  const units = btn.dataset.units.split(',');
  const labels = (btn.dataset.labels || btn.dataset.units).split(',');
  const i = Math.max(0, units.indexOf(value));
  btn.value = units[i];
  btn.textContent = labels[i];
  btn.setAttribute('aria-label', (btn.dataset.name || 'Unit') + ': ' + labels[i] + '. Tap to change.');
  if (btn.dataset.remember) {
    try { localStorage.setItem('nudi-unit-' + btn.dataset.remember, units[i]); } catch (e) { /* private mode */ }
  }
}
function unitButtonOptions(btn) {
  return btn.dataset.units.split(',');
}
document.addEventListener('click', e => {
  const btn = e.target.closest('button[data-units]');
  if (!btn) return;
  e.preventDefault();
  const units = unitButtonOptions(btn);
  setUnitButton(btn, units[(units.indexOf(btn.value) + 1) % units.length]);
  btn.dispatchEvent(new Event('change', { bubbles: true }));
});
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('button[data-units]').forEach(btn => {
    let saved = null;
    if (btn.dataset.remember) {
      try { saved = localStorage.getItem('nudi-unit-' + btn.dataset.remember); } catch (e) { /* private mode */ }
    }
    const start = btn.value;
    setUnitButton(btn, saved && unitButtonOptions(btn).includes(saved) ? saved : start);
    // A remembered unit has to reach the page's own code, which started with the default.
    if (btn.value !== start) btn.dispatchEvent(new Event('change', { bubbles: true }));
  });
});

// New equipment: head loss follows the category (the usual % for a return pump, 0 for anything else)
// until it's typed in by hand.
document.addEventListener('change', e => {
  const category = e.target;
  if (!category.matches || !category.matches('select[name$="category"]') || !category.form) return;
  const derate = category.form.querySelector('input[data-auto-derate]');
  if (!derate) return;
  derate.value = category.value === 'return_pump' ? derate.dataset.autoDerate : 0;
});
document.addEventListener('input', e => {
  if (e.target.matches && e.target.matches('input[data-auto-derate]')) delete e.target.dataset.autoDerate;
});

// Number boxes that show a unit picked by a unit button elsewhere in the form follow it.
document.addEventListener('change', e => {
  const field = e.target;
  if (!field.id || field.type !== 'hidden') return;
  document.querySelectorAll(`.unit-suffix[data-follows="${field.id}"]`).forEach(s => { s.textContent = field.value; });
});

// ---- Equipment: show only the fields that apply to the chosen category -------
function showFieldsForCategory(form) {
  const select = form.querySelector('select[name$="category"]');
  if (!select) return;
  form.querySelectorAll('[data-for-categories]').forEach(el => {
    const wrap = el.tagName === 'DIV' ? el : el.closest('[class~="space-y-1.5"]');
    if (wrap) wrap.classList.toggle('hidden', !el.dataset.forCategories.split(',').includes(select.value));
  });
}
document.addEventListener('change', e => {
  if (e.target.matches && e.target.matches('select[name$="category"]') && e.target.form) showFieldsForCategory(e.target.form);
});
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('form').forEach(f => { if (f.querySelector('[data-for-categories]')) showFieldsForCategory(f); });
});

// ---- Outlet picker: tap the pictures to place a pump outlet, sliders to aim it ----
const AIM_WORDS = ['toward the front', 'toward the front right', 'to the right', 'toward the back right',
                   'toward the back', 'toward the back left', 'to the left', 'toward the front left'];
function initOutletPicker(root) {
  const field = name => document.getElementById(root.dataset.prefix + name);
  const X = field('outlet_x'), Y = field('outlet_y'), Z = field('outlet_z'), H = field('outlet_heading'), T = field('outlet_tilt');
  if (!X || !Y || !Z || !H || !T) return;
  const top = root.querySelector('[data-view="top"]'), front = root.querySelector('[data-view="front"]');
  const headSlider = root.querySelector('[data-heading]'), tiltSlider = root.querySelector('[data-tilt]');
  const pct = (v, lo, hi) => Math.round(Math.max(0, Math.min(100, (v - lo) / (hi - lo) * 100)));
  const point = (svg, e) => { const r = svg.getBoundingClientRect(); return { x: (e.clientX - r.left) / r.width * 300, y: (e.clientY - r.top) / r.height * 120 }; };
  const fillMissing = () => {
    if (H.value === '') H.value = headSlider.value;
    if (T.value === '') T.value = 0;
  };
  top.addEventListener('pointerdown', e => {
    const p = point(top, e);
    X.value = pct(p.x, 12, 288); Y.value = pct(p.y, 18, 104);
    if (Z.value === '') Z.value = 50;
    fillMissing(); draw();
  });
  front.addEventListener('pointerdown', e => {
    const p = point(front, e);
    X.value = pct(p.x, 12, 288); Z.value = pct(p.y, 14, 102);
    if (Y.value === '') Y.value = 50;
    fillMissing(); draw();
  });
  headSlider.addEventListener('input', () => { H.value = headSlider.value; if (X.value !== '') draw(); else drawText(); });
  tiltSlider.addEventListener('input', () => { T.value = tiltSlider.value; if (X.value !== '') draw(); else drawText(); });
  root.querySelector('[data-clear]').addEventListener('click', () => {
    X.value = Y.value = Z.value = H.value = ''; T.value = 0; draw();
  });

  function drawText() {
    const h = Number(headSlider.value), t = Number(tiltSlider.value);
    root.querySelector('[data-heading-text]').textContent = Math.abs(t) >= 60 ? '(straight ' + (t > 0 ? 'up' : 'down') + ')' : AIM_WORDS[Math.floor(((h % 360) + 22.5) / 45) % 8];
    root.querySelector('[data-tilt-text]').textContent = t === 0 ? 'level' : (t > 0 ? 'up ' : 'down ') + Math.abs(t) + '°';
  }
  function place(svg, cx, cy, dx, dy) {
    const g = svg.querySelector('[data-marker]');
    g.classList.remove('hidden');
    g.setAttribute('transform', `translate(${cx} ${cy})`);
    const arrow = g.querySelector('[data-arrow]');
    arrow.setAttribute('x1', 0); arrow.setAttribute('y1', 0); arrow.setAttribute('x2', dx); arrow.setAttribute('y2', dy);
  }
  function draw() {
    headSlider.value = H.value === '' ? headSlider.value : H.value;
    tiltSlider.value = T.value === '' ? 0 : T.value;
    drawText();
    if (X.value === '' || Y.value === '') {
      root.querySelectorAll('[data-marker]').forEach(g => g.classList.add('hidden'));
      return;
    }
    const h = Number(headSlider.value) * Math.PI / 180, t = Number(tiltSlider.value) * Math.PI / 180;
    const x = 12 + Number(X.value) * 2.76;
    place(top, x, 18 + Number(Y.value) * 0.86, Math.sin(h) * Math.cos(t) * 28, Math.cos(h) * Math.cos(t) * 28);
    place(front, x, 14 + Number(Z.value === '' ? 50 : Z.value) * 0.88, Math.sin(h) * Math.cos(t) * 28, -Math.sin(t) * 28);
  }
  draw();
}
document.addEventListener('DOMContentLoaded', () => document.querySelectorAll('.outlet-picker').forEach(initOutletPicker));

// ---- Daily schedule editor: rows of time + what happens, kept as JSON in a hidden field ----
function initScheduleEditor(root) {
  const hidden = document.getElementById(root.dataset.input);
  const rows = root.querySelector('[data-rows]');
  if (!hidden || !rows) return;
  const listId = root.dataset.input + '-actions';
  const save = () => {
    const events = [...rows.querySelectorAll('[data-row]')].map(r => ({
      time: r.querySelector('input[type=time]').value,
      action: r.querySelector('input[type=text]').value.trim(),
    })).filter(e => e.time);
    hidden.value = JSON.stringify(events);
  };
  const addRow = (time = '', action = '') => {
    const row = document.createElement('div');
    row.dataset.row = '';
    row.className = 'flex items-center gap-2';
    row.innerHTML = `<input type="time" class="w-28 px-2 py-2 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm">
      <input type="text" list="${listId}" placeholder="What happens, e.g. Lights on" maxlength="60"
             class="flex-1 min-w-0 px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-white text-sm">
      <button type="button" aria-label="Remove this time" class="px-1.5 text-slate-500 hover:text-rose-400">✕</button>`;
    row.querySelector('input[type=time]').value = time;
    row.querySelector('input[type=text]').value = action;
    row.querySelector('button').addEventListener('click', () => { row.remove(); save(); });
    row.addEventListener('input', save);
    rows.appendChild(row);
    return row;
  };
  let events = [];
  try { events = JSON.parse(hidden.value || '[]'); } catch (e) { events = []; }
  events.forEach(e => addRow(e.time, e.action));
  if (!events.length) addRow();
  root.querySelector('[data-add]').addEventListener('click', () => addRow().querySelector('input').focus());
  save();
}
document.addEventListener('DOMContentLoaded', () => document.querySelectorAll('.schedule-editor').forEach(initScheduleEditor));
