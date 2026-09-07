const status = document.getElementById("status");
const retry = document.getElementById("retry");

async function load() {
  retry.hidden = true;
  status.textContent = "Loading offers…";
  try {
    const response = await fetch("/api/deals");
    if (!response.ok) throw new Error("Offers are unavailable. Please try again later.");
    const data = await response.json();
    status.textContent = `${data.counts.matched_rows} offers at ${data.counts.distinct_locations} locations. `
      + `Reference date: ${data.filters.as_of}. Posted within ${data.filters.max_age_days} days. `
      + (data.dataset_complete ? "" : "This is a selected historical sample. ")
      + "Offers may be outside their advertised period.";
  } catch (error) {
    status.textContent = "Offers are unavailable. Please try again later.";
    retry.hidden = false;
  }
}

retry.addEventListener("click", load);
load();
