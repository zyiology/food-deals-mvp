# Geocoding and publication

Phase 3 consumes the visually reviewed demo selection and resolves only those
location rows. It does not run the LLM or change original extraction artifacts.
The current selection contains 76 rows across 59 posts. Final pin review approved
52 rows and rejected 24, with none pending. The partial snapshot published on
2026-09-12 contains 52 rows at 30 distinct coordinates and 41 source images;
46 rows have building-level precision and six have outlet-level precision.
The final offline application of decisions made zero HTTP requests. See the
[current run record](processing-workflow.md#latest-recorded-run) for extraction
limitations, provenance, and publication counts.

The original 2026-09-07 pilot selected 20 rows across 13 posts, used 17 HTTP
requests in its first batch, and published 15 approved rows at 10 coordinates
with nine images. Those counts describe the historical pilot. The reviewed
`Bugis #03-08` alias means Bugis Junction; an alias alone does not approve coordinates.

## Inspect and resolve

```bash
uv run food-deals-mvp geocode --selection data/demo-selection.json --dry-run
uv run food-deals-mvp geocode --selection data/demo-selection.json
uv run food-deals-mvp report --stage geocode
```

The selection must contain unique eligible row IDs and the exact matching demo
dataset ID. The command validates normalized sources, demo identity and original
extraction caches. A stale selection or changed source/cache fails validation.
The dry run makes no requests or writes and reports the maximum query/attempt
budget, including bounded fallbacks and retries. Shared buildings reuse queries;
separate offers, source posts, units, and schedules retain separate row IDs.

Settings default to `data/geocoding-settings.json`; override with `--settings PATH`.
A live run needs an identifying `user_agent`. The project owner's approved contact
identity is configured in `data/geocoding-settings.json`.
Example shape (replace the contact placeholder before live use):

```json
{
  "endpoint": "https://nominatim.openstreetmap.org/search",
  "user_agent": "food-deals-mvp/0.1 (contact: YOUR_CONTACT)",
  "interval": 1.1,
  "connect_timeout": 10,
  "read_timeout": 30,
  "retries": 2
}
```

**Review the [public Nominatim policy](https://operations.osmfoundation.org/policies/nominatim/)
before live use.** This application uses a sequential, cached, small one-time batch,
with at least one second between request starts, identification, and attribution.
Do not run it on multiple machines or schedule recurring jobs under this workflow.
Regular jobs require reassessing the provider and stricter limits. No browser/API
request performs geocoding. Search parameters follow the
[Nominatim Search API](https://nominatim.org/release-docs/latest/api/Search/).

## Review pins

Open `data/reports/geocode-review.html`. Each card shows original location evidence,
queries, proposed candidate addresses/coordinates, and map links. Inspect the
physical place and its association with the offer, then explicitly choose a
candidate or reject it. Nothing is automatically approved. A correct building pin
is approximate; the original unit remains in the published card.

Enter a reviewer name and download `geocoding.json`. Save it as
`data/overrides/geocoding.json`, preserving the existing alias decisions included
in the download and any existing manual approvals unless deliberately replaced.
Keep this decisions file separate from `data/demo-selection.json`, which contains
`dataset_id` and `row_ids`. Then apply the review offline:

```bash
uv run food-deals-mvp geocode --selection data/demo-selection.json --offline
uv run food-deals-mvp publish --selection data/demo-selection.json --allow-partial
```

The review page itself makes no network requests; its map links open OpenStreetMap.
A selection left at “Leave pending” preserves any existing decision from the loaded
file. To omit an already approved row, explicitly choose rejection. Manual approvals
are edited in JSON; the page preserves them unless replaced with a chosen candidate
or rejection. Reload the review page after regenerating it to avoid exporting stale
decisions. An older download cannot silently approve a refreshed response.

Overrides contain `schema_version: 1` and a `decisions` list. Each decision includes
`decision_id`, `row_ids`, `location_fingerprints`, `action`, `reviewed_at`, `reviewer`,
`reason`, and `source`. Actions are:

- `alias`: requires `alias`; changes the query only, with source-specific evidence.
- `approve`: requires `candidate_id` and `response_fingerprint` from the review output.
- `manual`: requires `coordinates` with named `latitude`/`longitude`, `precision`
  (`building` or `outlet`), and `resolved_label`; cite the source for the location.
- `reject`: omits the row without deleting its internal record.

Every listed row requires its current location fingerprint. One alias and one pin
review decision may coexist per row; conflicting decisions fail validation. A group
approval must explicitly enumerate all affected row IDs and fingerprints. A stale
candidate approval returns the row to pending and is reported as an error; select
and save a current candidate before trying publication again.

## Cache and recovery

`data/cache/geocoding/` mirrors raw query responses for inspection. Application-wide
cache/checkpoints, endpoint throttle state, and the writer lock live under
`~/.config/food-deals-mvp/geocoding/`. This shared location prevents changing
`--data-dir` from resetting request pacing or duplicating cached requests.
The writer lock covers geocoding and publication. Run one writer at a time.

```bash
uv run food-deals-mvp geocode --selection data/demo-selection.json --offline
uv run food-deals-mvp geocode --selection data/demo-selection.json --resume
uv run food-deals-mvp geocode --selection data/demo-selection.json --refresh-query QUERY_KEY
```

Offline mode only reads caches and writes local matching/review artifacts. Missing
queries remain not attempted. Ordinary reruns reuse successful and empty responses;
recorded errors and interrupted attempts need explicit `--resume`. A targeted refresh
invalidates the old response before dispatch, including its approvals. Query keys
are listed in `data/intermediate/location-resolutions.json`. Refresh, resume, and
offline modes are mutually exclusive.

Retries are bounded for transient transport errors, 429, and 5xx. `Retry-After` is
honored and preserved across runs; delays over 60 seconds stop work for later resume.
Access denial stops requests and records an endpoint denial in shared state. Resolve
the provider access issue before clearing that denial; do not repeatedly retry a
block. Malformed responses and transport failures are errors, not empty results.

Raw response fingerprints bind approvals to the exact saved coordinates. Matching
changes can reevaluate caches without HTTP calls. Changing source evidence or a
response invalidates affected reviews. Do not delete shared state merely to bypass
an error or rerun a query.

## Published snapshot

`publish` requires matching reports, current approvals, and valid source/media
provenance. It is entirely offline. `--allow-partial` acknowledges this incomplete
demo; it never bypasses approval or artifact validation. Unresolved, rejected, and
unreviewed rows remain internal. Zero approved rows cannot replace a previous
snapshot. No snapshot is created until pin review is complete for at least one row.

The output is `data/published/deals.json`, with content-addressed images in
`data/published/media/`. Images are checked against the original manifest hashes
and source roots. Missing images produce placeholders; unsafe paths and changed
content fail publication. Media is staged before atomic JSON replacement, and old
referenced files are retained. Original exports remain unchanged.

The JSON embeds source/selection provenance, reconciled processing counts,
OpenStreetMap attribution, a media allowlist, and mapped-only deals with finite
named coordinates. Internal cache contents, local paths, and contact settings are
not public fields. Historical schedules are preserved. The snapshot suggests
`validity=all` and the latest selected posting date so the API/UI can initially show
the selected sample with date status. The API implements these defaults with a
configurable 60-day posting cutoff; the [Leaflet interface](leaflet-review.md) now
consumes these results.

CLI success is status 0. Invalid inputs and provider/review errors return 1;
argument errors return 2. Ambiguous/not-found locations and pending pin reviews
alone are not CLI errors. Inspect report counts rather than treating a successful
geocode command as publication approval.

## Verification

```bash
uv run ruff check
uv run ty check
uv run pytest
```

Geocoding tests use synthetic sources, responses, clocks, and temporary shared state.
They cover selection validation, caching and bounded recovery, review invalidation,
mapped-only partial publication, source/media checks, and safe review HTML. The test
suite blocks network access; it does not consume Nominatim capacity or approve real
pins. See the [Phase 3 plan](plans/04-geocoding.md) for scope and acceptance criteria.
