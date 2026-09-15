import { coordinateKey, groupCoordinates } from "./map-state.js";
import { mapConfig } from "./map-config.js";

const el = Object.fromEntries([
  "status", "retry", "filters", "meal-filter", "as-of", "today", "valid-only",
  "selected-area", "count", "deal-list", "map", "map-error", "map-error-text",
  "retry-map", "show-all",
].map(id => [id, document.getElementById(id)]));
const state = {
  rows: [], data: null, groups: new Map(), byDealId: new Map(),
  groupNodes: new Map(), collapsed: new Set(), activeKey: null, popupMode: "closed",
  selectedId: null, bounds: null, request: 0, controller: null,
  loading: false, error: false, fitted: false, meal: null, locationLabel: null,
  markers: new Map(), cards: new Map(),
};
let map = null;
let tiles = null;
let popup = null;
let popupNodes = null;
let removingPopup = false;
let groupSerial = 0;
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
  button.append(node("span", row.title));
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
  return { card, button, details, selectedLabel, row };
}

function dealCount(count) {
  return `${count} ${count === 1 ? "deal" : "deals"}`;
}

function pinIcon(number, count, active) {
  const wrapper = node("span", null, "pin-content");
  wrapper.append(node("span", String(number), "pin-number"));
  if (count > 1) wrapper.append(node("span", dealCount(count), "pin-badge"));
  return L.divIcon({ html: wrapper, className: `deal-pin${active ? " active" : ""}`,
    iconSize: null, iconAnchor: [18, 18] });
}

function focusListHeading() {
  el.count.focus({ preventScroll: true });
}

function removeNode(element, fallback = el.count) {
  if (element.contains(document.activeElement)) fallback.focus({ preventScroll: true });
  element.remove();
}

function placeNode(parent, element, index) {
  if (parent.children[index] === element) return;
  const focused = element.contains(document.activeElement) ? document.activeElement : null;
  const panel = el["deal-list"].parentElement;
  const scrollTop = panel.scrollTop;
  parent.insertBefore(element, parent.children[index] || null);
  if (focused) focused.focus({ preventScroll: true });
  panel.scrollTop = scrollTop;
}

function setExpanded(key, expanded) {
  const item = state.groupNodes.get(key);
  if (!item) return;
  if (!expanded && item.deals.contains(document.activeElement)) item.button.focus({ preventScroll: true });
  if (expanded) state.collapsed.delete(key);
  else state.collapsed.add(key);
  item.deals.hidden = !expanded;
  item.button.setAttribute("aria-expanded", String(expanded));
  item.disclosure.textContent = expanded ? "▾" : "▸";
}

function revealGroup(key) {
  setExpanded(key, true);
  const item = state.groupNodes.get(key);
  if (!item) return;
  item.heading.scrollIntoView({ block: "nearest" });
  item.button.focus({ preventScroll: true });
}

function createGroup(key) {
  const section = node("section", null, "location-group");
  section.dataset.coordinateKey = key;
  const heading = node("h3");
  const button = node("button", null, "group-disclosure");
  button.type = "button";
  button.id = `location-heading-${++groupSerial}`;
  const number = node("span", null, "number");
  number.setAttribute("aria-hidden", "true");
  const label = node("span", null, "group-label");
  const count = node("span", null, "group-count");
  const disclosure = node("span", null, "disclosure-icon");
  disclosure.setAttribute("aria-hidden", "true");
  button.append(number, label, count, disclosure);
  heading.append(button);
  const context = node("p", null, "group-context");
  const deals = node("div", null, "group-deals");
  deals.id = `location-deals-${groupSerial}`;
  deals.setAttribute("role", "region");
  deals.setAttribute("aria-labelledby", button.id);
  button.setAttribute("aria-controls", deals.id);
  button.addEventListener("click", () => setExpanded(key, state.collapsed.has(key)));
  section.append(heading, context, deals);
  return { section, heading, button, number, label, count, disclosure, context, deals };
}

// Programmatic teardown preserves intent; only a user dismissal closes it.
function closePopup() {
  if (popup && map) {
    if (popup.getElement()?.contains(document.activeElement)) {
      (state.groupNodes.get(state.activeKey)?.button || el.count).focus({ preventScroll: true });
    }
    removingPopup = true;
    map.closePopup(popup);
    removingPopup = false;
  }
  popup = null;
  popupNodes = null;
}

function updatePopup() {
  const group = state.groups.get(state.activeKey);
  if (!map || !group || state.popupMode === "closed") { closePopup(); return; }
  if (!popup) {
    const content = node("div");
    const title = node("strong");
    const description = node("p");
    const inspect = node("button", "Read offer details");
    inspect.type = "button";
    inspect.addEventListener("click", () => {
      setExpanded(state.activeKey, true);
      const card = state.cards.get(state.selectedId);
      if (!card) return;
      card.details.open = true;
      card.details.scrollIntoView({ block: "nearest" });
      card.details.querySelector("summary").focus({ preventScroll: true });
    });
    const view = node("button");
    view.type = "button";
    view.addEventListener("click", () => revealGroup(state.activeKey));
    content.append(title, description, inspect, view);
    popupNodes = { title, description, inspect, view };
    popup = L.popup({ autoPan: false, maxWidth: 300 }).setContent(content);
  }
  const row = group.rows.find(row => row.deal_id === state.selectedId);
  const dealMode = state.popupMode === "deal" && row;
  popupNodes.title.textContent = `${group.number}. ${dealMode ? row.title : group.label}`;
  popupNodes.description.textContent = dealMode ? row.location_label : dealCount(group.rows.length);
  const hideInspect = !dealMode;
  const hideView = dealMode && group.rows.length === 1;
  if ((hideInspect && document.activeElement === popupNodes.inspect)
      || (hideView && document.activeElement === popupNodes.view)) {
    (state.groupNodes.get(group.key)?.button || el.count).focus({ preventScroll: true });
  }
  popupNodes.inspect.hidden = hideInspect;
  popupNodes.view.hidden = Boolean(hideView);
  popupNodes.view.textContent = dealMode ? `View all ${group.rows.length} deals here` : "View deals";
  popup.options.maxWidth = Math.min(300, Math.max(120, map.getSize().x - 60));
  popup.options.offset = L.point(0, 7);
  popup.setLatLng([group.latitude, group.longitude]);
  if (!popup.isOpen()) popup.openOn(map);
  else {
    // Leaflet reattaches even an unchanged content node when measuring its layout.
    const focused = popup.getElement()?.contains(document.activeElement) ? document.activeElement : null;
    const scrollTop = popup.getElement()?.querySelector(".leaflet-popup-content")?.scrollTop;
    popup.update();
    if (focused) focused.focus({ preventScroll: true });
    const content = popup.getElement()?.querySelector(".leaflet-popup-content");
    if (content && scrollTop != null) content.scrollTop = scrollTop;
  }
  // Keep actions within a narrow map without moving its geographic viewport.
  const rect = popup.getElement().getBoundingClientRect();
  const mapRect = el.map.getBoundingClientRect();
  const shift = rect.left < mapRect.left + 8 ? mapRect.left + 8 - rect.left
    : rect.right > mapRect.right - 8 ? mapRect.right - 8 - rect.right : 0;
  popup.getElement().querySelector(".leaflet-popup-tip-container").style.transform = `translateX(${-shift}px)`;
  if (shift) {
    popup.options.offset = L.point(shift, 7);
    popup.setLatLng([group.latitude, group.longitude]);
  }
}

function updateSelection() {
  for (const group of state.groups.values()) {
    const active = group.key === state.activeKey;
    const containsSelected = group.rows.some(row => row.deal_id === state.selectedId);
    const item = state.groupNodes.get(group.key);
    item.section.classList.toggle("active", active);
    item.context.textContent = [active && "Active location", containsSelected && "Contains selected offer"].filter(Boolean).join(" · ");
    item.context.hidden = !item.context.textContent;
    for (const row of group.rows) {
      const selected = row.deal_id === state.selectedId;
      const card = state.cards.get(row.deal_id);
      card.card.classList.toggle("selected", selected);
      card.selectedLabel.hidden = !selected;
      card.button.setAttribute("aria-pressed", String(selected));
      card.button.setAttribute("aria-label", `Location ${group.number}: ${row.title}${selected ? ", selected" : ""}`);
    }
    const marker = state.markers.get(group.key);
    if (marker) {
      const signature = `${group.number}:${group.rows.length}:${active}`;
      if (marker._foodDealsIcon !== signature) {
        marker.setIcon(pinIcon(group.number, group.rows.length, active));
        marker._foodDealsIcon = signature;
      }
      marker.setZIndexOffset(active ? 1000 : 0);
      const label = `Location ${group.number}: ${group.label}; ${dealCount(group.rows.length)}${active ? "; active location" : ""}`;
      marker.options.title = label;
      marker.options.alt = label;
      const element = marker.getElement();
      element.title = label;
      element.setAttribute("aria-label", label);
      element.setAttribute("alt", label);
    }
  }
}

function select(id, fromMap) {
  const group = state.byDealId.get(id);
  if (!group) return;
  state.selectedId = id;
  state.activeKey = group.key;
  state.popupMode = "deal";
  setExpanded(group.key, true);
  const card = state.cards.get(id);
  card.details.open = true;
  updateSelection();
  updatePopup();
  if (fromMap) {
    card.card.scrollIntoView({ block: "nearest" });
    card.button.focus({ preventScroll: true });
  }
}

function selectLocation(key) {
  const group = state.groups.get(key);
  if (!group) return;
  if (group.rows.length === 1) { select(group.rows[0].deal_id, true); return; }
  if (state.byDealId.get(state.selectedId)?.key !== key) state.selectedId = null;
  state.activeKey = key;
  state.popupMode = "location";
  revealGroup(key);
  updateSelection();
  updatePopup();
}

function clearRows() {
  closePopup();
  if (el["deal-list"].contains(document.activeElement)
      || [...state.markers.values()].some(marker => marker.getElement() === document.activeElement)) focusListHeading();
  for (const marker of state.markers.values()) marker.remove();
  state.markers.clear();
  state.cards.clear();
  state.groupNodes.clear();
  state.groups.clear();
  state.byDealId.clear();
  el["deal-list"].replaceChildren();
}

function renderViewport() {
  if (state.loading || state.error || !state.data) return;
  if (map) {
    const b = map.getBounds();
    state.bounds = { south: b.getSouth(), north: b.getNorth(), west: b.getWest(), east: b.getEast() };
  }
  const derived = groupCoordinates(state.rows, map ? state.bounds : null);
  state.groups = derived.groups;
  state.byDealId = derived.byDealId;
  if (!state.byDealId.has(state.selectedId)) state.selectedId = null;
  if (!state.groups.has(state.activeKey)) {
    state.activeKey = null;
    state.popupMode = "closed";
  } else if (!state.selectedId && state.popupMode === "deal") state.popupMode = "location";

  for (const [key, item] of state.groupNodes) {
    if (!state.groups.has(key)) { removeNode(item.section); state.groupNodes.delete(key); }
  }
  for (const [id, item] of state.cards) {
    if (!state.byDealId.has(id)) {
      removeNode(item.card, state.groupNodes.get(coordinateKey(item.row))?.button || el.count);
      state.cards.delete(id);
    }
  }
  for (const [key, marker] of state.markers) {
    if (!state.groups.has(key)) {
      if (marker.getElement() === document.activeElement) focusListHeading();
      marker.remove();
      state.markers.delete(key);
    }
  }
  let index = 0;
  for (const group of state.groups.values()) {
    if (!state.groupNodes.has(group.key)) state.groupNodes.set(group.key, createGroup(group.key));
    const item = state.groupNodes.get(group.key);
    item.number.textContent = group.number;
    item.label.textContent = group.label;
    item.count.textContent = dealCount(group.rows.length);
    item.button.setAttribute("aria-label", `Location ${group.number}: ${group.label}, ${dealCount(group.rows.length)}`);
    placeNode(el["deal-list"], item.section, index++);
    group.rows.forEach((row, rowIndex) => {
      let card = state.cards.get(row.deal_id);
      if (card && JSON.stringify(card.row) !== JSON.stringify(row)) {
        // Refresh changed content while retaining the card's stable selection control.
        const replacement = createCard(row);
        replacement.details.open = card.details.open;
        const focused = card.card.contains(document.activeElement);
        if (focused && document.activeElement !== card.button) card.button.focus({ preventScroll: true });
        card.button.replaceChildren(...replacement.button.childNodes);
        card.card.replaceChildren(card.button, replacement.card.lastElementChild);
        if (focused) card.button.focus({ preventScroll: true });
        card = { ...replacement, card: card.card, button: card.button };
        state.cards.set(row.deal_id, card);
      }
      if (!card) { card = createCard(row); state.cards.set(row.deal_id, card); }
      placeNode(item.deals, card.card, rowIndex);
    });
    setExpanded(group.key, !state.collapsed.has(group.key));
    if (map && !state.markers.has(group.key)) {
      const marker = L.marker([group.latitude, group.longitude], {
        icon: pinIcon(group.number, group.rows.length, false), autoPanOnFocus: false,
      }).addTo(map);
      marker.on("click", () => selectLocation(group.key));
      marker.on("keydown", event => {
        if (!["Enter", " "].includes(event.originalEvent.key)) return;
        L.DomEvent.stop(event.originalEvent);
        selectLocation(group.key);
      });
      state.markers.set(group.key, marker);
    }
  }
  updateSelection();
  updatePopup();
  const count = state.byDealId.size;
  el.count.textContent = `${dealCount(count)} at ${state.groups.size} ${state.groups.size === 1 ? "location" : "locations"} ${map ? "in this view" : "in the list"}`;
  const total = state.rows.length;
  if (!total) {
    el.status.textContent = state.data.processing_summary.published_rows === 0
      ? "No mapped locations yet."
      : "No matching deals.";
  } else if (!count) {
    el.status.textContent = "No matching deals in this area.";
  } else {
    el.status.textContent = "";
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
  map.on("popupclose", event => {
    if (event.popup !== popup || removingPopup) return;
    if (popup.getElement()?.contains(document.activeElement)) {
      (state.groupNodes.get(state.activeKey)?.button || el.count).focus({ preventScroll: true });
    }
    state.popupMode = "closed";
    popup = null;
    popupNodes = null;
  });
  new ResizeObserver(() => map.invalidateSize({ pan: false })).observe(el.map);
}

async function load(initial = false) {
  const offersPanel = document.querySelector(".offers");
  const panelScroll = offersPanel.scrollTop;
  const request = ++state.request;
  state.controller?.abort();
  state.controller = new AbortController();
  state.loading = true;
  state.error = false;
  // Keep surviving list controls through refresh; temporarily remove the popup.
  closePopup();
  el.retry.hidden = true;
  el["show-all"].disabled = true;
  el["deal-list"].setAttribute("aria-busy", "true");
  el.count.textContent = "Offers in this view";
  el.status.textContent = "Loading offers…";
  const params = new URLSearchParams();
  if (!initial && el["as-of"].value) {
    params.set("as_of", el["as-of"].value);
    params.set("validity", el["valid-only"].checked ? "valid" : "all");
  }
  if (state.meal) params.set("meal", state.meal);
  try {
    const response = await fetch(`/api/deals${params.size ? `?${params}` : ""}`, { signal: state.controller.signal });
    if (!response.ok) throw new Error(response.status === 503 ? "Dataset unavailable. Prepare a valid published dataset and restart the server, then retry." : "Could not load offers. Check the server and try again.");
    const data = await response.json();
    if (request !== state.request) return;
    state.data = data;
    state.rows = data.deals;
    state.meal = data.filters.meal;
    const loadedKeys = new Set(state.rows.map(coordinateKey));
    for (const key of state.collapsed) if (!loadedKeys.has(key)) state.collapsed.delete(key);
    state.loading = false;
    el["as-of"].value = data.filters.as_of;
    el["valid-only"].checked = data.filters.validity === "valid";
    el["meal-filter"].value = data.filters.meal || "";
    for (const id of ["meal-filter", "as-of", "valid-only", "today"]) el[id].disabled = false;
    el["show-all"].disabled = !map || !state.rows.length;
    if (!state.fitted) { state.fitted = true; fitRows(); }
    renderViewport();
    offersPanel.scrollTop = panelScroll;
  } catch (error) {
    if (request !== state.request || error.name === "AbortError") return;
    state.loading = false;
    state.error = true;
    state.rows = [];
    state.selectedId = null;
    state.activeKey = null;
    state.popupMode = "closed";
    clearRows();
    el.count.textContent = "Deals unavailable";
    el.status.textContent = error instanceof TypeError ? "Could not reach the API. Check the server and try again." : error.message;
    el.retry.hidden = false;
  } finally {
    if (request === state.request) el["deal-list"].setAttribute("aria-busy", "false");
  }
}

el.filters.addEventListener("submit", event => { event.preventDefault(); if (el.filters.reportValidity()) load(); });
el["meal-filter"].addEventListener("change", () => { state.meal = el["meal-filter"].value || null; load(); });
el["as-of"].addEventListener("change", () => { if (el.filters.reportValidity()) load(); });
el["valid-only"].addEventListener("change", () => { if (el.filters.reportValidity()) load(); });
el.today.addEventListener("click", () => { el["as-of"].value = singaporeDate(); load(); });
el.retry.addEventListener("click", () => load(!el["as-of"].value));
el["show-all"].addEventListener("click", fitRows);
window.addEventListener("welcome:location", event => {
  const { latitude, longitude, meal, asOf, locationLabel } = event.detail ?? {};
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)
      || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return;
  if (!["drink", "breakfast", "lunch", "dinner", "snack"].includes(meal)
      || !/^\d{4}-\d{2}-\d{2}$/.test(asOf)) return;
  state.meal = meal;
  state.locationLabel = typeof locationLabel === "string"
    ? locationLabel.replace(/^Near\s+/i, "") : "Selected area";
  el["selected-area"].textContent = `Near ${state.locationLabel}`;
  el["selected-area"].hidden = false;
  el["as-of"].value = asOf;
  el["valid-only"].checked = true;
  state.fitted = true;
  if (map) map.setView([latitude, longitude], 14, { animate: false });
  load();
});
el["retry-map"].addEventListener("click", () => {
  if (!map) { location.reload(); return; }
  tileFailures = new Set();
  el["map-error"].hidden = true;
  tiles.redraw();
});
initMap();
load(true);
