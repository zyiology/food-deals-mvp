// Pure geographic membership and presentation identity; availability stays in the API.
export function numberedRows(rows, bounds) {
  return rows.filter(row => !bounds || (
    row.latitude >= bounds.south && row.latitude <= bounds.north
    && row.longitude >= bounds.west && row.longitude <= bounds.east
  )).sort((a, b) => Date.parse(b.posted_at) - Date.parse(a.posted_at)
    || (a.deal_id < b.deal_id ? -1 : a.deal_id > b.deal_id ? 1 : 0))
    .map((row, index) => ({ row, number: index + 1 }));
}

export function coordinateKey(row) {
  return `${row.latitude},${row.longitude}`;
}

export function groupCoordinates(entries) {
  const groups = new Map();
  for (const entry of entries) {
    const key = coordinateKey(entry.row);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(entry);
  }
  return groups;
}

export function visibleSelection(selectedId, entries) {
  return entries.some(({ row }) => row.deal_id === selectedId) ? selectedId : null;
}
