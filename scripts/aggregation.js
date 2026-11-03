(function (global) {
  const LB = global.LB = global.LB || {};
  const ALL_REFERENCE = { model: 'gpt-6-1-sol', name: 'GPT 6.1 Sol', target: 0.70 };
  const ALL_LEGACY_REFERENCE = { model: 'gpt-5-high', name: 'GPT-5', target: 0.50, fallback: { lma: 1434, aa: 45, lb: 70.48 } };

  function pickReference(rawData) {
    const find = id => (rawData || []).find(d => String(d.model || '').trim() === id);
    const current = find(ALL_REFERENCE.model);
    if (current) return { spec: ALL_REFERENCE, row: current };
    const legacy = find(ALL_LEGACY_REFERENCE.model);
    return legacy ? { spec: ALL_LEGACY_REFERENCE, row: legacy } : null;
  }

  function sortedValues(values) {
    return values.filter(v => v != null).sort((x, y) => x - y);
  }

  function percentileIn(arr, v) {
    const n = arr.length;
    if (n <= 1) return 1;
    let below = 0, ties = 0;
    for (const x of arr) { if (x < v) below++; else if (x === v) ties++; }
    return (below + (ties - 1) / 2) / (n - 1);
  }

  function quantileIn(arr, p) {
    const n = arr.length;
    if (!n) return 0;
    if (n === 1) return arr[0];
    const pos = p * (n - 1), lo = Math.floor(pos), frac = pos - lo;
    return lo >= n - 1 ? arr[n - 1] : arr[lo] + frac * (arr[lo + 1] - arr[lo]);
  }

  function allAnchors(resolved, refResolved, spec) {
    const idx = LB.aaIndex || {};
    const isV5 = idx.isV5 || (() => false);
    const showV5 = !!idx.v5Start;
    const AXES = ['lma', 'aa', 'lb'];
    const ratio = idx.v5Ratio > 0 ? idx.v5Ratio : 1;
    const onCurrentScale = (a, s) => s.value != null && (a !== 'aa' || !showV5 || isV5(s.version));
    const toCurrent = (a, s) => s.value == null ? null : onCurrentScale(a, s) ? s.value : s.value * ratio;
    const pinned = !spec.fallback;
    const valueOf = (r, a) => pinned && r === refResolved && !onCurrentScale(a, r.src[a]) ? null : toCurrent(a, r.src[a]);
    const fields = {};
    AXES.forEach(a => { fields[a] = sortedValues(resolved.map(r => valueOf(r, a))); });
    if (!pinned) {
      const anchor = {};
      const source = {};
      AXES.forEach(a => {
        const own = refResolved.src[a];
        if (own.state === 'live') { anchor[a] = toCurrent(a, own); source[a] = 'reference'; }
        else { anchor[a] = spec.fallback[a]; source[a] = 'fallback'; }
      });
      return { spec, pinned, anchor, source, target: null, ratio, fields, valueOf };
    }
    const refAxes = AXES.filter(a => valueOf(refResolved, a) != null);
    if (!refAxes.length) return null;
    const target = refAxes.reduce((s, a) => s + percentileIn(fields[a], valueOf(refResolved, a)), 0) / refAxes.length;
    const anchor = {};
    const source = {};
    AXES.forEach(a => {
      const own = valueOf(refResolved, a);
      if (own != null) { anchor[a] = own; source[a] = 'reference'; }
      else { anchor[a] = quantileIn(fields[a], target); source[a] = 'estimate'; }
    });
    return { spec, pinned, anchor, source, target, ratio, fields, valueOf };
  }

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
      const picked = pickReference(rawData);
      if (!picked) {
        if (typeof onMissingBaseline === 'function') onMissingBaseline();
        return [];
      }
      const AXES = ['lma', 'aa', 'lb'];
      const resolveSrc = (last, k, cur, curVersion) => {
        const c = parseNum(cur);
        if (c > 0) return { value: c, state: 'live', version: curVersion || '' };
        const h = last[k] && last[k].value;
        return h > 0 ? { value: h, state: 'stale', version: last[k].version || '' } : { value: null, state: 'missing' };
      };
      const resolved = rawData.map(d => {
        const model = String(d.model || '').trim();
        const last = (lastTrackedScores && lastTrackedScores[model]) || {};
        return { d, model, src: { lma: resolveSrc(last, 'lma', d.lma), aa: resolveSrc(last, 'aa', d.aa, d.aa_version), lb: resolveSrc(last, 'lb', d.lb) } };
      });
      const refResolved = resolved.find(r => r.d === picked.row);
      const anchors = allAnchors(resolved, refResolved, picked.spec);
      if (!anchors) {
        if (typeof onMissingBaseline === 'function') onMissingBaseline();
        return [];
      }
      const { anchor, fields, valueOf } = anchors;
      const target = anchors.spec.target;
      const rel = (v, refValue) => refValue > 0 ? v / refValue : 0;

      rows = resolved.map(r => {
        const { d, model, src } = r;
        const name = String(d.name || '').trim();
        const isRef = anchors.pinned && r === refResolved;
        const norm = { lma: 0, aa: 0, lb: 0 };
        const estimates = {};
        if (AXES.filter(a => src[a].value != null).length >= 2) {
          const present = AXES.filter(a => valueOf(r, a) != null);
          const pct = isRef ? anchors.target : present.reduce((s, a) => s + percentileIn(fields[a], valueOf(r, a)), 0) / present.length;
          AXES.forEach(a => {
            let v = valueOf(r, a);
            if (v == null) {
              v = isRef ? anchor[a] : quantileIn(fields[a], pct);
              estimates[a] = v;
            }
            norm[a] = rel(v, anchor[a]);
          });
        }
        const score = target * ((norm.lma + norm.aa + norm.lb) / 3);
        const untracked = AXES.some(a => src[a].state === 'stale');
        const row = { model, name, score, untracked, deactivated: !!(modelToDeactivated && modelToDeactivated[model]) };
        if (Object.keys(estimates).length) row.estimates = estimates;
        if (includeSegments) {
          row.lmaSegment = target * norm.lma;
          row.aaSegment = target * norm.aa;
          row.lbSegment = target * norm.lb;
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
          providerEstimated: key === 'aa' && Number(d.aa_estimated) === 1,
          aaVersion: key === 'aa' ? (d.aa_version || '') : undefined,
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
          const historical = lastTrackedScores && lastTrackedScores[model] && lastTrackedScores[model][key];
          const providerEstimated = key === 'aa' && (cur > 0
            ? Number(d.aa_estimated) === 1 : !!(historical && historical.providerEstimated));
          const aaVersion = key === 'aa' ? (cur > 0 ? (d.aa_version || '') : ((historical && historical.version) || '')) : undefined;
          return { model, name: String(d.name || '').trim(), score, untracked, providerEstimated, aaVersion, deactivated: !!(modelToDeactivated && modelToDeactivated[model]) };
        });
      }
      if (key === 'aa' && LB.aaIndex && rows.some(r => r.score > 0 && LB.aaIndex.isV5(r.aaVersion))) {
        rows = rows.filter(r => LB.aaIndex.isV5(r.aaVersion));
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
  LB.allAnchors = allAnchors;
  LB.allReference = ALL_REFERENCE;
  LB.allLegacyReference = ALL_LEGACY_REFERENCE;
  LB.pickReference = pickReference;
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
