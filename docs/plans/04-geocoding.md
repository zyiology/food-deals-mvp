# Phase 3: geocoding and dataset publication

Current run update (2026-09-12): all 76 selected rows have final pin decisions; 52 approved rows are published at 30 coordinates and 24 were rejected. See the [current run record](../processing-workflow.md#latest-recorded-run). The 20-row scope and 15-row verification below describe the original pilot.

Status: **implemented and verified on 2026-09-07; pin review complete and the partial demo snapshot published**. The user selected 20 eligible rows across 13 posts in `data/demo-selection.json`, then approved 15 pins and rejected five rows. Publication contains 15 rows at 10 distinct coordinates with nine source images. The remaining 106 posts and exhaustive pilot scoring are deferred. See the [operation guide](../geocoding.md) for implemented commands and recovery.

## Outcome and scope

Resolve selected explicit Singapore venues to WGS84 latitude/longitude, review the proposed pins, and publish a small mapped-only snapshot for the API and website. A correct building-level marker with the original unit displayed is acceptable. Unsupported branches and neighborhood centroids are not.

The 20 selected rows are offers at locations, not 20 distinct venues. City Square Mall, Westgate, Jewel, and Waterway Point have shared lookup opportunities. Preserve separate deal rows and their effective schedules even when they share coordinates. Final mapped coverage may be below 20; unresolved rows do not require further LLM processing or block a useful demo.

No branch discovery, linked-page ingestion, image extraction, campaign deduplication, scheduled geocoding, or public search endpoint is included. Use public Nominatim for the bounded one-time batch, with the controls below. A small evidenced manual correction file can resolve individual cases; unresolved cases may simply be omitted.

## Inputs and stage contracts

Required inputs are the selection file, matching demo candidates, validated normalized posts/media and source configuration, provider configuration, and any saved query responses or reviewed decisions. Consume `data/demo/candidates.json`, not the historical `data/intermediate/candidates.json` with its older validation outcomes.

Before requests, require supported schemas, matching demo/source identities, unique selection IDs, and existing selected rows with `status=candidate` and explicit location evidence. Reject empty, duplicate, unknown, stale, or ineligible selections instead of silently intersecting them with current data. Preserve the demo's original extraction/cache provenance. A change to the selected rows requires a fresh matching selection; do not rebuild extraction as a side effect.

Proposed artifacts:

| Path | Purpose |
| --- | --- |
| `data/cache/geocoding/` | Raw successful responses, including empty results, with request identity and retrieval time |
| `data/intermediate/location-resolutions.json` | One outcome per selected row, query references, proposed/approved coordinates and precision, evidence fingerprints, and review provenance |
| `data/reports/geocode.json` | Completion marker, input/output identities, query/attempt totals, row outcomes, errors, and exclusions |
| `data/reports/geocode-review.html` | Local review table with source location evidence, candidate address/type, proposed coordinates, map links, and affected row IDs |
| `data/overrides/geocoding.json` | Versioned reviewed approvals, rejections, aliases, or evidenced manual coordinates |
| `data/published/deals.json` | Validated mapped-only rows and embedded snapshot metadata/media allowlist |
| `data/published/media/` | Referenced, validated images under content-addressed filenames |

Exact typed schemas are implementation work. Include schema/version metadata, source/demo dataset IDs, selection fingerprint, provider settings and matching version, and output identities. Validate matching artifacts before consumption; a failed or interrupted run must not masquerade as a fresh completed result.

## Public Nominatim constraints

**Read the [public Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/) before live execution.** Checked on 2026-09-07: small one-time batches may be permissible, subject to the service's restrictions. This plan proposes a deliberate application-specific use; service availability and complete coverage are not guaranteed.

- Run sequentially on one machine, with at least one second between every request start, including retries and fallbacks. Use an application-wide lock and persisted last-request time for this endpoint, independent of `--data-dir`, so separate runs cannot evade the throttle.
- Cache query results, including empty responses; reuse them across selected rows and reruns. Keep the endpoint configurable without a code change.
- Send an application-identifying User-Agent. The policy requires an identifying User-Agent or Referer; a contact email is not a blanket requirement for this small batch. Recommended configuration: `food-deals-mvp/0.1 (+<real project/contact URL>)` or `food-deals-mvp/0.1 (contact: <real email>)`. Use only a user-supplied real identity, never a fabricated contact. Offline work can proceed before this is supplied.
- Retain provider attribution/licence metadata and publish an attribution entry linking to [OpenStreetMap copyright and ODbL information](https://www.openstreetmap.org/copyright). The website must visibly credit OpenStreetMap contributors for these results, independently of its eventual basemap attribution.
- Send only the venue/address search text needed for lookup; do not send captions, images, or unrelated personal/confidential data.
- No autocomplete, exhaustive POI/branch enumeration, or generic geocoding API. Browser/API requests never call the geocoder.
- Regular scripts or scripts lasting over a day have a four-request-per-minute restriction. Reassess provider choice before recurring or expanded work; this phase does not implement scheduling.

Use finite timeouts (proposed: 10-second connect, 30-second read) and at most two retries per query for transient transport/429/5xx failures. Honor both forms of `Retry-After`; if waiting would exceed 60 seconds, checkpoint and stop for later resume, preserving the provider's not-before time across runs. Stop on access denial (401/403) or invalid configuration instead of repeatedly retrying. Record malformed responses and exhausted retries as errors, never as empty successful results.

The dry run reports unique first queries, possible distinct fallbacks, cache hits, and the maximum HTTP attempt count including retries. There are at most two query formulations per selected location and three attempts per formulation: 120 attempts is a loose ceiling for 20 rows before deduplication and cache reuse, not a target. Use a smaller reported budget when queries overlap. Do not silently refresh negative caches to improve coverage.

## Query and matching design

Keep original caption evidence separate from provider-resolved address information. Normalize whitespace and formatting; remove only identified units/floors from queries, retaining them for display. Preserve road numbers and meaningful punctuation, including address ranges such as `167–169 Telok Ayer Street`.

Use location label, venue, address, and merchant together when constructing queries. Do not assume `venue` always names a building: the selected Hillion Mall row has `venue=Kei Kaisendon` and `label=Hillion Mall`. Likewise `Gelare Westgate` contains both merchant and branch context. Avoid blindly stripping merchant words or inventing aliases; use supported components or a reviewed alias when needed.

Bounded sequence:

1. Search an explicit address or supported merchant/venue with branch context and Singapore context. A clearly named mall can be searched directly when building precision is sufficient.
2. If necessary, search the explicitly supported building/mall/address without merchant and unit details. Do not repeat an identical normalized query.
3. Stop after two distinct formulations. Do not broaden an ambiguous locality to a neighborhood pin.

Use `/search` with free-form `q`, `format=jsonv2`, `countrycodes=sg`, `addressdetails=1`, `limit=5`, and explicit `accept-language=en`. Do not combine `q` with structured address parameters. The country filter is a hard filter; a viewbox is unnecessary for this sample. These parameters follow the [Nominatim Search API](https://nominatim.org/release-docs/latest/api/Search/).

Validate finite coordinates and world bounds, returned Singapore country evidence, result type, and agreement with the source building/address/branch. Reject streets, neighborhoods, and administrative areas as precise venues. Ranking and `importance` are not correctness probabilities. Conflicting house numbers or multiple plausible buildings require review. A result named Bugis does not establish which building contains `#03-08`.

Use deterministic rules to propose an unambiguous match at `building` or `outlet` precision. All proposed demo pins still require human review before publication. Keep provider lookup outcome (`matched`, `ambiguous`, `not_found`, `error`, or `not_attempted`) separate from review state (`pending`, `approved`, or `rejected`). A machine match alone is never publication approval.

Cache identity includes provider/endpoint, exact normalized query and response-affecting parameters. Store raw response evidence and available OSM object references; matching version is separate so matching can be rerun offline. Shared query results do not imply shared approval: a review decision must identify every affected source-location association explicitly.

## Pin review and corrections

Generate the local review page from saved results, with original location evidence, merchant/unit, query, candidate name/address/type, coordinates, proposed precision, reason, and all affected selected row IDs. Include ordinary map links for visual inspection; opening the review page itself makes no geocoding requests. Escape untrusted text and allow only safe link schemes.

Use the accepted JSON correction workflow instead of an admin UI. Each decision records its ID, affected row IDs and location/evidence fingerprints, decision, reviewer/time, reason, and supporting source. Candidate approvals also bind to the cached response and chosen candidate/coordinate fingerprint. A refresh or changed location evidence makes affected approvals stale; never transfer approval to a new result silently.

A manual coordinate approval requires a source URL/reference, supported place identity, named coordinate pair, and precision. A query alias also requires evidence and does not itself approve a pin. Reject stale or invalid decisions before publication. Review a shared building once when convenient, but explicitly confirm its association with all rows covered by that decision. Offer dates and terms remain unchanged.

Selected cases worth attention include Northpoint, Bugis `#03-08`, 777 Coffeeshop at Lengkok Bahru, and The Quayside. The user clarified that Bugis `#03-08` means **Bugis Junction**; its reviewed alias is saved separately from coordinate approval. These are review candidates, not confirmed errors. Do not guess a branch if Nominatim cannot resolve one. The former draft's Burnt Cones/Paragon and 313 Orchard Road examples are not required additions to this selection.

## Publication and API handoff

Publish only selected rows with current human approval, accepted precision, and a finite non-null coordinate pair. Retain unresolved/rejected/unreviewed rows internally with explicit reasons. Publish `deal_id=row_id` to preserve selection identity; shared pins and cross-channel duplicates keep distinct deal IDs.

Each public row contains source/post/offer identity, title, description, merchant, terms, effective availability, posting date, original caption, Telegram/information links, original location label/unit/scope, resolved location label, precision, named `latitude`/`longitude`, and safe media references. Keep provider-resolved addresses distinguishable from caption facts. Do not expose local paths, caches, review internals, or provider configuration/contact identity.

The envelope contains schema/dataset IDs, generation time, `Asia/Singapore`, full source date range, selected-source date range, selection provenance, `dataset_complete=false`, processing summary, attribution, media allowlist, and deals. Embed the manifest in the same JSON so publication has one atomic completion point. Report source posts, extracted/unprocessed posts, selected rows, reviewed mapped rows, and each omitted outcome separately; row counts and post counts must not be mixed. Derive counts from artifacts rather than hardcoding today's 136/30/106 totals.

Require explicit `publish --allow-partial` for this demo. It permits publication of approved rows while clearly reporting omitted pending/failed/unresolved rows and unprocessed sources. It never bypasses stale identities, corrupt artifacts, unsafe media, invalid coordinates, or missing approvals. Without that flag, reject incomplete processing. Refuse to replace the last good snapshot with zero approved rows; keep review artifacts available for diagnosis.

Copy only referenced images with validated source containment, saved content hashes, and supported MIME signatures. Missing/unavailable media produces a placeholder; changed hashes or unsafe paths require resolution before publication. Stage content-addressed media first, validate the complete envelope, then atomically replace `deals.json`. Retain old referenced media for already loaded snapshots; cleanup is deferred. `publish` performs no network requests.

Preserve all effective schedules and the existing date evaluator; do not filter out historical offers during publication. The API/UI should initially show the selected historical sample with date status and an optional validity filter, as required by Phase 2. Derive the historical reference date from the latest selected posting date so every selected post can appear with `validity=all`. Explain that the dataset is historical and includes some later advertised dates. Phases 4–5 must align their current-date/valid-only defaults and remove unmapped filters/tabs when those plans are reviewed. No API or UI implementation is part of this phase.

## Implementation sequence and proposed CLI

1. Add typed selection, provider settings, cached response, resolution/review, and publication contracts. Validate the current selection/source chain and deterministic fingerprints. Add CLI parsing and an offline dry run.
2. Implement bounded query construction, deduplication, the provider adapter, application-wide lock/throttle, durable cache/checkpoints, retries, and explicit error resume. Preserve original extraction artifacts.
3. Implement offline matching, fingerprint-bound JSON decisions, and the review page/report. Keep automatic proposals separate from human approval.
4. Implement mapped-only publication, partial-processing accounting, safe copied media, and atomic snapshot replacement. This defines the contract needed by FastAPI.
5. Run existing checks; propose focused test additions for approval under AGENTS.md. Once approved, implement those checks using synthetic responses and a fake clock.
6. With real provider identity configured, inspect the dry-run budget, perform the small geocoding run, and present proposed pins for review. Apply reviewed decisions locally, publish the approved subset, and verify an offline rerun.

Implemented commands:

```bash
uv run food-deals-mvp geocode --selection data/demo-selection.json --dry-run
uv run food-deals-mvp geocode --selection data/demo-selection.json
uv run food-deals-mvp geocode --selection data/demo-selection.json --resume
uv run food-deals-mvp geocode --selection data/demo-selection.json --offline
uv run food-deals-mvp publish --selection data/demo-selection.json --allow-partial
uv run food-deals-mvp report --stage geocode
```

`--offline` reuses caches and reviewed decisions, with missing queries reported as not attempted. Normal reruns reuse successful/empty responses and do not retry recorded errors without `--resume`. Support refresh only with an explicit target query key, mutually exclusive with offline/resume; refresh invalidates affected prior approvals. Default review decisions path is `data/overrides/geocoding.json`, overridable by a CLI argument. Avoid a `--limit 20` row cutoff: the selection file already defines the exact scope.

## Acceptance and proposed verification

- The validated selection is the sole request/publication scope. Wrong dataset IDs, duplicate/unknown IDs, ineligible rows, and stale review decisions fail before dependent work.
- Query tests cover selected shared malls, embedded unit labels, merchant-valued venue fields, and ambiguous localities. All-outlet offers without named participants cause zero requests. Shared queries preserve distinct row/date identities.
- Network tests verify throttling across retries/runs/data directories, exclusive locking, 429 and both Retry-After forms, timeout/5xx, access denial, malformed responses, negative-cache reuse, and explicit resume/refresh.
- Matching tests reject unsupported locality pins, conflicting addresses, wrong-country and non-finite/out-of-range/swapped coordinates. Human approval remains required even for an unambiguous match.
- Publication tests verify mapped-only approved rows, named coordinates, unique IDs, provenance and reconciled counts, partial-publication rules, historical schedule preservation, media containment/hash validation, and last-good-snapshot preservation on failure.
- Every published pin is visually reviewed against supported venue evidence. No minimum mapping percentage is required; assess whether the accepted subset is useful for the demo, omitting unresolved cases.
- After cache completion, offline matching/publication reproduces semantic results without network calls; generation timestamps may differ. Run `uv run ruff check`, `uv run ty check`, and `uv run pytest` as appropriate during implementation. Automated tests never use public geocoding capacity.

## Review decisions and remaining prerequisites

Confirmed: use the reviewed 20-row selection, defer additional extraction, accept building precision with the unit and “Approximate building location” shown, use JSON decisions, and omit unresolved rows publicly.

The user approved this implementation sequence, mandatory human pin approval, explicit partial publication, and the historical API/UI handoff. Public Nominatim ran with the user-approved project author email as its contact identity. The batch required 17 HTTP requests, with no provider errors. Matching and review were subsequently rebuilt offline. The saved review approved 15 rows, including a chosen Bugis Junction candidate, and rejected five. The real settings, reviewed alias, and pin decisions are stored in local data files.

The geocoding and publisher code, 33 focused synthetic tests, and operation guide are implemented. Ruff, ty, and the full 191-test suite pass. `data/published/deals.json` contains the approved partial snapshot with historical schedules intact; the suggested reference date is 2026-08-26 with `validity=all`. Next: review [FastAPI](05-fastapi.md).
