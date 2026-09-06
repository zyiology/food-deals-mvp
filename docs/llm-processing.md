# LLM extraction: operation and recovery

The Phase 2 implementation extracts caption-grounded offers and explicit location
candidates. It does not geocode, publish map rows, read images, or fetch linked pages.
Offline tests exercise its mechanics. Model quality remains unmeasured until the
[30-post pilot](llm-pilot-review.md) is reviewed and run.

## Dry-run

```bash
uv run food-deals-mvp extract --dry-run
uv run food-deals-mvp extract --post-ids config/llm-pilot-post-ids.json --limit 30 --dry-run
```

These commands require successful normalization with matching report, posts and
media dataset IDs. They report selection and cache availability without network
access, credentials or file writes. The pilot ID file is a JSON array with exactly
10 candidates per channel. Duplicate, unknown or unbalanced IDs fail validation;
`--limit` cannot truncate the pilot. Without an ID file, selection is ordered by
channel/message ID. A limit alone does not select a balanced pilot.

## Reviewed pilot, then full batch

The checked-in annotations are drafts awaiting user review, not approved ground
truth. Review their labels and the acceptance criteria first. Once approved, set
`OPENROUTER_API_KEY` in the environment using your normal secret-management method,
then run:

```bash
uv run food-deals-mvp extract --post-ids config/llm-pilot-post-ids.json --limit 30
uv run food-deals-mvp report --stage extract
```

The adapter checks the key and current endpoint capabilities/pricing before paid
work. It pins `meta/muse-spark-1.3-contributor` to the configured provider, requires
structured-output parameters, and disables provider fallbacks. Compatibility
advertised in metadata does not prove the endpoint will accept this particular
schema; the pilot must establish that. Authentication or configuration errors stop
the run. No model is changed automatically.

Inspect `data/intermediate/extractions.json` and `candidates.json` against the
annotations. The extraction report includes all source outcomes, review reasons,
counts, raw-cache fingerprints and spending. Pilot runs deliberately report
`partial`, because the other 106 source posts are `not_selected`. An expected
review outcome is different from a provider/schema failure.

After reviewing the complete pilot results and meeting the acceptance gate,
prepare a reviewed JSON file, for example `config/llm-pilot-review.json`:

```json
{
  "schema_version": 1,
  "reviewed_at": "2026-09-06T12:00:00+08:00",
  "accepted": true,
  "settings_hash": "copy from the reviewed extraction report",
  "cache_fingerprints": {
    "telegram:CHANNEL:MESSAGE": "copy this post's reviewed cache fingerprint"
  }
}
```

The example shows one entry for readability; the real file must contain all 30
pilot IDs, 10 per channel. Fill it only after human acceptance; generating this
file from counts alone would not evaluate factual accuracy. It binds full-batch
permission to the specific settings and original pilot caches. Then:

```bash
uv run food-deals-mvp extract --resume --pilot-review config/llm-pilot-review.json
```

The default 60-attempt run limit means the remaining batch may require more than
one invocation. Matching successes are reused, and spending remains cumulative.
Changed pilot caches or settings invalidate that approval.

## Settings, retries and refresh

`--settings PATH` accepts a JSON object; omitted fields use these defaults:

```json
{
  "model": "meta/muse-spark-1.3-contributor",
  "provider": "meta",
  "prompt_version": "caption-v1",
  "schema_version": "extraction-v1",
  "timeout": 60,
  "max_tokens": 6000,
  "temperature": 0,
  "max_attempts": 60,
  "max_total_attempts": 300,
  "retries": 2
}
```

The US$5 cap is not configurable. Unsupported models are rejected for live work.
Cache identities include source post ID, model-visible input hash, prompt/schema
content and versions, provider routing and inference settings. Reactions do not
invalidate extraction; text, links and relevant date context do.

Ordinary reruns use matching successes and request uncached posts. Failed entries
need `--resume`; successful but semantically flagged results stay cached for
review. `--refresh` explicitly requests fresh results for every selected post;
it is mutually exclusive with `--resume`. Retries, repair and refresh all reserve
funds and count as attempts. One schema-repair attempt is allowed. Transient
transport/429/server failures use bounded retries; `Retry-After` greater than
60 seconds stops the run for a later resume rather than retrying too early.

## Artifacts and the spending ledger

| Path | Purpose |
| --- | --- |
| `data/intermediate/extractions.json` | Parsed, optionally corrected results and source outcomes |
| `data/intermediate/candidates.json` | One internal row per offer/location; an unmapped row for offers without explicit places |
| `data/cache/llm/*.json` | Selected request checkpoints mirrored for inspection, including raw response, usage and model settings |
| `data/reports/extract.json` | Completion marker, outcomes, counts, review reasons, removed/added row IDs and cache fingerprints |
| `~/.config/food-deals-mvp/llm/meta--muse-spark-1.3-contributor/` | Authoritative model-wide ledger, receipts, cache and writer lock |

`--data-dir PATH` changes source/output artifacts, but never relocates or resets
the model-wide ledger. Its path is fixed relative to the current user's home,
independent of working directory, output directory and prompt version. All CLI
writers for this model share one exclusive lock. Keep a backup of this directory;
deleting or moving the whole directory, changing OS users, or manually modifying
accounting is outside the cap's guarantees. This tracks this application's work,
not unrelated requests made directly on the OpenRouter account.

Before dispatch, the application persists an attempt ID and maximum-cost
reservation. It conservatively reserves for the endpoint's entire advertised
input context plus the bounded output and request fee; this is a safety bound,
not an expected bill. Verified pricing metadata is retained, and provider price
ceilings constrain routing. The raw receipt is saved before actual cost settles
the reservation. A crash after saving the receipt can therefore be reconciled
without counting the charge twice.

Timeouts and missing usage remain unknown: their whole reservation stays charged
against remaining capacity. Missing results never prove a request was free.
Unbounded pricing, an unaffordable reservation, a charge above its reservation,
or an attempt ceiling stops paid work and preserves completed checkpoints. There
is no automatic budget increase or reservation release. If a generation has
unknown cost, reconcile its saved attempt/receipt with provider accounting before
manually changing the ledger; there is no automatic reconciliation CLI yet.

Successful receipts can reconstruct missing caches on recovery. An interrupted
refresh invalidates the earlier success for that post until resumed. Dry-run
also reports that interrupted attempt rather than presenting the old success as
a usable hit. Files are individually replaced atomically, with the report written
last. `report --stage extract` checks source and extraction artifact IDs; failed
or interrupted runs must not be treated as a newly successful snapshot.

## Reviewed corrections and date evaluation

`--corrections PATH` accepts a versioned list of field patches:

```json
{
  "schema_version": 1,
  "corrections": [{
    "correction_id": "review-001",
    "post_id": "telegram:CHANNEL:MESSAGE",
    "input_hash": "the post's extraction_input_hash",
    "cache_key": "the result's cache_key",
    "pointer": "/offers/0/availability/end_date",
    "expected": null,
    "value": "2026-08-31",
    "reason": "Reviewer found an explicit end date in the caption",
    "evidence": ["an exact supporting caption excerpt"],
    "reviewed_at": "2026-09-06T12:00:00+08:00"
  }]
}
```

Pointers address parsed response fields using JSON Pointer syntax. Array indices
refer to that particular cached response; `expected` guards against changed
values. Use the real source evidence, not the illustrative text above. Patches
can remove offers or correct dates/associations, and cannot rescue an unparsed
provider response. Stale input/cache hashes, unsupported evidence and mismatched
old values are rejected. Corrections are applied after parsing and leave the raw
cache unchanged; score the uncorrected model output in the pilot. Changes to
derived row IDs appear as removed/added IDs in the report. Later geocoding
corrections must not target removed IDs.

`availability.valid_on(availability, posted_at, reference_date)` returns `True`,
`False`, or `None` for unknown validity. Consumers include only `True` in a
“Valid on selected date” filter. It uses Singapore posting dates, inclusive
boundaries, exact-date sets and ISO weekdays. Null end dates add no expiry.
Contradictory or unresolved schedules remain unknown. Time-of-day, holiday,
stock and membership restrictions stay visible but are not evaluated.

CLI exit status is `0` for dry-run, a completed pilot selection, or a completed
full batch. It is `1` for stage/provider/budget errors or selected pending/failed
requests, and `2` for argument errors. `needs_review` alone is not a CLI failure.

## Offline checks

```bash
uv run ruff check
uv run ty check
uv run pytest
```

Tests use synthetic captions and temporary artifacts/state; network connections
are blocked. The checked-in pilot fixture is validated for balance, evidence,
schedule shape and prompt/schema freeze, without sending its captions to a model.
When local normalized exports are available, an additional check confirms the
fixture captions, links and input hashes match them. Passing these tests does not
establish the model's extraction accuracy.
