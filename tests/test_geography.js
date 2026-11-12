const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
require('../scripts/geography.js');

const geography = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'config', 'lab-geography.json'), 'utf8'));
const models = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'config', 'models.json'), 'utf8'));

test('each lab keeps only its best scored, active model', () => {
  const aggregated = [
    {model: 'gpt-a', name: 'GPT A', score: 0.70},
    {model: 'gpt-b', name: 'GPT B', score: 0.72},
    {model: 'gpt-c', name: 'GPT C', score: 0.90, deactivated: true},
    {model: 'claude-a', name: 'Claude A', score: 0.71},
    {model: 'claude-b', name: 'Claude B', score: 0}
  ];
  const modelToLogo = {'gpt-a': 'gpt', 'gpt-b': 'gpt', 'gpt-c': 'gpt', 'claude-a': 'claude', 'claude-b': 'claude'};
  const rawData = [{model: 'gpt-b', displayName: 'GPT B (Thinking)'}];
  const rows = LB.geography.selectRows({aggregated, modelToLogo, rawData, geography, warn: () => {}});
  assert.deepEqual(rows.map(r => [r.id, r.model, r.dev, r.city, r.country]), [
    ['gpt-b', 'GPT B (Thinking)', 'OpenAI', 'sf', 'US'],
    ['claude-a', 'Claude A', 'Anthropic', 'sf', 'US']
  ]);
});

test('only the top 15 labs by best score are shown', () => {
  const aggregated = Array.from({length: 20}, (_, i) => ({model: `m${i}`, name: `M${i}`, score: 0.5 + i / 100}));
  const modelToLogo = Object.fromEntries(aggregated.map((d, i) => [d.model, `lab${i}`]));
  const rows = LB.geography.selectRows({aggregated, modelToLogo, geography, warn: () => {}});
  assert.equal(rows.length, 15);
  assert.equal(rows[0].id, 'm19');
  assert.equal(rows[14].id, 'm5');
});

test('a lab missing from the map shows as Unmapped with a warning, never dropped', () => {
  const warnings = [];
  const aggregated = [{model: 'new-1', name: 'New One', score: 0.8}, {model: 'gpt-a', name: 'GPT A', score: 0.7}];
  const rows = LB.geography.selectRows({aggregated, modelToLogo: {'new-1': 'newlab', 'gpt-a': 'gpt'}, geography, warn: m => warnings.push(m)});
  assert.equal(rows.length, 2);
  assert.equal(rows[0].city, LB.geography.UNMAPPED_KEY);
  assert.equal(rows[0].cityName, 'Unmapped');
  assert.equal(rows[0].color, geography.unmapped.color);
  assert.equal(rows[0].dev, 'newlab');
  assert.equal(warnings.length, 1);
  assert.ok(warnings[0].includes('newlab'));
  assert.deepEqual(LB.geography.cityOrder(geography).slice(-1), [LB.geography.UNMAPPED_KEY]);
});

test('every lab in config/models.json has a place and every place a known city', () => {
  models.forEach(m => assert.ok(geography.labs[m.id], `missing ${m.id}`));
  Object.values(geography.labs).forEach(l => {
    assert.ok(geography.cities[l.city], `unknown city ${l.city}`);
    assert.equal(geography.cities[l.city].country, l.country);
  });
});

test('top sets the number of labs, capped at 15, default 15', () => {
  assert.equal(LB.geography.labLimit(undefined), 15);
  assert.equal(LB.geography.labLimit(25), 15);
  assert.equal(LB.geography.labLimit(12), 12);
  assert.equal(LB.geography.labLimit(0), 15);
});

test('the score axis keeps the overall grid and fits single sources', () => {
  const all = LB.geography.scoreAxis([0.512, 0.703], 'ALL');
  assert.equal(all.lo, 0.45);
  assert.equal(all.hi, 0.75);
  assert.equal(all.ticks.length, 6);
  assert.equal(all.valueDigits, 3);
  [[[1380, 1502], 'LMArena'], [[48, 73], 'Artificial Analysis'], [[61.2, 79.8], 'LiveBench']].forEach(([scores, q]) => {
    const a = LB.geography.scoreAxis(scores, q);
    assert.ok(a.lo < Math.min(...scores) && a.hi >= Math.max(...scores), q);
    assert.ok(a.ticks.length >= 2 && a.ticks.length <= 8, q);
  });
});
