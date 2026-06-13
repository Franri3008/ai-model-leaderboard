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
    const cfg = (LB.config) || {};
    const dataBase = opts.dataBase || cfg.dataBase || '.';
    const configBase = opts.configBase || cfg.configBase || '.';
    const dataMode = opts.dataMode || cfg.dataMode || 'static';
    const snapshotParam = opts.snapshotParam || null;

    // RTDB returns JSON arrays directly under fixed keys; static mode reads
    // CSVs and lets d3 parse them. The post-fetch row shape is identical.
    const fetchProcessed = dataMode === 'rtdb'
      ? () => d3.json(`${dataBase}/processed.json`).then(rows => rows || [])
      : () => d3.dsv(';', `${dataBase}/data/processed.csv`);
    const fetchHistory = dataMode === 'rtdb'
      ? () => d3.json(`${dataBase}/history.json`).then(rows => rows || [])
      : () => d3.dsv(';', `${dataBase}/data/history.csv`);
    const fetchSources = dataMode === 'rtdb'
      ? () => d3.json(`${dataBase}/sources.json`).catch(() => null)
      : () => d3.json(`${dataBase}/data/sources.json`).catch(() => null);

    const dataPromise = snapshotParam
      ? fetchHistory().then(history => {
        const snapshotDate = normalizeSnapshotDate(snapshotParam);
        return reconstructSnapshot(history, snapshotDate);
      })
      : fetchProcessed();

    return Promise.all([
      dataPromise,
      d3.json(`${configBase}/config/models.json`),
      d3.json(`${configBase}/config/tracking.json`),
      fetchHistory(),
      fetchSources()
    ]).then(([rawData, modelsData, trackingData, historyData, sourcesData]) => {
      const lastTrackedScores = buildLastTrackedScores(historyData);

      const idToColor = {};
      const idToOrg = {};
      modelsData.forEach(m => { idToColor[m.id] = m.color; idToOrg[m.id] = m.org; });

      const modelToOs = {};
      const modelToGeo = {};
      const modelToReleaseDate = {};
      const modelToDeactivated = {};
      const trackingMap = {};
      if (trackingData) {
        trackingData.forEach(t => {
          modelToOs[t.model] = t.os;
          if (t.geo) modelToGeo[t.model] = t.geo === 'USA' ? 'US' : t.geo;
          if (Number(t.deactivated) === 1) modelToDeactivated[t.model] = true;
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

      const sourceData = (sourcesData && typeof sourcesData === 'object') ? sourcesData : null;
      if (sourceData) {
        ['lma', 'aa', 'lb'].forEach(key => {
          const rows = sourceData[key];
          if (!Array.isArray(rows)) return;
          rows.forEach(r => {
            const id = String(r.id || '').trim();
            if (!id) return;
            const logo = r.logo ? String(r.logo).trim() : '';
            if (logo && !modelIcons[id]) modelIcons[id] = `logos/${logo}.png`;
            if (logo && !modelToLogo[id]) modelToLogo[id] = logo;
            if (logo && idToOrg[logo] && !modelToOrg[id]) modelToOrg[id] = idToOrg[logo];
            if (r.geo && !modelToGeo[id]) modelToGeo[id] = r.geo === 'USA' ? 'US' : r.geo;
          });
        });
      }

      return {
        rawData,
        lastTrackedScores,
        modelToOs,
        modelToGeo,
        modelToReleaseDate,
        modelToDeactivated,
        modelToLogo,
        modelToOrg,
        modelIcons,
        idToColor,
        idToOrg,
        trackingMap,
        sourceData
      };
    });
  }

  LB.loadData = loadData;
})(typeof window !== 'undefined' ? window : globalThis);
