"""Normalize the fixed Telegram export batch without network access."""

import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from .config import load_sources
from .models import (
    Exclusion,
    ImportReport,
    InputFile,
    Issue,
    Link,
    Media,
    MediaManifest,
    Posts,
    Source,
    SourcePost,
)
from .storage import atomic_write, error_detail, file_hash, fingerprint, parse_json

SINGAPORE = ZoneInfo("Asia/Singapore")


class Entity(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    type: str
    text: str
    href: str | None = None


class Record(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    id: int = Field(gt=0)
    type: str
    text: str | list[str | Entity]
    text_entities: list[Entity] = Field(default_factory=list)


class Export(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)
    id: int = Field(gt=0)
    name: str
    type: str
    messages: list[dict[str, JsonValue]]


class SourceError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def clickable_url(value: str) -> str | None:
    if not value or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
        return None
    candidate = value
    if "://" not in value:
        # Only recognize a DNS-style hostname, never an arbitrary URI scheme.
        if not re.match(
            r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}(?::[0-9]+)?(?:[/?#]|$)",
            value,
        ):
            return None
        candidate = "https://" + value
    try:
        parts = urlsplit(candidate)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return None
        if parts.username is not None or parts.password is not None:
            return None
        _ = parts.port
    except ValueError:
        return None
    return candidate


def normalize_text(record: Record) -> tuple[str, list[Link]]:
    fragments = record.text if isinstance(record.text, list) else [record.text]
    text = "".join(
        fragment if isinstance(fragment, str) else fragment.text
        for fragment in fragments
    )
    entities = [
        fragment for fragment in fragments if isinstance(fragment, Entity)
    ] + record.text_entities
    links: dict[str, Link] = {}
    for entity in entities:
        if entity.type not in {"link", "text_link"}:
            continue
        destination = entity.text if entity.type == "link" else entity.href
        if not destination:
            raise SourceError("invalid_link", "link entity has no destination")
        link = links.setdefault(
            destination,
            Link(
                destination=destination,
                labels=[],
                clickable_url=clickable_url(destination),
            ),
        )
        if entity.text not in link.labels:
            link.labels.append(entity.text)
    return text, list(links.values())


def timestamp(
    raw: dict[str, JsonValue], key: str, source: Source, warnings: list[str]
) -> datetime | None:
    exported = raw.get(key)
    unix = raw.get(key + "_unixtime")
    if exported is None and unix is None and key == "edited":
        return None
    try:
        local = datetime.fromisoformat(exported) if isinstance(exported, str) else None
        if exported is not None and local is None:
            raise ValueError("date must be a string")
        if local is not None and local.tzinfo is None:
            local = local.replace(tzinfo=ZoneInfo(source.export_timezone))
        if unix is not None:
            if (
                isinstance(unix, bool)
                or not isinstance(unix, (str, int))
                or not re.fullmatch(r"-?\d+", str(unix))
            ):
                raise ValueError("Unix timestamp must be integral seconds")
            result = datetime.fromtimestamp(int(unix), SINGAPORE)
            if local is not None and local != result:
                raise ValueError("Unix timestamp disagrees with exported date")
            if local is None:
                warnings.append(
                    f"{key}: exported date string absent; used Unix timestamp"
                )
            return result
        if local is None:
            raise ValueError("missing timestamp")
        warnings.append(
            f"{key}: Unix timestamp absent; used configured export timezone"
        )
        return local.astimezone(SINGAPORE)
    except (ValueError, OverflowError, OSError) as exc:
        raise SourceError("bad_timestamp", f"{key}: {exc}") from exc


def collect_media(raw: dict[str, JsonValue], root: Path, post_id: str) -> list[Media]:
    result: list[Media] = []
    for kind in ("photo", "file", "thumbnail"):
        if kind not in raw and not (kind == "thumbnail" and "file" in raw):
            continue
        reference = raw.get(kind)
        if reference is not None and not isinstance(reference, str):
            raise SourceError("invalid_media", f"{kind} reference must be a string")
        item = Media(
            media_id=f"{post_id}:{kind}",
            post_id=post_id,
            kind=kind,
            original_reference=reference,
            relative_path=None,
            status="absent",
        )
        if reference is None:
            pass
        elif reference.startswith("(File not included."):
            item.status = "omitted"
        else:
            relative = PurePosixPath(reference)
            try:
                target = (root / reference).resolve()
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or "\\" in reference
                    or not target.is_relative_to(root)
                ):
                    item.status = "unsafe"
                elif not target.is_file():
                    item.status = "missing"
                    item.relative_path = relative.as_posix()
                else:
                    item.status = "available"
                    item.relative_path = relative.as_posix()
                    item.content_hash = file_hash(target.read_bytes())
            except OSError, RuntimeError:
                item.status = "missing"
        result.append(item)
    return result


def normalize(config_path: Path, data_dir: Path) -> ImportReport:
    generated_at = datetime.now(UTC)
    counts: Counter[str] = Counter(
        raw_records=0,
        candidates=0,
        excluded=0,
        invalid_records=0,
        present_photos=0,
        unavailable_attachments=0,
        missing_photos=0,
        bad_timestamps=0,
        duplicate_source_keys=0,
    )
    errors: list[Issue] = []
    warnings: list[Issue] = []
    exclusions: list[Exclusion] = []
    inputs: list[InputFile] = []
    posts: list[SourcePost] = []
    media: list[Media] = []
    config_hash = "unavailable"
    try:
        config = load_sources(config_path)
        config_hash = fingerprint(config.model_dump(mode="json"))
    except (OSError, ValueError, KeyError) as exc:
        errors.append(
            Issue(
                code="invalid_config", source=config_path.name, detail=error_detail(exc)
            )
        )
        config = None
    seen: set[str] = set()
    for source in sorted(config.sources if config else [], key=lambda s: s.channel_id):
        root = (config_path.parent / source.export_root).resolve()
        source_file = f"{source.export_root}/result.json"
        try:
            path = root / "result.json"
            content = path.read_bytes()
            inputs.append(
                InputFile(
                    channel_id=source.channel_id,
                    source_file=source_file,
                    content_hash=file_hash(content),
                )
            )
            export = Export.model_validate(parse_json(content))
            if export.id != source.channel_id or export.type != "public_channel":
                raise ValueError(
                    "export channel ID/type does not match configured public channel"
                )
        except (OSError, ValueError) as exc:
            errors.append(
                Issue(
                    code="invalid_export", source=source.name, detail=error_detail(exc)
                )
            )
            continue
        for raw in export.messages:
            counts["raw_records"] += 1
            message_id = raw.get("id")
            try:
                record = Record.model_validate(raw)
                post_id = f"telegram:{source.channel_id}:{record.id}"
                if post_id in seen:
                    raise SourceError(
                        "duplicate_source_keys", "duplicate channel/message key"
                    )
                seen.add(post_id)
                text, links = normalize_text(record)
                date_warnings: list[str] = []
                posted_at = timestamp(raw, "date", source, date_warnings)
                edited_at = timestamp(raw, "edited", source, date_warnings)
                if posted_at is None:
                    raise SourceError("bad_timestamp", "posting date is required")
                if edited_at is not None and edited_at < posted_at:
                    raise SourceError(
                        "bad_timestamp", "editing timestamp precedes posting timestamp"
                    )
                for detail in date_warnings:
                    warnings.append(
                        Issue(
                            code="timestamp_fallback",
                            source=source.name,
                            message_id=record.id,
                            detail=detail,
                        )
                    )
                reason = None
                if record.type == "service" and raw.get("action") == "pin_message":
                    reason = "pin_service"
                elif record.type == "message" and not text.strip() and "poll" in raw:
                    reason = "empty_poll"
                elif record.type != "message" or not text.strip():
                    raise SourceError(
                        "unsupported_record", "unsupported record type or empty caption"
                    )
                if reason is not None:
                    exclusions.append(
                        Exclusion(post_id=post_id, reason=reason, raw_record=raw)
                    )
                    counts["excluded"] += 1
                    counts[reason] += 1
                    continue
                attachments = collect_media(raw, root, post_id)
                for item in attachments:
                    counts[f"media_{item.kind}_{item.status}"] += 1
                    if item.kind == "photo":
                        counts["present_photos"] += item.status == "available"
                        counts["missing_photos"] += item.status != "available"
                    if item.kind == "file":
                        counts["unavailable_attachments"] += item.status != "available"
                    if item.status in {"missing", "unsafe"}:
                        warnings.append(
                            Issue(
                                code="unavailable_media",
                                source=source.name,
                                message_id=record.id,
                                detail=f"{item.kind}: {item.status}",
                            )
                        )
                # This payload defines model-visible context for the next stage.
                extraction_input = {
                    "text": text,
                    "links": [link.model_dump() for link in links],
                    "posted_at": posted_at.isoformat(),
                    "edited_at": edited_at.isoformat() if edited_at else None,
                    "timezone": "Asia/Singapore",
                    "channel_id": source.channel_id,
                    "source_name": source.name,
                    "username": source.username,
                }
                posts.append(
                    SourcePost(
                        post_id=post_id,
                        channel_id=source.channel_id,
                        message_id=record.id,
                        source_name=source.name,
                        username=source.username,
                        telegram_url=f"https://t.me/{source.username}/{record.id}"
                        if source.username
                        else None,
                        posted_at=posted_at,
                        edited_at=edited_at,
                        text=text,
                        links=links,
                        media_ids=[item.media_id for item in attachments],
                        source_file=source_file,
                        source_content_hash=fingerprint(raw),
                        extraction_input_hash=fingerprint(extraction_input),
                        raw_record=raw,
                    )
                )
                media.extend(attachments)
                counts["candidates"] += 1
            except (ValueError, OSError) as exc:
                code = exc.code if isinstance(exc, SourceError) else "invalid_record"
                if code == "bad_timestamp":
                    counts["bad_timestamps"] += 1
                if code == "duplicate_source_keys":
                    counts["duplicate_source_keys"] += 1
                counts["invalid_records"] += 1
                errors.append(
                    Issue(
                        code=code,
                        source=source.name,
                        message_id=message_id if type(message_id) is int else None,
                        detail=error_detail(exc),
                    )
                )
    posts.sort(key=lambda post: (post.channel_id, post.message_id))
    media.sort(key=lambda item: (*map(int, item.post_id.split(":")[1:]), item.kind))
    exclusions.sort(key=lambda item: tuple(map(int, item.post_id.split(":")[1:])))
    counts["errors"] = len(errors)
    counts["warnings"] = len(warnings)
    identity = {
        "schema_version": 1,
        "config_hash": config_hash,
        "inputs": [item.model_dump() for item in inputs],
        "posts": [post.model_dump(mode="json") for post in posts],
        "media": [item.model_dump() for item in media],
    }
    dataset_id = fingerprint(identity)
    report = ImportReport(
        dataset_id=dataset_id,
        generated_at=generated_at,
        status="failed" if errors else "success",
        config_hash=config_hash,
        inputs=inputs,
        counts=dict(sorted(counts.items())),
        exclusions=exclusions,
        errors=errors,
        warnings=warnings,
    )
    if not errors:
        snapshot = Posts(dataset_id=dataset_id, generated_at=generated_at, posts=posts)
        manifest = MediaManifest(
            dataset_id=dataset_id, generated_at=generated_at, media=media
        )
        atomic_write(data_dir / "intermediate" / "media.json", manifest)
        atomic_write(data_dir / "intermediate" / "posts.json", snapshot)
    # Report is the completion marker. Readers must require success and matching IDs.
    atomic_write(data_dir / "reports" / "normalize.json", report)
    return report
