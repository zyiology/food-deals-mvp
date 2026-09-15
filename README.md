# Food deals MVP

A local application for exploring Telegram food offers around Singapore.
**Preprocessing, LLM extraction, geocoding/publication, Gemini meal classification, FastAPI, and the Leaflet interface are implemented.**
Full-batch processing of all 136 posts produced a partial published snapshot on
**2026-09-12**: 52 approved rows at 30 distinct coordinates, with 24 selected rows
rejected. Extraction has 131 successful posts, three needing review, and two
failures; none remain unprocessed. See the
[current run record](docs/processing-workflow.md#latest-recorded-run).

The original 30-post pilot and five-post annotation comparison remain historical
findings, not a full accuracy evaluation. The
[Phase 5 verification and limitations](docs/leaflet-review.md) describe the earlier
pilot snapshot; browser verification of the new snapshot is not recorded there.

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

A Git pull includes the application, Gemini classifier, tests, documentation, and
`.env.example`. It does not include `.env` or `data/published/`; both are ignored.
An existing server checkout keeps its ignored local files during a pull. A fresh
checkout must receive the prepared `data/published/deals.json` and
`data/published/media/` before the API can serve deals.

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

## Run the website

With `data/published/` present, configure the server once:

1. Register for a free [OneMap API account](https://www.onemap.gov.sg/apidocs/register).
2. Copy `.env.example` to `.env` and enter the OneMap account email/password and
   Gemini API key.

The credentials stay in the ignored local `.env` file. The server uses them only
to obtain a short-lived OneMap token, keeps the token in memory, and renews it
automatically. They are never returned to the browser. The Gemini key is used only
by the offline `classify-meals` command. Start the app from the repository root:

```bash
uv run --env-file .env uvicorn food_deals_mvp.api:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/> for the map and interactive deal cards.
Inspect <http://127.0.0.1:8000/api/deals> for JSON or
<http://127.0.0.1:8000/api/health> for dataset readiness.

The default response shows all 52 approved rows at 30 coordinates, using the
snapshot's suggested **August 31, 2026** reference date and `validity=all`.
Each row includes `validity_status`; showing a row does not mean it is redeemable
on that date. The snapshot has 46 rows with building-level precision and six with outlet-level precision.

The API accepts `as_of=YYYY-MM-DD`, `validity=all|valid`, and
`meal=drink|breakfast|lunch|dinner|snack`, for example:

```text
http://127.0.0.1:8000/api/deals?as_of=2026-08-31&validity=valid&meal=lunch
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
| `ONEMAP_EMAIL` | None | OneMap account email used server-side to obtain and renew search tokens. |
| `ONEMAP_PASSWORD` | None | OneMap account password used server-side to obtain and renew search tokens. |
| `ONEMAP_TOKEN` | None | Optional three-day token for temporary use; cannot renew without the account credentials. |
| `GEMINI_API_KEY` | None | Used only by the offline meal-classification command. It is not used while serving or browsing deals. |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Gemini model used by the offline meal-classification command. |

Export variables, pass them with the command, or use `uv run --env-file .env` as
shown above. Uvicorn does not load `.env` automatically.
From another directory, use `uv run --project /absolute/path/to/food-deals-mvp`
before the same Uvicorn arguments.

The app reads and validates the snapshot once at startup. **Restart after publishing
or changing settings**, including after fixing missing/invalid data. Serving the
published deals needs no LLM calls, pipeline geocoding, raw exports, or pipeline
caches. Interactive location search and reverse address lookup make live OneMap
calls using the configuration above. Unknown or unavailable images return 404.
Missing/invalid snapshots or invalid settings return 503 from the API while the
page stays accessible with a retry action.
A valid dataset with no matching rows returns 200 with an empty list. Invalid dates,
validity values, meal values, and unsupported query parameters return 422.

## Classify published deals by meal

After publishing or replacing `data/published/deals.json`, classify every published
deal and save its `meal_types` directly into that snapshot:

```bash
uv run --env-file .env food-deals-mvp classify-meals
```

The command validates that Gemini returns every deal ID exactly once, writes only
after all batches succeed, recalculates the dataset fingerprint, and saves the
previous snapshot under `data/backups/`. Restart the server after it completes.
Serving and filtering the saved labels makes no Gemini requests.

See the [FastAPI contract](docs/plans/05-fastapi.md) for response fields and caching.

## Browse the map

The **Find deals** dialog opens on startup. Choose a suggested postal code,
building, or address, then select **Show map** to center on it. **Nearby** requests
your device location; **Show map** with an empty address uses that location.
Location access is requested after these actions, not simply by opening the page.
You can also close the dialog to browse directly and reopen it with **Find deals**.
Submitting the dialog sends its meal and day choices to the deals API, enables
valid-only filtering, updates the visible main controls, and centers the selected
location. The selected location appears once below the main controls.

The map fits all results on the first successful load unless a submitted location
has already positioned it. Submitting a location centers at zoom 14; nearby offers
are determined by the visible map area, with no distance ranking or fixed radius.
Pan or zoom to filter the list locally. Numbers identify visible locations: each
exact coordinate has one pin and one expandable list group containing all its
deals. Locations are ordered by their newest deal; deals within a group are
newest first. A badge such as **2 deals** shows how many rows share the pin.
Groups start expanded; full offer details start closed.

Select a shared pin to reveal its group, or select a deal card to open that offer's
details. A single-deal pin opens its offer directly. Headings distinguish the
active location from the selected offer, including when collapsed. Selection
survives renumbering while its ID remains visible; collapse preferences survive
panning and refreshes for locations still in the loaded results. Dismissing a
popup keeps it closed until another explicit selection. **Show all locations**
restores the extent of the filtered results. Counts distinguish deal rows from
exact-coordinate locations, which may represent a whole building.

Change the meal, reference date, or **Valid on selected date** setting to query the API.
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

See the [front-end developer guide](docs/front-end.md) for current features,
startup flows, module responsibilities, API integration, and known limitations.

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
for the historical live-dataset checks and remaining human review. The browser
script dismisses the startup dialog and covers grouping, selection, collapse,
popup/focus retention, refresh/error states, desktop/mobile layout, and submitted-
location precedence. Live address search and device-location flows remain separate
[coverage gaps](docs/front-end.md#development-and-verification).
