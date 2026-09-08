# Processing workflow: normalize → extract → geocode → publish

Newcomer runbook for the offline pipeline. This is the ordered path; the
[LLM operation guide](llm-processing.md) and [geocoding operation guide](geocoding.md)
are the deep references for flags, recovery, and edge cases.

Setup first: `uv sync --locked`, and keep the three August 2026 exports at
`Telegram_AUG_2026/{GoodLobang,KiasuFoodies,SGFoodDeals}_AUG_2026/result.json`
with their media folders. Exports and generated artifacts are ignored by Git;
normalization never modifies exports. All stages accept `--data-dir PATH`
(default `data`, relative to cwd); use the same directory across stages.

## 1. Normalize and inspect

```bash
uv run food-deals-mvp normalize --sources config/sources.json
uv run food-deals-mvp report --stage normalize
```

`config/sources.json` defines each export root, numeric channel ID, display
name, public username, and export timezone. A successful run on the supplied
exports accounts for 139 raw records → 136 text candidates (2 pin-service
records and 1 empty-caption poll excluded), 132 available photos, and 4
unavailable video/animation attachments. Require a successful report with
matching dataset IDs before downstream work; rerun normalization if an
interrupted write leaves mismatched files.

## 2. Extract offers with the LLM

```bash
uv run food-deals-mvp extract --dry-run
uv run food-deals-mvp extract --accept-demo
uv run food-deals-mvp report --stage extract
```

Dry-run needs no key and makes no requests or writes. `--accept-demo` is the
authorization flag for live work beyond the pilot; without it (or legacy
`--pilot-review`), non-pilot requests stop. `OPENROUTER_API_KEY` must be set
for live runs. Live outputs are `data/intermediate/extractions.json`,
`data/intermediate/candidates.json`, and `data/reports/extract.json`.

Completion may take several invocations: the default ceiling is 60 attempts
per invocation (`max_total_attempts: 300`). Rerun with
`extract --accept-demo --resume` to retry failures and process uncached posts;
matching successes are reused. `--resume` and `--refresh` are mutually
exclusive; avoid `--refresh` unless deliberately replacing outputs.
`needs_review` alone is not a CLI failure; `failed`/`pending` selections are.

Spending is cumulative under a fixed US$5 cap, tracked in the model-wide
ledger at `~/.config/food-deals-mvp/llm/meta--muse-spark-1.3-contributor/`
(independent of `--data-dir`). Reservations stay deducted even when the actual
cost is unknown, so remaining budget is capacity, not a cost estimate. Back up
that directory; deleting it resets accounting outside the cap's guarantees.

## 3. Review extraction and apply corrections

```bash
uv run food-deals-mvp review-demo
```

Open `data/demo/review.html` and compare each card against its source
caption/image: captured offers (including posts with no offers), titles,
prices, conditions, restrictions, dates and their offer/branch association,
explicit locations and units, and whether offers or locations were wrongly
combined. The page starts on rows eligible for lookup; switch the filter to
see skipped rows and reasons. Download the selection only after review.

`review-demo` is offline: it rebuilds saved extraction results against their
original caches and current validation, without new model requests or ledger
access. It does not read a corrections file itself; it surfaces corrections
already saved into `intermediate/extractions.json` by `extract
--corrections`. Raw caches stay unchanged.

Corrections loop (do this before geocoding):

1. Write reviewed field patches to a corrections file (JSON Pointer `pointer`
   plus `expected` old value, supporting caption `evidence`, and matching
   `input_hash`/`cache_key`; see the LLM guide for the exact shape).
2. `uv run food-deals-mvp extract --corrections PATH --accept-demo` (add
   `--resume` if failures remain). A corrections-only rerun with nothing
   pending needs no provider calls.
3. `uv run food-deals-mvp review-demo` again and download a fresh selection.

Corrections can replace derived row IDs (reported as removed/added IDs), so
finalize them before geocoding. Only `candidate` rows with explicit locations
are eligible for the next stage.

## 4. Geocode the selection

Back up the previous `demo-selection.json`, `data/overrides/geocoding.json`,
and `data/published/deals.json` first: re-extraction changes dataset and row
IDs, and stale selections/decisions fail validation rather than transferring
silently. Save the newly downloaded selection (e.g. as
`data/demo-selection.json`), then:

```bash
uv run food-deals-mvp geocode --selection data/demo-selection.json --dry-run
uv run food-deals-mvp geocode --selection data/demo-selection.json
uv run food-deals-mvp report --stage geocode
```

Dry-run makes no requests or writes; inspect the query/attempt budget before
live lookup. Settings default to `data/geocoding-settings.json`; a live run
needs an identifying `user_agent`. Review the public Nominatim usage policy
before live use: sequential cached small batch, ≥1s between requests, no
multi-machine or scheduled runs under this workflow. Cached queries are
reused; `--offline` reads caches only, `--resume` retries errors, and
`--refresh-query KEY` targets one query (mutually exclusive modes).

## 5. Review pins

Open `data/reports/geocode-review.html`, inspect each place against its offer
evidence, then approve the correct candidate, reject unsupported locations, or
supply an evidence-backed alias/manual correction. Save the download as
`data/overrides/geocoding.json` (preserving existing alias decisions), then
apply it offline:

```bash
uv run food-deals-mvp geocode --selection data/demo-selection.json --offline
```

An alias that needs a new lookup requires another live geocoding run and a
fresh review round. Reload the review page after regenerating it; old
downloads cannot approve refreshed responses. Changing source evidence or a
cached response invalidates affected approvals.

## 6. Publish and verify

```bash
uv run food-deals-mvp publish --selection data/demo-selection.json --allow-partial
```

`publish` is entirely offline and requires matching reports, current
approvals, and valid source/media provenance. `--allow-partial` acknowledges
an incomplete demo; it never bypasses pin approval. Zero approved rows cannot
replace a previous snapshot. Output is `data/published/deals.json` with
content-addressed images in `data/published/media/`.

Restart Uvicorn afterward — the API loads its snapshot once at startup — then
check row counts, historical dates, overlapping locations, and several offers
against their captions:

```bash
uv run uvicorn food_deals_mvp.api:app --host 127.0.0.1 --port 8000
```

## Full-batch redo notes

- Omitting `--limit`/`--post-ids` selects all 136 posts. Pilot caches were
  stored under an earlier prompt version, so a dry-run reports 136 misses:
  that is the expected consistent full pass under the current prompt, not a
  reason to refresh the pilot for inspection alone.
- Expect 3+ invocations at 60 attempts each for 136 misses, plus retries.
- Process every post does not mean every offer gets a pin: offers without
  supported explicit locations stay internal, and unresolved/rejected rows
  stay out of the snapshot.

## Key artifacts

| Artifact | Contents |
| --- | --- |
| `data/intermediate/posts.json`, `media.json` | Normalized source snapshot |
| `data/reports/normalize.json` | Normalization completion marker |
| `data/intermediate/extractions.json`, `candidates.json` | Parsed/corrected results, internal rows |
| `data/cache/llm/*.json` | Mirrored raw request checkpoints for inspection |
| `data/reports/extract.json` | Extraction completion marker, counts, row-ID replacements |
| `data/demo/review.html`, `data/demo/candidates.json` | Offline review page and rebuilt rows |
| `data/demo-selection.json` | Downloaded row selection bound to a demo dataset ID |
| `data/cache/geocoding/` | Mirrored raw geocoding responses |
| `data/intermediate/location-resolutions.json`, `data/reports/geocode.json` | Matching results and report |
| `data/reports/geocode-review.html` | Pin review page |
| `data/overrides/geocoding.json` | Saved alias/approve/manual/reject decisions |
| `data/published/deals.json`, `data/published/media/` | Published mapped-only snapshot |
