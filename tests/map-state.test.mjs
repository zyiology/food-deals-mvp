import test from 'node:test';
import assert from 'node:assert/strict';
import { numberedRows, groupCoordinates, visibleSelection } from '../src/food_deals_mvp/static/map-state.js';

const row = (id, latitude, longitude, posted_at = '2026-08-26T10:00:00+08:00') => ({ deal_id: id, latitude, longitude, posted_at });
const bounds = { south: 1, north: 2, west: 103, east: 104 };

test('viewport includes edges and excludes each outside edge', () => {
  const rows = [row('sw', 1, 103), row('ne', 2, 104), row('s', .99, 103.5), row('n', 2.01, 103.5), row('w', 1.5, 102.99), row('e', 1.5, 104.01)];
  assert.deepEqual(numberedRows(rows, bounds).map(e => e.row.deal_id), ['ne', 'sw']);
});

test('numbering uses timestamp instants and stable IDs without mutating input', () => {
  const rows = [row('b', 1, 103), row('a', 1, 103, '2026-08-26T02:00:00Z'), row('new', 1, 103, '2026-08-26T03:00:00Z')];
  const before = structuredClone(rows);
  const entries = numberedRows(rows, bounds);
  assert.deepEqual(entries.map(e => [e.row.deal_id, e.number]), [['new', 1], ['a', 2], ['b', 3]]);
  assert.deepEqual(numberedRows([...rows].reverse(), bounds), entries);
  assert.deepEqual(rows, before);
});

test('selection follows ID through renumbering and clears when it leaves', () => {
  const rows = [row('a', 1, 103), row('b', 2, 104)];
  const entries = numberedRows(rows, { ...bounds, south: 1.5 });
  assert.equal(entries[0].number, 1);
  assert.equal(visibleSelection('b', entries), 'b');
  assert.equal(visibleSelection('a', entries), null);
  assert.equal(visibleSelection('b', []), null);
});

test('exact overlaps keep separate numbered rows and true coordinates', () => {
  const rows = [row('a', 1, 103), row('b', 1, 103), row('c', 1.000001, 103)];
  const groups = groupCoordinates(numberedRows(rows, null));
  assert.equal(groups.size, 2);
  assert.deepEqual(groups.get('1,103').map(e => e.number), [1, 2]);
  assert.equal(groups.get('1,103')[1].row, rows[1]);
});
