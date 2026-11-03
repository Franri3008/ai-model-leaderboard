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

function allView(rawData, history, viewDate) {
  LB.aaIndex.init(history);
  const lastTrackedScores = LB.buildLastTrackedScores(history, viewDate || null);
  const rows = LB.aggregate({rawData, lastTrackedScores, active: {question: 'ALL'}, includeSegments: true, ignoreModelFilter: true});
  return Object.fromEntries(rows.map(r => [r.model, r]));
}

test('AA v5 ratio ignores untagged rows written on or after the switch day', () => {
  LB.aaIndex.init([
    {model: 'a', date: '2026-10-20', aa: 60}, {model: 'a', date: '2026-11-02', aa: 48}, {model: 'a', date: '2026-11-02', aa: 48, aa_version: 'v5.0'},
    {model: 'b', date: '2026-10-20', aa: 50}, {model: 'b', date: '2026-11-02', aa: 40}, {model: 'b', date: '2026-11-02', aa: 40, aa_version: 'v5.0'},
    {model: 'c', date: '2026-10-20', aa: 40}, {model: 'c', date: '2026-11-02', aa: 32}, {model: 'c', date: '2026-11-02', aa: 32, aa_version: 'v5.0'},
    {model: 'gpt-5-high', date: '2026-10-20', aa: 23}, {model: 'gpt-5-high', date: '2026-11-02', lma: 1400}
  ]);
  assert.equal(LB.aaIndex.v5Ratio, 0.8);
  LB.aaIndex.init([]);
});

test('the ALL reference is GPT 6.1 Sol at 0.70, GPT-5 at 0.50 is the fallback, and the view stops without both', () => {
  assert.deepEqual(LB.allReference, {model: 'gpt-6-1-sol', name: 'GPT 6.1 Sol', target: 0.70});
  assert.deepEqual(LB.allLegacyReference, {model: 'gpt-5-high', name: 'GPT-5', target: 0.50, fallback: {lma: 1434, aa: 45, lb: 70.48}});
  assert.equal(LB.pickReference([{model: 'gpt-5-high'}, {model: 'gpt-6-1-sol'}]).spec, LB.allReference);
  assert.equal(LB.pickReference([{model: 'gpt-5-high'}]).spec, LB.allLegacyReference);
  let missing = false;
  const rows = LB.aggregate({rawData: [{model: 'x', lma: 1400, aa: 30, lb: 70}],
    active: {question: 'ALL'}, onMissingBaseline: () => { missing = true; }});
  assert.deepEqual(rows, []);
  assert.equal(missing, true);
});

const SNAPSHOT_HISTORY = [
  {model: 'gpt-5-high', date: '2026-04-01', lma: 1434, aa: 45, lb: 70.48},
  {model: 'gpt-5-high', date: '2026-07-09', lma: 1434},
  {model: 'x', date: '2026-04-01', lma: 1500, aa: 50, lb: 80},
  {model: 'y', date: '2026-04-01', lma: 1400, aa: 40},
  {model: 'gpt-6-1-sol', date: '2026-09-30', lma: 1483, aa: 52, aa_version: 'v4.3', lb: 81.62}
];

function snapshotView(date) {
  const visible = SNAPSHOT_HISTORY.filter(r => r.date <= date);
  return allView(LB.reconstructSnapshot(SNAPSHOT_HISTORY, date), visible, date);
}

test('a snapshot before GPT 6.1 Sol exists ranks with GPT-5 at exactly 0.50 and the anchors of that time', () => {
  const april = snapshotView('2026-04-10');
  assert.equal(april['gpt-5-high'].score, 0.5);
  assert.equal(april['gpt-6-1-sol'], undefined);
  assert.ok(Math.abs(april.x.score - (1500 / 2868 + 50 / 90 + 80 / 140.96) / 3) < 1e-12);
  const july = snapshotView('2026-09-29');
  assert.equal(july['gpt-5-high'].score, 0.5);
  assert.equal(july['gpt-5-high'].untracked, true);
  assert.ok(Math.abs(july.x.aaSegment - 0.5 * 50 / 45) < 1e-12);
  assert.ok(Math.abs(july.x.lbSegment - 0.5 * 80 / 70.48) < 1e-12);
  LB.aaIndex.init([]);
});

test('a snapshot from 30 September 2026 on ranks with GPT 6.1 Sol at exactly 0.70', () => {
  const rows = snapshotView('2026-10-01');
  assert.equal(rows['gpt-6-1-sol'].score, 0.7);
  assert.notEqual(rows['gpt-5-high'].score, 0.5);
  assert.ok(Math.abs(rows.x.lmaSegment - 0.7 * 1500 / 1483) < 1e-12);
  LB.aaIndex.init([]);
});

test('GPT 6.1 Sol scores exactly 0.70 when every source is live, and each part is 0.70 times value over its value', () => {
  const history = [{model: 'gpt-6-1-sol', date: '2026-11-02', lma: 1481, aa: 55, aa_version: 'v5.0', lb: 84.07}];
  const rawData = [
    {model: 'gpt-6-1-sol', lma: 1481, aa: 55, aa_version: 'v5.0', lb: 84.07},
    {model: 'x', lma: 1500, aa: 60, aa_version: 'v5.0', lb: 80},
    {model: 'gpt-5-high', lma: 1435, lb: 60}
  ];
  const rows = allView(rawData, history);
  const ref = rows['gpt-6-1-sol'];
  assert.equal(ref.score, 0.7);
  assert.deepEqual([ref.lmaSegment, ref.aaSegment, ref.lbSegment], [0.7, 0.7, 0.7]);
  assert.equal(ref.estimates, undefined);
  assert.equal(rows.x.aaSegment, 0.7 * (60 / 55));
  assert.equal(rows.x.lmaSegment, 0.7 * (1500 / 1481));
  assert.notEqual(rows['gpt-5-high'].score, 0.5);
  LB.aaIndex.init([]);
});

test('GPT 6.1 Sol stays at exactly 0.70 when a source is missing or only on an old scale', () => {
  const history = [
    {model: 'gpt-6-1-sol', date: '2026-10-22', lma: 1480, aa: 52, lb: 81.62},
    {model: 'p', date: '2026-10-27', lma: 1300, aa: 20, lb: 60},
    {model: 'q', date: '2026-10-27', lma: 1500, aa: 40, lb: 80}
  ];
  const rawData = [
    {model: 'gpt-6-1-sol', lma: 1400, aa: 30},
    {model: 'p', lma: 1300, aa: 20, lb: 60},
    {model: 'q', lma: 1500, aa: 40, lb: 80}
  ];
  const rows = allView(rawData, history, '2026-11-03');
  assert.equal(rows['gpt-6-1-sol'].score, 0.7);
  assert.equal(rows['gpt-6-1-sol'].estimates.lb, 70);
  assert.equal(rows.q.lbSegment, 0.7 * (80 / 70));
  const v5 = [
    {model: 'a', date: '2026-10-20', aa: 60}, {model: 'a', date: '2026-11-02', aa: 48, aa_version: 'v5.0'},
    {model: 'b', date: '2026-10-20', aa: 50}, {model: 'b', date: '2026-11-02', aa: 40, aa_version: 'v5.0'},
    {model: 'c', date: '2026-10-20', aa: 40}, {model: 'c', date: '2026-11-02', aa: 32, aa_version: 'v5.0'},
    {model: 'gpt-6-1-sol', date: '2026-10-20', lma: 1400, aa: 52, lb: 70}
  ];
  const v4Only = allView([
    {model: 'gpt-6-1-sol', lma: 1400, lb: 70},
    {model: 'a', lma: 1500, aa: 48, aa_version: 'v5.0', lb: 80},
    {model: 'b', lma: 1450, aa: 40, aa_version: 'v5.0', lb: 72},
    {model: 'c', lma: 1300, aa: 32, aa_version: 'v5.0', lb: 60}
  ], v5);
  assert.equal(v4Only['gpt-6-1-sol'].score, 0.7);
  assert.ok(v4Only['gpt-6-1-sol'].estimates.aa > 0);
  LB.aaIndex.init([]);
});

test('AA v4-only peers move onto the v5 scale with the ratio before the 0.70 reference applies', () => {
  const history = [
    {model: 'a', date: '2026-10-20', aa: 60}, {model: 'a', date: '2026-11-02', aa: 48, aa_version: 'v5.0'},
    {model: 'b', date: '2026-10-20', aa: 50}, {model: 'b', date: '2026-11-02', aa: 40, aa_version: 'v5.0'},
    {model: 'c', date: '2026-10-20', aa: 40}, {model: 'c', date: '2026-11-02', aa: 32, aa_version: 'v5.0'},
    {model: 'old', date: '2026-10-20', aa: 50},
    {model: 'older', date: '2026-10-20', aa: 30}
  ];
  const rawData = [
    {model: 'gpt-6-1-sol', lma: 1480, aa: 40, aa_version: 'v5.0', lb: 84},
    {model: 'a', lma: 1500, aa: 48, aa_version: 'v5.0', lb: 85},
    {model: 'b', lma: 1450, aa: 40, aa_version: 'v5.0', lb: 70},
    {model: 'c', lma: 1300, aa: 32, aa_version: 'v5.0', lb: 60},
    {model: 'old', lma: 1420, lb: 65},
    {model: 'older', lma: 1400, lb: 60}
  ];
  const rows = allView(rawData, history);
  assert.equal(rows['gpt-6-1-sol'].score, 0.7);
  assert.ok(Math.abs(rows.old.aaSegment - rows.b.aaSegment) < 1e-9);
  assert.ok(Math.abs(rows.older.aaSegment - 0.7 * (30 * 0.8) / 40) < 1e-9);
  assert.ok(rows.a.score > rows['gpt-6-1-sol'].score && rows.c.score < rows.b.score);
  LB.aaIndex.init([]);
});

test('the reference switch marker date comes from the first GPT 6.1 Sol row, with 30 September 2026 as fallback', () => {
  LB.referenceSwitch.init([{model: 'x', date: '2026-09-01'}, {model: 'gpt-6-1-sol', date: '2026-10-02'}, {model: 'gpt-6-1-sol', date: '2026-10-01'}]);
  assert.equal(LB.referenceSwitch.start, '2026-10-01');
  LB.referenceSwitch.init([{model: 'x', date: '2026-09-01'}]);
  assert.equal(LB.referenceSwitch.start, '2026-09-30');
  assert.equal(LB.referenceSwitch.markerText, 'On 30 September 2026 the reference moved from GPT-5 at 0.50 to GPT 6.1 Sol at 0.70. Scores before and after are not directly comparable.');
  assert.equal(LB.referenceSwitch.spans('2026-09-29', '2026-09-30'), true);
  assert.equal(LB.referenceSwitch.spans('2026-09-30', '2026-11-03'), false);
  assert.equal(LB.referenceSwitch.spans('2026-08-01', '2026-09-29'), false);
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
