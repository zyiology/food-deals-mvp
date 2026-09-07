# Phase 4: FastAPI and published data access

Status: implemented and verified for the selected demo. The read-only API, safe
image routes, and packaged HTML status shell are available. The Leaflet map and
interactive deal cards remain [Phase 5](06-leaflet.md).

## Outcome

Serve a validated published snapshot without provider credentials or calls to
normalization, extraction, geocoding, or publication. Public contracts live in
`public_models.py`; API response models omit extraction evidence and interpretation
notes. Importing the API does not import pipeline or provider adapters.

FastAPI serves the API and packaged static assets from one origin. No database,
authentication system, separate frontend server, or CORS configuration is needed
for this local MVP. See [the run instructions](../../README.md#run-the-local-api).

## HTTP contract

| Route | Behavior |
| --- | --- |
| `GET /` | Return the HTML status shell, including when the dataset is unavailable. |
| `GET /static/...` | Serve packaged CSS and JavaScript from a dedicated directory. Leaflet assets will be added in Phase 5. |
| `GET /media/{media_id}` | Resolve an allowlisted ID to a published image; unavailable, unknown, modified, or unsafe images return 404. |
| `GET /api/deals` | Return mapped rows and dataset/filter metadata. |
| `GET /api/health` | Return `ready: true` and `dataset_id`; return 503 with a concise reason when unavailable. |

`GET /api/deals` accepts only these query parameters:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `as_of` | Snapshot's `suggested_reference_date` (August 26, 2026 for this pilot) | Calendar date in exact `YYYY-MM-DD` format, evaluated in Singapore time. |
| `validity` | `all` | `all` includes offers outside their advertised period or with unknown validity; `valid` includes only rows for which the shared evaluator returns true. |

All queries apply the server-configured posting-age cutoff:
`FOOD_DEALS_MAX_AGE_DAYS`, default **60**, accepted range 1–3650. This implements the
agreed two-month cutoff as a fixed 60-day window, not calendar-month subtraction.
There is no `mapping` or `max_age_days` query parameter. Unknown parameters,
unsupported validity values, malformed dates, and impossible dates return 422.

Posting age is the difference between Singapore calendar dates. A cutoff of N
accepts `0 <= age < N`: age 59 is included under the default, age 60 is excluded,
and N=1 means the selected day. Future source posts are always excluded, even in
`validity=all`. The cutoff is independent of promotion expiry; an unspecified end
date still adds no expiry in the shared availability evaluator.

Response envelope:

```text
schema_version, dataset_id, generated_at, timezone: Asia/Singapore
source_date_range, selected_source_date_range
suggested_reference_date, suggested_validity
dataset_complete, processing_summary, attribution
filters: effective as_of, validity, max_age_days
counts: matched_rows, mapped_rows, distinct_locations, distinct_offers, distinct_posts
deals: public rows plus validity_status
```

Counts describe the returned rows after filtering; `distinct_locations` counts
exact coordinate pairs, not unique businesses. Dataset-wide processing counts are
separate. Rows sort by descending posting timestamp, then ascending `deal_id`.
All rows are mapped and have finite named latitude/longitude and accepted precision.
No unmapped rows or counts are exposed.

Each row includes its identity, source name/links, title, description, original
caption, posting date, terms, display availability, location/scope, precision,
media IDs, and safe image URL. Display availability contains start/end dates,
explicit dates, weekdays, restrictions, and date status. Extraction evidence and
interpretation notes are excluded. Captions are plain data; the browser must render
them as text, never trusted HTML.

Derived `validity_status` is `valid`, `outside_period`, or `unknown`. A valid result
means supported calendar constraints match; it does not guarantee stock, opening
hours, or redemption eligibility. Viewport filtering and marker numbering remain
client-side; there is no pagination or bounding-box endpoint.

## Loading, configuration, and failures

`api_settings.py` reads `FOOD_DEALS_PUBLISHED_DIR` and `FOOD_DEALS_MAX_AGE_DAYS` at
startup. The default published directory is the source checkout's
`data/published`, independent of launch working directory. Relative configured
paths resolve against that checkout. An installed wheel requires an explicit
absolute published directory. Media is read from its `media/` subdirectory.
Environment variables must be exported or passed to the command; `.env` is not
automatically loaded.

`DealRepository` validates the schema, content fingerprint, unique IDs, coordinates,
row counts, date-range metadata, URLs, and media references at startup. The loaded
snapshot stays in memory for the process lifetime. Publication and configuration
changes take effect after restarting the application, including recovery from an
unavailable dataset. There are no file watchers or reload endpoints.

Missing snapshots return 503 with `Prepare a dataset first`; malformed or invalid
snapshots return 503 with `Published dataset is invalid`. Invalid environment
settings return 503 with `Application configuration is invalid`. The HTML shell
remains available. An empty published snapshot is invalid under the publisher's
existing safeguard. A valid loaded snapshot whose filters match zero rows returns
200 with an empty list and zero result counts. Unexpected failures return a generic
500; responses and error logging avoid filesystem paths and private data.

Only allowlisted images are served. Each read checks containment, symlinks,
content hash, and image signature. Missing/modified images return 404 without making
the deal dataset unavailable; Phase 5 cards must handle image failures. Image
responses include the declared MIME type, `nosniff`, a content-hash ETag, and
`Cache-Control: no-cache` with conditional 304 support. Although filenames are
content-addressed, public URLs use attachment IDs that can change content after
republication, so immutable caching is inappropriate for those URLs.

The static mount exposes only packaged assets and cannot shadow API routes. No raw
exports, source images, pipeline caches, or repository directories are mounted.
The API and shell need no provider network access. Basemap configuration, tiles,
and Leaflet assets remain Phase 5 work.

## Verification

`tests/test_api.py` uses synthetic snapshots and temporary media with the suite's
network prohibition. Its 43 cases cover:

- Defaults, sorting, reconciled counts, public field projection, and provider-free imports.
- Singapore dates, future posts, advertised date constraints, unknown validity, and cutoff boundaries.
- Invalid parameters, missing/corrupt/invalid datasets, and successful empty filter results.
- Snapshot replacement taking effect only after restart.
- Static route containment, allowlisted media, conditional caching, missing/changed images, and symlinks.
- Environment configuration, working-directory independence, and installed-package path requirements.

The test client uses the `httpx2` development dependency. Existing availability
unit tests remain the detailed authority for schedule evaluation.

Manual pilot smoke verification returned 15 rows at 10 coordinates by default,
six rows in valid-only mode on August 26, and three in valid-only mode on September
7. All nine referenced images were available. Launching Uvicorn from outside the
checkout worked, and the built wheel included all three static shell assets.

## Confirmed decisions

- Mapped-only public API and UI.
- Historical snapshot reference date and `validity=all` by default.
- Fixed server-configurable cutoff, default 60 days; no age-control UI for now.
- Restart to reload data or settings.
- Missing/invalid data returns 503; zero matching rows returns 200.

Next: [Leaflet and final evaluation](06-leaflet.md).
