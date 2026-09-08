// Self-contained design preview. No API requests, map changes, or saved preferences.
const dialog = document.getElementById("welcome");
const openButton = document.getElementById("open-welcome");
const form = document.getElementById("welcome-form");
const picks = document.getElementById("welcome-picks");
const ready = document.getElementById("welcome-ready");
const areaInput = document.getElementById("welcome-area");
const suggestions = document.getElementById("welcome-suggestions");
const clearArea = document.getElementById("welcome-clear-area");
const dateInput = document.getElementById("welcome-date");
const customDay = document.getElementById("welcome-custom-day");
const areas = [
  ["Bugis", "Central"], ["Orchard", "Central"], ["Tampines", "East"],
  ["Tiong Bahru", "Central"], ["Chinatown", "Central"], ["City Hall", "Central"],
  ["Little India", "Central"], ["Farrer Park", "Central"], ["Paya Lebar", "East"],
  ["Katong", "East"], ["Bedok", "East"], ["Jurong East", "West"],
  ["Clementi", "West"], ["Bishan", "Central"], ["Ang Mo Kio", "North-East"],
  ["Serangoon", "North-East"], ["Woodlands", "North"], ["Yishun", "North"],
  ["Sengkang", "North-East"], ["Punggol", "North-East"], ["Hougang", "North-East"],
];
const meals = { drink: ["A drink", "🧋"], breakfast: ["Breakfast", "🍳"], lunch: ["Lunch", "🍜"], dinner: ["Dinner", "🍛"], snack: ["A snack", "🍟"] };
let matches = [];
let activeIndex = -1;

// Calendar arithmetic uses UTC on a Singapore date, independent of the browser timezone.
const todayParts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Singapore", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
const today = ["year", "month", "day"].map(type => todayParts.find(part => part.type === type).value).join("-");
dateInput.value = today;

function selection() {
  const values = new FormData(form);
  const day = values.get("day");
  const dateLabel = dateInput.value ? new Intl.DateTimeFormat("en-SG", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${dateInput.value}T12:00:00Z`)) : "Pick a date";
  return { meal: meals[values.get("meal")], day: day === "custom" ? dateLabel : day === "tomorrow" ? "Tomorrow" : "Today", area: areaInput.value.trim() || "Anywhere in Singapore" };
}

function updateSummary() {
  const value = selection();
  document.getElementById("welcome-summary").textContent = `${value.meal[0]} · ${value.day} · ${value.area}`;
  clearArea.hidden = !areaInput.value;
}

function hideSuggestions() {
  suggestions.hidden = true;
  areaInput.setAttribute("aria-expanded", "false");
  areaInput.removeAttribute("aria-activedescendant");
  activeIndex = -1;
}

function selectArea(name) {
  areaInput.value = name;
  hideSuggestions();
  updateSummary();
  areaInput.focus();
  // focus can open the list; a selected area should leave it closed.
  hideSuggestions();
}

function showSuggestions() {
  const query = areaInput.value.trim().toLowerCase();
  matches = areas.filter(([name]) => name.toLowerCase().includes(query)).slice(0, 5);
  suggestions.replaceChildren();
  activeIndex = -1;
  areaInput.removeAttribute("aria-activedescendant");
  matches.forEach(([name, region], index) => {
    const option = document.createElement("li");
    option.id = `welcome-area-option-${index}`;
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", "false");
    const label = document.createElement("span");
    label.textContent = name;
    const detail = document.createElement("small");
    detail.textContent = region;
    option.append(label, detail);
    option.addEventListener("pointerdown", event => event.preventDefault());
    option.addEventListener("click", () => selectArea(name));
    suggestions.append(option);
  });
  if (!matches.length) {
    const empty = document.createElement("li");
    empty.className = "welcome-no-area";
    empty.setAttribute("role", "presentation");
    empty.textContent = "No suggested area. You can keep what you've typed.";
    suggestions.append(empty);
  }
  document.getElementById("welcome-area-status").textContent = `${matches.length} suggested areas`;
  suggestions.hidden = false;
  areaInput.setAttribute("aria-expanded", "true");
}

areaInput.addEventListener("input", () => { showSuggestions(); updateSummary(); });
areaInput.addEventListener("focus", showSuggestions);
areaInput.addEventListener("blur", hideSuggestions);
areaInput.addEventListener("keydown", event => {
  if (event.key === "Escape" && !suggestions.hidden) {
    event.preventDefault();
    event.stopPropagation();
    hideSuggestions();
  } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    if (suggestions.hidden) showSuggestions();
    if (!matches.length) return;
    activeIndex = event.key === "ArrowDown" ? (activeIndex + 1) % matches.length : (activeIndex <= 0 ? matches.length : activeIndex) - 1;
    [...suggestions.children].forEach((option, index) => option.setAttribute("aria-selected", String(index === activeIndex)));
    const active = suggestions.children[activeIndex];
    areaInput.setAttribute("aria-activedescendant", active.id);
    active.scrollIntoView({ block: "nearest" });
  } else if (event.key === "Enter" && !suggestions.hidden && activeIndex >= 0) {
    event.preventDefault();
    selectArea(matches[activeIndex][0]);
  }
});
clearArea.addEventListener("click", () => { areaInput.value = ""; areaInput.focus(); showSuggestions(); updateSummary(); });
document.querySelectorAll("[data-area]").forEach(button => button.addEventListener("click", () => selectArea(button.dataset.area)));
form.addEventListener("change", () => {
  const custom = new FormData(form).get("day") === "custom";
  const wasHidden = customDay.hidden;
  customDay.hidden = !custom;
  dateInput.required = custom;
  if (custom && wasHidden) dateInput.focus();
  updateSummary();
});
form.addEventListener("submit", event => {
  event.preventDefault();
  hideSuggestions();
  const value = selection();
  document.getElementById("welcome-ready-meal").textContent = value.meal[0];
  document.getElementById("welcome-ready-icon").textContent = value.meal[1];
  document.getElementById("welcome-ready-day").textContent = value.day;
  document.getElementById("welcome-ready-area").textContent = value.area;
  picks.hidden = true;
  ready.hidden = false;
  dialog.setAttribute("aria-labelledby", "welcome-ready-title");
  dialog.scrollTop = 0;
  document.getElementById("welcome-ready-title").focus({ preventScroll: true });
});

function showPicks() {
  ready.hidden = true;
  picks.hidden = false;
  dialog.setAttribute("aria-labelledby", "welcome-title");
  dialog.scrollTop = 0;
  document.getElementById("welcome-title").focus({ preventScroll: true });
}
function openWelcome() {
  if (!dialog.open) dialog.showModal();
  showPicks();
}
document.getElementById("welcome-back").addEventListener("click", showPicks);
for (const id of ["close-welcome", "welcome-skip", "welcome-explore"]) document.getElementById(id).addEventListener("click", () => dialog.close());
dialog.addEventListener("close", () => { hideSuggestions(); openButton.focus({ preventScroll: true }); });
openButton.hidden = false;
openButton.addEventListener("click", openWelcome);
updateSummary();
openWelcome();
