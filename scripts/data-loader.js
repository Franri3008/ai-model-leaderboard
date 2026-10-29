(function (global) {
  const LB = global.LB = global.LB || {};
  const LIVEBENCH_V2_START = '2026-10-26';
  const AA_V5_START_FALLBACK = null;
  const AA_RATIO_MIN_MODELS = 3;

  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

  function formatLongDate(iso) {
    const [y, m, d] = String(iso).split('-').map(Number);
    return `${d} ${MONTHS[m - 1]} ${y}`;
  }

  function reconstructSnapshot(historyData, snapshotDate) {
    const latest = {};
    historyData.forEach(row => {
      if (row.date <= snapshotDate) latest[row.model] = row;
    });
    return Object.values(latest);
  }

  function spansLiveBenchV2(fromDate, toDate) {
    return !!fromDate && !!toDate && fromDate < LIVEBENCH_V2_START && toDate >= LIVEBENCH_V2_START;
  }

  function liveBenchNoteHtml(viewDate) {
    if (viewDate && viewDate < LIVEBENCH_V2_START) return '';
    return `<div class="lb-version-note" style="margin-top:6px;font-size:11px;color:#bbb;font-style:italic;text-align:center;">${LB.liveBench.noteText}</div>`;
  }

  function isAaV5(version) {
    return /^v5/i.test(String(version == null ? '' : version).trim());
  }

  function hasNum(v) {
    if (v == null || String(v).trim() === '') return false;
    const n = parseFloat(String(v).replace(/,/g, '.'));
    return !isNaN(n) && n > 0;
  }

  function findAaV5Start(historyData) {
    let first = null;
    (historyData || []).forEach(row => {
      if (isAaV5(row.aa_version) && (!first || String(row.date) < first)) first = String(row.date);
    });
    return first || AA_V5_START_FALLBACK;
  }

  function median(values) {
    const arr = values.slice().sort((a, b) => a - b);
    const mid = Math.floor(arr.length / 2);
    return arr.length % 2 ? arr[mid] : (arr[mid - 1] + arr[mid]) / 2;
  }

  function findAaV5Ratio(historyData) {
    const byModel = {};
    (historyData || []).slice().sort((a, b) => String(a.date).localeCompare(String(b.date))).forEach(row => {
      const m = String(row.model || '').trim();
      if (!m || !hasNum(row.aa)) return;
      const v = parseFloat(String(row.aa).replace(/,/g, '.'));
      const slot = byModel[m] = byModel[m] || {};
      if (isAaV5(row.aa_version)) slot.v5 = v;
      else if (slot.v5 == null) slot.v4 = v;
    });
    const ratios = Object.values(byModel).filter(s => s.v4 > 0 && s.v5 > 0).map(s => s.v5 / s.v4);
    return ratios.length >= AA_RATIO_MIN_MODELS ? median(ratios) : null;
  }

  function findGpt5AaV5(historyData) {
    let best = null;
    (historyData || []).forEach(row => {
      if (String(row.model || '').trim() !== 'gpt-5-high' || !isAaV5(row.aa_version) || !hasNum(row.aa)) return;
      if (!best || String(row.date) >= best.date) best = { date: String(row.date), value: parseFloat(String(row.aa).replace(/,/g, '.')) };
    });
    return best ? best.value : null;
  }

  function initAaIndex(historyData) {
    const aa = LB.aaIndex;
    aa.v5Start = findAaV5Start(historyData);
    aa.v5Ratio = findAaV5Ratio(historyData);
    aa.gpt5V5 = findGpt5AaV5(historyData);
    aa.noteText = aa.v5Start ? `Artificial Analysis Index v5 scores from ${formatLongDate(aa.v5Start)}. They run lower than v4 scores.` : '';
    aa.markerText = aa.v5Start ? `Artificial Analysis moved its Intelligence Index to v5 on ${formatLongDate(aa.v5Start)}. v5 scores run lower, so scores before and after are not comparable.` : '';
    return aa;
  }

  function aaSwitchShown(viewDate) {
    const start = LB.aaIndex.v5Start;
    return !!start && !(viewDate && viewDate < start);
  }

  function spansAaV5(fromDate, toDate) {
    const start = LB.aaIndex.v5Start;
    return !!start && !!fromDate && !!toDate && fromDate < start && toDate >= start;
  }

  function aaVersionLabel(version, viewDate) {
    if (!aaSwitchShown(viewDate)) return '';
    const major = isAaV5(version) ? 'v5' : 'v4';
    return ` <span class="aa-version" style="color:#999;font-size:0.85em;">${major}</span>`;
  }

  function aaNoteHtml(viewDate) {
    if (!aaSwitchShown(viewDate)) return '';
    return `<div class="aa-version-note" style="margin-top:6px;font-size:11px;color:#bbb;font-style:italic;text-align:center;">${LB.aaIndex.noteText}</div>`;
  }

  function aaVersionOf(row, lastTrackedScores) {
    if (row && hasNum(row.aa)) return row.aa_version || '';
    const model = row && String(row.model || '').trim();
    const last = model && lastTrackedScores && lastTrackedScores[model] && lastTrackedScores[model].aa;
    return last ? (last.version || '') : '';
  }

  function normalizeSnapshotDate(snapshotParam) {
    return snapshotParam
      .replace(/_/g, '-')
      .replace(/^(\d{4})-(\d{1,2})-(\d{1,2})$/, (m, y, mo, d) => `${y}-${mo.padStart(2, '0')}-${d.padStart(2, '0')}`);
  }

  function buildLastTrackedScores(historyData, viewDate) {
    const out = {};
    if (!Array.isArray(historyData)) return out;
    const parseNum = LB.util.parseNum;
    const dropLiveBenchV1 = !viewDate || viewDate >= LIVEBENCH_V2_START;
    historyData.forEach(row => {
      const m = String(row.model || '').trim();
      if (!m) return;
      if (!out[m]) out[m] = {};
      ['lma', 'aa', 'lb'].forEach(k => {
        const raw = row[k];
        if (raw == null || String(raw).trim() === '') return;
        if (k === 'lb' && dropLiveBenchV1 && String(row.date) < LIVEBENCH_V2_START) return;
        const v = parseNum(raw);
        if (v <= 0) return;
        const existing = out[m][k];
        if (!existing || row.date >= existing.date) {
          out[m][k] = { value: v, date: row.date, providerEstimated: k === 'aa' && Number(row.aa_estimated) === 1 };
          if (k === 'aa') out[m][k].version = row.aa_version || '';
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
      const snapshotDate = snapshotParam ? normalizeSnapshotDate(snapshotParam) : null;
      const visibleHistory = snapshotDate ? historyData.filter(row => row.date <= snapshotDate) : historyData;
      const lastTrackedScores = buildLastTrackedScores(visibleHistory, snapshotDate);
      initAaIndex(visibleHistory);

      const idToColor = {};
      const idToOrg = {};
      modelsData.forEach(m => { idToColor[m.id] = m.color; idToOrg[m.id] = m.org; });

      const modelToOs = {};
      const modelToGeo = {};
      const modelToReleaseDate = {};
      const modelToCost = {};
      const modelToDeactivated = {};
      const trackingMap = {};
      const modelIcons = {};
      const modelToLogo = {};
      const modelToOrg = {};
      if (trackingData) {
        trackingData.forEach(t => {
          const model = String(t.model || '').trim();
          const logo = String(t.logo || '').trim();
          if (!model) return;
          modelToOs[model] = t.os;
          if (t.geo) modelToGeo[model] = t.geo === 'USA' ? 'US' : t.geo;
          if (Number(t.deactivated) === 1) modelToDeactivated[model] = true;
          if (t.release_date) {
            const rd = new Date(t.release_date);
            if (!isNaN(rd.getTime())) modelToReleaseDate[model] = rd;
          }
          if (t.cost_output != null && t.cost_output !== '') {
            const c = Number(t.cost_output);
            if (!isNaN(c) && c > 0) modelToCost[model] = c;
          }
          if (logo) {
            modelIcons[model] = `logos/${logo}.png`;
            modelToLogo[model] = logo;
            if (idToOrg[logo]) modelToOrg[model] = idToOrg[logo];
          }
          trackingMap[model] = t;
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
        modelToCost,
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
  LB.buildLastTrackedScores = buildLastTrackedScores;
  LB.reconstructSnapshot = reconstructSnapshot;
  LB.normalizeSnapshotDate = normalizeSnapshotDate;
  LB.liveBench = {
    v2Start: LIVEBENCH_V2_START,
    noteText: `LiveBench 2.0 scores, from ${formatLongDate(LIVEBENCH_V2_START)}.`,
    markerText: `LiveBench moved to version 2.0 on ${formatLongDate(LIVEBENCH_V2_START)}. Scores before and after come from different tests.`,
    spans: spansLiveBenchV2,
    noteHtml: liveBenchNoteHtml
  };
  LB.aaIndex = {
    v5Start: AA_V5_START_FALLBACK,
    v5Ratio: null,
    gpt5V5: null,
    noteText: '',
    markerText: '',
    init: initAaIndex,
    isV5: isAaV5,
    spans: spansAaV5,
    label: aaVersionLabel,
    noteHtml: aaNoteHtml,
    versionOf: aaVersionOf
  };
})(typeof window !== 'undefined' ? window : globalThis);
