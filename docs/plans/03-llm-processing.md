# Phase 2: LLM processing and availability

Status: **pipeline implemented and offline checks pass; draft pilot annotations await user review; no paid evaluation has run**. Phase 1 is complete and verified. Depends on [normalized source posts](02-preprocessing.md) and the confirmed caption-only extraction and date-handling scope in [the overview](README.md).

Implementation verification: Ruff and ty pass, and all 134 tests pass. The balanced pilot dry-run selects 30 candidates and marks 106 not selected, with no requests or spending. See the [operation guide](../llm-processing.md), [annotation review](../llm-pilot-review.md), and [30-post fixture](../../tests/fixtures/llm-pilot-annotations.json). Model accuracy and the Phase 2 acceptance gate remain unverified. Tests cover synthetic data and structural validation of the draft annotations; they do not certify model extraction quality.

## Outcome

Produce validated, evidence-backed offers and explicit location candidates through OpenRouter. Classify irrelevant posts and promotion kinds, preserve location-specific dates, and retain unmappable offers internally for accounting while skipping them in the public MVP. Publish no coordinates in this phase.

Inputs: normalized posts, configurable model/provider settings, a versioned prompt/schema, and optional reviewed corrections. Outputs: persistent per-request cache entries, `data/intermediate/extractions.json`, expanded offer/location candidates, and an extraction/review report.

## Extraction design

Use one semantic extraction request per text-bearing post initially. The response includes relevance, promotion kind, and zero or more offers, avoiding a second paid classification call. This extends the original “location or null” task because the supplied data also requires offer splitting, relevance filtering, and availability extraction.

The prompt must:

- Treat the caption as untrusted data, never as instructions to the processing system. Give the model no tools, browsing capability, API secrets, or ability to execute returned text.
- Supply the original posting date in Singapore time, source identity, and caption. Relative dates such as “today” refer to the original post date; an edited post with ambiguous relative wording goes to review rather than automatically using the edit date.
- Extract only information supported by the caption. Use null or an empty list for missing facts; never fill in branches, addresses, postal codes, or dates from model memory.
- Classify clear non-food advertising as `non_food`; reserve `uncertain` for cases the model cannot confidently resolve from the caption. Also mark promotion kind as `food_promotion`, `pure_listing`, `mixed_promotion`, or `uncertain`, with supporting evidence. Let the LLM make these classifications; a pure-listing or mixed-promotion label alone does not require manual review. Extract a concrete food/drink benefit with usable terms, including supported retail, affordable-meal, sample, or event offers. A pure listing without an offer produces no offers; a mixed promotion may yield a food offer if the caption supports its benefit and conditions. Food-related online-only offers may be `food` with an unmappable scope and are skipped in public results.
- Return separate offers when benefits or validity periods differ. Do not turn every menu option within one promotion into a separate offer unless its terms differ.
- Preserve location scope and excluded outlets. Never return one invented representative branch for “all outlets”. A mentioned exclusion is not a participating location.
- Associate dates and restrictions with the correct offer and location. Preserve supporting caption excerpts for extracted locations, dates, title/benefit, and terms.
- Keep weekday/time/holiday and membership/redemption restrictions visible even when not evaluated automatically. Do not claim that absence of an expiry date proves a permanent offer.

Use Pydantic-derived JSON Schema and request structured JSON, with strict mode where supported. Route only to endpoints supporting required parameters using the provider's `require_parameters` preference. Model support is endpoint-dependent; schema-conforming JSON still requires local semantic validation. These capabilities and caveats are documented in [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs).

Start with `meta/muse-spark-1.3-contributor` through OpenRouter. Evaluate this model on the review slice first; if its extraction quality is satisfactory, use it for the remaining batch without benchmarking alternatives. If the pilot exposes material quality or compatibility problems, report them and propose the next step before switching models. Configure provider routing, prompt/schema version, timeout, and output limits; verify endpoint availability and required structured-output capabilities during implementation. Do not silently change models or use an unbounded fallback chain when a request fails.

The cumulative spending cap is **US$5 for this model across the pilot and full batch**, including retries, repair attempts, and explicit refreshes. Treat $5 as a ceiling, not an assertion that processing all 136 candidates is guaranteed to fit. Reuse successful pilot caches for the full run. This revision records the model and budget decision; it does not run paid requests.

## Internal response shape

The shared contract is in [the overview](README.md). In the extraction response, each offer has common availability and `locations[]`, with each location holding an optional availability override. Validate and materialize one effective availability object per final location row. This prevents shared dates from overwriting outlet-specific periods.

Resolve availability field by field: inherit the offer-level value when the location supplies no information for that field; explicit location-specific information always takes precedence. For example, a location-specific end date replaces the shared end date while retaining a shared start date and weekday constraint unless the caption also overrides those constraints. No local override means inherit the complete shared availability.

Distinguish missing information from an explicit exception. In the extraction override, an omitted or null value means inherit, not clear. Represent a caption-supported removal of an inherited constraint explicitly, for example with a `clear_fields` list limited to date boundaries, `valid_dates`, and `weekdays`; require evidence and reject a field that is both set and cleared. Clearing materializes null in the effective availability. A local range alone does not implicitly clear shared weekdays or exact dates. If the caption explicitly replaces the entire schedule, replace or clear all affected constraints with evidence; if its meaning is ambiguous, retain `needs_review` rather than guessing.

Preserve applicable shared restrictions and evidence alongside local additions; replace a shared restriction only when the caption supports a local exception. Derive the effective `date_status` after merging: unresolved ambiguity in any applicable constraint remains `needs_review`, while missing facts alone remain unspecified. Validate date ordering, intersections of date lists/ranges/weekdays, and evidence on the materialized result. Contradictory or impossible schedules go to review and must not be silently broadened.

Illustrative expected interpretation of **GoodLobang 4623**, not an actual model result:

```text
post_id: telegram:1216422279:4623
relevance: food
offer: 1-for-1 selected yogurt shakes
location scope: explicit
locations:
  - Jewel Changi Airport, B2-234
    start_date: 2026-08-14
    end_date: 2026-08-16
  - Waterway Point, 01-63
    start_date: 2026-08-17
    end_date: 2026-08-19
```

SGFoodDeals 4904 instead produces three offers at Westgate: ice cream ending August 30, coffee/mocktails August 31–September 6, and croffles September 7–13. KiasuFoodies 5257 produces two overlapping Gotcha offers. Titles and summaries must refer to the specific benefit in their row; retain the full post as source context.

An offer with multiple explicit locations expands to one row per location; an offer with no explicit locations is retained internally with an unmapped status and reason, and produces no public row. Likewise, locations that remain unresolved after geocoding are excluded from public results. Do not build a separate unmapped-offer list or tab for this MVP; report skipped counts/reasons in processing output. A partially enumerated outlet set maps only listed participating places and retains an incomplete-scope note. Broad roundups with insufficient association evidence remain in review; never pair every mentioned place with every benefit.

## Availability contract and rules

`availability` fields:

| Field | Meaning |
| --- | --- |
| `start_date`, `end_date` | Inclusive ISO dates or null when genuinely unspecified. |
| `valid_dates` | Optional nonempty set of exact dates; null means no explicit-date constraint. |
| `weekdays` | Optional nonempty set of ISO weekdays; null means no weekday constraint. |
| `restrictions_text` | Original/supported time windows, holiday exclusions, stock limits, and other conditions. |
| `date_status` | `parsed`, `unspecified`, or `needs_review`; ambiguity is distinct from missing information. |
| `evidence` | Caption excerpts and interpretation notes supporting date fields. |

For a selected Singapore date `D`, a successfully parsed or genuinely unspecified offer is eligible when:

```text
posting_date <= D
AND (start_date is null OR start_date <= D)
AND (end_date is null OR D <= end_date)
AND (valid_dates is null OR D is in valid_dates)
AND (weekdays is null OR ISO_weekday(D) is in weekdays)
```

Thus a null end date adds no expiry, as requested; explicit weekdays still apply under the confirmed scope. An entirely unspecified period becomes eligible from its posting date. Never replace an unparsed or contradictory known date with null and thereby make an offer indefinitely eligible. `needs_review` dates remain inspectable with validity unknown and are excluded from the default date-valid view until corrected.

Interpretation rules:

- “Today only” sets both boundaries to the posting date. “Now till 14 Aug” uses the posting date as start and August 14 as end; “till 14 Aug” without a stated start may leave start null. Record this distinction in evidence.
- Month/day references inherit a year from the post context when unambiguous. Cross-year ranges require a consistent ordering; flag contradictions rather than guessing a distant year. Validate calendar dates and explicit weekday/date agreement.
- “Today & 12 Aug” becomes an explicit date set; separate-date offers do not run on the intervening dates. “22, 23, 29, 30 Aug” is another required example.
- “Every Tue & Wed, till 9 Sep” constrains weekdays and end date; “Mon–Fri” with no stated end remains recurring under the no-expiry rule.
- Explicit time-of-day cutoffs such as “28 Aug, 10PM”, overnight windows, and public-holiday exceptions stay visible in restrictions. This MVP evaluates dates, not exact redemption time or holiday calendars; the interface must use that wording.
- A complicated schedule that cannot fit the supported date constraints must remain `needs_review`, or be split into separate offers only when the source supports that split. Do not broaden it silently.

Implement this evaluator once in Python for API use. LLMs extract date facts; they do not decide today's activity. Compare dates using an injected reference date in tests, independent of machine-local timezone.

## Implementation steps and operational behavior

1. Finalize the schema and prompt using the data review's cases, including the inheritance and explicit-clearing contract above. Define field length/list size limits and deterministic ID assignment after validation. Extract a reusable normalized-dataset loader shared by extraction and the existing report command: validate the report, posts, and media manifest; require report status `success` and matching dataset IDs across all three. Missing, invalid, failed, or mismatched artifacts stop both dry-run and live extraction before work selection or any paid request; never accept a retained old posts snapshot after a failed normalization run.
2. Build the HTTP adapter with API credentials from environment variables. Add a dry-run mode reporting candidate count and cache hits/misses without sending requests. Print no authorization headers.
3. Build a local cache key from extraction-input hash, prompt/schema versions, model/provider routing configuration, and inference settings. Save raw response, validated result, usage/cost metadata if returned, and processing status. Do not cache a timeout or invalid response as a successful “no deal”.
4. Process sequentially initially, checkpointing each completed request. Use bounded retries for timeouts, rate limits, and transient server errors, honoring `Retry-After`. Authentication/configuration errors stop the run. Permit at most one schema-repair attempt per failed response before recording it for review; all attempts count toward both the request budget and cumulative US$5 spending cap.
5. Enforce explicit maximum request/attempt counts and the cumulative US$5 cap across pilot, full processing, retries, repairs, refreshes, and resumed runs. Persist spend accounting alongside checkpoints; a new run must not reset the remaining budget. Before a paid request, require enough remaining budget for a conservative maximum request cost based on verified endpoint pricing and bounded input/output tokens, or an enforceable provider-side cap covering this work. Reconcile actual reported costs after each attempt. Report unknown usage as unknown, and stop paid work if spend or the next request’s maximum cost cannot be bounded; do not rely only on checking costs after a request. If $5 is exhausted before completion, preserve results and report unfinished work without raising the cap automatically.
6. Validate response structure and meaning: evidence excerpts exist, dates are consistent, location exclusions are not included, offer/location associations are supported, and non-food responses do not leak into normal map rows. Route uncertain classification or invalid offers to review without losing the source record.
7. Apply field-level reviewed overrides after successful parsing, using source/input hashes to reject stale corrections. Each correction includes the target, reason, evidence, and review timestamp. Overrides should be able to exclude a false positive or correct an offer/date association without another paid request.
8. Expand effective offer/location rows and emit reports. Keep results for all supplied source IDs, including successful exclusions and provider failures. Regenerate artifacts from the supplied batch and matching caches so prompt/schema changes or reviewed corrections do not leave stale derived rows. Record unmapped skips separately from non-food exclusions and provider failures.

For crash-safe spending, persist an attempt ID, request/cache identity, and conservative maximum-cost reservation before dispatching each request, retry, or repair. Reconcile the reservation against actual reported cost after the response is durably recorded. A timeout or crash after dispatch is potentially billable: retain its reservation and unknown status across restarts, even when there is no cached response. Release unused funds only when accounting evidence supports doing so; never treat a missing result as a free attempt. Calculate remaining budget as $5 minus reconciled charges and outstanding reservations. If an unresolved charge cannot be bounded by its reservation, stop paid work pending reconciliation.

Use one durable budget ledger for this model's pilot and full-batch work, independent of prompt versions, cache refreshes, or output-directory changes. Acquire an exclusive writer lock covering the ledger and extraction checkpoints before paid processing; reject a second writer. Persisted state must survive interruption, and failure to write a reservation must prevent dispatch. Recovery must reconcile a saved response with its attempt ID without charging twice or silently freeing an outstanding reservation. Explicit account/endpoint compatibility and bounded-cost preflight remain prerequisites for the first paid pilot request.

Implemented commands (paid pilot follows annotation review):

```bash
uv run food-deals-mvp extract --dry-run
uv run food-deals-mvp extract --post-ids config/llm-pilot-post-ids.json --limit 30
uv run food-deals-mvp extract --resume --pilot-review config/llm-pilot-review.json
uv run food-deals-mvp report --stage extract
```

`--post-ids` selects the explicit pilot ID file described below; reject duplicates, unknown IDs, or a pilot list that does not contain exactly 10 candidates from each channel. The file has been created with the approved annotation work. `--limit` caps deterministic selection and does not by itself provide channel balance; taking the first 30 normalized posts is not the pilot. A limit or ID selection is a deliberate partial run and must be recorded as such, with other source IDs marked not selected. `--resume` retries unfinished work while preserving matching successful caches and respecting unresolved spending reservations; a separate explicit option should refresh selected successful entries.

## Acceptance and proposed verification

Start with a curated **30-post review slice: 10 posts from each channel**. Select for edge-case coverage rather than taking the earliest posts. Before paid evaluation, prepare an explicit ID file and human-reviewed expected relevance, promotion kind, offer count/benefits, locations/scope/exclusions, effective availability, restrictions, evidence, and expected review reasons. Include deliberately unmappable cases and distinguish missing facts from ambiguous facts. Review expected labels and pilot results with the user before processing the remaining 106 candidates. If the selected model performs satisfactorily, continue with matching pilot caches and the remaining portion of the same US$5 budget; no alternative-model benchmark is required.

Selection must cover clear non-food exclusions, online-only offers, all/selected outlets and exclusions, explicit and ambiguous locations, multiple offers, outlet-specific dates, separate dates, weekdays, unknown expiry, pure listings, and mixed promotions. Include GoodLobang 4623 and SGFoodDeals 4883 for outlet-specific dates, SGFoodDeals 4904 and KiasuFoodies 5257 for offer splitting, and separate-date examples such as GoodLobang 4607 and KiasuFoodies 5282. Fill the remaining channel slots from the data review after caption inspection. These are required coverage anchors, not a complete annotation fixture.

Reserve three posts per channel (nine total) as held-out evaluation examples: their captions and expected answers must not be used as prompt examples or to tune the initial prompt. Score the other 21 and the nine held-out posts separately. If prompt changes use held-out failures, label subsequent results as re-evaluation rather than an independent holdout score; report the original failures and all additional spending.

Proposed concrete acceptance criteria for user review before the pilot:

| Check | Required result before continuing to the remaining batch |
| --- | --- |
| Accounting and execution | All 30 selected source IDs have a recorded outcome; no unresolved provider/schema failures at acceptance. A valid exclusion or an expected `needs_review` outcome counts as an outcome, not a request failure. |
| Critical correctness | Zero accepted invented locations/addresses/benefits, excluded outlets treated as participants, non-food or online-only offers treated as physical candidates, or unsupported offer/location associations. Zero accepted incorrect effective date constraints, including broadened date gaps or lost weekdays. An unexpected review flag instead of a wrong accepted result is safe but still counts as an extraction error below. |
| Complete post interpretation | At least 27/30 posts, including at least 9/10 per channel and 8/9 held-out posts, match the reviewed expectations for relevance, promotion kind, offers, locations/scope, effective dates, material restrictions, and review disposition. Compare semantic content, not wording, IDs, or array order. |
| Required edge cases | Every required offer-splitting, outlet-specific-date, separate-date, weekday, and unknown-expiry example matches its expected interpretation. Mandatory examples cannot be traded against the aggregate threshold. |
| Evidence and evaluation | Every accepted location, benefit, and asserted date has supporting caption evidence. Report expected/actual offer and location counts, missing/extra items, and every classification/date/restriction error with its source ID; aggregate counts alone cannot pass the gate. |
| Operational behavior | Offline checks pass for budget reservations/recovery, concurrent-writer rejection, source-artifact validation, cache reuse/invalidation, retries, and availability evaluation. No request exceeds the cumulative spending/attempt controls. |
| Human review | The user reviews the full pilot report, including any errors permitted by the aggregate threshold, and agrees to continue. Manual corrections may prepare usable results but must not conceal errors in the model's scored output. |

A failed gate pauses the remaining batch. Report the failures and propose prompt/schema fixes or the next evaluation step within the original budget; do not silently switch models or increase the cap. Pure-listing and mixed-promotion labels alone still do not create a mandatory per-post review gate in normal processing.

- All accepted locations have source evidence; no all-outlet expansion uses model memory.
- More Yogurt's dates remain outlet-specific; Geláre's three benefits have separate periods.
- A&W food offers remain distinct from hair-care ads and delivery-only vouchers. The LLM marks pure listings and mixed promotions with evidence; uncertain or invalid results remain reviewable.
- Unmapped food offers remain accounted for internally and produce no public rows; supported locations from partially mappable offers remain usable.
- Pilot and resumed batch work share the US$5 cap. Verify stopping before an unaffordable or unbounded request, including retries/repairs, while preserving completed work.
- Simulate interruption before dispatch, after dispatch but before response persistence, and after response persistence but before ledger reconciliation. Verify that reservations survive, charges are not counted twice, concurrent writers are rejected, and output-directory or prompt changes cannot reset the cap.
- Reject missing/failed normalization reports and mismatched dataset IDs before any model call, including when an older valid posts file remains present.
- Test current versus historical dates, future-post exclusion, inclusive end dates, null boundaries, explicit date gaps, weekdays, and unresolved dates.
- Test field-level inheritance, local precedence, evidence-backed clearing, preservation of unaffected restrictions, and contradictions after merging location availability.
- Re-running unchanged inputs uses cached validated results. Changing prompt/model/text/date context invalidates relevant cache entries; changing reactions does not.
- Simulate invalid JSON, unsupported schema, response truncation, timeout, 429, and authentication failure without real paid calls.
- Compare human-labelled expected offers/locations/dates against output and report counts and specific errors. Do not equate valid JSON with factual accuracy.

The user approved the offline tests, annotation fixtures and documentation additions. The corresponding tests and draft fixture have been added; annotation content still needs review before paid evaluation. Live model runs are explicit CLI evaluation steps, never a requirement of normal unit tests.

## Confirmed decisions

1. Pilot `meta/muse-spark-1.3-contributor` through OpenRouter, with a cumulative US$5 cap for this model across all processing. Continue with it if satisfactory; do not compare alternatives without a demonstrated need.
2. Let the LLM mark pure listings and mixed promotions, alongside food relevance and evidence. Retain supported concrete food benefits; these category labels do not automatically require manual review.
3. Skip unmapped food offers in the public MVP. Retain internal results and report exclusion reasons, without a separate user-facing list.
4. Evaluate explicit weekday restrictions in the first version, together with dates, ranges, and explicit date lists. Keep time-of-day and holiday restrictions as visible text.
5. Inherit unspecified location availability fields from the offer; explicit location-specific facts take precedence. Explicit removal of a shared constraint requires evidence and a distinct representation from missing information.
6. Use a curated 30-post pilot, with 10 posts per channel. Review the proposed concrete criteria and annotations before evaluation, and review results before the remaining batch.
7. Persist maximum-cost reservations before paid attempts, preserve unresolved reservations on recovery, and prevent concurrent spending writers. Require a successful normalization report and matching artifact dataset IDs before extraction.

Next: [geocoding and publication](04-geocoding.md).
