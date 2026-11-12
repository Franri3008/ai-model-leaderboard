(function (global) {
  const LB = global.LB = global.LB || {};
  const UNMAPPED_KEY = '_unmapped';
  const TOP_LABS = 15;

  function selectRows(input) {
    const { aggregated, modelToLogo, rawData, geography } = input;
    const limit = input.limit || TOP_LABS;
    const warn = input.warn || (msg => global.console && global.console.warn(msg));
    const cities = (geography && geography.cities) || {};
    const labs = (geography && geography.labs) || {};
    const unmapped = (geography && geography.unmapped) || { name: 'Unmapped', country: 'Unmapped', color: '#9ca3af' };
    const nameOf = {};
    (rawData || []).forEach(d => {
      const model = String(d.model || '').trim();
      if (model) nameOf[model] = String(d.displayName || d.name || '').trim();
    });

    const best = {};
    (aggregated || []).forEach(d => {
      if (!(d.score > 0) || d.deactivated) return;
      const lab = String((modelToLogo && modelToLogo[d.model]) || '').trim() || d.model;
      if (!best[lab] || d.score > best[lab].score) best[lab] = d;
    });

    return Object.keys(best)
      .map(lab => ({ lab, d: best[lab] }))
      .sort((a, b) => b.d.score - a.d.score || a.lab.localeCompare(b.lab))
      .slice(0, limit)
      .map(({ lab, d }) => {
        const place = labs[lab];
        const city = place && cities[place.city];
        if (!city) warn(`geography: lab "${lab}" has no entry in config/lab-geography.json, shown as Unmapped`);
        return {
          model: nameOf[d.model] || d.name || d.model,
          id: d.model,
          lab,
          dev: place && place.label ? place.label : lab,
          city: city ? place.city : UNMAPPED_KEY,
          cityName: city ? city.name : unmapped.name,
          country: city ? (place.country || city.country) : unmapped.country,
          color: city ? city.color : unmapped.color,
          score: d.score
        };
      });
  }

  function labLimit(top) {
    const n = parseInt(top, 10);
    return n > 0 ? Math.min(n, TOP_LABS) : TOP_LABS;
  }

  function scoreAxis(scores, question) {
    const min = Math.min.apply(null, scores), max = Math.max.apply(null, scores);
    if (!question || question === 'ALL') {
      const lo = Math.floor((min - 0.02) * 20) / 20;
      const hi = Math.ceil((max + 0.01) * 20) / 20;
      const ticks = [];
      const n = Math.max(0, Math.ceil((hi + 0.001 - (lo + 0.05)) / 0.05));
      for (let i = 0; i < n; i++) ticks.push(lo + 0.05 + i * 0.05);
      return { lo, hi, ticks, valueDigits: 3, tickDigits: 2 };
    }
    const span = Math.max(max - min, Math.abs(max) * 0.02, 1e-6);
    const raw = span * 1.4 / 5;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map(k => k * mag).find(v => v >= raw);
    const lo = Math.floor((min - span * 0.25) / step) * step;
    const hi = Math.ceil((max + span * 0.05) / step) * step;
    const ticks = [];
    for (let i = 1; lo + i * step <= hi + step * 1e-3; i++) ticks.push(lo + i * step);
    const digits = question === 'LiveBench' ? 1 : 0;
    const tickDigits = Math.max(0, -Math.floor(Math.log10(step) + 1e-9));
    return { lo, hi, ticks, valueDigits: digits, tickDigits: Math.max(digits, tickDigits) };
  }

  function cityOrder(geography) {
    return Object.keys((geography && geography.cities) || {}).concat(UNMAPPED_KEY);
  }

  LB.geography = { selectRows, cityOrder, labLimit, scoreAxis, UNMAPPED_KEY, TOP_LABS };
})(typeof window !== 'undefined' ? window : globalThis);
