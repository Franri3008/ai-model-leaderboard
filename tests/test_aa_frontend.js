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
