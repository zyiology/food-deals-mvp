# Phase 1: preprocessing and shared contracts

Status: revised to reflect user decisions on 2026-09-06; implementation has not started. Uses the confirmed scope in [the overview](README.md). This phase makes no LLM or geocoding requests.

## Outcome

Turn the raw exports into a deterministic, inspectable source-post dataset with correct timestamps, links, and media references. Account for excluded service records and polls without discarding useful captions. This is source normalization; the semantic food/deal decisions belong to Phase 2.

Inputs: the three export directories under `Telegram_AUG_2026/` and explicit source configuration. Outputs: `data/intermediate/posts.json`, a media manifest, and an import report. Preserve original export files unchanged.

## Implementation steps

1. **Establish the project foundation.** Replace the greeting entry point with CLI argument handling; add shared typed contracts, configuration, and JSON read/write helpers. Use the existing `uv` project and Python requirement. Add Pydantic for validation; add runtime dependencies only when needed by their phase. Propose pytest and ty alongside the approved test work.
2. **Define sources explicitly.** Configure each export root, numeric channel ID, source name, and user-confirmed public username: GoodLobang → `goodlobang`, KiasuFoodies → `kiasufoodies`, and SGFoodDeals → `sgfooddeals`. Construct `https://t.me/<username>/<message_id>` from that configuration; no further username confirmation is needed. Do not derive source identity from caption mentions or footers.
3. **Read and inventory.** Validate the export envelope and records, record file hashes, and report unknown record shapes. Ignore filesystem metadata such as `.DS_Store`. Use explicit export paths rather than scanning unrelated JSON/cache files. An unreadable/invalid export is a failed import, not an empty channel.
4. **Normalize Telegram text.** Support both strings and arrays of strings/entity objects. Concatenate fragments in original order; preserve Unicode, line breaks, prices, unit numbers, and punctuation. Keep the exact flattened text for display/evidence and a separately derived model-input text if trimming is useful. Original captions are approved for public deal details, with compact excerpts on cards. Preserve the raw record or its immutable source reference. Do not strip whole lines based on hashtags or mentions.
5. **Retain links.** Collect visible `link` text and hidden `text_link.href` destinations from the original text structure and entity metadata; deduplicate by destination without losing labels. Add `https://` only to validated scheme-less web links when exposing them as clickable URLs. Preserve the original value; only permit HTTP(S) navigation. Do not expand short URLs or download landing pages in this phase.
6. **Normalize dates and identity.** Use Unix timestamps to create timezone-aware timestamps, with `Asia/Singapore` date context for extraction. Validate agreement with exported date strings; report conflicting or missing timestamps instead of silently shifting dates. Fall back to explicitly configured export timezone only when Unix timestamps are absent. Use the channel/message pair for stable `post_id`.
7. **Apply structural exclusions.** Record the two `pin_message` service records and the empty-caption poll as excluded with distinct reasons. Keep all 136 nonempty captions, including non-food advertising and captions with missing videos, for semantic classification. Support the supplied record shapes; future image-only ingestion is outside this batch’s scope.
8. **Build a media manifest.** Resolve each referenced photo beneath its configured export root, validate containment including symlinks, and verify the file exists. Store a source-relative reference and availability status. Recognize Telegram's omitted-file sentinel and absent thumbnails as unavailable. Do not serve arbitrary export files. Photo display/copying is completed during publication/API work.
9. **Make reruns of the supplied batch deterministic.** Rebuild the normalized snapshot from the three configured exports on each run, using channel/message ID as the unique source key. Reject duplicate source keys as an input validation error. The same inputs must produce the same record IDs/order/content; generation/run metadata may differ. Later imports are not expected: do not implement upserts, overlapping-export merging, revision precedence, deletion inference, or incremental import state.
10. **Write validated artifacts and report.** Use deterministic ordering by channel ID/message ID and atomic replacement through a temporary file in the same directory. Report raw counts, retained candidates, excluded reasons, missing media, bad timestamps, and duplicate source keys. Stop before downstream extraction if required source validation fails.

## Fingerprints and responsibilities

Maintain two hashes: a source-content hash for traceability, and an extraction-input hash covering exactly the model-visible text, required date context, and source metadata. Reactions, file modification times, or export folder renames must not trigger model calls. The Phase 2 cache adds its model/prompt/schema settings to the extraction-input hash.

The importer does not create coordinates, assert a food deal, generate branch names, infer promotional dates, or merge campaigns across channels. Preserve the supplied raw records or immutable source references for inspection; later-export compatibility is deferred.

Suggested command interface, not yet implemented:

```bash
uv run food-deals-mvp normalize --sources config/sources.json
uv run food-deals-mvp report --stage normalize
```

Fail with a useful message if a configured export root is missing. Reports may contain source excerpts and relative paths but should not dump credentials or large raw records into terminal logs.

## Acceptance and proposed verification

- Reconcile **139 raw records = 136 text candidates + 2 pin-service records + 1 poll**.
- Confirm **132 present photos**, **four unavailable video/animation attachments**, and no missing referenced photos for the current exports.
- All supplied Unix dates agree with Singapore-local exported dates; preserved posting/editing timestamps retain their correct day.
- KiasuFoodies' “here” links retain their destination URLs. SGFoodDeals footers never change the configured source channel.
- Running the importer twice yields identical normalized content/IDs, with no duplicate source posts.
- Duplicate channel/message keys fail validation instead of silently overwriting a source post; no later-export revision workflow is required.

Proposed focused tests, to request approval for during implementation: text flattening and hidden links, service/poll exclusions, omitted-media sentinel, path traversal/symlink escape, timestamp fallback/conflict, duplicate source keys, malformed export, and deterministic batch reruns. A small sample plus aggregate checks against the supplied exports is enough; do not copy all photos into test fixtures.

## Confirmed decisions

1. Use `goodlobang`, `kiasufoodies`, and `sgfooddeals` for their respective source channels, as confirmed by the user.
2. Keep original captions in public deal details, with compact excerpts on cards.
3. Process the three supplied exports only. Retain deterministic reruns for development and recovery; defer support for later, partial, overlapping, or revised exports.

Exit artifact: reviewed source dataset and report. Next: [LLM processing](03-llm-processing.md).
