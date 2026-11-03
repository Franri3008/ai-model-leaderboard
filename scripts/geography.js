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

  function cityOrder(geography) {
    return Object.keys((geography && geography.cities) || {}).concat(UNMAPPED_KEY);
  }

  LB.geography = { selectRows, cityOrder, UNMAPPED_KEY, TOP_LABS };
})(typeof window !== 'undefined' ? window : globalThis);
