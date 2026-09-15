// Pure geographic membership and presentation identity; availability stays in the API.
export function coordinateKey(row) {
  return `${row.latitude},${row.longitude}`;
}

function groupLabel(rows) {
  const resolved = new Set(rows.map(row => row.resolved_label?.trim()).filter(Boolean));
  if (resolved.size === 1) return [...resolved][0];
  if (!resolved.size) {
    const labels = rows.map(row => row.location_label?.trim());
    if (labels[0] && labels.every(label => label === labels[0])) return labels[0];
  }
  return "Shared map location";
}

export function groupCoordinates(rows, bounds = null) {
  const sorted = rows.filter(row => !bounds || (
    row.latitude >= bounds.south && row.latitude <= bounds.north
    && row.longitude >= bounds.west && row.longitude <= bounds.east
  )).sort((a, b) => Date.parse(b.posted_at) - Date.parse(a.posted_at)
    || (a.deal_id < b.deal_id ? -1 : a.deal_id > b.deal_id ? 1 : 0));
  const groups = new Map();
  const byDealId = new Map();
  for (const row of sorted) {
    const key = coordinateKey(row);
    if (!groups.has(key)) groups.set(key, {
      key, number: groups.size + 1, latitude: row.latitude, longitude: row.longitude,
      label: "", rows: [],
    });
    const group = groups.get(key);
    group.rows.push(row);
    byDealId.set(row.deal_id, group);
  }
  for (const group of groups.values()) group.label = groupLabel(group.rows);
  return { groups, byDealId };
}
