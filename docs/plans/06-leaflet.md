# Phase 5: Leaflet interface and end-to-end evaluation

Status: planned; aligned with the implemented mapped-only API. Map interactions remain to be reviewed and implemented. Depends on [FastAPI's public contract](05-fastapi.md). Preserves the requested numbered viewport markers and matching deal cards.

## Outcome and layout

Build a small HTML/CSS/JavaScript app served by FastAPI. Desktop layout has a scrollable deal list beside the map; narrow screens stack the map and list with usable minimum heights. Use local pinned Leaflet assets, retain their licence, and avoid adding a frontend framework or build system solely for this MVP.

```text
Food deals     Date [2026-08-26]  [Today]  [ ] Valid on selected date
Posted within 60 days (server setting)
Source posts: Aug 1–31, 2026      Updated: <dataset generation time>
+----------------------------+------------------------------------+
| 6 mapped deals in this view|                                    |
| 1. Offer / venue          |        Numbered markers             |
| 2. Offer / venue          |                                    |
| ...                        |             Map                    |
+----------------------------+------------------------------------+
```

Numbers above are illustrative, not measured counts. Show dataset incompleteness if partial publication was deliberately selected. Keep provider/cache details out of the ordinary browsing flow.

## State and viewport algorithm

Maintain a small explicit state object: loaded rows, request/filter state, current map bounds, selected `deal_id`, and current `deal_id → display number` mapping. Stable IDs identify deals; display numbers never enter storage or API identity.

1. Fetch `/api/deals` on initial load, then use `as_of` and `validity` on date/toggle changes. Initialize controls from the response’s effective `filters`. All returned rows are mapped; the backend evaluates availability and applies the configured posting cutoff.
2. Initialize the map over Singapore; on first successful load, optionally fit all filtered mapped points with a maximum zoom suitable for a single point. If no points exist, retain a Singapore-wide view. Do not refit on ordinary panning, selecting a card, or refreshing data for a filter change after initialization.
3. On map `moveend` (which covers completed pan/zoom changes), derive `visibleRows` by checking each mapped row against the geographic bounds. Boundary points count as visible. Keep this a pure filter over true stored coordinates.
4. Sort visible rows by descending posting timestamp, then stable `deal_id`, matching the API tie-break. Assign ephemeral integers `1..N` from that single array.
5. Render both markers and cards from the same array and number mapping. Reuse marker objects keyed by ID when practical. Clear obsolete cards/markers so old numbers cannot remain after pan, zoom, or filtering.
6. Clicking a marker selects its ID, opens details, highlights the card, and scrolls that card into view. Clicking a card selects/highlights its marker and opens the same details. A keyboard-operable card button must provide the same action.
7. Preserve selection by ID when renumbering if that row remains visible. If it leaves the viewport or filter results, clear selection and close its popup; do not select whichever row inherits its old number.
8. Avoid event loops from popup auto-pan and selection. Prefer no popup auto-pan initially, or process a resulting move through the same update path while retaining ID-based selection. A card click must not reset the viewport to all results.

Leaflet provides the map bounds/events, `LatLngBounds.contains`, markers, and `DivIcon` needed for this design; see the [Leaflet API reference](https://leafletjs.com/reference.html). Pin a supported stable version at implementation time rather than using an unversioned latest CDN URL.

At 136 source captions before expansion, filtering the downloaded rows on each completed movement is a reasonable starting point. Measure rendered row/marker counts after extraction; only add clustering, server bounding-box queries, or virtualized lists if actual performance demands them.

## Overlapping coordinates

Several offers can share a mall/building coordinate, including related posts from different channels. Do not merge or silently hide them, and do not change the stored coordinates to make markers look separate.

For the first version, retain individual numbered markers/cards and provide an overlap chooser when a coordinate has more than one visible row. Clicking the topmost marker opens a list of all numbered offers at that exact coordinate; each choice selects its matching card. Every offer also remains selectable from the sidebar. Label the marker as having multiple offers through an accessible title/badge. This makes fully stacked markers usable without a clustering dependency.

At low zoom, unrelated nearby coordinates can also visually overlap. The complete sidebar remains the fallback and zooming separates them. If this is too awkward in the pilot, prefer a small explicit spiderfy interaction as a later refinement; any display offset must leave the underlying coordinate and viewport membership unchanged.

## Cards and details

Each compact card shows its current number, grounded offer title, merchant/venue/unit, posting date, validity dates or “End date not stated”, relevant restrictions, and optional lazy-loaded image. Details show full terms/source caption and separate actions for the Telegram post and supporting information URL. Building matches show “Approximate building location”.

Render captions/model-derived strings using `textContent` or safe DOM construction. Never insert raw captions into `innerHTML` or Leaflet HTML popup strings. Permit only validated HTTP(S) external links; use `noopener noreferrer` for links opened in a new tab. These external-link settings must not suppress the basemap's page Referer header.

Show one viewport-filtered list with ephemeral map numbers. There are no mapped/unmapped tabs: unresolved rows remain internal. Keep count labels explicit: rows are offers at locations, not unique restaurants. Display the partial-sample limitation and the effective “Posted within N days” from `filters.max_age_days`; the cutoff is a server setting, not a browser control.

The date control initially uses the API's effective `filters.as_of` (August 26, 2026 for this pilot), is always visible, and has a “Today” action calculated in Singapore time. The “Valid on selected date” toggle starts unchecked (`all`) and requests the backend's `valid` or `all` mode. In `all`, cards clearly label out-of-period or unknown-validity offers. Do not duplicate date evaluation in JavaScript; use API-provided status.

## Implementation steps

1. Add static HTML/CSS with map/list layout, visible controls, status area, and a nonzero map height. Ensure viewport resize calls the map's size update after layout changes.
2. Add fetch/loading/error state handling. Cancel or ignore obsolete requests when filters change rapidly so an earlier response cannot overwrite a later date selection. Retain last good data only if it is labelled with its actual filters; otherwise clear it while loading.
3. Implement pure viewport filtering, stable sorting, and numbering helpers, then wire them to Leaflet events and card rendering.
4. Implement selection by ID, popup/detail content, overlap chooser, and keyboard/focus behavior. Use a visible focus style and selection cue beyond color alone.
5. Add date/toggle controls, the fixed cutoff label, dataset date-range display, and source/image details. Apply date/validity filters through new API requests; panning stays entirely local.
6. Add empty/error states and a useful retry action. Distinguish “No deals in this area”, “No deals match this date/filter”, “No mapped locations yet”, unavailable dataset, and unavailable map tiles. Missing images must not break cards.
7. Complete the manual data/browser evaluation and record observed usefulness, coverage, and remaining problems before deciding on a later enrichment phase.

## Basemap configuration and attribution

If using standard OSM tiles, follow the [tile usage policy](https://operations.osmfoundation.org/policies/tiles/): use `https://tile.openstreetmap.org/{z}/{x}/{y}.png`, visible OpenStreetMap attribution, normal browser caching and Referer behavior, and no bulk prefetch/offline-download features. Keep the tile URL and attribution configurable. Automated browser checks should stub tiles rather than pan/zoom against the public service.

A tile failure should leave the deal list, filters, and source links usable and display a clear map error. Do not claim full offline map support because the API is local. The tile service and geocoding service have separate policies and failure modes.

## Acceptance and proposed verification

Functional checks:

- Initial load shows Singapore, the effective historical reference date, dataset range, cutoff, and all 15 approved pilot rows before viewport filtering. A current-date view can legitimately have few or no offers from an August export.
- Pan/zoom recomputes one matching contiguous number sequence for cards and markers. Identical viewport/data yields identical ordering.
- Selecting a marker or card selects the same stable row; renumbering never transfers selection to a different offer. Leaving the viewport clears selection.
- Multi-location offers appear at their individual locations with their corresponding dates; overlapping rows remain individually accessible.
- Changing date/validity filters updates the map and list consistently; there are no unmapped results or tabs.
- Rapid filter changes cannot show a stale response. Broken images, empty data, API failure, and tile failure have distinct recoverable states.
- All actions needed to inspect a deal can be performed through keyboard-operable list controls. Narrow screens retain readable cards, usable map controls, and visible attribution.
- Raw text containing HTML-like markup renders as text; unsafe URL schemes cannot become active links.

Propose focused tests for viewport membership/order/numbering, selection transitions, overlap chooser, and stale-response handling, plus a small browser smoke check if the project adopts a browser test tool. Request test/dependency approval during implementation; a large frontend harness is not a prerequisite for this small interface. Keep a manual desktop/narrow-screen checklist for visual interactions.

End-to-end review with the supplied exports:

1. Rebuild locally from saved caches and verify the source → offer → location → map counts reconcile.
2. Start on the suggested August 26 date with all 15 rows; inspect August 9 and August 18 for any retained sample rows, then switch to the current Singapore date. The reference date controls both availability and future-post exclusion.
3. Inspect Orchard, a non-central area with mapped data, and an empty area. Check at least several displayed offers against their captions and exact venue evidence.
4. Confirm all pilot pins show building-level precision, the selected-sample limitation is visible, and omitted branches stay absent. Check that unknown expiry and the independent posting cutoff follow the API contract.
5. Decide whether the number and correctness of useful offers justify branch discovery, image extraction, or more recent exports. Record measured results; do not equate “the page runs” with the MVP's usefulness criterion.

## Review questions

1. Is the overlap chooser sufficient initially, or are individually separated pins essential? Recommendation: chooser first, then refine after seeing actual overlap density.
2. Should the initial view fit all filtered mapped deals or use a fixed Singapore extent? Recommendation: fit once on first load, preserve the user's viewport thereafter.
Confirmed API/UI scope: mapped-only results, a visible historical date selector, `validity=all` initially, and a displayed server-configured posting cutoff. No unmapped tabs or age selector are planned.
