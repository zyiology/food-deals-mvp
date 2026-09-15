# Front-end developer guide

This guide describes the implementation reviewed on **2026-09-15**. Update it
when user flows, module responsibilities, or API integration change. The
[Leaflet plan](plans/06-leaflet.md) records the original design, and the
[Leaflet review](leaflet-review.md) records historical pilot verification.
The [location-grouping plan](plans/07-location-grouping.md) records the subsequent
shared-pin design, implemented and checked on 2026-09-15.
Current dataset counts and publication history belong in the
[processing workflow](processing-workflow.md#latest-recorded-run).

## Start here

Follow the README's [setup](../README.md#setup) and
[local API instructions](../README.md#run-the-local-api), then open the app's `/`
route. FastAPI serves plain HTML, CSS, JavaScript modules, and bundled Leaflet
1.9.4 assets. There is no frontend framework, package installation, or build step.
Serve the page through the application so its absolute `/api`, `/static`, and
`/media` paths resolve correctly.

Published deals come from the server's snapshot. Live postal-code, building,
address, and reverse address lookup use OneMap through the backend. Durable
configuration uses `ONEMAP_EMAIL` and `ONEMAP_PASSWORD` in the ignored `.env`,
loaded with `uv run --env-file .env`; credentials stay on the server. Browser
device location is a separate capability and can still supply coordinates when
reverse address lookup fails. Basemap tiles also require network access.

## Features and current limits

| Area | Current behavior |
| --- | --- |
| Welcome dialog | Opens on every page load; close it to browse directly or reopen it with **Find deals**. |
| Nearby | Requests device coordinates after a user action, optionally resolves an address, and centers the map when **Show map** is submitted. |
| Location search | Suggests Singapore postal codes, buildings, and addresses; a submitted selection centers the map. |
| Meal and day choices in the dialog | Preview controls only. They do not change the deal request, main reference date, or displayed results. The UI currently does not label them as previews. |
| Map and list | Pan/zoom filters downloaded rows to visible bounds; each exact coordinate has one numbered pin and expandable list group. |
| Selection and shared locations | Shared pins reveal their group; sole-deal pins and deal cards open individual details. Count badges replace the overlap chooser. Active location and selected offer have separate cues. |
| Main date controls | Reference date, **Today**, and **Valid on selected date** request backend filtering. **Today** uses Singapore time. |
| Offer details | Dates, restrictions, source images, original captions, and safe source links; building-level pins are labelled approximate. |
| Layout and access | Desktop list beside map; map above list at widths up to 720px. Keyboard controls, focus styles, status messages, and a skip link are implemented. |

“Nearby” is a map-centering action followed by viewport filtering. There is no
fixed search radius, distance ranking, device-position marker, or continuous
location tracking. Locations are ordered by their newest deal, with newest-first deals
inside each group. Different nearby coordinates can still overlap visually;
zooming and the list are the fallback.
There is no clustering or spiderfy interaction.

The backend publishes mapped offer/location rows, so counts are not counts of
unique restaurants. The frontend displays the returned validity status and
incomplete-dataset notice. It does not establish current stock, opening hours,
holiday availability, or user eligibility. A historical dataset can legitimately
show no results for today's date.

## Startup and location flows

### Initial map view

`app.js` initializes the map at `[1.3521, 103.8198]`, zoom 11, and requests
`/api/deals` without filters. Independently, `welcome.js` opens the dialog and
focuses the selected meal. Opening the dialog alone does not request device
location. The map and deals load behind it.

The first successful deals response supplies the effective reference date and
validity controls. Unless a submitted location has already positioned the map,
the app fits the returned rows with 40px padding and maximum zoom 15. An empty
first response leaves the initial Singapore view and still consumes this one-time
fit. Subsequent date/filter loads preserve the viewport. **Show all locations**
explicitly fits all currently matching rows.

Submitting a location dispatches `welcome:location` on `window` with
`detail: { latitude, longitude }`, then closes the dialog. `app.js` validates
finite coordinates and their geographic ranges, sets `state.fitted = true`, and
centers the map at zoom 14. That flag prevents a late initial deals response from
overwriting the chosen view. Location selection does not fetch deals or change
their date filters.

### Device location

- **Nearby** clears the address selection and requests a position, displaying
  the resolved address or coordinate fallback while keeping the dialog open.
- **Show map** with an empty address requests or reuses a position, resolves its
  address, then dispatches the location event.
- The request uses `getCurrentPosition` with high accuracy disabled, a 10-second
  timeout, and a maximum cached age of 60 seconds. Concurrent calls share a
  pending request; a recent position is reused in memory.
- Coordinates are sent as JSON to `POST /api/locations/reverse`. A null response
  shows “No nearby address found”; a failed lookup shows “Address unavailable”.
  Both retain usable device coordinates.
- Denied permission and unavailable location produce separate error messages.
  Users can retry, enter an address, or close the dialog to browse manually.
- Request counters prevent late results from updating the dialog after it closes
  or the user changes the area. Device location is not continuously watched.

### Address search

Typing at least two trimmed characters schedules a search after 350ms. The input
allows up to 120 characters. Searches call `GET /api/locations?q=...`; editing,
blur, or closing the suggestions cancels the pending timer/request. A request
counter also rejects obsolete responses. A browser-memory cache uses lowercase
queries, a five-minute lifetime, and a maximum of 100 entries.

Suggestions support clicks and Arrow Up/Down plus Enter. Escape dismisses an
open suggestion list. Selecting a suggestion fills the input; **Show map**
submits it. Submission also accepts the sole result for the current query.
Otherwise it asks the user to choose a suggestion. Editing a selected address
invalidates that selection.

The dialog distinguishes no matches, unavailable search, a busy service, and
general request failures. Choices and caches survive reopening within the same
page, but there is no persistence through reloads in local storage or the URL.

## Code map

Paths below are relative to the repository root.

| File | Responsibility / where to make changes |
| --- | --- |
| [static/index.html](../src/food_deals_mvp/static/index.html) | Page structure, main filters, map/list containers, welcome form, accessibility attributes, and script/style loading. |
| [static/app.js](../src/food_deals_mvp/static/app.js) | Deals requests, map lifecycle, viewport rendering, cards, selection/popups, metadata, and recovery actions. Receives `welcome:location`. |
| [static/map-state.js](../src/food_deals_mvp/static/map-state.js) | Pure viewport membership, stable ordering/numbering, exact-coordinate grouping, and selection retention. |
| [static/map-config.js](../src/food_deals_mvp/static/map-config.js) | Initial Singapore center/zoom, tile URL, tile maximum zoom, and provider attribution. Fit-to-results and location-selection zooms are in `app.js`. |
| [static/welcome.js](../src/food_deals_mvp/static/welcome.js) | Dialog lifecycle, preview controls, device location, reverse lookup, autocomplete, and the location event. |
| [static/app.css](../src/food_deals_mvp/static/app.css) | Main layout, cards, numbered pins, popup styling, focus states, and mobile layout. |
| [static/welcome.css](../src/food_deals_mvp/static/welcome.css) | Dialog layout, input states, suggestions, and responsive meal/day choices. |
| [static/vendor/leaflet/](../src/food_deals_mvp/static/vendor/leaflet/) | Bundled Leaflet assets and licence. |
| [api.py](../src/food_deals_mvp/api.py) | HTTP routes and static/media serving. |
| [location_search.py](../src/food_deals_mvp/location_search.py) | OneMap authentication, provider requests, and normalized location results. |
| [api_models.py](../src/food_deals_mvp/api_models.py), [deal_repository.py](../src/food_deals_mvp/deal_repository.py) | Public deal response contract, snapshot loading, and server-side filtering. |

The two entry modules share the page but keep their state separate. Their
integration is the location event; meal/day values are not included in it.

## State and API boundaries

### Map/list state

`app.js` keeps loaded rows and response metadata, request/loading/error state,
map bounds, visible coordinate groups and deal-to-group lookups. Group nodes and
markers use coordinate keys; cards and the selected offer use `deal_id`. Display
numbers are derived presentation, never identity.

On Leaflet `moveend`, `renderViewport()`:

1. Includes rows inside geographic bounds, including boundary coordinates. With
   Leaflet unavailable, all returned rows are included.
2. Sorts by descending `posted_at` instant and ascending `deal_id` for ties.
3. Groups by the original latitude/longitude pair and assigns contiguous location
   numbers in first-appearance order. No rounding or proximity merge is used.
4. Reconciles surviving list/marker nodes and selection by their keys; removes
   obsolete nodes and updates headings, marker accessible names, counts and popups.

Headings use a shared trimmed `resolved_label` when all nonempty resolved labels
agree. Without resolved labels, every row must have the same nonempty trimmed
`location_label`; otherwise the heading is **Shared map location**. Original
merchant, location, unit and precision remain in each card. Groups containing any
building-precision row show an approximation note.

Groups start expanded and offer details start closed. A group disclosure changes
only expansion. Collapse preferences survive viewport changes and successful
refreshes for coordinates still present in the loaded results; removed coordinates
are pruned, and reload resets preferences. Collapsed content leaves the tab order.

The active coordinate, selected `deal_id`, and popup intent (`closed`, `location`,
`deal`) are separate state. A shared pin expands and focuses its group, retaining
only a selection already in that group, and opens a compact location popup. A
single-deal pin selects its offer, opens details, and focuses its card control.
Selecting a card expands its group and opens a deal popup without moving focus.
**Read offer details**, **View deals**, and **View all N deals here** expand their
targets before scrolling and focusing them; they retain selection and popup mode.
A collapsed heading still indicates whether it contains the selected offer.

Renumbering preserves valid identities and popup mode. User dismissal keeps the
popup closed across pan, zoom and refresh. Removing a selected deal clears only
that selection while its location survives; an open deal popup becomes a location
popup. Removing the active coordinate closes its popup. Reconciliation does not
expand collapsed groups or initiate list navigation.

Surviving controls retain focus and open details during viewport reconciliation,
including required DOM moves. Popup text and controls update in place; focus is
restored after Leaflet reattaches popup content for measurement. If focused content
must be hidden or removed, focus moves to its surviving group control or the list
heading with `preventScroll`. Changed card content on refresh retains the card's
selection control and open/closed details state; replacing focused detail content
falls back to that selection control.

Popup auto-pan and marker focus auto-pan are disabled. Popups shift horizontally
to keep their actions inside narrow maps without changing geographic bounds.
A `ResizeObserver` updates map size after layout changes. **Show all locations**
fits all loaded rows, while a submitted location takes precedence over initial fit.

### Network boundary

| Request | Trigger and response use |
| --- | --- |
| `GET /api/deals` | Initial load; response provides rows, effective filters, source range, generation time, completeness, and location attribution. |
| `GET /api/deals?as_of=YYYY-MM-DD&validity=all\|valid` | Main date/toggle changes and retries with initialized controls. Backend computes validity and applies its posting-age cutoff. |
| `GET /api/locations?q=...` | Autocomplete; consumes `results` containing labels, addresses, postal codes, and coordinates. |
| `POST /api/locations/reverse` | Device coordinates in a JSON body; returns a location object or null for the dialog's address label. |
| `/media/...` and configured tile URL | Source images from the app; basemap tiles from the configured provider. |

Date evaluation stays in the backend. The frontend formats the supplied dates and
statuses; the posting cutoff is displayed from `filters.max_age_days` and has no
browser control. See the [FastAPI contract](plans/05-fastapi.md) for deal fields
and [api.py](../src/food_deals_mvp/api.py) for the later location endpoints.

Each deals load marks the list busy, temporarily removes the popup while retaining
its intent, aborts the previous request, and increments a request counter. Existing
cards and pins remain until the latest response reconciles them, preserving
surviving controls. Only that response can commit state. A successful refresh
retains visible selection and surviving collapse preferences; a request failure
clears rows, pins, active location, selection and popup intent. Panning and
selecting do not issue deal API requests, though panning may load basemap tiles.

### Rendering and recovery

Offer text and location suggestions use DOM construction and `textContent`.
External offer links allow HTTP(S), reject embedded credentials, and open with
`noopener noreferrer`. Source images must be on the same origin under `/media/`;
they load lazily and show a text fallback on failure.

| Condition | UI behavior |
| --- | --- |
| No published rows / no date matches / no viewport matches | Separate messages; empty area suggests moving the map or showing all locations. |
| Deals API failure | Old rows/pins clear and **Try again** appears. Dataset-unavailable text explains that the server may need a prepared snapshot and restart. |
| Tile failure | Pins and list remain usable; **Retry map** redraws tiles. |
| Missing Leaflet | After dismissing the welcome dialog, all matching rows remain browsable as a list; map retry reloads the page. Location events cannot position a missing map. |
| Broken source image | The image is replaced with “Source image unavailable.” |

Tile attribution comes from `map-config.js`; published location attribution comes
from the deals response. Keep both visible. The app does not implement offline
tile downloads or basemap prefetching.

## Development and verification

The README lists [development commands](../README.md#development-checks),
including Node map-state tests and the isolated Playwright browser script.

| Checks | Scope |
| --- | --- |
| [map-state.test.mjs](../tests/map-state.test.mjs) | Boundaries, timestamp order/ties, exact coordinates, label agreement/fallback, input immutability, contiguous numbering and deal lookups. |
| [browser_smoke.py](../tests/browser_smoke.py) | Shared pins and headings, keyboard/disclosure access, selection and popup modes, dismissal, collapse retention, group movement/focus recovery, membership changes, filters/stale responses, error recovery, safe text/links, mobile layout and submitted-location precedence. |
| [test_api.py](../tests/test_api.py) | Backend/API regression checks. |
| [test_location_search.py](../tests/test_location_search.py) | Stubbed OneMap authentication, missing configuration, search result mapping and reverse lookup. |

### Location-grouping validation — 2026-09-15

The browser script now dismisses the welcome dialog on initial load and reload,
so it can exercise map/list controls. It intercepts all HTTP traffic, uses synthetic
snapshots and tiles, and makes no live OneMap or basemap requests. Checks cover
both ordinary fixtures and 105 distinct coordinates including a 120-deal building,
long labels, conflicting labels, unit/merchant retention and separate count badges.
Desktop (1440px) and narrow mobile (375px/390px) checks found no horizontal page
overflow; screenshots were inspected for readable headings and large counts.

Validation results are recorded in the [plan completion record](plans/07-location-grouping.md#implementation-and-verification).
The earlier [Leaflet review](leaflet-review.md) remains historical pilot evidence.

### Remaining limits and coverage gaps

Different-coordinate marker overlap remains outside this iteration. Grouping
preserves every returned offer/location row; it does not deduplicate offers or
assert that a shared building coordinate identifies one restaurant.

Browser checks exercise the submitted-location event and verify that a late
initial deals response cannot override it. They do not exercise real geolocation,
autocomplete or reverse-lookup UI flows. Follow-up coverage remains:

- Reopen the dialog and inspect its keyboard focus behavior.
- Stub geolocation success, denied permission and timeout/unavailable results.
- Cover autocomplete keyboard selection, single-result submission, stale
  responses, no matches and service errors.
- Cover reverse lookup success, null and failure while preserving coordinates.
- Verify the separation between preview meal/day choices and working date filters.

No live OneMap verification or current-published-snapshot browser review was done
for location grouping. Live setup verification should separately exercise a
forward postal-code search and reverse address lookup with configured credentials.
Physical-phone review remains separate from emulated mobile viewports. Hiding or
labelling preview controls is a proposed UI follow-up, not an implemented feature.
