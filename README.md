# Food deals MVP

A local application for exploring Telegram food offers around Singapore.
**Preprocessing, LLM extraction, geocoding/publication, FastAPI, and the Leaflet interface are implemented.** Phase 2
has a completed 30-post paid pilot and an offline visual demo review. Only five
posts were compared against the original draft annotations. The user subsequently
approved 20 demo rows for geocoding. Pin review is complete: the published demo
contains 15 approved rows at 10 distinct coordinates; five rows were omitted.
The API serves this snapshot with a numbered map and matching deal cards.
See the [Phase 5 verification and limitations](docs/leaflet-review.md).

The normalization CLI converts the three supplied August 2026 exports into an
inspectable source dataset. The extraction CLI adds structured offer/location/date
extraction, and Phase 3 resolves selected locations and publishes reviewed mapped
rows. To (re)build the dataset, follow the [processing workflow](docs/processing-workflow.md);
stage details live in the [LLM operation guide](docs/llm-processing.md) and
[geocoding operation guide](docs/geocoding.md).

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
exports without modifying them. See the [processing workflow](docs/processing-workflow.md)
for the normalize commands and expected counts.

## Run the local API

With the published demo already present, start the app from the repository root:

```bash
uv run uvicorn food_deals_mvp.api:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/> for the map and interactive deal cards.
Inspect <http://127.0.0.1:8000/api/deals> for JSON or
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
invalid settings return 503 from the API while the page stays accessible with a retry action.
A valid dataset with no matching rows returns 200 with an empty list. Invalid dates,
validity values, and unsupported query parameters return 422.

See the [FastAPI contract](docs/plans/05-fastapi.md) for response fields and caching.

## Browse the map

The map fits all results on the first load. Pan or zoom to filter the list locally;
numbers are reassigned to the visible rows. Select a card or marker to open details.
Selection follows the offer ID through renumbering and clears when it leaves the
view or filter results. A **+ badge** opens a chooser for offers sharing an exact
coordinate. **Show all locations** restores the extent of the filtered results.

Change the reference date or enable **Valid on selected date** to query the API.
**Today** uses Singapore time. The posting cutoff remains a server setting.
Cards distinguish valid, outside-period, and unknown availability; expanding details
shows terms, the original caption, and source links. Building-level pins are labelled
approximate. On narrow screens the map sits above the list; list controls also work
with a keyboard.

Leaflet 1.9.4 and its licence are bundled locally. The basemap requires network
access; tile failures leave the pins and list usable with a map retry button.
Configure the tile provider and attribution in
[src/food_deals_mvp/static/map-config.js](src/food_deals_mvp/static/map-config.js).
The default uses OpenStreetMap standard tiles with visible attribution and normal
browser caching; do not add bulk prefetching or offline tile downloads.

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

Frontend checks are separate from pytest. Pure map-state checks require Node.js 22
or later and use its built-in test runner. Browser checks use a pinned, isolated
Playwright script; no frontend build system or Python runtime dependency is added:

```bash
node --test tests/map-state.test.mjs
uv run --isolated --no-project --with playwright==1.62.0 python -m playwright install chromium
uv run tests/browser_smoke.py
```

The installation downloads Chromium into the user cache. Browser checks serve local
static assets through request interception and use synthetic API responses, stubbed
tiles, and deliberately broken images. They need neither a running API nor provider
keys and make no live tile requests. See [the review record](docs/leaflet-review.md)
for the separate live-dataset checks and remaining human review.
