# Phase 2: LLM processing and availability

Status: revised to reflect user decisions on 2026-09-06; implementation has not started. Depends on [normalized source posts](02-preprocessing.md) and the confirmed caption-only extraction and date-handling scope in [the overview](README.md).

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

1. Finalize the schema and prompt using the data review's cases. Define field length/list size limits and deterministic ID assignment after validation.
2. Build the HTTP adapter with API credentials from environment variables. Add a dry-run mode reporting candidate count and cache hits/misses without sending requests. Print no authorization headers.
3. Build a local cache key from extraction-input hash, prompt/schema versions, model/provider routing configuration, and inference settings. Save raw response, validated result, usage/cost metadata if returned, and processing status. Do not cache a timeout or invalid response as a successful “no deal”.
4. Process sequentially initially, checkpointing each completed request. Use bounded retries for timeouts, rate limits, and transient server errors, honoring `Retry-After`. Authentication/configuration errors stop the run. Permit at most one schema-repair attempt per failed response before recording it for review; all attempts count toward both the request budget and cumulative US$5 spending cap.
5. Enforce explicit maximum request/attempt counts and the cumulative US$5 cap across pilot, full processing, retries, repairs, refreshes, and resumed runs. Persist spend accounting alongside checkpoints; a new run must not reset the remaining budget. Before a paid request, require enough remaining budget for a conservative maximum request cost based on verified endpoint pricing and bounded input/output tokens, or an enforceable provider-side cap covering this work. Reconcile actual reported costs after each attempt. Report unknown usage as unknown, and stop paid work if spend or the next request’s maximum cost cannot be bounded; do not rely only on checking costs after a request. If $5 is exhausted before completion, preserve results and report unfinished work without raising the cap automatically.
6. Validate response structure and meaning: evidence excerpts exist, dates are consistent, location exclusions are not included, offer/location associations are supported, and non-food responses do not leak into normal map rows. Route uncertain classification or invalid offers to review without losing the source record.
7. Apply field-level reviewed overrides after successful parsing, using source/input hashes to reject stale corrections. Each correction includes the target, reason, evidence, and review timestamp. Overrides should be able to exclude a false positive or correct an offer/date association without another paid request.
8. Expand effective offer/location rows and emit reports. Keep results for all supplied source IDs, including successful exclusions and provider failures. Regenerate artifacts from the supplied batch and matching caches so prompt/schema changes or reviewed corrections do not leave stale derived rows. Record unmapped skips separately from non-food exclusions and provider failures.

Proposed commands:

```bash
uv run food-deals-mvp extract --dry-run
uv run food-deals-mvp extract --limit 25
uv run food-deals-mvp extract --resume
uv run food-deals-mvp report --stage extract
```

`--limit` selects work deterministically, preferably via a review-slice ID file during evaluation. A limit is a deliberate partial run and must be recorded as such. `--resume` retries unfinished work while preserving matching successful caches; a separate explicit option should refresh selected successful entries.

## Acceptance and proposed verification

Start with the proposed 20–25-post review slice, including clear exclusions, missing locations, multi-offer/multi-outlet posts, separate dates, and unknown expiry. Review expected labels and pilot results with the user before processing the remaining candidates. Include pure listings and mixed promotions in this quality check without adding a mandatory per-post review gate for those labels. If the selected model performs satisfactorily, continue with matching pilot caches and the remaining portion of the same US$5 budget; no alternative-model benchmark is required.

- All accepted locations have source evidence; no all-outlet expansion uses model memory.
- More Yogurt's dates remain outlet-specific; Geláre's three benefits have separate periods.
- A&W food offers remain distinct from hair-care ads and delivery-only vouchers. The LLM marks pure listings and mixed promotions with evidence; uncertain or invalid results remain reviewable.
- Unmapped food offers remain accounted for internally and produce no public rows; supported locations from partially mappable offers remain usable.
- Pilot and resumed batch work share the US$5 cap. Verify stopping before an unaffordable or unbounded request, including retries/repairs, while preserving completed work.
- Test current versus historical dates, future-post exclusion, inclusive end dates, null boundaries, explicit date gaps, weekdays, and unresolved dates.
- Re-running unchanged inputs uses cached validated results. Changing prompt/model/text/date context invalidates relevant cache entries; changing reactions does not.
- Simulate invalid JSON, unsupported schema, response truncation, timeout, 429, and authentication failure without real paid calls.
- Compare human-labelled expected offers/locations/dates against output and report counts and specific errors. Do not equate valid JSON with factual accuracy.

Propose the corresponding automated tests and annotation fixtures for approval during implementation. Live model runs are explicit CLI evaluation steps, never a requirement of normal unit tests.

## Confirmed decisions

1. Pilot `meta/muse-spark-1.3-contributor` through OpenRouter, with a cumulative US$5 cap for this model across all processing. Continue with it if satisfactory; do not compare alternatives without a demonstrated need.
2. Let the LLM mark pure listings and mixed promotions, alongside food relevance and evidence. Retain supported concrete food benefits; these category labels do not automatically require manual review.
3. Skip unmapped food offers in the public MVP. Retain internal results and report exclusion reasons, without a separate user-facing list.
4. Evaluate explicit weekday restrictions in the first version, together with dates, ranges, and explicit date lists. Keep time-of-day and holiday restrictions as visible text.

Next: [geocoding and publication](04-geocoding.md).
