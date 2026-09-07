"""Validated mapped-only publication without provider requests."""

import os
import tempfile
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import load_sources
from .geocoding import (
    apply_decision,
    load_decisions,
    load_geocoding_report,
    load_inputs,
    location_hash,
    places,
    row_decision,
    selection_hash,
)
from .geocoding_models import QueryCache
from .models import MediaManifest, SourcePost
from .nominatim import load_cache, state_root, utc_now, writer_lock
from .public_models import (
    Attribution,
    PublicDeal,
    PublicMedia,
    PublishedDataset,
    safe_url,
)
from .storage import atomic_write, file_hash, fingerprint, load_normalized, read_json


def copy_media(
    data_dir: Path,
    sources_path: Path,
    manifest: MediaManifest,
    posts: list[SourcePost],
) -> tuple[list[PublicMedia], dict[str, list[str]]]:
    sources = load_sources(sources_path)
    roots = {
        s.channel_id: (sources_path.parent / s.export_root).resolve()
        for s in sources.sources
    }
    wanted = {p.post_id: p for p in posts}
    by_post: dict[str, list[str]] = {p.post_id: [] for p in posts}
    assets = []
    directory = data_dir / "published/media"
    for item in manifest.media:
        post = wanted.get(item.post_id)
        if post is None or item.kind != "photo":
            continue
        if item.status == "unsafe":
            raise ValueError(
                "unsafe selected media must be resolved before publication"
            )
        if item.status != "available" or not item.relative_path:
            continue
        root = roots.get(post.channel_id)
        if root is None:
            raise ValueError("missing source configuration for published media")
        path = (root / item.relative_path).resolve()
        if not path.is_relative_to(root):
            raise ValueError("published media escapes configured source root")
        if not path.exists():
            continue
        content = path.read_bytes()
        digest = file_hash(content)
        if digest != item.content_hash:
            raise ValueError("selected media content hash changed")
        if content.startswith(b"\xff\xd8\xff"):
            extension, mime = "jpg", "image/jpeg"
        elif content.startswith(b"\x89PNG\r\n\x1a\n"):
            extension, mime = "png", "image/png"
        else:
            raise ValueError("unsupported selected image signature")
        asset = PublicMedia.model_validate(
            {
                "media_id": item.media_id,
                "filename": f"{digest}.{extension}",
                "content_hash": digest,
                "mime_type": mime,
            }
        )
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / asset.filename
        if target.is_symlink():
            raise ValueError("published media target is a symlink")
        if not target.exists() or file_hash(target.read_bytes()) != digest:
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        assets.append(asset)
        by_post[item.post_id].append(item.media_id)
    return assets, by_post


def publish(
    data_dir: Path,
    selection_path: Path,
    *,
    allow_partial: bool = False,
    decisions_path: Path | None = None,
    sources_path: Path = Path("config/sources.json"),
) -> PublishedDataset:
    with writer_lock(state_root()):
        demo, selection, selected = load_inputs(data_dir, selection_path)
        report, resolutions = load_geocoding_report(data_dir)
        decisions = load_decisions(
            decisions_path or data_dir / "overrides/geocoding.json", selected
        )
        if (
            resolutions.demo_dataset_id != demo.dataset_id
            or resolutions.source_dataset_id != demo.source_dataset_id
            or resolutions.selection_fingerprint != selection_hash(selection)
            or resolutions.decisions_fingerprint
            != fingerprint(decisions.model_dump(mode="json"))
            or {r.row_id for r in resolutions.rows} != set(selection.row_ids)
            or len(resolutions.rows) != len(selection.row_ids)
        ):
            raise ValueError("stale selection/decisions; rerun geocode --offline")
        lookup = {r.row_id: r for r in selected}
        for result in resolutions.rows:
            if result.location_fingerprint != location_hash(lookup[result.row_id]):
                raise ValueError("stale location resolution")
            verified_places = []
            for key, digest in result.cache_fingerprints.items():
                if not re_full_hash(key):
                    raise ValueError("invalid query cache key")
                entry = QueryCache.model_validate(
                    read_json(data_dir / f"cache/geocoding/{key}.json")
                )
                verified = load_cache(
                    data_dir / f"cache/geocoding/{key}.json", entry.query
                )
                shared = load_cache(state_root() / f"cache/{key}.json", entry.query)
                if (
                    verified is None
                    or fingerprint(verified.model_dump(mode="json")) != digest
                    or (
                        shared is not None
                        and fingerprint(shared.model_dump(mode="json")) != digest
                    )
                ):
                    raise ValueError(
                        "query response changed; rerun matching and pin review"
                    )
                verified_places.extend(places(verified))
            if any(place not in verified_places for place in result.candidates):
                raise ValueError(
                    "resolution candidate differs from cached provider evidence"
                )
            checked = result.model_copy(deep=True)
            checked.review = "pending"
            checked.coordinates = None
            checked.precision = None
            checked.resolved_label = None
            checked.decision_id = None
            apply_decision(checked, row_decision(decisions, result.row_id))
            if checked != result:
                raise ValueError("resolution does not match reviewed decisions")
        approved = [r for r in resolutions.rows if r.review == "approved"]
        if not approved:
            raise ValueError("no approved pins; preserving the last published snapshot")
        posts, manifest, _ = load_normalized(data_dir)
        post_lookup = {p.post_id: p for p in posts.posts}
        processed = sum(r.status in {"success", "needs_review"} for r in demo.results)
        complete = (
            processed == len(posts.posts)
            and len(selected) == len(demo.rows)
            and len(approved) == len(selected)
            and not report.errors
        )
        if not complete and not allow_partial:
            raise ValueError("incomplete demo requires publish --allow-partial")
        public_posts = [
            post_lookup[p] for p in sorted({lookup[r.row_id].post_id for r in approved})
        ]
        assets, by_post = copy_media(data_dir, sources_path, manifest, public_posts)
        deals = []
        for result in approved:
            row = lookup[result.row_id]
            post = post_lookup[row.post_id]
            if (
                result.coordinates is None
                or result.precision is None
                or not result.resolved_label
                or row.location is None
            ):
                raise ValueError("approved pin lacks required public fields")
            media_ids = by_post[post.post_id]
            deals.append(
                PublicDeal(
                    **result.coordinates.model_dump(),
                    deal_id=row.row_id,
                    post_id=row.post_id,
                    offer_id=row.offer_id,
                    source_name=post.source_name,
                    title=row.title,
                    description=row.description,
                    merchant=row.merchant,
                    terms=row.terms,
                    availability=row.availability,
                    posted_at=post.posted_at,
                    source_caption=post.text,
                    telegram_url=safe_url(post.telegram_url),
                    information_links=[
                        url
                        for link in post.links
                        if (url := safe_url(link.clickable_url))
                    ],
                    location_label=row.location.label,
                    unit=row.location.unit,
                    location_scope=row.location_scope,
                    resolved_label=result.resolved_label,
                    precision=result.precision,
                    media_ids=media_ids,
                    image_url=f"/media/{media_ids[0]}" if media_ids else None,
                )
            )
        summary = {
            "source_posts": len(posts.posts),
            "extracted_posts": processed,
            "unprocessed_posts": len(posts.posts) - len(demo.results),
            "failed_extraction_posts": len(demo.results) - processed,
            "selected_posts": len({r.post_id for r in selected}),
            "selected_rows": len(selected),
            "published_rows": len(deals),
            "omitted_rows": len(selected) - len(deals),
        }
        summary.update(
            {
                f"omitted_{key}": value
                for key, value in Counter(
                    r.outcome if r.review == "pending" else r.review
                    for r in resolutions.rows
                    if r.review != "approved"
                ).items()
            }
        )
        sg = ZoneInfo("Asia/Singapore")
        source_dates = [p.posted_at.astimezone(sg).date() for p in posts.posts]
        selected_dates = [
            post_lookup[r.post_id].posted_at.astimezone(sg).date() for r in selected
        ]
        snapshot = PublishedDataset(
            dataset_id="pending",
            generated_at=utc_now(),
            source_dataset_id=posts.dataset_id,
            demo_dataset_id=demo.dataset_id,
            selection_fingerprint=selection_hash(selection),
            resolution_dataset_id=resolutions.dataset_id,
            source_date_range=(min(source_dates), max(source_dates)),
            selected_source_date_range=(min(selected_dates), max(selected_dates)),
            suggested_reference_date=max(selected_dates),
            dataset_complete=complete,
            processing_summary=summary,
            attribution=[Attribution()],
            media=assets,
            deals=deals,
        )
        snapshot.dataset_id = fingerprint(
            snapshot.model_dump(mode="json", exclude={"dataset_id", "generated_at"})
        )
        atomic_write(data_dir / "published/deals.json", snapshot)
        return snapshot


def re_full_hash(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)
