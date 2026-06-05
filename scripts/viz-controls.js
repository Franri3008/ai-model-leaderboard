(function (global) {
  const LB = global.LB = global.LB || {};

  const SOURCE_PARAM_MAP = {
    aiw: 'ALL',
    llma: 'LMArena',
    aa: 'Artificial Analysis',
    lb: 'LiveBench'
  };
  const CHECK_HTML = '<svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg>';
  const DEFAULT_GEOS = [
    { value: 'US', label: 'US' },
    { value: 'China', label: 'China' },
    { value: 'France', label: 'France' }
  ];
  const DEFAULT_GEO_COLORS = { US: '#ec787a', China: '#fadb56', France: '#5c5a74' };
  const OS_COLORS = { open: '#188ab2', proprietary: '#ef476f' };

  function queryParams() {
    return new URLSearchParams(global.location ? global.location.search : '');
  }

  function readIntParam(params, name, fallback, allowedValues) {
    const raw = params.get(name);
    if (raw == null || raw === '') return fallback;
    const value = parseInt(raw, 10);
    if (isNaN(value)) return fallback;
    if (Array.isArray(allowedValues) && !allowedValues.includes(value)) return fallback;
    return value;
  }

  function readPositiveIntParam(params, name, fallback) {
    const value = readIntParam(params, name, null);
    return value && value > 0 ? value : fallback;
  }

  function readSourceParam(params, fallback) {
    const sourceParam = params.get('source');
    if (!sourceParam) return fallback;
    return SOURCE_PARAM_MAP[String(sourceParam).toLowerCase()] || fallback;
  }

  function readColorParam(params, fallback) {
    const colorParam = params.get('color');
    if (colorParam === 'white') return '#ffffff';
    if (colorParam === 'gray' || colorParam === 'grey') return '#f9fafc';
    return fallback;
  }

  function readWeeksParam(params, fallback) {
    const explicitWeeks = readPositiveIntParam(params, 'weeks', null);
    if (explicitWeeks) return explicitWeeks;

    const periodParam = params.get('period');
    if (periodParam === 'month') return 4;
    if (periodParam === 'day' || periodParam === 'week') return 1;
    return fallback;
  }

  function readQuery(options = {}) {
    const params = queryParams();
    return {
      params,
      snapshot: params.get('snapshot'),
      palette: readIntParam(params, 'palette', options.paletteDefault, options.paletteValues),
      source: readSourceParam(params, options.sourceDefault),
      top: readPositiveIntParam(params, 'top', options.topDefault),
      style: readIntParam(params, 'style', options.styleDefault, options.styleValues),
      highlight: params.get('highlight') || null,
      color: readColorParam(params, options.colorDefault),
      bop: params.get('bop') === '1' ? 1 : (options.bopDefault || 0),
      logo: params.get('logo') === '1',
      display: params.get('display') === '1' ? 1 : (options.displayDefault || 0),
      weeks: readWeeksParam(params, options.weeksDefault)
    };
  }

  function applyPageChrome(options = {}) {
    const bgColor = options.bgColor;
    if (bgColor) {
      document.body.style.background = bgColor;
      const footnote = document.getElementById(options.footnoteId || 'footnote-container');
      if (footnote) footnote.style.background = bgColor;
    }

    const grid = document.querySelector(options.gridSelector || '.viz-grid');
    if (grid && options.logo) grid.classList.add('with-logo');
    if (grid && options.displayMode !== undefined) {
      grid.classList.add(options.displayMode === 1 ? 'display-mode-1' : 'display-mode-0');
    }
  }

  function syncUrlFlag(name, enabled) {
    const url = new URL(global.location.href);
    if (enabled) url.searchParams.set(name, '1');
    else url.searchParams.delete(name);
    global.history.replaceState(null, '', url.toString());
  }

  function updateTabIndicator(activeTab, indicatorSelector) {
    const indicator = document.querySelector(indicatorSelector || '.tab-indicator');
    if (!activeTab || !indicator) return;
    const container = activeTab.closest('.tabs-container');
    if (!container) return;
    const containerRect = container.getBoundingClientRect();
    const tabRect = activeTab.getBoundingClientRect();
    indicator.style.left = (tabRect.left - containerRect.left) + 'px';
    indicator.style.width = tabRect.width + 'px';
    indicator.classList.add('active');
  }

  function setActiveTab(value, options = {}) {
    const selector = options.tabSelector || '.tab';
    const attr = options.attr || 'data-question';
    const tabs = Array.from(document.querySelectorAll(selector));
    if (!tabs.length) return null;

    let activeTab = null;
    tabs.forEach(tab => {
      const isActive = tab.getAttribute(attr) === value;
      tab.classList.toggle('active', isActive);
      if (isActive) activeTab = tab;
    });

    if (!activeTab) activeTab = document.querySelector(selector + '.active');
    updateTabIndicator(activeTab, options.indicatorSelector);
    return activeTab;
  }

  function setupTabs(options = {}) {
    const selector = options.tabSelector || '.tab';
    const attr = options.attr || 'data-question';
    const tabs = Array.from(document.querySelectorAll(selector));

    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        const value = tab.getAttribute(attr);
        setActiveTab(value, options);
        if (typeof options.onChange === 'function') options.onChange(value, tab);
      });
    });

    const activeTab = document.querySelector(selector + '.active');
    const activeValue = options.value !== undefined
      ? options.value
      : (activeTab ? activeTab.getAttribute(attr) : null);
    setActiveTab(activeValue, options);

    window.addEventListener('resize', () => {
      const currentActive = document.querySelector(selector + '.active');
      updateTabIndicator(currentActive, options.indicatorSelector);
    });
  }

  function setupValueButtons(options = {}) {
    const selector = options.selector;
    if (!selector) return;
    const attr = options.attr || 'data-value';
    const buttons = Array.from(document.querySelectorAll(selector));
    let currentValue = options.value;

    function setActive(value) {
      currentValue = value;
      buttons.forEach(btn => {
        btn.classList.toggle(options.activeClass || 'active', parseInt(btn.getAttribute(attr), 10) === value);
      });
    }

    setActive(currentValue);
    buttons.forEach(btn => {
      btn.addEventListener('click', () => {
        const value = parseInt(btn.getAttribute(attr), 10);
        if (currentValue === value) return;
        setActive(value);
        if (typeof options.onChange === 'function') options.onChange(value, btn);
      });
    });
  }

  function filterLegendHtml(extraHtml) {
    return `
      <div class="legend-wrapper-inner" style="display: flex; gap: clamp(16px, 4vw, 48px); justify-content: center; align-items: flex-start; flex-wrap: wrap;">
        <div style="display: flex; flex-direction: column; align-items: center; gap: 4px;">
          <div style="font-size: clamp(10px, 1.2vw, 12px); font-weight: 600; color: #666;">Licensing</div>
          <div class="legend" style="margin: 0; padding: 0;">
            <div class="legend-item" tabindex="0" data-os="1"><div class="legend-square"></div><span>Open Source</span></div>
            <div class="legend-item" tabindex="0" data-os="0"><div class="legend-square"></div><span>Proprietary</span></div>
          </div>
        </div>
        <div style="display: flex; flex-direction: column; align-items: center; gap: 4px;">
          <div style="font-size: clamp(10px, 1.2vw, 12px); font-weight: 600; color: #666;">Country</div>
          <div class="legend" style="margin: 0; padding: 0;">
            ${DEFAULT_GEOS.map(geo => `<div class="legend-item" tabindex="0" data-geo="${geo.value}"><div class="legend-square"></div><span>${geo.label}</span></div>`).join('')}
          </div>
        </div>
      </div>
      ${extraHtml || ''}
    `;
  }

  function nextOsFilter(activeOsFilter, osVal) {
    if (activeOsFilter === null || activeOsFilter === undefined) return osVal === 1 ? 0 : 1;
    if (activeOsFilter === osVal) return activeOsFilter;
    return null;
  }

  function nextHiddenGeos(hiddenGeos, geoVal, maxHidden) {
    const current = Array.isArray(hiddenGeos) ? hiddenGeos.slice() : [];
    if (current.includes(geoVal)) return current.filter(geo => geo !== geoVal);
    if (current.length >= (maxHidden == null ? 2 : maxHidden)) return current;
    current.push(geoVal);
    return current;
  }

  function bindFilterLegend(container) {
    if (container.__lbFilterLegendBound) return;
    container.__lbFilterLegendBound = true;

    container.querySelectorAll('.legend-item[data-os]').forEach(item => {
      item.addEventListener('click', () => {
        const opts = container.__lbFilterLegendOptions || {};
        const osVal = parseInt(item.getAttribute('data-os'), 10);
        const activeOsFilter = nextOsFilter(opts.activeOsFilter, osVal);
        if (activeOsFilter === opts.activeOsFilter) return;
        if (typeof opts.onChange === 'function') {
          opts.onChange({ activeOsFilter, hiddenGeos: (opts.hiddenGeos || []).slice() });
        }
      });
    });

    container.querySelectorAll('.legend-item[data-geo]').forEach(item => {
      item.addEventListener('click', () => {
        const opts = container.__lbFilterLegendOptions || {};
        const geoVal = item.getAttribute('data-geo');
        const hiddenGeos = nextHiddenGeos(opts.hiddenGeos, geoVal, opts.maxHiddenGeos);
        if (hiddenGeos.length === (opts.hiddenGeos || []).length
          && hiddenGeos.every((geo, index) => geo === (opts.hiddenGeos || [])[index])) return;
        if (typeof opts.onChange === 'function') {
          opts.onChange({ activeOsFilter: opts.activeOsFilter, hiddenGeos });
        }
      });
    });

    container.querySelectorAll('.legend-item[data-os], .legend-item[data-geo]').forEach(item => {
      item.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          item.click();
        }
      });
    });
  }

  function renderFilterLegend(options = {}) {
    const container = typeof options.container === 'string'
      ? document.querySelector(options.container)
      : options.container;
    if (!container) return;

    container.__lbFilterLegendOptions = options;
    if (options.center !== false) {
      container.style.display = 'flex';
      container.style.justifyContent = 'center';
    }

    if (!container.querySelector('.legend-wrapper-inner')) {
      container.innerHTML = filterLegendHtml(options.extraHtml);
    }
    bindFilterLegend(container);

    const activeOsFilter = options.activeOsFilter;
    const hiddenGeos = Array.isArray(options.hiddenGeos) ? options.hiddenGeos : [];
    const paletteMode = options.paletteMode;
    const geoColors = options.geoColors || DEFAULT_GEO_COLORS;
    const matchOsBorder = !!options.matchOsBorder;

    [
      { value: 1, bg: paletteMode === 1 ? OS_COLORS.open : '#ffffff', dimWhen: 0 },
      { value: 0, bg: paletteMode === 1 ? OS_COLORS.proprietary : '#ffffff', dimWhen: 1 }
    ].forEach(os => {
      const item = container.querySelector(`.legend-item[data-os="${os.value}"]`);
      if (!item) return;
      const square = item.querySelector('.legend-square');
      if (!square) return;
      square.style.background = os.bg;
      square.style.borderColor = matchOsBorder && paletteMode === 1 ? os.bg : '#111';
      square.setAttribute('data-palette', paletteMode === 1 ? 1 : 0);
      square.innerHTML = (activeOsFilter === null || activeOsFilter === undefined || activeOsFilter === os.value) ? CHECK_HTML : '';
      item.classList.toggle('dim', activeOsFilter === os.dimWhen);
    });

    DEFAULT_GEOS.forEach(geo => {
      const item = container.querySelector(`.legend-item[data-geo="${geo.value}"]`);
      if (!item) return;
      const square = item.querySelector('.legend-square');
      if (!square) return;
      const isHidden = hiddenGeos.includes(geo.value);
      const bg = paletteMode === 2 ? geoColors[geo.value] : '#ffffff';
      square.style.background = bg;
      square.style.borderColor = paletteMode === 2 ? bg : '#111';
      square.setAttribute('data-palette', paletteMode === 2 ? 2 : 0);
      square.innerHTML = !isHidden ? CHECK_HTML : '';
      item.classList.toggle('dim', isHidden);
    });
  }

  LB.vizControls = {
    readQuery,
    applyPageChrome,
    syncUrlFlag,
    setActiveTab,
    setupTabs,
    setupValueButtons,
    renderFilterLegend
  };
})(typeof window !== 'undefined' ? window : globalThis);
