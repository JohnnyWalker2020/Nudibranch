// Arrange: move a page's cards up and down, saved for the whole app.
//
// A page marks its list of cards with data-arrange="<page>" and each card with data-card="<key>"
// and data-card-title. partials/arrange_apply.html puts the saved order in place as the page loads;
// this file runs the Arrange button (partials/arrange_button.html).
(function () {
  function csrf() {
    try { return JSON.parse(document.body.getAttribute('hx-headers'))['X-CSRFToken']; } catch (e) { return ''; }
  }
  function cards(box) {
    return Array.from(box.children).filter(el => el.hasAttribute('data-card'));
  }
  function save(box, order) {
    const body = new URLSearchParams({ page: box.dataset.arrange, order: JSON.stringify(order) });
    return fetch('/tools/settings/card-order/', { method: 'POST', body, headers: { 'X-CSRFToken': csrf() } })
      .then(res => { if (!res.ok) throw new Error('save failed'); });
  }
  function refreshArrows(box) {
    const list = cards(box);
    list.forEach((card, i) => {
      const bar = card.querySelector(':scope > .arrange-bar');
      if (!bar) return;
      bar.querySelector('[data-move="-1"]').disabled = i === 0;
      bar.querySelector('[data-move="1"]').disabled = i === list.length - 1;
    });
  }
  function start(box, toggle) {
    box.classList.add('arranging');
    cards(box).forEach(card => {
      const bar = document.createElement('div');
      bar.className = 'arrange-bar';
      const title = document.createElement('span');
      title.textContent = card.dataset.cardTitle || card.dataset.card;
      const arrows = document.createElement('span');
      arrows.className = 'flex gap-1';
      arrows.innerHTML = '<button type="button" data-move="-1" aria-label="Move up">▲</button>'
                       + '<button type="button" data-move="1" aria-label="Move down">▼</button>';
      bar.append(title, arrows);
      card.prepend(bar);
    });
    const panel = document.createElement('div');
    panel.className = 'arrange-panel sticky top-20 z-30 flex flex-wrap items-center justify-between gap-2 p-3 rounded-2xl bg-slate-950/95 backdrop-blur border border-cyan-500/40 shadow-xl';
    panel.innerHTML = '<p class="text-xs text-slate-300">Move the cards with ▲ ▼. Their contents are tucked away until you\'re done.</p>'
      + '<span class="flex gap-2"><button type="button" data-arrange-reset class="px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-400 hover:text-white">Back to normal</button>'
      + '<button type="button" data-arrange-done class="px-4 py-1.5 rounded-lg text-xs font-bold bg-cyan-500 text-slate-950 hover:bg-cyan-400">Done</button></span>';
    box.prepend(panel);
    refreshArrows(box);
    toggle.disabled = true;
    panel.querySelector('[data-arrange-done]').focus();
  }
  function stop(box, toggle) {
    box.classList.remove('arranging');
    box.querySelectorAll(':scope > [data-card] > .arrange-bar, :scope > .arrange-panel').forEach(el => el.remove());
    toggle.disabled = false;
  }

  document.addEventListener('click', e => {
    const toggle = e.target.closest('[data-arrange-toggle]');
    if (toggle) {
      const box = document.querySelector(`[data-arrange="${toggle.dataset.arrangeToggle}"]`);
      if (box && !box.classList.contains('arranging')) start(box, toggle);
      return;
    }
    const box = e.target.closest('[data-arrange].arranging');
    if (!box) return;
    const pageToggle = document.querySelector(`[data-arrange-toggle="${box.dataset.arrange}"]`);
    const move = e.target.closest('[data-move]');
    if (move) {
      const card = move.closest('[data-card]');
      const list = cards(box);
      const i = list.indexOf(card);
      const j = i + Number(move.dataset.move);
      if (j < 0 || j >= list.length) return;
      if (Number(move.dataset.move) < 0) box.insertBefore(card, list[j]);
      else box.insertBefore(card, list[j].nextSibling);
      refreshArrows(box);
      move.focus();
      return;
    }
    if (e.target.closest('[data-arrange-done]')) {
      const order = cards(box).map(c => c.dataset.card);
      save(box, order).then(() => stop(box, pageToggle)).catch(() => alert("Couldn't save the new order. Try again."));
      return;
    }
    if (e.target.closest('[data-arrange-reset]')) {
      save(box, []).then(() => window.location.reload()).catch(() => alert("Couldn't reset the order. Try again."));
    }
  });
})();

// Folding: a card with a [data-card-mini] line folds down to just that line, and its fold button
// ([data-card-fold]) or the line itself opens and closes it. Which cards are folded is kept in this
// browser only, per page; partials/arrange_apply.html folds them again as the page loads.
(function () {
  function key(box) { return 'nudi-folded:' + box.dataset.arrange; }
  function foldable(box) {
    return Array.from(box.children).filter(el => el.hasAttribute('data-card') && el.querySelector(':scope > [data-card-mini]'));
  }
  function remember(box) {
    const folded = foldable(box).filter(c => c.classList.contains('card-folded')).map(c => c.dataset.card);
    try { localStorage.setItem(key(box), JSON.stringify(folded)); } catch (e) { /* folds just won't be remembered */ }
    refreshAll(box);
  }
  function setFolded(card, folded) {
    card.classList.toggle('card-folded', folded);
    const fold = card.querySelector('[data-card-fold]');
    if (fold) fold.setAttribute('aria-expanded', folded ? 'false' : 'true');
  }
  function refreshAll(box) {
    const button = document.querySelector(`[data-fold-all="${box.dataset.arrange}"]`);
    if (!button) return;
    const all = foldable(box);
    const allFolded = all.length && all.every(c => c.classList.contains('card-folded'));
    button.querySelector('[data-fold-all-label]').textContent = allFolded ? 'Unfold all' : 'Fold all';
    button.hidden = !all.length;
  }

  document.addEventListener('click', e => {
    const all = e.target.closest('[data-fold-all]');
    if (all) {
      const box = document.querySelector(`[data-arrange="${all.dataset.foldAll}"]`);
      if (!box) return;
      const cards = foldable(box);
      const fold = !cards.every(c => c.classList.contains('card-folded'));
      cards.forEach(c => setFolded(c, fold));
      remember(box);
      return;
    }
    const toggle = e.target.closest('[data-card-fold], [data-card-mini]');
    if (!toggle) return;
    const card = toggle.closest('[data-card]');
    const box = card && card.parentElement;
    if (!box || !box.hasAttribute('data-arrange') || box.classList.contains('arranging')) return;
    const folding = toggle.hasAttribute('data-card-fold');
    setFolded(card, folding);
    remember(box);
    // Keep the card where the reader is looking
    if (!folding) card.scrollIntoView({ block: 'nearest' });
    else (card.querySelector('[data-card-mini]') || card).focus({ preventScroll: true });
  });
  document.querySelectorAll('[data-arrange]').forEach(refreshAll);
})();
