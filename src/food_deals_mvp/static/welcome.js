// Location search is live; meal and day matching remain a preview.
const dialog = document.getElementById("welcome");
const openButton = document.getElementById("open-welcome");
const form = document.getElementById("welcome-form");
const areaInput = document.getElementById("welcome-area");
const suggestions = document.getElementById("welcome-suggestions");
const clearArea = document.getElementById("welcome-clear-area");
const dateInput = document.getElementById("welcome-date");
const customDay = document.getElementById("welcome-custom-day");
const nearby = document.getElementById("welcome-nearby");
const locationError = document.getElementById("welcome-location-error");
const locationSuccess = document.getElementById("welcome-location-success");
const areaStatus = document.getElementById("welcome-area-status");
let locationRequest = 0;
let pendingPosition = null;
let locatedPosition = null;
let selectedLocation = null;
let matches = [];
let matchesQuery = "";
let activeIndex = -1;
let searchRequest = 0;
let searchController = null;
let searchTimer = null;
const searchCache = new Map();

const todayParts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Singapore", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
dateInput.value = ["year", "month", "day"].map(type => todayParts.find(part => part.type === type).value).join("-");

function hasRecentPosition() {
  return locatedPosition && Date.now() - locatedPosition.timestamp < 60000;
}

function updateArea() {
  locationRequest += 1;
  nearby.textContent = "Nearby";
  nearby.removeAttribute("aria-busy");
  const isNearby = !areaInput.value.trim();
  nearby.setAttribute("aria-pressed", String(isNearby));
  clearArea.hidden = !areaInput.value;
  locationError.hidden = true;
  locationSuccess.hidden = !(isNearby && hasRecentPosition() && locatedPosition.addressLabel);
  locationSuccess.textContent = locatedPosition?.addressLabel || "";
  areaInput.removeAttribute("aria-describedby");
}

function getPosition() {
  if (hasRecentPosition()) return Promise.resolve(locatedPosition);
  if (!navigator.geolocation) return Promise.reject({ code: 2 });
  if (!pendingPosition) {
    pendingPosition = new Promise((resolve, reject) => {
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: false, timeout: 10000, maximumAge: 60000,
      });
    }).then(result => {
      locatedPosition = { latitude: result.coords.latitude, longitude: result.coords.longitude, timestamp: result.timestamp };
      return locatedPosition;
    }).finally(() => { pendingPosition = null; });
  }
  return pendingPosition;
}

function openMap(coordinates) {
  hideSuggestions();
  window.dispatchEvent(new CustomEvent("welcome:location", {
    detail: { latitude: coordinates.latitude, longitude: coordinates.longitude },
  }));
  dialog.close();
}

async function resolveAddress(coordinates) {
  if (coordinates.addressLabel) return coordinates.addressLabel;
  const fallback = `${coordinates.latitude.toFixed(5)}, ${coordinates.longitude.toFixed(5)}`;
  try {
    const response = await fetch("/api/locations/reverse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ latitude: coordinates.latitude, longitude: coordinates.longitude }),
    });
    if (!response.ok) throw new Error("Address lookup failed");
    const address = await response.json();
    coordinates.addressLabel = address
      ? `Near ${address.label === address.address ? address.address : `${address.label} · ${address.address}`}`
      : `${fallback} · No nearby address found`;
    return coordinates.addressLabel;
  } catch {
    // Keep the device location usable when address lookup is unavailable.
    return `${fallback} · Address unavailable`;
  }
}

async function locate(showMap = false) {
  const request = ++locationRequest;
  nearby.textContent = "Locating…";
  nearby.setAttribute("aria-busy", "true");
  locationError.hidden = true;
  locationSuccess.hidden = true;
  try {
    const coordinates = await getPosition();
    if (request !== locationRequest || !dialog.open) return;
    nearby.textContent = "Finding address…";
    const addressLabel = await resolveAddress(coordinates);
    if (request !== locationRequest || !dialog.open) return;
    locationSuccess.textContent = addressLabel;
    locationSuccess.hidden = false;
    if (showMap) openMap(coordinates);
  } catch (error) {
    if (request !== locationRequest || !dialog.open) return;
    locationError.textContent = error.code === 1
      ? "Location access is blocked. Allow it in your browser or enter an address."
      : "Location unavailable. Try again or enter an address.";
    locationError.hidden = false;
    areaInput.setAttribute("aria-describedby", "welcome-location-error");
  } finally {
    if (request === locationRequest) {
      nearby.textContent = "Nearby";
      nearby.removeAttribute("aria-busy");
    }
  }
}

function hideSuggestions() {
  clearTimeout(searchTimer);
  searchController?.abort();
  searchRequest += 1;
  suggestions.hidden = true;
  areaInput.setAttribute("aria-expanded", "false");
  areaInput.removeAttribute("aria-activedescendant");
  areaInput.removeAttribute("aria-busy");
  activeIndex = -1;
}

function selectLocation(result) {
  selectedLocation = result;
  areaInput.value = result.label !== result.address && result.postal_code
    ? `${result.label}, ${result.postal_code}` : result.label;
  hideSuggestions();
  updateArea();
  areaInput.focus();
  hideSuggestions();
}

function showSearchMessage(message) {
  suggestions.replaceChildren();
  const item = document.createElement("li");
  item.className = "welcome-no-area";
  item.setAttribute("role", "presentation");
  item.textContent = message;
  suggestions.append(item);
  suggestions.hidden = false;
  areaInput.setAttribute("aria-expanded", "true");
  areaStatus.textContent = message;
}

function renderMatches() {
  suggestions.replaceChildren();
  activeIndex = -1;
  areaInput.removeAttribute("aria-activedescendant");
  matches.forEach((result, index) => {
    const option = document.createElement("li");
    option.id = `welcome-area-option-${index}`;
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", "false");
    const label = document.createElement("span");
    label.textContent = result.label;
    option.append(label);
    if (result.address !== result.label) {
      const detail = document.createElement("small");
      detail.textContent = result.address;
      option.append(detail);
    }
    option.addEventListener("pointerdown", event => event.preventDefault());
    option.addEventListener("click", () => selectLocation(result));
    suggestions.append(option);
  });
  if (!matches.length) {
    showSearchMessage("No matches. Try a postal code or street address.");
    return;
  }
  areaStatus.textContent = `${matches.length} suggested locations`;
  suggestions.hidden = false;
  areaInput.setAttribute("aria-expanded", "true");
}

function scheduleSearch() {
  hideSuggestions();
  if (selectedLocation) return;
  const query = areaInput.value.trim();
  matches = [];
  matchesQuery = "";
  if (query.length < 2) return;
  const request = searchRequest;
  showSearchMessage("Searching…");
  areaInput.setAttribute("aria-busy", "true");
  searchTimer = setTimeout(async () => {
    const controller = new AbortController();
    searchController = controller;
    try {
      const key = query.toLowerCase();
      const cached = searchCache.get(key);
      let results;
      if (cached && Date.now() - cached.savedAt < 300000) {
        results = cached.results;
      } else {
        const response = await fetch(`/api/locations?${new URLSearchParams({ q: query })}`, { signal: controller.signal });
        if (!response.ok) {
          throw new Error(response.status === 503 ? "Location search is unavailable. Use Nearby for now."
            : response.status === 429 ? "Search is busy. Try again shortly." : "Search failed. Try again.");
        }
        results = (await response.json()).results;
        searchCache.set(key, { results, savedAt: Date.now() });
        if (searchCache.size > 100) searchCache.delete(searchCache.keys().next().value);
      }
      if (request !== searchRequest || !dialog.open) return;
      matches = results;
      matchesQuery = query;
      renderMatches();
    } catch (error) {
      if (error.name === "AbortError" || request !== searchRequest || !dialog.open) return;
      showSearchMessage(error instanceof TypeError ? "Search unavailable. Try again." : error.message);
    } finally {
      if (request === searchRequest) areaInput.removeAttribute("aria-busy");
    }
  }, 350);
}

areaInput.addEventListener("input", () => { selectedLocation = null; updateArea(); scheduleSearch(); });
areaInput.addEventListener("focus", scheduleSearch);
areaInput.addEventListener("blur", hideSuggestions);
areaInput.addEventListener("keydown", event => {
  if (event.key === "Escape" && !suggestions.hidden) {
    event.preventDefault();
    event.stopPropagation();
    hideSuggestions();
  } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    if (suggestions.hidden) { scheduleSearch(); return; }
    if (!matches.length) return;
    activeIndex = event.key === "ArrowDown" ? (activeIndex + 1) % matches.length : (activeIndex <= 0 ? matches.length : activeIndex) - 1;
    [...suggestions.children].forEach((option, index) => option.setAttribute("aria-selected", String(index === activeIndex)));
    const active = suggestions.children[activeIndex];
    areaInput.setAttribute("aria-activedescendant", active.id);
    active.scrollIntoView({ block: "nearest" });
  } else if (event.key === "Enter" && !suggestions.hidden && activeIndex >= 0) {
    event.preventDefault();
    selectLocation(matches[activeIndex]);
  }
});
clearArea.addEventListener("click", () => {
  areaInput.value = "";
  selectedLocation = null;
  areaInput.focus();
  hideSuggestions();
  updateArea();
});
nearby.addEventListener("click", () => {
  areaInput.value = "";
  selectedLocation = null;
  hideSuggestions();
  updateArea();
  locate();
});
form.addEventListener("change", () => {
  const custom = new FormData(form).get("day") === "custom";
  const wasHidden = customDay.hidden;
  customDay.hidden = !custom;
  dateInput.required = custom;
  dateInput.disabled = !custom;
  if (custom && wasHidden) dateInput.focus();
});
form.addEventListener("submit", event => {
  event.preventDefault();
  if (!areaInput.value.trim()) {
    hideSuggestions();
    locate(true);
  } else if (selectedLocation) {
    openMap(selectedLocation);
  } else if (matchesQuery === areaInput.value.trim() && matches.length === 1) {
    selectLocation(matches[0]);
    openMap(selectedLocation);
  } else {
    areaInput.focus();
    locationError.textContent = "Choose a suggested location.";
    locationError.hidden = false;
    areaInput.setAttribute("aria-describedby", "welcome-location-error");
  }
});

function openWelcome() {
  if (!dialog.open) dialog.showModal();
  dialog.scrollTop = 0;
  updateArea();
  form.querySelector('[name="meal"]:checked').focus({ preventScroll: true });
}
document.getElementById("close-welcome").addEventListener("click", () => dialog.close());
dialog.addEventListener("close", () => {
  hideSuggestions();
  updateArea();
  openButton.focus({ preventScroll: true });
});
openButton.hidden = false;
openButton.addEventListener("click", openWelcome);
openWelcome();
