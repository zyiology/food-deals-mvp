# Location grouping for the map and deal list

Status: **Implemented and verified on 2026-09-15.**
Prepared on 2026-09-15 following discussion of the current overlapping markers.

See the [front-end guide](../front-end.md) for current behavior and the
[Leaflet plan](06-leaflet.md) for the original implementation. This plan
replaces per-deal map numbering and the exact-coordinate overlap chooser.

## Goal and scope

Give every visible map number a matching location heading in the list. Deals
sharing a coordinate appear beneath that heading and use one shared map pin.
Users should never need to find a hidden deal number underneath another pin.

The user approved implementation of this plan, then separately approved the
focused tests and documentation in steps 5–6. The design below records the agreed
scope; the [completion record](#implementation-and-verification) documents results.

In scope:

- One numbered marker and one expandable list group per exact coordinate.
- Individual deal cards inside each location group, preserving offer details.
- Consistent selection, ordering, counts, keyboard access, and refresh behavior.
- Frontend changes using the existing API and bundled Leaflet.

Deferred until a demonstrated need: visual overlap between different coordinates,
clustering, zoom-to-cluster behavior, spiderfy, and marker offsets. No proximity
threshold or coordinate rounding will be introduced for grouping.

Backend schemas, publication, offer deduplication, location search, date filtering,
and the welcome dialog's product behavior are outside this change.

## Presentation

```text
MAP                         LIST

[1] 2 deals                 1. Location X · 2 deals           ▾
                               Deal 1 title
                               Merchant / unit / validity / dates
                               Offer details & original caption

                               Deal 2 title
                               Merchant / unit / validity / dates
                               Offer details & original caption

[2]                         2. Location Y · 1 deal            ▾
                               Deal 3 title
                               Merchant / unit / validity / dates
                               Offer details & original caption
```

1. Numbers identify locations within the current viewport, not individual deals.
   Only the group heading and shared pin carry the numbered badge. Deal controls
   include their location number in accessible labels where context is needed.
2. Groups start expanded, so browsing does not require opening every location.
   Each heading has a disclosure control that collapses or expands its deal list.
   Use the same structure for single-deal groups to keep behavior consistent.
3. Reuse existing deal summaries, validity labels, restrictions, source dates,
   images, and nested offer details. Remove the per-deal number rather than
   redesigning the content in this change. Full offer details start closed.
4. A multi-deal pin has a separate badge reading, for example, `2 deals`. Remove
   the `+N` badge. A single-deal pin needs only its location number. Allow enough
   width for large numbers and counts without clipping or covering the number.
5. Show a short map note explaining that numbers match locations in the list.
   Pin accessible names include location number, label, and deal count.

The ordering tradeoff is intentional: deals at one place remain together even
when other places have posts between them chronologically.

## Group identity and labels

### Identity

Reuse `coordinateKey(row)` from `map-state.js`, based on the original latitude
and longitude pair. This matches the current exact-overlap definition. Do not
group by merchant, free-text label, unit, or rounded coordinates.

A group represents a mapped point, potentially an entire building with multiple
merchants or units. It is not a claim that its deals belong to one restaurant.
Keep every returned row, its `deal_id`, merchant, original location label, unit,
and precision. An offer published at multiple coordinates appears in each
applicable group. Do not merge or deduplicate offers during rendering.

### Heading label

Use the API's existing `resolved_label` when all nonempty resolved labels in the
group agree after trimming whitespace. This supplies a shared mapped-place label
without inventing a merchant or stripping unit text heuristically.

If there is no resolved label, use `location_label` only when every row has the
same nonempty trimmed value. If labels conflict, use the neutral heading
`Shared map location`; retain all original labels in the deal cards. Select
labels deterministically, independently of input order or the selected deal.

Keep each building-precision card's `Approximate building location` text. If any
member has building precision, also show an approximation note in the group
context. A shared coordinate must not imply outlet-level precision.

## Ordering and derived state

Replace the per-row numbering pipeline with a pure location-group derivation:

1. Filter rows to true geographic bounds, including boundary coordinates. With
   no map available, include all returned rows.
2. Sort rows by descending `posted_at` instant, then ascending `deal_id`, retaining
   the current deterministic tie-break and leaving the input array untouched.
3. Collect sorted rows by coordinate key. The first appearance of a coordinate
   determines group order; members retain the sorted order within their group.
   Thus a location's newest deal determines its position, with the existing
   deal-ID tie-break resolving equal timestamps across groups.
4. Assign contiguous location numbers `1..G` to the resulting groups.
5. Derive lookups for coordinate key to group and `deal_id` to group from that
   same result. Render list headings, pins, popups, and counts from these groups.

Suggested group shape: `{ key, number, latitude, longitude, label, rows }`.
Keep the helper API small; replace `numberedRows` and adapt `groupCoordinates`
rather than retaining two competing numbering pipelines.

State responsibilities:

| State | Identity and lifetime |
| --- | --- |
| Visible groups and lookup maps | Recomputed from current rows and bounds. |
| Marker objects and list group nodes | Keyed by coordinate key. |
| Deal card nodes and selected deal | Keyed by `deal_id`. |
| Active location | Coordinate key, separate from the selected deal. |
| Popup intent | `closed`, `location`, or `deal`, separate from selection. An open popup targets the active coordinate and, in deal mode, the selected `deal_id`. |
| Collapsed groups | Coordinate keys retained during pan/zoom within the loaded result set, pruned when a successful response removes a coordinate. |
| Display number | Derived presentation only; never identity or persisted state. |

New groups default to expanded. A group that leaves and re-enters the viewport
retains its collapse preference while it remains in the loaded results. Preserve
collapse preferences across successful filter refreshes for surviving coordinate
keys; a full page reload resets them. API failure clears active selection and
rendered content as today and resets popup intent to `closed`; it must not leave
stale pins visible.

## Interaction and selection

### Selecting a location from the map

- A pin activates its location, expands the group, and scrolls its heading into
  view. Keyboard activation follows the same path and focuses the heading's
  disclosure button with `preventScroll` after the deliberate scroll.
- For a location with several deals, do not choose a deal arbitrarily. Clear a
  previously selected deal from another group. Retain selection if it already
  belongs to this group.
- Show a compact location popup with number, label, count, and a `View deals`
  action that returns focus to the expanded list group. The list replaces the
  old numbered overlap chooser; do not maintain a duplicate chooser in the popup.
  Multi-deal pin activation sets popup mode to `location`, even when retaining
  a selected deal within that group.
- For a single-deal location, select its sole deal and open its details, retaining
  today's useful direct access. Use deal popup mode and scroll to and focus that
  deal's selection button instead of the group disclosure button.

### Selecting a deal from the list

- Select by `deal_id`, activate and expand its parent group, open that deal's
  details, and highlight the shared marker. Set popup mode to `deal` and keep
  focus on the user's control.
- The selected popup shows the location number, deal title, and original location
  label. Keep `Read offer details`; for multi-deal groups, replace the old chooser
  action with `View all N deals here`, which reveals the group's list.
- `Read offer details` first expands the parent group, then opens the deal's
  details, scrolls them into view, and focuses their summary with `preventScroll`.
  This must work after the selected group has been collapsed. Both `View deals`
  and `View all N deals here` expand the target group, scroll its heading into
  view, and focus its disclosure button with `preventScroll`. These navigation
  actions retain the selected deal and current popup mode.
- Distinguish the active location from the selected deal with explicit text and
  visual styling. Only one deal is selected at a time; selecting a group alone
  does not mark all its deals as selected.
- List disclosure toggles only expansion. It does not select an arbitrary deal,
  move the map, or open a popup. Collapsing a group retains selection, with a
  visible indication on its heading if it contains the selected deal.

### Pan, zoom, filtering, and cleanup

- Retain active location and selected deal by their keys while visible, even if
  their location number changes. Update an open popup's text to the new number
  without changing its mode. A location popup stays in location mode even if a
  selected deal survives or the group becomes a single-deal location.
- User dismissal sets popup intent to `closed` without clearing selection or the
  active location. Pan, zoom, and successful filter refreshes must not reopen it.
  Explicit pin or deal selection opens the corresponding popup again. Temporary
  popup removal during loading or rendering must not be treated as user dismissal;
  preserve intent until the latest response is reconciled.
- If the selected deal disappears, clear deal selection. Retain the active
  location if it still has visible members; change an open deal popup to location
  mode, but leave a dismissed popup closed. Show active-location context in the
  group heading independently of popup visibility.
  If the active location disappears, clear it and close its popup.
- Reconciliation must not repeatedly reopen a deliberately collapsed group or
  initiate list navigation. Expansion and scrolling happen on explicit selection
  or the popup navigation actions above; focus recovery below uses `preventScroll`.
- Reuse surviving DOM nodes during viewport changes to preserve keyboard focus
  and open offer details. Node reuse alone is insufficient: moving an existing
  group with DOM insertion can lose focus within it. Avoid unnecessary moves;
  when a move is required, preserve the focused descendant or restore focus to
  that same surviving control with `preventScroll`. Update surviving popup text
  and controls in place rather than closing and recreating the popup on every
  viewport change. If a focused control must be removed, use the focus fallback
  below. Remove obsolete groups, markers, cards, and handlers.
- Preserve existing request cancellation/stale-response protection, initial fit,
  submitted-location precedence, and `Show all locations` behavior. Keep popup
  auto-pan and marker focus auto-pan disabled.

## Counts, accessibility, and fallback states

Use copy such as `8 deals at 3 locations in this view`. Deal count means returned
offer/location rows; location count means visible coordinate groups. Do not
substitute unique restaurant, campaign, or post counts. Compute viewport counts
locally rather than using the API's whole-result totals.

The missing-map fallback uses the same groups with `in the list` wording. Existing
empty-data, no-date-match, empty-viewport, loading, API-error, tile-error, and image
fallback states remain usable, including a list with zero or one group.

Use a real button for group disclosure, with `aria-expanded`, `aria-controls`,
and a visible focus indicator. Give the group a semantic heading and associate
its deal container with it. Keep disclosure controls separate from deal controls;
do not nest interactive elements inside another button. Collapsed content must
leave the keyboard tab order. Before programmatically hiding or removing focused
content, move focus to a surviving group control or the list heading as appropriate.

Keep all deal inspection possible from the keyboard and retain selection cues
beyond color. Check the desktop scrolling panel and the map-above-list mobile
layout; location labels and count badges must wrap or size without horizontal
page overflow. Continue constructing text with safe DOM APIs and preserve source
link validation, image containment, attribution, and reduced-motion behavior.

## Implementation sequence

1. **Group derivation — `static/map-state.js`.** Implement filtering, ordering,
   label selection, group numbering, and ID lookups. Adapt selection retention
   to the new shape. Establish one authoritative model for both map and list.
2. **Grouped list — `static/app.js` and `static/app.css`.** Add group headings,
   disclosure controls, collapse-state tracking, and keyed group reconciliation.
   Reuse deal cards inside groups and remove their standalone number badges.
3. **Shared pins and selection — `static/app.js`.** Key markers by coordinate,
   render one pin per group, add explicit count badges, and replace chooser code
   with location/list navigation. Implement location and deal selection paths,
   refresh retention, explicit popup intent, in-place popup updates, and focus
   handling together. Distinguish user dismissal from temporary popup teardown.
4. **Copy and layout — `static/index.html`, `static/app.js`, `static/app.css`.**
   Update counts, map explanation, accessible names, active-location styling,
   and narrow-screen spacing. Verify marker title/alt updates reach the actual
   Leaflet DOM after renumbering, not just marker options.
5. **Verification.** Run existing relevant checks and inspect desktop/mobile
   behavior. Propose the focused test changes below and obtain approval before
   modifying tests, as required by `AGENTS.md`.
6. **Documentation follow-up.** After implementation, request approval to update
   current behavior in `docs/front-end.md` and README's browsing section, and to
   link the plan from `docs/plans/README.md`. Record actual validation and remaining
   limitations; preserve `06-leaflet.md` as historical context.

Paths under `static/` above are relative to `src/food_deals_mvp/`. No additional
frontend library, build step, or backend migration is expected.

## Proposed verification and acceptance criteria

These test changes are recommendations for the implementation stage, not changes
made by writing this plan.

### Pure state tests — `tests/map-state.test.mjs`

- Two rows at X and one at Y produce groups numbered 1 and 2, containing all three
  original rows. Nearby but unequal coordinates remain separate groups.
- Boundary membership, timestamp time zones, stable ties, shuffled input, and
  input immutability retain deterministic results.
- Group order follows its newest member; member order remains newest first.
- Shared, missing, and conflicting labels follow the heading rules, independently
  of input order. Merchant/unit differences do not split a coordinate group.
- Selection follows deal identity through renumbering; removing one member does
  not transfer selection to a different deal sharing the same location.
- Empty results, single groups, and no-map derivation produce correct counts and
  contiguous location numbers.

### Browser checks — `tests/browser_smoke.py`

At planning time, the front-end guide recorded that this script did not dismiss
the startup welcome dialog. The approved test update includes that fixture/setup
correction so map/list checks can exercise the interface. Deals and tiles are
stubbed; these grouping tests require no live OneMap calls.

- Exactly one marker and heading per coordinate, with all member cards accessible
  and no old per-deal numbers or `+N` chooser left behind.
- Pin activation expands and focuses the correct group; sole-deal pins open the
  deal directly. Deal selection highlights its shared pin and matching card.
- Collapse/expand works using keyboard controls. Collapse state survives viewport
  reconciliation; explicit map selection reopens a collapsed target.
- Select a deal, collapse its group, then activate `Read offer details` from its
  popup: the group expands, details open, and their summary is visible and focused.
  Both group-navigation popup actions expand and focus a collapsed target heading
  without changing deal selection.
- Select a deal in a multi-deal group, then activate its pin: selection survives
  while the popup switches to location mode. Pan to renumber and confirm that mode
  remains unchanged. A dismissed popup stays closed through pan and successful
  refresh; explicit selection reopens it. Removing a selected deal changes an
  open deal popup to location mode only when its active coordinate survives.
- Keep keyboard focus inside surviving deal details and, separately, on a popup
  action while viewport changes renumber groups. Confirm the same control keeps
  focus, details remain open, and reconciliation does not scroll the list. Exercise
  a required group move as well as unchanged order, and verify fallback focus when
  the focused target is removed.
- Pan and filter changes renumber both surfaces together, retain valid identities,
  and clear removed selections without stale popups, markers, or focus traps.
- Counts update when group membership changes, including transitions between one
  and several deals at a coordinate.
- Missing Leaflet, failed tiles, empty data, and failed refreshes retain expected
  grouped-list or recovery behavior. Existing safe-text/link behavior still holds.

Run the Node state suite using the repository's documented command and the
approved isolated browser runner through `uv`. If supporting Python files change,
run `uv run ruff check`, `uv run ty check`, and relevant `uv run pytest` checks.
Record actual commands and results; do not treat proposed tests as passing evidence.

### Visual review

Inspect desktop and a narrow mobile viewport with a single-deal group, several
deals in one building, long labels, conflicting labels, and large counts. Confirm
readable pin numbers, distinct count badges, usable group disclosures, preserved
merchant/unit details, visible attribution, and deliberate focus/scroll behavior.
Different-coordinate marker overlap is explicitly outside acceptance for this
iteration; revisit it only if ordinary use reveals a problem.

Implementation is complete when every visible coordinate group has one matching
numbered pin and heading, every deal remains individually inspectable, selection
survives renumbering correctly, and the approved checks establish these behaviors.


## Implementation and verification

Completed on **2026-09-15** after user approval of implementation and the separate
test/documentation follow-up. Frontend changes are confined to `map-state.js`,
`app.js`, `app.css`, and `index.html`; there are no backend/schema changes or added
frontend dependencies. The [front-end guide](../front-end.md) and README describe
current behavior. `06-leaflet.md` remains historical context.

Implemented one authoritative coordinate-group derivation, keyed list/marker
reconciliation, group disclosure and collapse preferences, separate location/deal
selection and popup intent, keyboard pin activation, safe focus fallback, and
matching location/deal counts. Popup updates preserve focused controls, and narrow-
map popup placement keeps actions within the map without auto-panning. During
refresh, existing cards/pins remain while the list is busy; only the latest
response reconciles them, and failures clear them. The popup is temporarily
removed during loading while its intent is retained.

### Checks run

| Command | Result |
| --- | --- |
| `node --test tests/map-state.test.mjs` | 6 tests passed. |
| `uv run tests/browser_smoke.py` | All 12 reported browser check groups passed; no JavaScript errors. |
| `uv run ruff check` | Passed. |
| `uv run ty check` | Passed. |
| `uv run pytest` | 240 passed; one dependency deprecation warning from Starlette's AnyIO alias. |
| `node --check src/food_deals_mvp/static/app.js` | Passed. |
| `git diff --check` | Passed. |

State coverage includes boundaries, timestamp instants/ties, original row
preservation, exact-coordinate separation, deterministic label fallback, empty
results and identity lookups. Browser coverage includes matching pins/headings,
keyboard disclosure/navigation, selected details reopened from collapsed groups,
popup dismissal and mode retention, focus during renumbering and required group
moves, selected-member removal, count transitions, stale responses, errors,
missing-map fallback, and submitted-location precedence over delayed initial fit.

Synthetic desktop/mobile inspection included long labels, conflicting labels,
105 locations and a building with 120 deals. Counts and numbers remain separate;
375px and 390px mobile checks found no horizontal page overflow. Screenshots of
the long group headings were inspected at 1440px and 375px widths. All browser
HTTP requests were intercepted; no running API, provider credentials or live tile
service was needed.

### Remaining limitations

- Different-coordinate visual overlap, clustering and spiderfy remain deferred.
- Device-location, autocomplete and reverse-lookup UI flows are outside these
  grouping checks; the location event integration is covered.
- No current published-dataset, live OneMap or physical-phone verification was
  performed for this change. Synthetic browser checks do not establish those.
