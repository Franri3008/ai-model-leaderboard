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
      const maxLma = parseNum(gpt5.lma) || 1434;
      const maxAa = parseNum(gpt5.aa) || 45;
      const maxLb = parseNum(gpt5.lb) || 70.48;

      rows = rawData.map(d => {
        const model = String(d.model || '').trim();
        const name = String(d.name || '').trim();
        const lma = parseNum(d.lma);
        const aa = parseNum(d.aa);
        const lb = parseNum(d.lb);
        const hasLma = lma > 0, hasAa = aa > 0, hasLb = lb > 0;
        const missing = (hasLma ? 0 : 1) + (hasAa ? 0 : 1) + (hasLb ? 0 : 1);
        let nLma = hasLma ? (lma / (2 * maxLma)) : 0;
        let nAa = hasAa ? (aa / (2 * maxAa)) : 0;
        let nLb = hasLb ? (lb / (2 * maxLb)) : 0;
        if (missing === 1) {
          if (!hasLma && hasAa && hasLb) nLma = (nAa + nLb) / 2;
          else if (!hasAa && hasLma && hasLb) nAa = (nLma + nLb) / 2;
          else if (!hasLb && hasLma && hasAa) nLb = (nLma + nAa) / 2;
        }
        const score = (nLma + nAa + nLb) / 3;
        const last = (lastTrackedScores && lastTrackedScores[model]) || {};
        const untracked = (!hasLma && last.lma && last.lma.value > 0)
          || (!hasAa && last.aa && last.aa.value > 0)
          || (!hasLb && last.lb && last.lb.value > 0);
        const row = { model, name, score, untracked, deactivated: !!(modelToDeactivated && modelToDeactivated[model]) };
        if (includeSegments) {
          row.lmaSegment = nLma;
          row.aaSegment = nAa;
          row.lbSegment = nLb;
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
      if (global.ModelFilter && global.ModelFilter.isHidden(d.model)) return false;
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
})(typeof window !== 'undefined' ? window : globalThis);
