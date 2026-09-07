# Food deals MVP

A local application for exploring Telegram food offers around Singapore.
**Preprocessing, LLM extraction, geocoding/publication, and the read-only FastAPI API are implemented.** Phase 2
has a completed 30-post paid pilot and an offline visual demo review. Only five
posts were compared against the original draft annotations. The user subsequently
approved 20 demo rows for geocoding. Pin review is complete: the published demo
contains 15 approved rows at 10 distinct coordinates; five rows were omitted.
The API serves this snapshot and a basic status page. The Leaflet map and deal-card
interface remain [Phase 5](docs/plans/06-leaflet.md).

The normalization CLI converts the three supplied August 2026 exports into an
inspectable source dataset. It preserves captions, hidden links, timestamps,
and raw records; inventories media; and reports structural exclusions. It makes
no LLM, geocoding, or linked-page requests. Text candidates still include
non-food advertising; semantic classification belongs to Phase 2.

The extraction CLI adds structured offer/location/date extraction, evidence checks,
cache recovery, reviewed corrections, and cumulative spending controls. See the
[operation guide](docs/llm-processing.md) and
[historical pilot review](docs/llm-pilot-review.md). The current demo workflow
uses a small visually reviewed sample; no model accuracy or mapping coverage is claimed.

```bash
uv run food-deals-mvp extract --dry-run
uv run food-deals-mvp review-demo
```

Dry-run needs no key and makes no requests or writes. `review-demo` rebuilds saved
pilot caches offline into `data/demo/candidates.json` and `data/demo/review.html`,
preserving the original results. Open the page to compare cards with captions/images
and download a small row selection for the next geocoding phase. No exhaustive
annotation review is required. Additional live extraction uses `--accept-demo`;
the operation guide explains cache versions and the shared US$5 ledger.

Phase 3 consumes `data/demo-selection.json`, caches bounded Nominatim lookups,
and renders `data/reports/geocode-review.html` for explicit pin approval. The
publisher includes only reviewed mapped rows and runs entirely offline. See the
[geocoding operation guide](docs/geocoding.md) for review, recovery, and publication.

```bash
uv run food-deals-mvp geocode --selection data/demo-selection.json --offline
uv run food-deals-mvp publish --selection data/demo-selection.json --allow-partial
```

Publication requires saved pin decisions in `data/overrides/geocoding.json`; a
reviewed location alias alone does not approve coordinates.

## Setup

Use Python 3.14 or later and `uv`. From the repository root:

```bash
uv sync --locked
```

This installs the application and development tools (Ruff, ty, and pytest).
No provider keys are required for preprocessing.

Keep the supplied exports at these paths, including their exported media folders:

```text
Telegram_AUG_2026/
  GoodLobang_AUG_2026/result.json
  KiasuFoodies_AUG_2026/result.json
  SGFoodDeals_AUG_2026/result.json
```

The exports and generated artifacts are ignored by Git. Normalization reads
exports without modifying them.

## Run the local API

With the published demo already present, start the app from the repository root:

```bash
uv run uvicorn food_deals_mvp.api:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/> for the status page. The map and interactive deal
cards are the next phase. Inspect <http://127.0.0.1:8000/api/deals> for JSON or
<http://127.0.0.1:8000/api/health> for dataset readiness.

The default response shows all 15 approved rows at 10 coordinates, using the
snapshot's suggested **August 26, 2026** reference date and `validity=all`.
Each row includes `validity_status`; showing a row does not mean it is redeemable
on that date. All pilot coordinates have building-level precision.

The API accepts `as_of=YYYY-MM-DD` and `validity=all|valid`, for example:

```text
http://127.0.0.1:8000/api/deals?as_of=2026-08-26&validity=valid
```

The agreed two-month posting cutoff is implemented as **60 days**, measured
relative to the reference date using Singapore calendar dates. Ages 0–59 are
included; age 60 and future posts are excluded, including in `validity=all`.
Promotion expiry is evaluated separately. Configure the cutoff on the server:

```bash
FOOD_DEALS_MAX_AGE_DAYS=60 uv run uvicorn food_deals_mvp.api:app --host 127.0.0.1 --port 8000
```

| Environment variable | Default | Behavior |
| --- | --- | --- |
| `FOOD_DEALS_MAX_AGE_DAYS` | `60` | Integer from 1 to 3650; applies to every query. No browser/query override. |
| `FOOD_DEALS_PUBLISHED_DIR` | Checkout's `data/published` | Contains `deals.json` and `media/`. Relative paths resolve against the checkout, independently of working directory. An installed wheel requires an explicit absolute path. |

Export variables or pass them with the command; `.env` is not loaded automatically.
From another directory, use `uv run --project /absolute/path/to/food-deals-mvp`
before the same Uvicorn arguments.

The app reads and validates the snapshot once at startup. **Restart after publishing
or changing settings**, including after fixing missing/invalid data. It makes no
LLM or geocoding calls and needs no provider keys, raw exports, or pipeline caches
at runtime. Unknown or unavailable images return 404. Missing/invalid snapshots or
invalid settings return 503 from the API while the status page stays accessible.
A valid dataset with no matching rows returns 200 with an empty list. Invalid dates,
validity values, and unsupported query parameters return 422.

See the [FastAPI contract](docs/plans/05-fastapi.md) for response fields and caching.

## Normalize and inspect

```bash
uv run food-deals-mvp normalize --sources config/sources.json
uv run food-deals-mvp report --stage normalize
```

[config/sources.json](config/sources.json) defines each export root, numeric channel
ID, display name, public username, and export timezone. Export roots are resolved
relative to the configuration file, independently of the current directory.
Telegram links use the configured usernames, not mentions in captions.

Both commands accept `--data-dir PATH` to choose the output directory (default:
`data`, relative to the current directory). Use the same directory for normalization
and reporting. For example:

```bash
uv run food-deals-mvp normalize --sources config/sources.json --data-dir /tmp/food-deals
uv run food-deals-mvp report --stage normalize --data-dir /tmp/food-deals
```

A successful run on the supplied exports accounts for:

| Result | Count |
| --- | ---: |
| Raw records | 139 |
| Text candidates | 136 |
| Excluded pin-service records | 2 |
| Excluded empty-caption polls | 1 |
| Available photos | 132 |
| Unavailable video/animation attachments | 4 |

The four omitted thumbnails are counted separately from their parent attachments.
Unavailable media does not discard a useful caption. Paths escaping an export
root, including symlink escapes, are marked unsafe and are not read.

## Output and reruns

| Artifact | Contents |
| --- | --- |
| `data/intermediate/posts.json` | Ordered source posts, exact captions, link destinations and labels, Singapore-aware timestamps, raw records, media IDs, and source/extraction fingerprints |
| `data/intermediate/media.json` | Media references, availability status, safe source-relative paths, and hashes of available files |
| `data/reports/normalize.json` | Latest run status, input/configuration hashes, counts, excluded raw records, errors, and warnings |

Each artifact contains a schema version, dataset ID, generation timestamp, and
timezone. Unchanged inputs produce identical content and IDs apart from generation
timestamps. Reactions affect source traceability but not extraction fingerprints;
caption, link, and relevant date-context changes affect extraction fingerprints.
The importer rebuilds the supplied batch; it does not merge overlapping or later
exports. Photos remain in their original export folders.

Commands exit with status `0` on success and `1` on import or artifact errors.
Invalid configuration, unreadable/malformed exports, duplicate source keys, and
conflicting timestamps fail normalization. When source validation fails, the CLI
writes a failure report and preserves previous posts/media snapshots. If the
output directory itself cannot be written, a report cannot be guaranteed.
Expected omitted media is recorded without failing the run; unexpected missing or
unsafe media is also reported as a warning.

Files are replaced atomically individually, not as a multi-file transaction. The
report is written last as the completion marker. Run one writer at a time, require
a successful report, and require matching dataset IDs before consuming artifacts.
The `report` command checks these IDs; rerun normalization if an interrupted write
leaves mismatched files. A retained snapshot after a failed run must not be treated
as the result of that failed run.

## Development checks

```bash
uv run ruff check
uv run ty check
uv run pytest
```

Tests use synthetic exports and temporary output/state directories, with network
connections blocked and no provider credentials. They cover captions/links, exclusions, media containment,
timestamps, fingerprints, deterministic reruns, failure recovery, and CLI behavior.
An additional aggregate check runs against the three local exports when present;
it is skipped when those exports are absent. Tests do not copy the photo collection
or write to the normal `data/` output directory.

Extraction checks also cover availability inheritance, evidence grounding, cache
identity/recovery, bounded retries and repair, spending reservations, interrupted
refreshes, demo continuation, and offline review. The archived pilot fixture is
checked for balance, source evidence, schedule shapes, and its original identity;
it no longer freezes the current prompt. Demo review does not claim model accuracy.

API regression tests use synthetic snapshots and temporary images with network
access blocked. They cover filters, public response fields, failure states, restart
behavior, environment settings, static/media containment, and cache revalidation.
