(function (global) {
  const LB = global.LB = global.LB || {};

  function aggregate(input) {
    const parseNum = LB.util.parseNum;
    const {
      rawData,
      lastTrackedScores,
      modelToGeo,
      modelToOs,
      modelToDeactivated,
      modelToLogo,
      active,
      hiddenGeos,
      activeOsFilter,
      modeParam,
      includeSegments,
      onMissingBaseline,
      sourceData,
      snapshotMode
    } = input;

    let rows;
    if (active.question === 'ALL') {
      const gpt5 = rawData.find(d => d.model === 'gpt-5-high' || d.name === 'GPT-5 (Thinking)');
      if (!gpt5) {
        if (typeof onMissingBaseline === 'function') onMissingBaseline();
        return [];
      }
      const anchor = { lma: parseNum(gpt5.lma) || 1434, aa: parseNum(gpt5.aa) || 45, lb: parseNum(gpt5.lb) || 70.48 };
      const AXES = ['lma', 'aa', 'lb'];

      // resolve each source: live value, else last tracked score (stale), else missing
      const resolveSrc = (last, k, cur) => {
        const c = parseNum(cur);
        if (c > 0) return { value: c, state: 'live' };
        const h = last[k] && last[k].value;
        return h > 0 ? { value: h, state: 'stale' } : { value: null, state: 'missing' };
      };
      const resolved = rawData.map(d => {
        const model = String(d.model || '').trim();
        const last = (lastTrackedScores && lastTrackedScores[model]) || {};
        return { d, model, src: { lma: resolveSrc(last, 'lma', d.lma), aa: resolveSrc(last, 'aa', d.aa), lb: resolveSrc(last, 'lb', d.lb) } };
      });

      // per-axis sorted field of known values, used to estimate a missing source by percentile
      const fields = {};
      AXES.forEach(a => { fields[a] = resolved.map(r => r.src[a].value).filter(v => v != null).sort((x, y) => x - y); });
      const pctile = (a, v) => {
        const arr = fields[a], n = arr.length;
        if (n <= 1) return 1;
        let below = 0, ties = 0;
        for (const x of arr) { if (x < v) below++; else if (x === v) ties++; }
        return (below + (ties - 1) / 2) / (n - 1);
      };
      const quantile = (a, p) => {
        const arr = fields[a], n = arr.length;
        if (!n) return 0;
        if (n === 1) return arr[0];
        const pos = p * (n - 1), lo = Math.floor(pos), frac = pos - lo;
        return lo >= n - 1 ? arr[n - 1] : arr[lo] + frac * (arr[lo + 1] - arr[lo]);
      };

      rows = resolved.map(({ d, model, src }) => {
        const name = String(d.name || '').trim();
        const present = AXES.filter(a => src[a].value != null);
        const norm = { lma: 0, aa: 0, lb: 0 };
        const estimates = {};
        if (present.length) {
          // a model missing a source is placed on it at the percentile it holds on the sources it has,
          // then that percentile is mapped back to a real value from the source's own distribution
          const target = present.reduce((s, a) => s + pctile(a, src[a].value), 0) / present.length;
          AXES.forEach(a => {
            let v = src[a].value;
            if (v == null) { v = quantile(a, target); estimates[a] = v; }
            norm[a] = v / (2 * anchor[a]);
          });
        }
        const score = (norm.lma + norm.aa + norm.lb) / 3;
        const untracked = AXES.some(a => src[a].state === 'stale');
        const row = { model, name, score, untracked, deactivated: !!(modelToDeactivated && modelToDeactivated[model]) };
        if (Object.keys(estimates).length) row.estimates = estimates;
        if (includeSegments) {
          row.lmaSegment = norm.lma;
          row.aaSegment = norm.aa;
          row.lbSegment = norm.lb;
        }
        return row;
      });
    } else if (active.question === 'LMArena' || active.question === 'Artificial Analysis' || active.question === 'LiveBench') {
      const key = active.question === 'LMArena' ? 'lma' : active.question === 'Artificial Analysis' ? 'aa' : 'lb';
      if (sourceData && Array.isArray(sourceData[key]) && !snapshotMode) {
        rows = sourceData[key].map(d => ({
          model: String(d.id || '').trim(),
          name: String(d.name || '').trim(),
          score: parseNum(d.score),
          untracked: !d.tracked,
          deactivated: !!(modelToDeactivated && modelToDeactivated[String(d.id || '').trim()])
        }));
      } else {
        rows = rawData.map(d => {
          const model = String(d.model || '').trim();
          const cur = parseNum(d[key]);
          let score = cur;
          let untracked = false;
          if (cur <= 0) {
            const last = lastTrackedScores && lastTrackedScores[model] && lastTrackedScores[model][key];
            if (last && last.value > 0) {
              score = last.value;
              untracked = true;
            }
          }
          return { model, name: String(d.name || '').trim(), score, untracked, deactivated: !!(modelToDeactivated && modelToDeactivated[model]) };
        });
      }
    } else {
      rows = rawData.map(d => ({
        model: String(d.model || '').trim(),
        name: String(d.name || '').trim(),
        score: parseNum(d.lma),
        untracked: false,
        deactivated: !!(modelToDeactivated && modelToDeactivated[String(d.model || '').trim()])
      }));
    }

    let result = rows.filter(d => {
      if (d.score <= 0) return false;
      if (!input.ignoreModelFilter && global.ModelFilter && global.ModelFilter.isHidden(d.model)) return false;
      if (hiddenGeos && hiddenGeos.length > 0) {
        const geo = (modelToGeo && modelToGeo[d.model]) || 'Other';
        if (hiddenGeos.includes(geo)) return false;
      }
      if (activeOsFilter !== null && activeOsFilter !== undefined) {
        const os = (modelToOs && modelToOs[d.model] !== undefined) ? modelToOs[d.model] : 0;
        if (os !== activeOsFilter) return false;
      }
      return true;
    });

    if (modeParam === 1) {
      const bestByLogo = {};
      result.forEach(d => {
        const logo = (modelToLogo && modelToLogo[d.model]) || '';
        if (!logo) return;
        if (!bestByLogo[logo] || d.score > bestByLogo[logo].score) {
          bestByLogo[logo] = d;
        }
      });
      result = Object.values(bestByLogo);
    }

    return result;
  }

  LB.aggregate = aggregate;
  function computeFrontier(items) {
    const valid = (items || []).filter(it =>
      it && it.model && it.date instanceof Date && !isNaN(it.date.getTime()));
    const groups = {};
    valid.forEach(it => { (groups[it.group] = groups[it.group] || []).push(it); });
    const frontier = new Set();
    Object.keys(groups).forEach(key => {
      const pts = groups[key];
      pts.forEach(p => {
        const dominated = pts.some(q => q !== p && (
          (q.date < p.date && q.score >= p.score) ||
          (q.date.getTime() === p.date.getTime() && q.score > p.score)
        ));
        if (!dominated) frontier.add(p.model);
      });
    });
    return frontier;
  }

  LB.computeFrontier = computeFrontier;
})(typeof window !== 'undefined' ? window : globalThis);
