(function (global) {
  'use strict';

  const STYLES = `
    .mfc-bubble {
      position: fixed;
      top: 50%;
      right: 14px;
      transform: translateY(-50%);
      width: 44px;
      height: 44px;
      border-radius: 50%;
      background: #2756d3;
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      border: 1px solid rgba(0, 0, 0, 0.08);
      opacity: 0.35;
      transition: opacity 0.25s ease, transform 0.2s ease, background 0.2s ease;
      z-index: 1000;
      font-size: 17px;
      line-height: 1;
      padding: 0;
    }
    .mfc-bubble.mfc-active { opacity: 0.7; }
    .mfc-bubble:hover { opacity: 1; transform: translateY(-50%) scale(1.06); }
    .mfc-bubble.mfc-open { opacity: 1; background: #1d3fa3; }
    .mfc-bubble:focus-visible { outline: 2px solid #1d3fa3; outline-offset: 3px; }

    .mfc-panel {
      position: fixed;
      top: 50%;
      right: 70px;
      transform: translateY(-50%) translateX(18px);
      width: 320px;
      max-width: calc(100vw - 90px);
      max-height: 72vh;
      background: #fff;
      border: 1px solid #d1d5db;
      border-radius: 10px;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.18s ease, transform 0.25s cubic-bezier(0.2, 0.7, 0.2, 1);
      z-index: 1001;
      font-family: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    .mfc-panel.mfc-open {
      opacity: 1;
      pointer-events: auto;
      transform: translateY(-50%) translateX(0);
    }

    .mfc-search {
      width: 100%; box-sizing: border-box;
      padding: 8px 12px; border: none; outline: none;
      border-bottom: 1px solid #e5e7eb; font-size: 12px;
      font-family: inherit;
    }
    .mfc-search:focus { background: #f9fafb; }

    .mfc-list { overflow-y: auto; padding: 0; flex: 1 1 auto; }
    .mfc-item {
      display: flex; align-items: center; gap: 8px;
      padding: 6px 12px; cursor: pointer; font-size: 12px;
      user-select: none; color: #1f2937;
      margin: 0;
    }
    .mfc-item:hover { background: #f3f4f6; }
    .mfc-item input { cursor: pointer; flex-shrink: 0; }
    .mfc-name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

    .mfc-toggle-all {
      display: block;
      width: 100%;
      padding: 10px 12px;
      border: none;
      border-bottom: 1px solid #e5e7eb;
      background: #f9fafb;
      font-weight: 700;
      font-size: 12px;
      color: #1f2937;
      cursor: pointer;
      text-align: center;
      font-family: inherit;
      letter-spacing: 0.02em;
    }
    .mfc-toggle-all:hover { background: #eef2f6; }
    .mfc-toggle-all:focus-visible { outline: 2px solid #2756d3; outline-offset: -2px; }

    @media (max-width: 640px) {
      .mfc-panel { right: 60px; width: calc(100vw - 76px); }
      .mfc-bubble { width: 38px; height: 38px; font-size: 15px; right: 10px; }
    }
  `;

  function escAttr(s) { return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;'); }
  function escText(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

  let opts = null;
  const hidden = new Set();
  let bubble, panel, list, search;
  let activityTimer = null;
  let mounted = false;

  function ensureStyles() {
    if (document.getElementById('mfc-styles')) return;
    const style = document.createElement('style');
    style.id = 'mfc-styles';
    style.textContent = STYLES;
    document.head.appendChild(style);
  }

  function buildDOM() {
    bubble = document.createElement('button');
    bubble.className = 'mfc-bubble';
    bubble.type = 'button';
    bubble.title = 'Filter models';
    bubble.setAttribute('aria-label', 'Filter models');
    bubble.innerHTML = '<i class="fa-solid fa-list-check" aria-hidden="true"></i>';

    panel = document.createElement('div');
    panel.className = 'mfc-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Models filter');
    panel.innerHTML = `
      <input type="text" class="mfc-search" placeholder="Search models…" autocomplete="off" />
      <div class="mfc-list"></div>
    `;
    document.body.appendChild(bubble);
    document.body.appendChild(panel);

    list = panel.querySelector('.mfc-list');
    search = panel.querySelector('.mfc-search');
  }

  function close() {
    panel.classList.remove('mfc-open');
    bubble.classList.remove('mfc-open');
    bubble.setAttribute('aria-expanded', 'false');
  }

  function open() {
    panel.classList.add('mfc-open');
    bubble.classList.add('mfc-open');
    bubble.setAttribute('aria-expanded', 'true');
    if (search) { search.value = ''; filterListByQuery(''); search.focus(); }
  }

  function attachEvents() {
    bubble.addEventListener('click', (e) => {
      e.stopPropagation();
      if (panel.classList.contains('mfc-open')) close();
      else open();
    });

    document.addEventListener('click', (e) => {
      if (!panel.classList.contains('mfc-open')) return;
      if (panel.contains(e.target) || bubble.contains(e.target)) return;
      close();
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && panel.classList.contains('mfc-open')) {
        close();
        bubble.focus();
      }
    });

    document.addEventListener('mousemove', () => {
      bubble.classList.add('mfc-active');
      if (activityTimer) clearTimeout(activityTimer);
      activityTimer = setTimeout(() => bubble.classList.remove('mfc-active'), 1800);
    }, { passive: true });

    search.addEventListener('input', () => filterListByQuery(search.value));
  }

  function currentItems() {
    return (opts && typeof opts.getModels === 'function') ? opts.getModels() : [];
  }

  function notify() {
    if (opts && typeof opts.onChange === 'function') {
      opts.onChange(new Set(hidden));
    }
  }

  function refresh() {
    if (!list || !opts) return;
    const items = currentItems()
      .map(it => ({
        model: String(it.model || '').trim(),
        name: String(it.name || '').trim() || String(it.model || '').trim(),
        color: it.color || '#2756d3'
      }))
      .filter(it => it.model);

    const knownModels = new Set(items.map(it => it.model));
    [...hidden].forEach(m => { if (!knownModels.has(m)) hidden.delete(m); });

    const allChecked = hidden.size === 0;
    const masterLabel = allChecked ? 'Clear all' : 'Select all';

    list.innerHTML = `
      <button type="button" class="mfc-toggle-all">${masterLabel}</button>
    ` + items.map(it => {
      const checked = hidden.has(it.model) ? '' : 'checked';
      return `<label class="mfc-item" data-name="${escAttr(it.name.toLowerCase())}">
        <input type="checkbox" data-model="${escAttr(it.model)}" ${checked} style="accent-color:${escAttr(it.color)}" />
        <span class="mfc-name" title="${escAttr(it.name)}">${escText(it.name)}</span>
      </label>`;
    }).join('');

    const masterBtn = list.querySelector('.mfc-toggle-all');
    if (masterBtn) {
      masterBtn.addEventListener('click', () => {
        if (hidden.size === 0) {
          items.forEach(it => hidden.add(it.model));
        } else {
          hidden.clear();
        }
        list.querySelectorAll('input[data-model]').forEach(cb => {
          cb.checked = !hidden.has(cb.getAttribute('data-model'));
        });
        updateMaster();
        notify();
      });
    }

    list.querySelectorAll('input[data-model]').forEach(cb => {
      cb.addEventListener('change', () => {
        const m = cb.getAttribute('data-model');
        if (cb.checked) hidden.delete(m);
        else hidden.add(m);
        updateMaster();
        notify();
      });
    });

    if (search && search.value) filterListByQuery(search.value);
  }

  function updateMaster() {
    if (!list) return;
    const masterBtn = list.querySelector('.mfc-toggle-all');
    if (!masterBtn) return;
    masterBtn.textContent = hidden.size === 0 ? 'Clear all' : 'Select all';
  }

  function filterListByQuery(q) {
    const needle = (q || '').trim().toLowerCase();
    list.querySelectorAll('.mfc-item').forEach(it => {
      const name = it.getAttribute('data-name') || '';
      it.style.display = (!needle || name.includes(needle)) ? 'flex' : 'none';
    });
  }

  function syncCheckboxes() {
    if (!list) return;
    list.querySelectorAll('input[data-model]').forEach(cb => {
      cb.checked = !hidden.has(cb.getAttribute('data-model'));
    });
    updateMaster();
  }

  function init(options) {
    opts = options || {};
    ensureStyles();
    if (!mounted) {
      buildDOM();
      attachEvents();
      mounted = true;
    }
    refresh();
  }

  global.ModelFilter = {
    init,
    refresh,
    isHidden(model) { return hidden.has(model); },
    getHidden() { return new Set(hidden); },
    setHidden(modelIds) {
      hidden.clear();
      (modelIds || []).forEach(m => hidden.add(m));
      syncCheckboxes();
      notify();
    },
    open, close
  };
})(window);
