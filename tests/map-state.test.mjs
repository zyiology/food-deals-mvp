import test from 'node:test';
import assert from 'node:assert/strict';
import { coordinateKey, groupCoordinates } from '../src/food_deals_mvp/static/map-state.js';

const row = (id, latitude, longitude, posted_at = '2026-08-26T10:00:00+08:00') => ({ deal_id: id, latitude, longitude, posted_at });
const bounds = { south: 1, north: 2, west: 103, east: 104 };
const groups = (rows, viewport = null) => [...groupCoordinates(rows, viewport).groups.values()];

test('viewport includes boundaries and excludes each outside edge', () => {
  const rows = [row('sw', 1, 103), row('ne', 2, 104), row('s', .99, 103.5), row('n', 2.01, 103.5), row('w', 1.5, 102.99), row('e', 1.5, 104.01)];
  assert.deepEqual(groups(rows, bounds).map(g => g.rows[0].deal_id), ['ne', 'sw']);
});

test('groups follow newest members, timestamp instants and stable ID ties', () => {
  const rows = [row('b', 1, 103), row('a', 2, 104, '2026-08-26T02:00:00Z'), row('new', 1, 103, '2026-08-26T03:00:00Z')];
  const before = structuredClone(rows);
  const result = groups(rows, bounds);
  assert.deepEqual(result.map(g => [g.number, g.rows.map(r => r.deal_id)]), [[1, ['new', 'b']], [2, ['a']]]);
  assert.deepEqual(groups([...rows].reverse(), bounds), result);
  assert.deepEqual(rows, before);
  assert.deepEqual(groups(rows.slice(0, 2)).map(g => g.rows[0].deal_id), ['a', 'b']);
});

test('exact coordinates retain every original row regardless of merchant or unit', () => {
  const rows = [row('a', 1, 103), row('b', 1, 103), row('c', 1.000001, 103)];
  Object.assign(rows[0], { merchant: 'Cafe', unit: '01-01' });
  Object.assign(rows[1], { merchant: 'Bakery', unit: '02-02' });
  const result = groupCoordinates(rows);
  assert.equal(result.groups.size, 2);
  assert.equal(result.byDealId.size, 3);
  const shared = result.groups.get(coordinateKey(rows[0]));
  assert.deepEqual(shared.rows, rows.slice(0, 2));
  assert.equal(shared.rows[1], rows[1]);
  assert.equal(result.byDealId.get('a'), shared);
  assert.equal(result.byDealId.get('b'), shared);
  assert.notEqual(result.byDealId.get('c'), shared);
  assert.equal(result.byDealId.get('c').latitude, 1.000001);
});

test('labels use trimmed resolved agreement then unanimous original labels', () => {
  const cases = [
    [[{ resolved_label: ' Place ' }, { resolved_label: 'Place' }], 'Place'],
    [[{ resolved_label: 'Place' }, { resolved_label: '' }], 'Place'],
    [[{ resolved_label: 'A', location_label: 'Same' }, { resolved_label: 'B', location_label: 'Same' }], 'Shared map location'],
    [[{ location_label: ' Place ' }, { location_label: 'Place' }], 'Place'],
    [[{ location_label: 'Place' }, {}], 'Shared map location'],
    [[{ location_label: 'A' }, { location_label: 'B' }], 'Shared map location'],
    [[{}, { resolved_label: ' ', location_label: ' ' }], 'Shared map location'],
  ];
  for (const [labels, expected] of cases) {
    const rows = labels.map((label, index) => ({ ...row(String(index), 1, 103), ...label }));
    assert.equal(groups(rows)[0].label, expected);
    assert.equal(groups([...rows].reverse())[0].label, expected);
  }
});

test('deal lookups follow identity through renumbering without transferring selection', () => {
  const rows = [row('a', 1, 103), row('b', 2, 104), row('c', 2, 104)];
  assert.equal(groupCoordinates(rows).byDealId.get('b').number, 2);
  const visible = groupCoordinates(rows, { ...bounds, south: 1.5 });
  assert.equal(visible.byDealId.get('b').number, 1);
  assert.equal(visible.byDealId.has('a'), false);
  const removed = groupCoordinates(rows.filter(r => r.deal_id !== 'b'));
  assert.equal(removed.byDealId.has('b'), false);
  assert.deepEqual(removed.groups.get('2,104').rows.map(r => r.deal_id), ['c']);
});

test('empty, single-location and missing-map results have contiguous location numbers', () => {
  const empty = groupCoordinates([]);
  assert.equal(empty.groups.size, 0);
  assert.equal(empty.byDealId.size, 0);
  assert.deepEqual(groups([row('a', 1, 103), row('b', 1, 103)]).map(g => g.number), [1]);
  const rows = [row('a', 1, 103), row('b', 2, 104), row('c', 3, 105)];
  assert.deepEqual(groups(rows).map(g => g.number), [1, 2, 3]);
  assert.equal(groupCoordinates(rows).byDealId.size, rows.length);
  assert.deepEqual(groups(rows, { ...bounds, south: 4 }), []);
});
