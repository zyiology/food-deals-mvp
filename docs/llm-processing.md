# LLM extraction: operation and recovery

The Phase 2 pipeline extracts caption-grounded offers and explicit location candidates.
The full-batch run on 2026-09-11 selected all 136 posts: 131 succeeded, three
need review, and two failed; none remain unprocessed. Its report remains `partial`,
with 142 offers and 86 explicit location rows. A reviewed subset was published on
2026-09-12; see the [current run record](processing-workflow.md#latest-recorded-run).
The original 30-post pilot and five-post comparison against draft annotations
remain historical findings, not an accuracy evaluation of the full batch.
See the [Phase 2 plan](plans/03-llm-processing.md) for the original approved scope.

## Offline demo review

```bash
uv run food-deals-mvp review-demo
```

Open `data/demo/review.html` to compare offer cards with source captions/images.
The default filter shows rows eligible for location lookup; switch to all rows to
inspect skipped reasons. Select the reviewed rows for geocoding
and download `demo-selection.json`. Nothing is preselected or approved automatically.
This selection is for subsequent geocoding, not a set of verified pins.

The command writes `data/demo/candidates.json` and a self-contained review HTML page.
It reads only local source artifacts and the mirrored caches selected by the original
extraction report, verifies source/cache identities, and preserves original settings.
It surfaces corrections already saved into the extraction artifacts by a prior
`extract --corrections` run, but never requests new model output, accesses the
authoritative ledger, reads a corrections file itself, or rewrites the original
extraction artifacts. Missing or changed caches
stop the rebuild rather than silently substituting a different version.
Use `--data-dir PATH` for saved artifacts and `--sources PATH` for optional source images.
Images must remain within configured export roots and match their saved content hashes.

Promotion taxonomy and model review notes are advisory. Evidence comparison tolerates
decorative emoji differences and observed encoding artifacts while retaining meaningful
text, numbers, and negations. Unsupported benefit/location/date evidence and impossible
schedules still block affected rows. Valid sibling rows can remain usable.
The original annotation fixture and five-post score are historical records; no complete
annotation review or 27/30 score is required for this demo.

## Dry-run and additional extraction

```bash
uv run food-deals-mvp extract --dry-run
uv run food-deals-mvp extract --post-ids config/llm-pilot-post-ids.json --limit 30 --dry-run
```

Live (non-dry-run) extraction reports progress to stderr: a summary of selected,
requested and cached posts, then one line per requested post as it completes. The
final report stays on stdout. Dry-run prints no progress because it is instant.

Dry-run requires successful normalization with matching report/posts/media identities.
It makes no requests or writes. The pilot ID file still selects exactly 10 posts per
channel; duplicates, unknown IDs, imbalance, and a truncating limit are rejected.

The revised prompt changes live cache identities, so a dry-run may report misses even
though old pilot outputs are available for offline review. Do not refresh the pilot
merely to inspect it. `review-demo` explicitly keeps original prompt provenance.

If additional live extraction is useful, set `OPENROUTER_API_KEY` using your normal
secret management and make an explicit demo continuation decision:

```bash
uv run food-deals-mvp extract --accept-demo --limit 10
uv run food-deals-mvp extract --accept-demo --resume
uv run food-deals-mvp report --stage extract
```

These commands can incur charges. `--limit` alone selects by channel/message ID, not
a balanced sample. `--accept-demo` replaces the requirement for exhaustive pilot
approval; the legacy `--pilot-review PATH` file remains supported for compatibility.
Without either mechanism, non-pilot work needing requests stops. Matching successes
are reused, failures need `--resume`, and spending remains cumulative.

The adapter checks credentials, endpoint capability, and bounded pricing, pins the
configured model/provider, and disables provider fallbacks. Authentication/configuration
errors stop the run. The US$5 cap and existing request/recovery controls remain intact.

Live outputs remain `data/intermediate/extractions.json`, `candidates.json`, and
`data/reports/extract.json`. A pilot report is intentionally `partial` because
106 posts were not selected. Pipeline statuses and aggregate counts are not accuracy
scores. Rows remain unmapped until the later geocoding phase.

## Settings, retries and refresh

`--settings PATH` accepts a JSON object; omitted fields use these defaults:

```json
{
  "model": "meta/muse-spark-1.3-contributor",
  "provider": "meta",
  "prompt_version": "caption-v2",
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
schedule shape and original experiment identity, without sending its captions to a model.
When local normalized exports are available, an additional check confirms the
fixture captions, links and input hashes match them. Passing these tests does not
establish the model's extraction accuracy.
