"""Offline review of original caches under current demo validation rules."""

import base64
import html
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import JsonValue

from .config import load_sources
from .extraction import cached, load_extraction_report
from .extraction_models import CandidateArtifact, ExtractionArtifact, PostResult
from .extraction_validation import expand, normalized_evidence
from .llm_budget import utc_now
from .models import MediaManifest, SourcePost
from .storage import atomic_write, file_hash, fingerprint, load_normalized, read_json


class DemoArtifact(CandidateArtifact):
    extraction_dataset_id: str
    validation_version: str = "demo-v1"
    results: list[PostResult]
    original_settings: dict[str, dict[str, JsonValue]]
    cache_fingerprints: dict[str, str]


def source_image(post: SourcePost, media: MediaManifest, sources: Path) -> str:
    if not sources.exists():
        return ""
    config = load_sources(sources)
    source = next((s for s in config.sources if s.channel_id == post.channel_id), None)
    if source is None:
        return ""
    root = (sources.parent / source.export_root).resolve()
    for item in media.media:
        if (
            item.post_id != post.post_id
            or item.status != "available"
            or not item.relative_path
        ):
            continue
        path = (root / item.relative_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        content = path.read_bytes()
        if file_hash(content) != item.content_hash:
            continue
        mime = (
            "image/jpeg"
            if content.startswith(b"\xff\xd8\xff")
            else ("image/png" if content.startswith(b"\x89PNG\r\n\x1a\n") else None)
        )
        if mime:
            return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"
    return ""


def build_demo_review(
    data_dir: Path, sources: Path = Path("config/sources.json")
) -> Path:
    report = load_extraction_report(data_dir)
    posts, media, _ = load_normalized(data_dir)
    saved = ExtractionArtifact.model_validate(
        read_json(data_dir / "intermediate/extractions.json")
    )
    lookup = {post.post_id: post for post in posts.posts}
    results = []
    rows = []
    settings = {}
    fingerprints = {}
    for original in saved.results:
        if original.post_id not in report.selected_ids:
            continue
        post = lookup[original.post_id]
        # Never guess among cache versions or relabel an old response with today's prompt.
        if len(original.cache_key) != 64 or any(
            c not in "0123456789abcdef" for c in original.cache_key
        ):
            raise ValueError("invalid saved cache key")
        entry = cached(
            data_dir / "cache/llm" / f"{original.cache_key}.json",
            post,
            original.cache_key,
        )
        if entry is None:
            raise ValueError(f"missing original cache: {post.post_id}")
        identity = fingerprint(
            {
                "post_id": post.post_id,
                "input": post.extraction_input_hash,
                "settings": entry.settings,
            }
        )
        cache_hash = fingerprint(entry.model_dump(mode="json"))
        if identity != entry.cache_key or cache_hash != report.cache_fingerprints.get(
            post.post_id
        ):
            raise ValueError(f"original cache fingerprint differs: {post.post_id}")
        if fingerprint(entry.settings) != report.settings_hash:
            raise ValueError(f"original settings differ: {post.post_id}")
        outcome = PostResult(
            post_id=post.post_id,
            input_hash=post.extraction_input_hash,
            cache_key=entry.cache_key,
            status="success" if entry.extraction else "failed",
            extraction=entry.extraction.model_copy(deep=True)
            if entry.extraction
            else None,
            errors=[entry.error] if entry.error else [],
        )
        rows.extend(expand(post, outcome))
        results.append(outcome)
        settings[post.post_id] = entry.settings
        fingerprints[post.post_id] = cache_hash
    if {r.post_id for r in results} != set(report.selected_ids):
        raise ValueError("saved extraction does not cover the selected posts")
    artifact = DemoArtifact(
        dataset_id=fingerprint(
            {
                "version": "demo-v1",
                "source": posts.dataset_id,
                "rows": [r.model_dump(mode="json") for r in rows],
                "caches": fingerprints,
            }
        ),
        generated_at=utc_now(),
        source_dataset_id=posts.dataset_id,
        extraction_dataset_id=report.dataset_id,
        rows=rows,
        results=results,
        original_settings=settings,
        cache_fingerprints=fingerprints,
    )
    page = render_review(artifact, lookup, media, sources)
    output = data_dir / "demo"
    atomic_write(output / "candidates.json", artifact)
    target = output / "review.html"
    # An interrupted render must not leave half an HTML document.
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=output, delete=False
    ) as stream:
        temporary = Path(stream.name)
        stream.write(page)
    try:
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target.resolve()


def render_review(
    artifact: DemoArtifact,
    posts: dict[str, SourcePost],
    media: MediaManifest,
    sources: Path,
) -> str:
    esc = html.escape
    cards = []
    images = {
        post_id: source_image(posts[post_id], media, sources)
        for post_id in {r.post_id for r in artifact.rows}
    }
    for index, row in enumerate(artifact.rows, 1):
        post = posts[row.post_id]
        location = row.location
        schedule = row.availability
        dates = (
            ", ".join(str(day) for day in schedule.valid_dates)
            if schedule.valid_dates
            else (
                f"{schedule.start_date or 'Start not stated'} → {schedule.end_date or 'End not stated'}"
            )
        )
        if schedule.weekdays:
            dates += "; " + ", ".join(
                ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d - 1]
                for d in schedule.weekdays
            )
        image = images[row.post_id]
        photo = (
            f'<img loading="lazy" alt="Source post image" src="{image}">'
            if image
            else "<p>No source image available</p>"
        )
        url = post.telegram_url
        link = (
            f'<a href="{esc(url, quote=True)}" target="_blank" rel="noopener noreferrer">Open source post</a>'
            if url and urlsplit(url).scheme in {"http", "https"}
            else ""
        )
        eligible = row.status == "candidate"
        warning = "; ".join(row.warnings)
        terms = "\n".join(
            dict.fromkeys(
                normalized_evidence(term)
                for term in [*row.terms, *schedule.restrictions_text]
            )
        )
        cards.append(f'''<article data-status="{row.status}">
<div><p>{index} · {esc(post.source_name)} {post.message_id}</p>
<h2>{esc(row.title)}</h2><p>{esc(row.description)}</p>
<p><strong>{esc(location.label if location else "No explicit location")}</strong> {esc(location.unit or "") if location else ""}</p>
<p>{esc(dates)} · {esc(schedule.date_status)}</p><pre>{esc(terms)}</pre>
<p>{"Ready for location lookup; pin not verified" if eligible else "Skipped: " + esc("; ".join(row.reasons))}</p>
<p>{"Notes: " + esc(warning) if warning else ""}</p>
<label><input class="selection" type="checkbox" value="{esc(row.row_id, quote=True)}" {"disabled" if not eligible else ""}> Include in demo selection</label>
</div><div>{photo}<details><summary>Original caption · posted {post.posted_at.date()}</summary><pre>{esc(post.text)}</pre></details>{link}</div></article>''')
    no_rows = [
        r
        for r in artifact.results
        if not any(row.post_id == r.post_id for row in artifact.rows)
    ]
    outcomes = "".join(
        f"<li>{esc(r.post_id)}: {esc(r.status)} — {esc('; '.join(r.errors) or 'No food offers extracted')}</li>"
        for r in no_rows
    )
    counts = Counter(r.status for r in artifact.rows)
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Food deals · demo review</title><style>
body{{font:16px system-ui;background:#f4f5f0;color:#20372c;max-width:1200px;margin:auto;padding:24px}}
header{{position:sticky;top:0;background:#f4f5f0;padding:12px 0;z-index:1}}h1{{margin:0}}h2{{font-size:1.25rem}}
article{{display:grid;grid-template-columns:1fr 1fr;gap:24px;background:white;padding:24px;margin:20px 0;border-radius:12px}}
img{{max-width:100%;max-height:340px;object-fit:contain}}pre{{white-space:pre-wrap;font:inherit;overflow-wrap:anywhere}}
button,select{{font:inherit;padding:8px;margin:8px 8px 0 0}}[hidden]{{display:none}}@media(max-width:700px){{article{{grid-template-columns:1fr}}}}
</style><header><h1>Food deals · demo review</h1>
<p>Historical source posts · {len(artifact.results)} posts · {len(artifact.rows)} rows · {counts["candidate"]} ready for location lookup</p>
<select id="filter" aria-label="Show rows"><option value="candidate">Ready for location lookup</option><option value="all">All rows, including skipped</option></select>
<button id="export">Download selected row IDs</button><span id="count">0 selected</span></header>
<p>Inspect a small sample (roughly 10–15 cards). Selection is for the demo, not an accuracy score. Map locations will be checked in Phase 3. Original caches are unchanged; advisory notes need not block selection.</p>
{"".join(cards)}<details><summary>Posts with no rows ({len(no_rows)})</summary><ul>{outcomes}</ul></details>
<script>
const boxes = [...document.querySelectorAll('.selection')];
const filter = document.querySelector('#filter');
function show() {{ document.querySelectorAll('article').forEach(a => a.hidden = filter.value !== 'all' && a.dataset.status !== filter.value); }}
filter.addEventListener('change', show); show();
boxes.forEach(b => b.addEventListener('change', () => document.querySelector('#count').textContent = boxes.filter(b => b.checked).length + ' selected'));
document.querySelector('#export').addEventListener('click', () => {{
const row_ids = boxes.filter(b => b.checked && !b.disabled).map(b => b.value);
if (!row_ids.length) {{ alert('Select at least one card first.'); return; }}
const data = {{schema_version:1, dataset_id:{json.dumps(artifact.dataset_id)}, row_ids}};
const url = URL.createObjectURL(new Blob([JSON.stringify(data,null,2)], {{type:'application/json'}}));
const a = document.createElement('a'); a.href=url; a.download='demo-selection.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
}});
</script></html>"""
