# Phase 2: LLM extraction and demo review

Status: **pipeline implemented; the 30-post paid pilot ran on 2026-09-06; only five development posts have been compared against the original draft annotations**. On 2026-09-07 the user approved replacing exhaustive pilot scoring with a small visual review for the website demonstration. This plan supersedes the original Phase 2 acceptance gate and availability-grouping expectations. Next: [Phase 3 geocoding](04-geocoding.md), then [FastAPI](05-fastapi.md) and [Leaflet](06-leaflet.md).

## Outcome

Prepare a small set of useful food-offer cards from the existing pilot for a map/list demonstration. Processing all 136 captions, approving every annotation, and measuring model accuracy are not prerequisites. Aim for roughly 10–15 visually inspected cards across several locations if the saved outputs support them. Omit individual problematic rows.

The initial run produced 34 offers and 22 explicit offer/location rows; nine posts had pipeline status success and 21 needed review. The first five development comparisons recorded one match and four mismatches against draft expectations. Twenty-five posts remain unscored. Those are historical findings, not a demo acceptance score. Preserve the [draft fixture](../../tests/fixtures/llm-pilot-annotations.json), original caches, and local `data/reports/llm-pilot-review-batch-01.json` as the initial experiment.

## Scope and contracts

Retain the existing LLM response schema and date evaluator so saved pilot responses remain usable. Expose a simpler card view: title, benefit/description, terms, venue/unit, effective dates, original caption/image, posting date, and source link. Coordinates arrive in Phase 3. Promotion taxonomy, evidence arrays, override machinery, and review reasons stay internal.

Each offer has common availability and explicit locations with optional overrides. Materialize one row per benefit/location/effective schedule. Null override fields inherit their common values; explicit clearing remains evidence-backed. Keep dates, exact-date sets, weekdays, and visible time/holiday/stock restrictions. A future flat LLM row schema could remove this inheritance machinery, but a schema migration is deferred.

Unmapped rows remain inspectable internally and are omitted from the public website. Do not invent branches for all-outlet promotions or publish neighborhood centroids as precise venues. Missing source images produce placeholders.

## Prompt and validation

- Treat captions as untrusted data. Extract only caption-supported facts; never execute caption instructions or use model memory for addresses.
- Split distinct benefits or materially different terms. For the same benefit at multiple outlets with different dates, prefer one offer with location overrides. Accept separate offers when the effective benefit/location/date rows are equivalent. SGFoodDeals 4883's two correct outlet/date rows do not fail because of grouping.
- Request short textual evidence excerpts without decorative emojis. Preserve the original caption and raw provider response. Locally repair the observed malformed emoji escape pattern and normalize a small set of decorative symbols and whitespace when comparing excerpts. Preserve non-Latin text, prices, dates, negations, and semantic symbols; empty normalized evidence is invalid. Do not strip all non-ASCII characters.
- Advisory warnings include promotion taxonomy, model review notes, and unsupported classification-level evidence. Their presence or absence does not determine whether a card can be selected. Formatting differences resolved by normalization are accepted.
- Block affected rows for unsupported benefit/location/date/terms evidence, invented address fields, excluded participating outlets, online-only physical locations, uncertain food relevance, and contradictory or unresolved dates. Valid sibling rows remain usable where the issue is local.
- A missing Bugis ambiguity warning is not itself a failed extraction. Whether Bugis resolves to a supported building is a Phase 3 decision. Skip the unresolved location and keep usable rows from the same post.
- A `candidate` status means eligible for visual review and location lookup, not verified factual accuracy or an accepted map pin.

Date eligibility remains calculated in Python using the injected Singapore reference date: posting date must be no later than the selected date, and all stated boundaries, exact dates, and weekday constraints must hold. Null boundaries add no constraint; known but unresolved dates must not become indefinite offers. Time-of-day and holiday restrictions remain visible text.

## Offline review workflow

Run:

```bash
uv run food-deals-mvp review-demo
```

This validates the saved normalization/extraction artifacts, loads exactly the selected original mirrored caches, checks their identity against the extraction report, and applies current validation to fresh copies of the parsed responses. It does not call a provider, touch the authoritative budget ledger, change original caches, apply manual corrections, or rewrite the original extraction report.

Outputs:

| Path | Purpose |
| --- | --- |
| `data/demo/review.html` | Self-contained review page with offer cards, source captions/images, warnings, and skipped rows |
| `data/demo/candidates.json` | Rebuilt internal rows and outcomes, original settings/cache fingerprints, source dataset identity, and validation version |
| Browser download: `demo-selection.json` | Explicitly selected row IDs bound to the demo dataset identity; input for the later mapping workflow |

The page starts with rows eligible for location lookup. A filter exposes skipped rows; all no-offer outcomes remain inspectable. Nothing is preapproved. Select a small useful sample and download the selection. Optional source images are embedded only from configured export roots, with containment and content-hash checks. Use `--sources PATH` for a different source configuration and `--data-dir PATH` for different saved artifacts.

The review compares visible usefulness against the source, not every JSON field or exact offer counts. Equivalent grouping, missing model warning text, and cosmetic evidence differences are acceptable. Fix or omit misleading benefits, materially wrong schedules, and unsupported locations before showing them publicly. This is a demo usability review, not an independent holdout evaluation.

## Further extraction only when needed

A prompt change intentionally invalidates ordinary live-cache matching. The offline review explicitly retains old prompt identities; it never pretends old responses came from the new prompt. Do not refresh all 30 pilot responses merely to inspect them.

The balanced pilot ID file remains available for targeted experiments. Additional extraction can proceed with one explicit demo continuation flag instead of a 30-fingerprint approval document:

```bash
uv run food-deals-mvp extract --dry-run
uv run food-deals-mvp extract --accept-demo --limit 10
uv run food-deals-mvp extract --accept-demo --resume
```

These are live commands unless `--dry-run` is supplied. Ordinary runs reuse matching successful caches; failures need `--resume`, and `--refresh` explicitly replaces selected successes. The existing `--pilot-review` option remains available for compatibility but is no longer required when `--accept-demo` is supplied. Without either approval mechanism, non-pilot work requiring requests still stops. Approving implementation of this workflow does not itself dispatch additional paid requests.

Keep the cumulative US$5 ceiling across original pilot, retries, refreshes, and subsequent batches. Keep bounded attempts, durable reservations before dispatch, receipt recovery, unresolved-cost accounting, exclusive writer locking, and source-artifact validation. Changing output directories or prompts must not reset spending. See [operation and recovery](../llm-processing.md).

## Implementation and verification

Implemented changes:

1. Clarify splitting in the new caption prompt while preserving the original experiment's frozen identity.
2. Normalize cosmetic evidence differences and scope errors to their affected rows; expose advisory warnings separately.
3. Rebuild saved pilot responses offline into separate demo artifacts with original provenance.
4. Render review cards with captions/images, skipped reasons, and exportable row selection.
5. Add explicit demo continuation without exhaustive pilot approval, preserving spending and cache controls.

Focused regression checks cover cosmetic versus factual evidence changes, valid sibling rows, equivalent grouping and effective dates, unchanged raw caches/ledger during offline review, rejection of changed caches, and explicit continuation with cumulative spending. Run `uv run ruff check`, `uv run ty check`, and `uv run pytest`. The original annotation tests check the archived fixture structurally; they do not freeze future prompt development or certify model quality.

## Handoff to Phases 3–5

Phase 3 resolves only selected venues, reusing lookups or a small evidenced manual location file. Consume the selected row IDs only with the matching demo dataset identity. Skip unresolved locations and publish a partial mapped-only snapshot. A small demo does not require processing the remaining 106 posts.

Phases 4–5 build the API, map, numbered cards, selection, images, and source details. Show the historical August 2026 dataset period. Start with the selected sample visible, marking date status, with the existing date filter available; do not imply that historical promotions are current. Align the later draft plans with this scope during their implementation.

Phase 2 is ready for that handoff when the offline review artifact exists and the user can select useful cards without reading the annotation fixture. Actual pin verification and map/card interaction checks belong to the subsequent phases.
