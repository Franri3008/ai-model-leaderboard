(function (global) {
  const LB = global.LB = global.LB || {};

  function reconstructSnapshot(historyData, snapshotDate) {
    const latest = {};
    historyData.forEach(row => {
      if (row.date <= snapshotDate) latest[row.model] = row;
    });
    return Object.values(latest);
  }

  function normalizeSnapshotDate(snapshotParam) {
    return snapshotParam
      .replace(/_/g, '-')
      .replace(/^(\d{4})-(\d{1,2})-(\d{1,2})$/, (m, y, mo, d) => `${y}-${mo.padStart(2, '0')}-${d.padStart(2, '0')}`);
  }

  function buildLastTrackedScores(historyData) {
    const out = {};
    if (!Array.isArray(historyData)) return out;
    const parseNum = LB.util.parseNum;
    historyData.forEach(row => {
      const m = String(row.model || '').trim();
      if (!m) return;
      if (!out[m]) out[m] = {};
      ['lma', 'aa', 'lb'].forEach(k => {
        const raw = row[k];
        if (raw == null || String(raw).trim() === '') return;
        const v = parseNum(raw);
        if (v <= 0) return;
        const existing = out[m][k];
        if (!existing || row.date >= existing.date) {
          out[m][k] = { value: v, date: row.date };
        }
      });
    });
    return out;
  }

  function loadData(options) {
    const opts = options || {};
    const dataBase = opts.dataBase || '.';
    const snapshotParam = opts.snapshotParam || null;

    const dataPromise = snapshotParam
      ? d3.dsv(';', `${dataBase}/data/history.csv`).then(history => {
        const snapshotDate = normalizeSnapshotDate(snapshotParam);
        return reconstructSnapshot(history, snapshotDate);
      })
      : d3.dsv(';', `${dataBase}/data/processed.csv`);

    return Promise.all([
      dataPromise,
      d3.json(`${dataBase}/config/models.json`),
      d3.json(`${dataBase}/config/tracking.json`),
      d3.dsv(';', `${dataBase}/data/history.csv`)
    ]).then(([rawData, modelsData, trackingData, historyData]) => {
      const lastTrackedScores = buildLastTrackedScores(historyData);

      const idToColor = {};
      const idToOrg = {};
      modelsData.forEach(m => { idToColor[m.id] = m.color; idToOrg[m.id] = m.org; });

      const modelToOs = {};
      const modelToGeo = {};
      const modelToReleaseDate = {};
      const trackingMap = {};
      if (trackingData) {
        trackingData.forEach(t => {
          modelToOs[t.model] = t.os;
          if (t.geo) modelToGeo[t.model] = t.geo === 'USA' ? 'US' : t.geo;
          if (t.release_date) {
            const rd = new Date(t.release_date);
            if (!isNaN(rd.getTime())) modelToReleaseDate[t.model] = rd;
          }
          trackingMap[t.model] = t;
        });
        if (snapshotParam) {
          rawData.forEach(d => {
            const t = trackingMap[String(d.model || '').trim()];
            if (t) {
              if (!d.name) d.name = t.name;
              if (!d.logo) d.logo = t.logo;
              if (!d.geo) d.geo = t.geo === 'USA' ? 'US' : t.geo;
            }
          });
        }
      }

      const modelIcons = {};
      const modelToLogo = {};
      const modelToOrg = {};
      rawData.forEach(d => {
        const model = String(d.model || '').trim();
        const name = String(d.name || '').trim();
        const logo = String(d.logo || '').trim();
        d.displayName = name || model;
        if (logo) {
          modelIcons[model] = `logos/${logo}.png`;
          modelToLogo[model] = logo;
          if (idToOrg[logo]) modelToOrg[model] = idToOrg[logo];
        }
      });

      return {
        rawData,
        lastTrackedScores,
        modelToOs,
        modelToGeo,
        modelToReleaseDate,
        modelToLogo,
        modelToOrg,
        modelIcons,
        idToColor,
        idToOrg,
        trackingMap
      };
    });
  }

  LB.loadData = loadData;
})(typeof window !== 'undefined' ? window : globalThis);
