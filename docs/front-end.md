# Front-end developer guide

This guide describes the implementation reviewed on **2026-09-15**. Update it
when user flows, module responsibilities, or API integration change. The
[Leaflet plan](plans/06-leaflet.md) records the original design, and the
[Leaflet review](leaflet-review.md) records historical pilot verification.
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
| Map and list | Pan/zoom filters downloaded rows to visible bounds and assigns matching numbers to cards and markers. |
| Selection and overlaps | Selecting a card or marker opens details; exact-coordinate overlaps have a numbered chooser and `+` badge. |
| Main date controls | Reference date, **Today**, and **Valid on selected date** request backend filtering. **Today** uses Singapore time. |
| Offer details | Dates, restrictions, source images, original captions, and safe source links; building-level pins are labelled approximate. |
| Layout and access | Desktop list beside map; map above list at widths up to 720px. Keyboard controls, focus styles, status messages, and a skip link are implemented. |

“Nearby” is a map-centering action followed by viewport filtering. There is no
fixed search radius, distance ranking, device-position marker, or continuous
location tracking. The list remains ordered by posting time. Different nearby
coordinates can still overlap visually; zooming and the list are the fallback.
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
map bounds, visible entries, display numbers, coordinate groups, a selected
`deal_id`, and card/marker maps keyed by ID.

On Leaflet `moveend`, `renderViewport()`:

1. Reads bounds and includes rows on their boundaries.
2. Sorts by descending `posted_at`, with ascending `deal_id` as the tie-breaker.
3. Assigns temporary numbers `1..N` from that one visible array.
4. Retains selection only if its ID remains visible; removes obsolete nodes and
   renders cards and markers from the same entries.

Keep display numbers out of identity and storage. Exact-coordinate groups use
the original latitude/longitude pair; chooser behavior does not offset stored
coordinates. Selection opens the matching card details and popup. Selection from
the map also scrolls to and focuses the card. Popup auto-pan and marker focus
auto-pan are disabled. A `ResizeObserver` updates the map size after layout changes.

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

Each deals load clears old cards and markers, aborts the previous request, and
increments a request counter. Only the latest response can commit state. A
successful refresh retains selection by ID if it remains in the new viewport
results; a request failure clears selection. Panning and selecting do not issue
deal API requests, though panning may load basemap tiles.

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

| Existing checks | Scope |
| --- | --- |
| [map-state.test.mjs](../tests/map-state.test.mjs) | Pure viewport boundaries, order/numbering, coordinate groups, and selection retention. |
| [browser_smoke.py](../tests/browser_smoke.py) | Original map/card/filter interactions and failure states using intercepted HTTP, synthetic data, stubbed tiles, and broken images. |
| [test_api.py](../tests/test_api.py) | Backend/API regression checks. |
| [test_location_search.py](../tests/test_location_search.py) | Stubbed OneMap token creation/reuse/renewal, missing configuration, search result mapping, and reverse lookup. |

**Coverage gap:** the browser script does not dismiss the startup welcome dialog
or cover its location flows. The dialog can block its map/list interactions, and
the script has no location endpoint stubs. The historical passing results in the
[Leaflet review](leaflet-review.md) predate these additions and do not establish
that the current script passes or that the new flows work in a browser.

This guide is based on source inspection; no new browser or live OneMap
verification was performed for this documentation update. Recommended follow-up
coverage is:

- Dismiss/reopen the dialog and verify keyboard focus and narrow-screen layout.
- Stub geolocation success, denied permission, and timeout/unavailable results.
- Cover autocomplete keyboard selection, single-result submission, stale
  responses, no matches, and service errors.
- Cover reverse lookup success, null, and failure while preserving coordinates.
- Submit a location before and after the first deals response; confirm zoom 14
  and that a late response cannot refit the map.
- Verify the current separation between preview meal/day choices and working
  main date filters.

Live setup verification should separately exercise a forward postal-code search
and a reverse address lookup with configured OneMap credentials. A browser pass
with the current published snapshot and a physical-phone review also remain
separate from synthetic checks. Hiding or labelling the preview controls is a
proposed UI follow-up, not an implemented feature.
