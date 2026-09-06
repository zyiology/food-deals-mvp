# Phase 4: FastAPI and published data access

Status: draft. Depends on the [published dataset contract](README.md) and [Phase 3 publication](04-geocoding.md). API development can use a small approved fixture before the full geocoding run is complete.

## Outcome

Serve the local web app, filtered public deal records, and safe source images. Requests read an already prepared snapshot. Starting or viewing the application must not require OpenRouter credentials or trigger normalization, extraction, geocoding, or publication.

Use FastAPI, Pydantic contracts, and an ASGI server within the existing `uv` package. Serve vanilla frontend assets from the same origin; there is no need for a separate frontend server, database, authentication system, or CORS configuration in this local MVP.

## Proposed HTTP contract

| Route | Behavior |
| --- | --- |
| `GET /` | Return the application HTML shell. |
| `GET /static/...` | Serve packaged CSS, JavaScript, and pinned Leaflet assets from a dedicated static directory. |
| `GET /media/{media_id}` | Resolve an opaque allowlisted ID to a published image; unknown IDs return 404. Never accept arbitrary filesystem paths. |
| `GET /api/deals` | Return public rows plus dataset/filter metadata using the query contract below. |
| `GET /api/health` | Return ready state and dataset ID when a valid dataset is loaded; 503 with a concise reason when unavailable. |

Use a dedicated static mount; FastAPI's [static-files documentation](https://fastapi.tiangolo.com/tutorial/static-files/) explains mounting `StaticFiles`. Do not mount the repository or the whole raw export root, and do not let a root static mount shadow API routes.

`GET /api/deals` parameters:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `as_of` | Current Singapore date | ISO `YYYY-MM-DD` reference date. Required in response metadata even if omitted by client. |
| `validity` | `valid` | `valid` applies the shared date evaluator; `all` includes expired/upcoming/unknown-validity offers from posts available by `as_of`. |
| `mapping` | `mapped` | `mapped`, `unmapped`, or `all`, based on accepted coordinates. |
| `max_age_days` | Omitted | Optional positive integer restricting posting age relative to `as_of`. Proposed accepted range: 1–3650. |

Never include a post dated after `as_of`, even in `validity=all`; this mode broadens promotion periods, not source history. Posting age is the difference between Singapore calendar dates; `max_age_days=N` accepts ages `0 <= age < N`, so one day means the selected day. Reject unsupported enums, malformed dates, and out-of-range ages through typed validation with a 422 response.

Keep viewport filtering client-side at this scale. The API returns the relevant full set once per date/filter change; map pans must not generate API or geocoding calls. Server-side bounding boxes/pagination are deferred until measured dataset size warrants them.

Response envelope:

```text
schema_version
dataset_id
generated_at
timezone: Asia/Singapore
source_date_range
dataset_complete, processing_summary
filters: effective as_of, validity, mapping, max_age_days
counts: matched_rows, mapped_rows, unmapped_rows, distinct_offers, distinct_posts
deals: public rows plus validity_status for the effective reference date
```

Counts refer to the rows returned after all filters and must reconcile. Dataset-wide processing counts are separate and labelled accordingly. To display mapped and unmapped tabs/counts together, the browser requests `mapping=all` and partitions the response locally.

Each returned row includes source identity/links, title, description, source caption, posting date, terms, availability/restrictions, location/scope, mapping reason, precision, nullable named coordinates, and safe image URL. Derived validity status is `valid`, `outside_period`, or `unknown`; future source posts have already been excluded. A `valid` result means only that supported date constraints match, not guaranteed redemption at the present hour.

## Implementation steps

1. Add application configuration for published dataset/media paths and frontend map settings. Resolve defaults from the package/project configuration deliberately, without assuming the launch working directory. Bind the documented local command to `127.0.0.1`.
2. Load and validate one immutable dataset snapshot at startup: supported schema version, unique IDs, required public fields, finite coordinates, media references, and metadata/count consistency. Keep the parsed result in memory; do not reread the JSON for every map request.
3. Provide a repository/read service independent of route handlers and an injected clock/date provider. Import the shared availability evaluator from Phase 2; never implement a second slightly different date rule inside routes.
4. Implement query validation, filtering, derived validity status, and deterministic sorting by descending `posted_at`, then `deal_id`. This order supplies stable ties for ephemeral frontend numbering.
5. Project internal records into explicit public response models. Keep local file paths, API keys, prompts, model responses, private review notes, and provider error bodies out of responses. Serialize source text as text, not trusted HTML.
6. Serve packaged static assets and allowlisted images with appropriate MIME types and cache behavior. Validate media IDs/path containment including symlinks. Use placeholders for unavailable media and return 404 for unknown IDs. Content-addressed image names allow long-lived caching safely.
7. Handle unavailable data clearly. The HTML shell remains accessible; `/api/health` and `/api/deals` return 503 with a helpful “Prepare a dataset first” or “Published dataset is invalid” message. An explicitly valid empty dataset returns 200 with an empty list. Unexpected errors are logged locally without leaking paths or secrets.
8. Keep reload behavior simple: publication writes a new snapshot, then the operator restarts the app to load it. State this in future run instructions. Do not introduce file watchers, live mutation, or an unauthenticated admin reload endpoint for the MVP.

Proposed local launch command, not yet implemented:

```bash
uv run uvicorn food_deals_mvp.api:app --host 127.0.0.1 --port 8000
```

The app can serve its dataset and UI without LLM/geocoding network access. Basemap tiles still require internet access unless a separately permitted offline provider is introduced; local hosting does not make the basemap offline.

## Acceptance and proposed verification

- App launch and `/api/deals` succeed without provider credentials when a valid dataset exists; external-service adapters are not imported into request-side work.
- Response fields match the public contract, use named latitude/longitude, and expose no raw cache/provider content.
- Verify inclusive dates, unknown expiry, explicit date gaps, weekdays, `needs_review` validity, future-post exclusion, and the post-age boundary through API calls backed by a fixture.
- Invalid parameters return 422; unavailable/invalid data returns 503; a valid empty set returns 200; missing image IDs return 404.
- A mapped row always has valid coordinates; an unmapped row cannot appear on the map simply because a stale coordinate was retained.
- Deterministic sorting and response counts agree. No server viewport endpoint is required for the existing volume.
- Attempt traversal/absolute paths/escaped symlinks through media routing and confirm rejection. Confirm static routes do not shadow API routes.
- A newly published file is loaded after restart. A corrupt replacement never appears as a silently empty successful dataset.

Propose FastAPI client tests for the route contract and failure states, reusing the shared date evaluator's unit cases rather than duplicating every internal test. Request approval before adding test fixtures or user-facing run documentation during implementation.

## Review questions

1. Is restart-to-reload acceptable for this local MVP? Recommendation: yes.
2. Is a configurable post-age filter with no default age limit preferable to a fixed “recent posts” cutoff? Recommendation: yes, to preserve unknown-expiry offers while allowing stale posts to be hidden explicitly.
3. Should unmapped deals be exposed in the same response for the separate UI tab? Recommendation: yes via `mapping=all`, keeping the default API view mapped.

Next: [Leaflet and final evaluation](06-leaflet.md).
