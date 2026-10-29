const { test } = require('node:test');
const assert = require('node:assert/strict');
require('../scripts/util.js');
require('../scripts/aggregation.js');
require('../scripts/tooltip.js');
require('../scripts/data-loader.js');

test('AA scores display without provider labels while our imputed estimates stay labelled', () => {
  const cell = LB.tooltip.renderScoreCell('gpt', 'aa', 39, String, {}, null, true);
  assert.equal(cell.html, '39');
  assert.equal(cell.estimated, undefined);
  const imputed = LB.tooltip.renderScoreCell('gpt', 'aa', 0, String, {}, 39);
  assert.equal(imputed.estimated, true);
  assert.ok(!imputed.html.includes('AA estimate'));
  const measured = LB.tooltip.renderScoreCell('gpt', 'aa', 39, String, {}, null, false);
  assert.equal(measured.html, '39');
});

test('AA estimate status survives live source rows and static snapshots', () => {
  const rawData = [{model: 'gpt', aa: 39, aa_estimated: '1'}];
  const input = {rawData, active: {question: 'Artificial Analysis'}};
  assert.equal(LB.aggregate(input)[0].providerEstimated, true);
  assert.equal(LB.aggregate({...input, sourceData: {aa: [{id: 'gpt', score: 39, aa_estimated: 1, tracked: true}]}})[0].providerEstimated, true);
  assert.equal(LB.aggregate({...input, rawData: [{model: 'gpt', aa: 39}]})[0].providerEstimated, false);
});

test('snapshot fallbacks cannot leak future AA scores or estimate status', async () => {
  const history = [
    {model: 'gpt', date: '2026-01-01', aa: 57},
    {model: 'gpt', date: '2026-02-01', aa: null},
    {model: 'gpt', date: '2026-09-11', aa: 39, aa_estimated: 1}
  ];
  global.d3 = {json: async url => url.endsWith('/history.json') ? history
    : url.endsWith('/sources.json') ? {} : []};
  const state = await LB.loadData({dataMode: 'rtdb', dataBase: 'fixture', snapshotParam: '2026-02-01'});
  assert.equal(state.rawData[0].aa, null);
  assert.equal(state.lastTrackedScores.gpt.aa.value, 57);
  assert.equal(state.lastTrackedScores.gpt.aa.providerEstimated, false);
  const cell = LB.tooltip.renderScoreCell('gpt', 'aa', 0, String,
    {gpt: {aa: {value: 39, providerEstimated: true}}});
  assert.ok(!cell.html.includes('AA estimate'));
  assert.ok(cell.html.includes('39'));
  assert.equal(cell.untracked, true);
});

test('LiveBench 1.0 scores never fill in for a missing 2.0 score', () => {
  const history = [
    {model: 'old', date: '2026-10-22', lma: 1400, aa: 40, lb: 79.19},
    {model: 'old', date: '2026-10-26', lma: 1400, aa: 40, lb: null},
    {model: 'new', date: '2026-10-22', lb: 78.54},
    {model: 'new', date: '2026-10-26', lb: 64.57}
  ];
  const now = LB.buildLastTrackedScores(history, null);
  assert.equal(now.old.lb, undefined);
  assert.equal(now.old.lma.value, 1400);
  assert.equal(now.old.aa.value, 40);
  assert.equal(now.new.lb.value, 64.57);
  const past = LB.buildLastTrackedScores(history.filter(r => r.date <= '2026-10-22'), '2026-10-22');
  assert.equal(past.old.lb.value, 79.19);
  const rawData = [{model: 'old', name: 'Old', lma: 1400, aa: 40, lb: null}];
  const rows = LB.aggregate({rawData, lastTrackedScores: now, active: {question: 'LiveBench'}});
  assert.equal(rows.length, 0);
  const cell = LB.tooltip.renderScoreCell('old', 'lb', 0, v => v.toFixed(1), now);
  assert.equal(cell.html, '-');
});

test('LiveBench 2.0 marker and note texts are exact and read the one start date', () => {
  assert.equal(LB.liveBench.v2Start, '2026-10-26');
  assert.equal(LB.liveBench.noteText, 'LiveBench 2.0 scores, from 26 October 2026.');
  assert.equal(LB.liveBench.markerText, 'LiveBench moved to version 2.0 on 26 October 2026. Scores before and after come from different tests.');
  assert.ok(LB.liveBench.noteHtml(null).includes(LB.liveBench.noteText));
  assert.ok(LB.liveBench.noteHtml('2026-10-26').includes(LB.liveBench.noteText));
  assert.equal(LB.liveBench.noteHtml('2026-10-25'), '');
  assert.equal(LB.liveBench.spans('2026-09-28', '2026-10-26'), true);
  assert.equal(LB.liveBench.spans('2026-10-26', '2026-10-26'), false);
  assert.equal(LB.liveBench.spans('2026-09-01', '2026-10-24'), false);
});

test('AA v5 switch date comes from the first v5 history row, with no switch before one exists', () => {
  const v4Only = [{model: 'a', date: '2026-10-01', aa: 60, aa_version: 'v4.3'}, {model: 'b', date: '2026-10-29', aa: 50}];
  LB.aaIndex.init(v4Only);
  assert.equal(LB.aaIndex.v5Start, null);
  assert.equal(LB.aaIndex.spans('2026-10-01', '2026-11-30'), false);
  assert.equal(LB.aaIndex.noteHtml(null), '');
  assert.equal(LB.aaIndex.label('v4.3', null), '');
  LB.aaIndex.init([...v4Only,
    {model: 'a', date: '2026-11-03', aa: 48, aa_version: 'v5.0'},
    {model: 'b', date: '2026-11-02', aa: 40, aa_version: 'v5.0'}]);
  assert.equal(LB.aaIndex.v5Start, '2026-11-02');
  assert.equal(LB.aaIndex.markerText, 'Artificial Analysis moved its Intelligence Index to v5 on 2 November 2026. v5 scores run lower, so scores before and after are not comparable.');
  assert.equal(LB.aaIndex.spans('2026-10-05', '2026-11-02'), true);
  assert.equal(LB.aaIndex.spans('2026-11-02', '2026-11-09'), false);
  assert.ok(LB.aaIndex.noteHtml(null).includes(LB.aaIndex.noteText));
  assert.equal(LB.aaIndex.noteHtml('2026-11-01'), '');
});

test('AA tooltip labels tell v4 from v5 once the switch exists', () => {
  LB.aaIndex.init([{model: 'a', date: '2026-11-02', aa: 48, aa_version: 'v5.0'}]);
  assert.ok(LB.aaIndex.label('v5.0', null).includes('>v5<'));
  assert.ok(LB.aaIndex.label('v4.3', null).includes('>v4<'));
  assert.ok(LB.aaIndex.label('', null).includes('>v4<'));
  assert.equal(LB.aaIndex.label('v4.3', '2026-10-30'), '');
  const last = LB.buildLastTrackedScores([{model: 'old', date: '2026-10-20', aa: 60, aa_version: 'v4.3'}], null);
  assert.equal(LB.aaIndex.versionOf({model: 'old', aa: null}, last), 'v4.3');
  assert.equal(LB.aaIndex.versionOf({model: 'new', aa: 48, aa_version: 'v5.0'}, last), 'v5.0');
});

test('AA baseline normalises each index version against its own GPT-5 reference', () => {
  const history = [
    {model: 'a', date: '2026-10-20', aa: 60}, {model: 'a', date: '2026-11-02', aa: 48, aa_version: 'v5.0'},
    {model: 'b', date: '2026-10-20', aa: 50}, {model: 'b', date: '2026-11-02', aa: 40, aa_version: 'v5.0'},
    {model: 'c', date: '2026-10-20', aa: 40}, {model: 'c', date: '2026-11-02', aa: 32, aa_version: 'v5.0'}
  ];
  LB.aaIndex.init(history);
  assert.equal(LB.aaIndex.v5Ratio, 0.8);
  assert.deepEqual(LB.aaAnchors({model: 'gpt-5-high', lma: 1434}), {v4: 45, v5: 36, v5Source: 'ratio'});
  assert.deepEqual(LB.aaAnchors({model: 'gpt-5-high', aa: 44, aa_version: 'v4.3'}), {v4: 44, v5: 35.2, v5Source: 'ratio'});
  assert.deepEqual(LB.aaAnchors({model: 'gpt-5-high', aa: 30, aa_version: 'v5.0'}), {v4: 45, v5: 30, v5Source: 'gpt5'});
  LB.aaIndex.init([...history, {model: 'gpt-5-high', date: '2026-11-03', aa: 33, aa_version: 'v5.0'}]);
  assert.deepEqual(LB.aaAnchors({model: 'gpt-5-high', lma: 1434}), {v4: 45, v5: 33, v5Source: 'gpt5'});
  LB.aaIndex.init(history);
  const rawData = [
    {model: 'gpt-5-high', lma: 1434, lb: 70},
    {model: 'v5model', lma: 1434, aa: 36, aa_version: 'v5.0', lb: 70},
    {model: 'v4stale', lma: 1434, lb: 70}
  ];
  const lastTrackedScores = LB.buildLastTrackedScores([{model: 'v4stale', date: '2026-10-20', aa: 45}], null);
  const rows = LB.aggregate({rawData, lastTrackedScores, active: {question: 'ALL'}, includeSegments: true});
  const seg = Object.fromEntries(rows.map(r => [r.model, r.aaSegment]));
  assert.equal(seg.v5model, 0.5);
  assert.equal(seg.v4stale, 0.5);
});

test('AA tab ranks only v5 scores once any v5 score is in view', () => {
  LB.aaIndex.init([{model: 'new', date: '2026-11-02', aa: 48, aa_version: 'v5.0'}]);
  const rawData = [{model: 'new', aa: 48, aa_version: 'v5.0'}, {model: 'old', aa: null}];
  const lastTrackedScores = LB.buildLastTrackedScores([{model: 'old', date: '2026-10-20', aa: 60}], null);
  const rows = LB.aggregate({rawData, lastTrackedScores, active: {question: 'Artificial Analysis'}});
  assert.deepEqual(rows.map(r => [r.model, r.aaVersion]), [['new', 'v5.0']]);
  const before = LB.aggregate({rawData: [{model: 'old', aa: null}], lastTrackedScores, active: {question: 'Artificial Analysis'}});
  assert.deepEqual(before.map(r => r.model), ['old']);
  LB.aaIndex.init([]);
});
