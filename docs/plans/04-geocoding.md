# Phase 3: geocoding and dataset publication

Status: draft. Depends on [validated extraction](03-llm-processing.md). “Coordinate conversion” here means resolving textual places to WGS84 latitude/longitude, not reprojecting existing coordinates; the source exports contain no deal coordinates.

## Outcome

Resolve explicit Singapore venues conservatively, retain failed/ambiguous cases with reasons, and publish a validated dataset for the app. A correct building-level marker with its unit shown is acceptable; a guessed branch or neighborhood centroid is not.

Inputs: extracted offer/location rows, geocoding configuration, query cache, and reviewed location overrides. Outputs: location-resolution artifact, review report, safe media allowlist, and `data/published/deals.json`.

## Public Nominatim constraints

**Read and follow the [public Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/) before running the geocoder.** The draft's provider choice is suitable only conditionally for small one-time work; it is not a promise that any batch size is permitted.

- Use one process/thread on one machine, with at least one second between request starts, including retries and fallback queries. Prevent concurrent CLI runs against this public service.
- Identify the app with a custom User-Agent and contact information. Cache successful and no-result queries. Provide attribution in published data and the UI.
- Scripts running regularly or longer than a day are limited to four requests per minute; larger bulk tasks are discouraged. Switch providers before scheduling imports or materially expanding volume.
- Never enumerate all branches/POIs or implement autocomplete against this service. Keep the endpoint configurable so it can be changed without application-code changes.

Recheck policy at execution time. The app developer remains responsible for deliberate service use; no generic public geocoding endpoint will be exposed by this application. No live geocoding was performed for this plan.

## Query and match design

Keep original location evidence separate from a normalized search query. Normalize whitespace and simple formatting, preserve discriminating road numbers and venue names, and remove only extracted unit/floor components from the search query. Keep units in card details. Do not indiscriminately split addresses on `&`, slashes, or hyphens: “167–169 Telok Ayer Street” and adjacent units are not necessarily separate venues.

Recommended bounded query sequence:

1. The explicit street address or merchant plus named venue/branch, with Singapore context.
2. If no supported match is found, the explicitly named building/mall/address without merchant and unit details.
3. Stop at two distinct query formulations per location; retain unresolved/ambiguous results for review. Never broaden to a city/region centroid to manufacture a hit.

Use Nominatim search with `format=jsonv2`, `countrycodes=sg`, `addressdetails=1`, a small candidate limit such as five, and a consistent language setting. A Singapore viewbox may be a ranking aid but must not accidentally cut off valid islands. The hard country filter and coordinate checks matter more than adding “Singapore” to text. Query syntax and parameters come from the [Nominatim Search API](https://nominatim.org/release-docs/latest/api/Search/).

For each response, validate finite numeric coordinates, world coordinate bounds, Singapore country evidence, and compatibility with the source venue/address. Review name/address agreement and result type; an OSM importance rank is not a probability of correctness. Do not accept a first result solely because it exists or lies within Singapore.

Automatic acceptance should require an unambiguous matching named building, explicit address, or outlet plus matching branch context. Mark accepted precision as `building` or `outlet`. Multiple plausible candidates, “Bugis” without a specific supported building, neighborhood-only matches, and a merchant with multiple unknown branches remain `ambiguous`. Human review can approve a result or supply coordinates with a source and reason.

Query-cache identity and deal-location identity are different. Several offers can share the same building lookup/cache entry while retaining different merchants, units, date periods, source IDs, and deal IDs. Do not merge offers because their coordinates coincide.

## Implementation steps

1. Add a provider interface returning candidates and normalized error/status information. Implement Nominatim behind it; keep URL, identity, throttle, timeouts, and query policy in configuration.
2. Validate all input rows and select only explicit candidates. `all_outlets`, `selected_outlets`, online-only, and unspecified offers without named participants get `not_attempted` with a reason. Excluded branch names must never enter the query queue.
3. Deduplicate queries before network work. Key caches by provider/endpoint, exact normalized query, country/language filters, and response-affecting options. Record retrieval time and raw candidate evidence; version matching logic separately so cached responses can be re-evaluated locally.
4. Check reviewed overrides first. An override can select a candidate, supply an evidenced coordinate pair, normalize a proven venue alias, or mark a location unmappable. Key it to the intended candidate/evidence fingerprint and flag stale overrides when extraction changes. Do not reuse source-specific corrections indiscriminately across similarly named venues.
5. Apply single-run locking and throttle every network attempt. Add finite connect/read timeouts, bounded retries/backoff, and `Retry-After` support. Stop on access denial rather than repeatedly retrying a block. Transient failure is `error`, not `not_found`; retry unfinished errors on an explicit resume.
6. Cache no-result and ambiguous responses as well as successful lookups, so normal reruns avoid repeated requests. Provide explicit targeted refresh when source data or provider coverage changes. Never trigger refresh from a browser view.
7. Match candidates and emit a review file containing original evidence, query, candidate names/addresses, coordinates, precision proposal, status, and reason. Review every accepted pilot pin; choose thresholds using those results, rather than arbitrary confidence numbers.
8. Combine locations with the effective offer/date rows and validate the public schema. A failed candidate retains its row with null coordinates; successful locations from the same post are still usable. Count processing failures separately from valid unmapped offers.
9. Prepare safe media: copy only referenced, validated images into content-addressed published paths or build an equivalently strict ID-to-file allowlist. Preserve attribution/source links and MIME information. Missing media is a placeholder state, not a publication failure. Keep the original exports unchanged.
10. Build and validate the final snapshot and its manifest before atomic publication. Stage images first, then replace the single dataset file; keep old referenced media available for any previously loaded snapshot. Do not publish a half-written file or remove the last good snapshot on failure.

The public artifact contains all reviewed relevant rows, including unmapped rows. Uncertain/non-food/extraction-error source records remain in reports rather than masquerading as deals. Explicitly selected partial publication includes counts of failed/unprocessed sources and marks the dataset incomplete; default publication rejects unresolved processing failures, while legitimate ambiguous geography is allowed.

Proposed commands:

```bash
uv run food-deals-mvp geocode --dry-run
uv run food-deals-mvp geocode --limit 20
uv run food-deals-mvp geocode --resume
uv run food-deals-mvp publish
uv run food-deals-mvp report --stage geocode
```

The dry run reports unique uncached queries and the maximum planned fallback/attempt budget. `publish` performs no network requests. Corrections can be applied by rerunning local matching/publication with unchanged extraction caches.

## Acceptance and proposed verification

- Review representative malls, street addresses, units, ambiguous localities, and shared buildings. Use Burnt Cones/Paragon, the two More Yogurt outlets, 313 Orchard Road, and the ambiguous “Bugis” example from the exports.
- Every accepted pilot marker corresponds to supported location evidence, with building-level results labelled accordingly. Record matched/ambiguous/not-found/error counts; mapping coverage is measured, not assumed.
- “All outlets” without a list causes zero geocoding requests. Two offers at the same building reuse a query but remain separate rows.
- Offline repeat runs reproduce output using cache/overrides. A matching-rule update can re-evaluate raw cached candidates without a network call.
- Verify throttle/lock behavior, including retries; simulate 429, timeout, access denial, empty results, malformed responses, wrong-country candidates, and swapped/out-of-range coordinates.
- Verify snapshot schema, unique IDs, coordinate-pair invariants, provenance, media containment, partial-publication handling, and preservation of the last good snapshot on failure.

Propose tests for these behaviors for approval during implementation. Stub network responses and clock behavior; normal automated tests should never consume public geocoding capacity.

## Review questions

1. Is building-level precision acceptable for mall outlets? Recommendation: yes, while displaying the original unit and “Approximate building location”.
2. What contact identity should the Nominatim User-Agent use? Configure it before any live requests; do not invent or publish a contact address.
3. Is a JSON correction file sufficient for the first review workflow? Recommendation: yes; an admin UI would add avoidable scope.
4. After measuring explicit-location coverage, should branch discovery or image extraction be the next investment? Decide from the unresolved-case report.

Next: [FastAPI](05-fastapi.md).
