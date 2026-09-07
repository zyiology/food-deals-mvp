import { numberedRows, coordinateKey, groupCoordinates, visibleSelection } from "./map-state.js";
import { mapConfig } from "./map-config.js";

const el = Object.fromEntries([
  "status", "retry", "filters", "as-of", "today", "valid-only", "dataset-meta",
  "sample-note", "count", "deal-list", "map", "map-error", "map-error-text",
  "retry-map", "show-all", "location-attribution",
].map(id => [id, document.getElementById(id)]));
const state = {
  rows: [], data: null, entries: [], groups: new Map(), numbers: new Map(),
  selectedId: null, bounds: null, request: 0, controller: null,
  loading: false, error: false, fitted: false, markers: new Map(), cards: new Map(),
};
let map = null;
let tiles = null;
let popup = null;
let tileFailures = new Set();

function node(tag, text, className) {
  const result = document.createElement(tag);
  if (text != null) result.textContent = text;
  if (className) result.className = className;
  return result;
}

function externalLink(label, value) {
  try {
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return null;
    const link = node("a", label);
    link.href = url.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    return link;
  } catch { return null; }
}

function singaporeDate(value = new Date()) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Singapore", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(value);
  const part = type => parts.find(item => item.type === type).value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function dateSummary(availability) {
  const parts = [];
  if (availability.valid_dates?.length) parts.push(`Dates: ${availability.valid_dates.join(", ")}`);
  if (availability.start_date) parts.push(`From ${availability.start_date}`);
  parts.push(availability.end_date ? `Until ${availability.end_date}` : "End date not stated");
  if (availability.weekdays?.length) {
    const names = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
    parts.push(availability.weekdays.map(day => names[day]).join(", "));
  }
  return parts.join(" · ");
}

function createCard(row) {
  const card = node("article", null, "deal-card");
  card.dataset.dealId = row.deal_id;
  const button = node("button", null, "card-select");
  button.type = "button";
  const number = node("span", null, "number");
  number.setAttribute("aria-hidden", "true");
  button.append(number, node("span", row.title));
  button.addEventListener("click", () => select(row.deal_id, false));
  const body = node("div", null, "card-body");
  const selectedLabel = node("p", "✓ Selected offer", "selected-label");
  selectedLabel.hidden = true;
  body.append(selectedLabel);
  const venue = [row.merchant, row.location_label, row.unit && `Unit ${row.unit}`].filter(Boolean);
  body.append(node("p", venue.join(" · "), "venue"));
  const labels = { valid: "Valid on selected date", outside_period: "Outside advertised dates", unknown: "Validity unknown" };
  body.append(node("p", labels[row.validity_status], `validity ${row.validity_status}`));
  body.append(node("p", dateSummary(row.availability)));
  for (const restriction of row.availability.restrictions_text) body.append(node("p", restriction));
  body.append(node("p", `${row.source_name} · Posted ${singaporeDate(new Date(row.posted_at))}`, "muted"));
  if (row.precision === "building") body.append(node("p", "Approximate building location", "muted"));
  if (row.image_url) {
    const url = new URL(row.image_url, location.origin);
    if (url.origin === location.origin && url.pathname.startsWith("/media/")) {
      const img = node("img", null, "deal-image");
      img.alt = `Source image for ${row.title}`;
      img.loading = "lazy";
      img.src = url.href;
      img.addEventListener("error", () => img.replaceWith(node("p", "Source image unavailable.", "muted")), { once: true });
      body.append(img);
    }
  }
  const details = node("details", null, "details");
  details.append(node("summary", "Offer details & original caption"));
  details.append(node("p", row.description));
  if (row.terms.length) {
    const terms = node("ul", null, "terms");
    for (const term of row.terms) terms.append(node("li", term));
    details.append(terms);
  }
  details.append(node("p", "Time, holiday, stock and eligibility restrictions may still apply.", "muted"));
  const links = node("div", null, "source-links");
  const telegram = externalLink("Telegram post ↗", row.telegram_url);
  if (telegram) links.append(telegram);
  row.information_links.forEach((url, index) => {
    const link = externalLink(`More information${row.information_links.length > 1 ? ` ${index + 1}` : ""} ↗`, url);
    if (link) links.append(link);
  });
  details.append(links, node("p", row.source_caption, "caption"));
  body.append(details);
  card.append(button, body);
  return { card, button, number, details, selectedLabel };
}

function pinIcon(number, count, selected) {
  const pin = node("span", null, "pin");
  pin.append(node("span", String(number), "pin-number"));
  const wrapper = node("span");
  wrapper.append(pin);
  if (count > 1) wrapper.append(node("span", `+${count - 1}`, "pin-badge"));
  return L.divIcon({ html: wrapper, className: `deal-pin${selected ? " selected" : ""}`, iconSize: [32, 32], iconAnchor: [16, 34] });
}

function closePopup() {
  if (popup && map) map.closePopup(popup);
  popup = null;
}

function openPopup(row, content) {
  if (!map) return;
  closePopup();
  popup = L.popup({ autoPan: false, maxWidth: 300 }).setLatLng([row.latitude, row.longitude]).setContent(content).openOn(map);
}

function showChooser(group) {
  const content = node("div", null, "popup-choices");
  content.append(node("strong", `${group.length} offers at this location`));
  for (const { row, number } of group) {
    const button = node("button", `${number}. ${row.title}`);
    button.type = "button";
    button.addEventListener("click", () => select(row.deal_id, true));
    content.append(button);
  }
  openPopup(group[0].row, content);
  content.querySelector("button")?.focus({ preventScroll: true });
}

function showSelectedPopup(row) {
  const content = node("div");
  content.append(node("strong", `${state.numbers.get(row.deal_id)}. ${row.title}`), node("p", row.location_label));
  const inspect = node("button", "Read offer details");
  inspect.type = "button";
  inspect.addEventListener("click", () => {
    const card = state.cards.get(row.deal_id);
    card.details.open = true;
    card.details.querySelector("summary").focus();
  });
  content.append(inspect);
  const group = state.groups.get(coordinateKey(row));
  if (group.length > 1) {
    const other = node("button", `See all ${group.length} offers here`);
    other.type = "button";
    other.addEventListener("click", () => showChooser(group));
    content.append(node("p"), other);
  }
  openPopup(row, content);
}

function updateSelection() {
  for (const { row, number } of state.entries) {
    const selected = row.deal_id === state.selectedId;
    const card = state.cards.get(row.deal_id);
    card.card.classList.toggle("selected", selected);
    card.selectedLabel.hidden = !selected;
    card.button.setAttribute("aria-pressed", String(selected));
    card.button.setAttribute("aria-label", `${number}. ${row.title}${selected ? ", selected" : ""}`);
    const marker = state.markers.get(row.deal_id);
    if (marker) {
      marker.setIcon(pinIcon(number, state.groups.get(coordinateKey(row)).length, selected));
      marker.setZIndexOffset(selected ? 1000 : 0);
    }
  }
}

function select(id, fromMap) {
  const entry = state.entries.find(({ row }) => row.deal_id === id);
  if (!entry) return;
  state.selectedId = id;
  updateSelection();
  const card = state.cards.get(id);
  card.details.open = true;
  showSelectedPopup(entry.row);
  if (fromMap) {
    card.card.scrollIntoView({ block: "nearest" });
    card.button.focus({ preventScroll: true });
  }
}

function clearRows() {
  closePopup();
  for (const marker of state.markers.values()) marker.remove();
  state.markers.clear();
  state.cards.clear();
  state.entries = [];
  state.numbers.clear();
  el["deal-list"].replaceChildren();
}

function renderViewport() {
  if (state.loading || state.error || !state.data) return;
  if (map) {
    const b = map.getBounds();
    state.bounds = { south: b.getSouth(), north: b.getNorth(), west: b.getWest(), east: b.getEast() };
  }
  state.entries = numberedRows(state.rows, state.bounds);
  state.numbers = new Map(state.entries.map(({ row, number }) => [row.deal_id, number]));
  state.groups = groupCoordinates(state.entries);
  state.selectedId = visibleSelection(state.selectedId, state.entries);
  closePopup();
  for (const [id, item] of state.cards) {
    if (!state.numbers.has(id)) { item.card.remove(); state.cards.delete(id); }
  }
  for (const [id, marker] of state.markers) {
    if (!state.numbers.has(id)) { marker.remove(); state.markers.delete(id); }
  }
  state.entries.forEach(({ row, number }, index) => {
    if (!state.cards.has(row.deal_id)) state.cards.set(row.deal_id, createCard(row));
    const card = state.cards.get(row.deal_id);
    card.number.textContent = number;
    // Leave unchanged nodes in place to preserve keyboard focus and open details.
    if (el["deal-list"].children[index] !== card.card) el["deal-list"].insertBefore(card.card, el["deal-list"].children[index] || null);
    if (map && !state.markers.has(row.deal_id)) {
      const count = state.groups.get(coordinateKey(row)).length;
      const marker = L.marker([row.latitude, row.longitude], {
        icon: pinIcon(number, count, false),
        title: `${number}. ${row.title}${count > 1 ? `; ${count} offers at this location` : ""}`,
        alt: `${number}. ${row.title}${count > 1 ? `; ${count} offers at this location` : ""}`,
        autoPanOnFocus: false,
      }).addTo(map);
      marker.on("click", () => {
        const group = state.groups.get(coordinateKey(row));
        if (group.length > 1) showChooser(group);
        else select(row.deal_id, true);
      });
      state.markers.set(row.deal_id, marker);
    }
    const marker = state.markers.get(row.deal_id);
    if (marker) {
      const count = state.groups.get(coordinateKey(row)).length;
      marker.options.title = `${number}. ${row.title}${count > 1 ? `; ${count} offers at this location` : ""}`;
      marker.options.alt = marker.options.title;
    }
  });
  updateSelection();
  const selected = state.entries.find(({ row }) => row.deal_id === state.selectedId);
  if (selected) showSelectedPopup(selected.row);
  el.count.textContent = `${state.entries.length} offers at locations ${map ? "in this view" : "in the list"}`;
  const total = state.rows.length;
  if (!total) {
    el.status.textContent = state.data.processing_summary.published_rows === 0
      ? "No mapped locations yet."
      : "No deals match this date/filter. Try another reference date or turn off the validity filter.";
  } else if (!state.entries.length) {
    el.status.textContent = "No deals in this area. Move the map or show all locations.";
  } else {
    el.status.textContent = `${state.entries.length} of ${total} matching rows · ${state.data.filters.as_of}. Each row is one offer at one location.`;
  }
}

function fitRows() {
  if (map && state.rows.length) map.fitBounds(state.rows.map(row => [row.latitude, row.longitude]), { padding: [40, 40], maxZoom: 15, animate: false });
}

function mapError(message) {
  el["map-error-text"].textContent = message;
  el["map-error"].hidden = false;
}

function initMap() {
  if (!window.L) {
    mapError("Map assets are unavailable. You can still browse all matching offers below.");
    return;
  }
  map = L.map(el.map).setView(mapConfig.center, mapConfig.zoom);
  tiles = L.tileLayer(mapConfig.tileUrl, { attribution: mapConfig.attribution, maxZoom: mapConfig.maxZoom });
  tiles.on("tileerror", event => {
    tileFailures.add(event.tile.src);
    mapError("Map tiles are unavailable. The offer pins and list still work.");
  });
  tiles.on("tileload", event => {
    tileFailures.delete(event.tile.src);
    if (!tileFailures.size) el["map-error"].hidden = true;
  });
  tiles.addTo(map);
  map.on("moveend", renderViewport);
  new ResizeObserver(() => map.invalidateSize({ pan: false })).observe(el.map);
}

async function load(initial = false) {
  const request = ++state.request;
  state.controller?.abort();
  state.controller = new AbortController();
  state.loading = true;
  state.error = false;
  clearRows();
  el.retry.hidden = true;
  el["show-all"].disabled = true;
  el["deal-list"].setAttribute("aria-busy", "true");
  el.count.textContent = "Offers in this view";
  el.status.textContent = "Loading offers…";
  el["dataset-meta"].textContent = "";
  el["sample-note"].hidden = true;
  const params = new URLSearchParams();
  if (!initial && el["as-of"].value) {
    params.set("as_of", el["as-of"].value);
    params.set("validity", el["valid-only"].checked ? "valid" : "all");
  }
  try {
    const response = await fetch(`/api/deals${params.size ? `?${params}` : ""}`, { signal: state.controller.signal });
    if (!response.ok) throw new Error(response.status === 503 ? "Dataset unavailable. Prepare a valid published dataset and restart the server, then retry." : "Could not load offers. Check the server and try again.");
    const data = await response.json();
    if (request !== state.request) return;
    state.data = data;
    state.rows = data.deals;
    state.loading = false;
    el["as-of"].value = data.filters.as_of;
    el["valid-only"].checked = data.filters.validity === "valid";
    for (const id of ["as-of", "valid-only", "today"]) el[id].disabled = false;
    el["show-all"].disabled = !map || !state.rows.length;
    const updated = new Intl.DateTimeFormat("en-SG", { timeZone: "Asia/Singapore", dateStyle: "medium", timeStyle: "short" }).format(new Date(data.generated_at));
    el["dataset-meta"].textContent = `Posted within ${data.filters.max_age_days} days · Source posts: ${data.source_date_range.join(" – ")} · Updated: ${updated} SGT`;
    el["sample-note"].hidden = data.dataset_complete;
    el["sample-note"].textContent = "Selected historical sample — coverage is incomplete. Past dates use saved posts, including later edits.";
    el["location-attribution"].replaceChildren();
    for (const attribution of data.attribution) {
      const link = externalLink(attribution.text, attribution.url);
      if (link) el["location-attribution"].append(node("span", "Location data: "), link, node("span", ` (${attribution.licence}) `));
    }
    if (!state.fitted) { state.fitted = true; fitRows(); }
    renderViewport();
  } catch (error) {
    if (request !== state.request || error.name === "AbortError") return;
    state.loading = false;
    state.error = true;
    state.rows = [];
    state.selectedId = null;
    el.status.textContent = error instanceof TypeError ? "Could not reach the API. Check the server and try again." : error.message;
    el.retry.hidden = false;
  } finally {
    if (request === state.request) el["deal-list"].setAttribute("aria-busy", "false");
  }
}

el.filters.addEventListener("submit", event => { event.preventDefault(); if (el.filters.reportValidity()) load(); });
el["as-of"].addEventListener("change", () => { if (el.filters.reportValidity()) load(); });
el["valid-only"].addEventListener("change", () => { if (el.filters.reportValidity()) load(); });
el.today.addEventListener("click", () => { el["as-of"].value = singaporeDate(); load(); });
el.retry.addEventListener("click", () => load(!el["as-of"].value));
el["show-all"].addEventListener("click", fitRows);
el["retry-map"].addEventListener("click", () => {
  if (!map) { location.reload(); return; }
  tileFailures = new Set();
  el["map-error"].hidden = true;
  tiles.redraw();
});
initMap();
load(true);
