# Food deals MVP

A local application for exploring Telegram food offers around Singapore.
**Phase 1 (preprocessing) is implemented.** LLM extraction, geocoding, the API,
and the map interface are planned in [docs/plans/README.md](docs/plans/README.md).

The current CLI normalizes the three supplied August 2026 exports into an
inspectable source dataset. It preserves captions, hidden links, timestamps,
and raw records; inventories media; and reports structural exclusions. It makes
no LLM, geocoding, or linked-page requests. Text candidates still include
non-food advertising; semantic classification belongs to Phase 2.

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

Tests use synthetic exports and temporary output directories, with no network or
provider credentials. They cover captions/links, exclusions, media containment,
timestamps, fingerprints, deterministic reruns, failure recovery, and CLI behavior.
An additional aggregate check runs against the three local exports when present;
it is skipped when those exports are absent. Tests do not copy the photo collection
or write to the normal `data/` output directory.
