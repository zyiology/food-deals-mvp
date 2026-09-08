# Leaflet verification and demo review

Implementation and verification completed on **2026-09-08**. The published demo
is usable for reviewing map/list interactions. It is a selected historical sample;
this review does not establish extraction accuracy or complete restaurant coverage.
The user's assessment of usefulness remains the final review gate before expansion.

## Reproducible checks

Run from the repository root:

```bash
uv run ruff check
uv run ty check
uv run pytest
node --test tests/map-state.test.mjs
uv run --isolated --no-project --with playwright==1.62.0 python -m playwright install chromium
uv run tests/browser_smoke.py
```

The browser script declares its pinned Playwright dependency using uv script
metadata. It runs independently of pytest and the app environment. Chromium is
installed in the user cache; no browser or frontend framework is needed to run the
API. The [Playwright library guide](https://playwright.dev/python/docs/library)
describes the browser installation mechanism.

Recorded results: Ruff and ty pass; all 234 Python tests and four Node tests pass.
The standalone Chromium checks pass at desktop and 390-pixel viewport widths:

- Inclusive viewport boundaries, timestamp sorting with stable ID ties, contiguous
  numbering, exact-coordinate grouping, and selection after renumbering.
- Matching card/marker numbers, keyboard list selection, map keyboard panning and
  zoom controls, overlap chooser and focus transfer, selection clearing on exit.
- No API request for map movement; no viewport refit on selection or filter changes.
- Effective historical date, validity toggle, Singapore Today across a UTC date
  boundary, unknown validity and expiry labels, and empty area/date/dataset states.
- A deliberately late response that ignores cancellation cannot replace newer data.
- API failure clears old rows/pins and recovers through retry. Tile failure preserves
  list/selection and recovers through map retry. Missing Leaflet leaves a usable list.
- Missing-image fallback, literal HTML-like caption text, blocked unsafe links,
  safe external-link attributes, visible attribution, and no horizontal overflow.

All browser-test HTTP requests are intercepted. Synthetic API data and local
Leaflet/static assets are served through interception; tiles are stubbed and images
are deliberately unavailable. No public map service is exercised by these tests.
The existing Python suite continues to check the real API's availability evaluator.
The synthetic browser responses do not implement another date evaluator.

## Supplied-data evaluation

A separate browser pass used the running FastAPI server and real published media,
with stubbed tiles. Desktop (1440 × 1000) and narrow (390 × 844) screenshots were
inspected. Initial loading showed all 15 rows at 10 coordinates; no JavaScript
errors or horizontal overflow were observed. Number badges, source images, date
controls, details, and attribution remained readable. This verifies layout and
interaction, not live basemap availability or physical-device touch behavior.

The reference date and validity controls produced these visible counts after
showing all locations:

| Reference date | All rows | Valid on selected date |
| --- | ---: | ---: |
| 2026-08-09 | 3 | 3 |
| 2026-08-18 | 9 | 4 |
| 2026-08-26 | 15 | 6 |
| 2026-09-08 | 15 | 3 |

These are offer/location rows, not unique restaurants. All mode retains expired
and future promotions while excluding future posts and posts outside the 60-day
posting window. The September count therefore does not mean all 15 are redeemable.

Spot checks compared displayed rows and full captions in these areas:

| Area | Observation |
| --- | --- |
| Orchard Gateway | Gotcha's 1-for-1 drinks row retains August 3–9 and the named venue; it is outside period on August 26. |
| Westgate | Three Gelare rows share a building coordinate. The chooser exposes all three, with separate ice cream, coffee/mocktail, and croffle periods matching the caption. Unit 04-07 and dine-in restrictions are accessible. |
| Northpoint | The Cai-Ca row retains the branch and August 28 end date. Details expose the follow/flash-post redemption steps and stock limitation. The Bugis branch remains a separate row. |

The Westgate malformed emoji escape is still present in extracted restriction
text, as expected from the plan. The original caption remains intact. No frontend
repair or new extraction was attempted. Source links were inspected as link targets;
the external Telegram/information pages were not crawled during this pass.

## Offline pipeline reconciliation

A temporary copy of `data/` was rebuilt with `normalize`, `review-demo`,
`geocode --offline`, and `publish --allow-partial`. Existing source exports and saved
caches were used; the running server's snapshot was not replaced. Geocoding reported
zero HTTP attempts. The rebuilt 15 published rows and processing counts were exactly
equal to the original snapshot.

Counts reconcile as follows: 139 raw records → 136 text candidates; 30 posts have
saved extraction results and 106 remain unprocessed. The selection contains 20 rows
from 13 posts; 15 reviewed rows from nine posts and 14 offers are published at ten
coordinates, with five rows omitted. Every published coordinate has building-level
precision. This is partial-sample reconciliation, not full-export quality scoring.

## Remaining review and limitations

Exact-coordinate choosers work for the sample. Different nearby coordinates can
still overlap visually around central Singapore at the initial zoom; the complete
list and zoom controls are the current fallback. No clustering or spiderfy is added.
The mobile list is long because source images are retained, but images load lazily.

The sample supports inspecting offer dates and source evidence around several
areas. Only three rows pass the date evaluator on September 8, so it provides little
evidence about the usefulness of a broad, current food-deal service. Reviewing more
recent exports is a reasonable next experiment if the interface meets the user's
needs; branch discovery and image extraction are not justified by these interaction
checks alone. No enrichment or additional paid processing was performed.

User review checklist before deciding on further scope:

- Browse the normal page with live tiles and confirm map context is useful.
- Try the overlap chooser at Westgate and the central-area pins at different zooms.
- Try the page on a physical phone, including touch panning and source details.
- Assess whether the selected offers and caption/terms presentation are useful
  enough to expand the dataset; choose the next data scope separately.
