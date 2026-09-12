"""Sequential, resumable extraction with inspectable outcomes for every source post."""

import time
from collections import Counter
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

from pydantic import AwareDatetime, Field, JsonValue

from .extraction_models import (
    Candidate,
    CandidateArtifact,
    Corrections,
    Extraction,
    ExtractionArtifact,
    ExtractionReport,
    PostResult,
)
from .extraction_prompt import post_input
from .extraction_validation import apply_corrections, expand
from .llm_budget import STATE_DIR, Budget, BudgetStop, Receipt, utc_now, writer_lock
from .models import Contract, SourcePost
from .openrouter import (
    OpenRouter,
    ProviderError,
    Settings,
    parse_response,
    response_cost,
)
from .storage import atomic_write, error_detail, fingerprint, load_normalized, read_json


class Client(Protocol):
    def preflight(self) -> Decimal: ...
    def complete(self, post: SourcePost, repair: bool = False) -> JsonValue: ...


class CacheEntry(Contract):
    schema_version: Literal[1] = 1
    cache_key: str
    post_id: str
    input_hash: str
    settings: dict[str, JsonValue]
    attempt_id: str
    saved_at: AwareDatetime
    raw: JsonValue
    extraction: Extraction | None
    error: str | None


class PilotReview(Contract):
    schema_version: Literal[1] = 1
    reviewed_at: AwareDatetime
    accepted: Literal[True]
    settings_hash: str
    # Bind approval to the precise raw pilot outputs, before manual corrections.
    cache_fingerprints: dict[str, str] = Field(min_length=30, max_length=30)


def cache_key(post: SourcePost, settings: Settings) -> str:
    if fingerprint(post_input(post)) != post.extraction_input_hash:
        raise ValueError(f"extraction input fingerprint mismatch: {post.post_id}")
    return fingerprint(
        {
            "post_id": post.post_id,
            "input": post.extraction_input_hash,
            "settings": settings.identity(),
        }
    )


def select_posts(
    posts: list[SourcePost], id_file: Path | None, limit: int | None
) -> list[SourcePost]:
    selected = posts
    if id_file is not None:
        ids = read_json(id_file)
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            raise ValueError("pilot ID file must be a JSON array of source IDs")
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate pilot IDs")
        unknown = set(ids) - {post.post_id for post in posts}
        if unknown:
            raise ValueError(f"unknown pilot IDs: {sorted(unknown)}")
        selected = [post for post in posts if post.post_id in ids]
        counts = Counter(post.channel_id for post in selected)
        if len(selected) != 30 or len(counts) != 3 or set(counts.values()) != {10}:
            raise ValueError(
                "pilot must contain exactly 10 candidates from each of three channels"
            )
        if limit is not None and limit < 30:
            raise ValueError("--limit cannot truncate the balanced 30-post pilot")
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be positive")
        selected = selected[:limit]
    return selected


def cached(path: Path, post: SourcePost, key: str) -> CacheEntry | None:
    if not path.exists():
        return None
    entry = CacheEntry.model_validate(read_json(path))
    if (entry.cache_key, entry.post_id, entry.input_hash) != (
        key,
        post.post_id,
        post.extraction_input_hash,
    ):
        raise ValueError("cache identity mismatch")
    if entry.extraction is not None and entry.extraction != parse_response(entry.raw):
        raise ValueError("cached extraction differs from raw response")
    return entry


def checkpoint(
    post: SourcePost,
    settings: Settings,
    receipt: Receipt,
    directory: Path,
    *,
    persist: bool = True,
) -> CacheEntry:
    extracted = None
    error = receipt.error
    if error is None:
        try:
            extracted = parse_response(receipt.raw)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            error = error_detail(exc)
    entry = CacheEntry(
        cache_key=receipt.cache_key,
        post_id=post.post_id,
        input_hash=post.extraction_input_hash,
        settings=settings.identity(),
        attempt_id=receipt.attempt_id,
        saved_at=utc_now(),
        raw=receipt.raw,
        extraction=extracted,
        error=error,
    )
    if persist:
        atomic_write(directory / f"{receipt.cache_key}.json", entry)
    return entry


def validate_pilot_review(
    path: Path | None, posts: list[SourcePost], settings: Settings, directory: Path
) -> None:
    if path is None:
        raise ValueError(
            "additional paid work requires --accept-demo or legacy --pilot-review approval"
        )
    review = PilotReview.model_validate(read_json(path))
    if review.settings_hash != fingerprint(settings.identity()):
        raise ValueError("pilot review settings are stale")
    selected = [post for post in posts if post.post_id in review.cache_fingerprints]
    counts = Counter(post.channel_id for post in selected)
    if len(selected) != 30 or len(counts) != 3 or set(counts.values()) != {10}:
        raise ValueError("pilot review must cover 10 posts per channel")
    for post in selected:
        key = cache_key(post, settings)
        entry = cached(directory / f"{key}.json", post, key)
        if (
            entry is None
            or entry.extraction is None
            or fingerprint(entry.model_dump(mode="json"))
            != review.cache_fingerprints[post.post_id]
        ):
            raise ValueError(
                f"pilot review cache is missing, failed or changed: {post.post_id}"
            )


def extract(
    data_dir: Path,
    settings: Settings,
    *,
    dry_run: bool = False,
    post_ids: Path | None = None,
    limit: int | None = None,
    resume: bool = False,
    refresh: bool = False,
    corrections_path: Path | None = None,
    pilot_review: Path | None = None,
    accept_demo: bool = False,
    client: Client | None = None,
    state_dir: Path = STATE_DIR,
    progress: Callable[[str], None] | None = None,
) -> ExtractionReport:
    # Validate source completion BEFORE selection, recovery, locking or provider access.
    posts, _media, source_report = load_normalized(data_dir)
    ordered = sorted(posts.posts, key=lambda post: (post.channel_id, post.message_id))
    selected = select_posts(ordered, post_ids, limit)
    keys = {post.post_id: cache_key(post, settings) for post in ordered}
    corrections = (
        Corrections.model_validate(read_json(corrections_path))
        if corrections_path
        else Corrections(corrections=[])
    )
    if len({item.correction_id for item in corrections.corrections}) != len(
        corrections.corrections
    ):
        raise ValueError("duplicate correction IDs")
    for correction in corrections.corrections:
        if (
            correction.post_id not in keys
            or keys[correction.post_id] != correction.cache_key
        ):
            raise ValueError(f"stale or unknown correction {correction.correction_id}")
    if resume and refresh:
        raise ValueError("--resume and --refresh are mutually exclusive")
    cache_dir = state_dir / "cache"
    if dry_run:
        return build_outputs(
            data_dir,
            ordered,
            selected,
            keys,
            settings,
            corrections,
            posts.dataset_id,
            source_report.counts,
            cache_dir,
            Budget(state_dir),
            [],
            dry_run=True,
        )
    with writer_lock(state_dir):
        budget = Budget(state_dir)
        receipts = {receipt.attempt_id: receipt for receipt in budget.recover()}
        by_key = {keys[post.post_id]: post for post in ordered}
        latest = {attempt.cache_key: attempt for attempt in budget.ledger.attempts}
        # Recover responses written before a crash, and never resurrect a pre-refresh success.
        for key, attempt in latest.items():
            if key not in by_key:
                continue
            post = by_key[key]
            entry = cached(cache_dir / f"{key}.json", post, key)
            if entry is None or entry.attempt_id != attempt.attempt_id:
                receipt = receipts.get(attempt.attempt_id) or Receipt(
                    attempt_id=attempt.attempt_id,
                    cache_key=key,
                    raw=None,
                    cost=None,
                    error="interrupted attempt; charge unknown and reservation retained",
                )
                checkpoint(post, settings, receipt, cache_dir)
        pending = []
        reused = 0
        for post in selected:
            entry = cached(
                cache_dir / f"{keys[post.post_id]}.json", post, keys[post.post_id]
            )
            if entry is None or refresh or (resume and entry.extraction is None):
                pending.append(post)
            elif entry.extraction is not None:
                reused += 1
        if pending and post_ids is None and not accept_demo:
            validate_pilot_review(pilot_review, ordered, settings, cache_dir)
        # Check every correction before any paid work; malformed corrections cannot waste funds.
        for post in ordered:
            if any(item.post_id == post.post_id for item in corrections.corrections):
                entry = cached(
                    cache_dir / f"{keys[post.post_id]}.json", post, keys[post.post_id]
                )
                result = PostResult(
                    post_id=post.post_id,
                    input_hash=post.extraction_input_hash,
                    cache_key=keys[post.post_id],
                    status="pending",
                    extraction=entry.extraction.model_copy(deep=True)
                    if entry and entry.extraction
                    else None,
                )
                apply_corrections(post, result, corrections)
        errors: list[str] = []
        attempts = 0
        if progress is not None:
            progress(
                f"extract: {len(selected)} selected, {len(pending)} to request, "
                f"{reused} cached"
            )
        try:
            adapter = (client or OpenRouter(settings)) if pending else None
            if adapter is not None:
                maximum = adapter.preflight()
                for index, post in enumerate(pending, start=1):
                    repaired = False
                    retries = 0
                    entry: CacheEntry | None = None
                    while True:
                        if attempts >= settings.max_attempts:
                            raise BudgetStop("run attempt limit reached")
                        attempt = budget.reserve(
                            post.post_id,
                            keys[post.post_id],
                            maximum,
                            settings.max_total_attempts,
                            pricing_evidence=getattr(adapter, "pricing_evidence", None),
                        )
                        attempts += 1
                        try:
                            raw = adapter.complete(post, repair=repaired)
                        except ProviderError as exc:
                            # Transport/errors can be billable. Preserve the entire reservation.
                            budget.record(attempt, None, None, str(exc))
                            receipt = Receipt.model_validate(
                                read_json(
                                    state_dir
                                    / "receipts"
                                    / f"{attempt.attempt_id}.json"
                                )
                            )
                            entry = checkpoint(post, settings, receipt, cache_dir)
                            if not exc.transient:
                                raise
                            if repaired or retries >= settings.retries:
                                break
                            if exc.retry_after > 60:
                                raise ProviderError(
                                    "provider Retry-After exceeds 60 seconds; resume later"
                                ) from exc
                            time.sleep(max(exc.retry_after, min(2**retries, 10)))
                            retries += 1
                            continue
                        try:
                            cost = response_cost(raw)
                        except BudgetStop:
                            budget.record(
                                attempt,
                                raw,
                                None,
                                "invalid usage cost; reservation retained",
                            )
                            raise
                        budget.record(attempt, raw, cost, None)
                        receipt = Receipt.model_validate(
                            read_json(
                                state_dir / "receipts" / f"{attempt.attempt_id}.json"
                            )
                        )
                        entry = checkpoint(post, settings, receipt, cache_dir)
                        if isinstance(raw, dict) and raw.get("error"):
                            detail = raw["error"]
                            code = (
                                detail.get("code") if isinstance(detail, dict) else None
                            )
                            if code not in {408, 429, 500, 502, 503, 504}:
                                raise ProviderError(
                                    "OpenRouter returned an authentication/configuration or unknown error"
                                )
                            if repaired or retries >= settings.retries:
                                break
                            time.sleep(min(2**retries, 10))
                            retries += 1
                            continue
                        if entry.extraction is not None:
                            break
                        if repaired:
                            break
                        repaired = True
                    if progress is not None and entry is not None:
                        detail = entry.error or (
                            f"{len(entry.extraction.offers)} offers"
                            if entry.extraction is not None
                            else "no extraction"
                        )
                        progress(
                            f"extract: [{index}/{len(pending)}] {post.post_id}: {detail}"
                        )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(error_detail(exc))
        return build_outputs(
            data_dir,
            ordered,
            selected,
            keys,
            settings,
            corrections,
            posts.dataset_id,
            source_report.counts,
            cache_dir,
            budget,
            errors,
            attempts_this_run=attempts,
            reused=reused,
        )


def build_outputs(
    data_dir: Path,
    posts: list[SourcePost],
    selected: list[SourcePost],
    keys: dict[str, str],
    settings: Settings,
    corrections: Corrections,
    source_dataset_id: str,
    source_counts: dict[str, int],
    cache_dir: Path,
    budget: Budget,
    errors: list[str],
    *,
    dry_run: bool = False,
    attempts_this_run: int = 0,
    reused: int | None = None,
) -> ExtractionReport:
    selected_ids = {post.post_id for post in selected}
    results: list[PostResult] = []
    rows: list[Candidate] = []
    counts: Counter[str] = Counter(
        raw_records=source_counts.get("raw_records", 0),
        text_candidates=len(posts),
        selected=len(selected),
    )
    cache_fingerprints = {}
    latest = {attempt.cache_key: attempt for attempt in budget.ledger.attempts}
    for post in posts:
        key = keys[post.post_id]
        result = PostResult(
            post_id=post.post_id,
            input_hash=post.extraction_input_hash,
            cache_key=key,
            status="not_selected" if post.post_id not in selected_ids else "pending",
        )
        entry = cached(cache_dir / f"{key}.json", post, key)
        attempt = latest.get(key)
        if (
            dry_run
            and attempt
            and (entry is None or entry.attempt_id != attempt.attempt_id)
        ):
            receipt_path = budget.directory / "receipts" / f"{attempt.attempt_id}.json"
            receipt = (
                Receipt.model_validate(read_json(receipt_path))
                if receipt_path.exists()
                else Receipt(
                    attempt_id=attempt.attempt_id,
                    cache_key=key,
                    raw=None,
                    cost=None,
                    error="interrupted attempt; charge unknown and reservation retained",
                )
            )
            if (receipt.attempt_id, receipt.cache_key) != (attempt.attempt_id, key):
                raise ValueError("receipt identity differs from reservation")
            entry = checkpoint(post, settings, receipt, cache_dir, persist=False)
        if post.post_id in selected_ids:
            counts[
                "cache_hits"
                if entry and entry.extraction is not None
                else "cache_misses"
            ] += 1
            if entry is not None:
                result.extraction = (
                    entry.extraction.model_copy(deep=True) if entry.extraction else None
                )
                result.status = "success" if entry.extraction else "failed"
                result.errors = [entry.error] if entry.error else []
                cache_fingerprints[post.post_id] = fingerprint(
                    entry.model_dump(mode="json")
                )
                if not dry_run:
                    atomic_write(data_dir / "cache/llm" / f"{key}.json", entry)
            if result.extraction:
                try:
                    apply_corrections(post, result, corrections)
                    rows.extend(expand(post, result))
                except ValueError as exc:
                    result.status = "needs_review"
                    result.errors.append(error_detail(exc))
                counts[f"relevance_{result.extraction.relevance}"] += 1
                counts[f"promotion_{result.extraction.promotion_kind}"] += 1
                counts["offers"] += len(result.extraction.offers)
        results.append(result)
        counts[f"status_{result.status}"] += 1
    counts["explicit_location_rows"] = sum(row.location is not None for row in rows)
    counts.update(f"row_{row.status}" for row in rows)
    counts["attempts_this_run"] = attempts_this_run
    if reused is not None:
        counts["cache_hits"] = reused
        counts["cache_misses"] = len(selected) - reused
    identity = {
        "source_dataset_id": source_dataset_id,
        "settings": settings.identity(),
        "results": [item.model_dump(mode="json") for item in results],
        "rows": [row.model_dump(mode="json") for row in rows],
    }
    dataset_id = fingerprint(identity)
    generated_at = utc_now()
    replacements = {}
    previous_path = data_dir / "intermediate/candidates.json"
    if previous_path.exists():
        previous = CandidateArtifact.model_validate(read_json(previous_path))
        for post in selected:
            before = {
                row.row_id for row in previous.rows if row.post_id == post.post_id
            }
            after = {row.row_id for row in rows if row.post_id == post.post_id}
            if before and before != after:
                replacements[post.post_id] = {
                    "removed": sorted(before - after),
                    "added": sorted(after - before),
                }
    report = ExtractionReport(
        dataset_id=dataset_id,
        generated_at=generated_at,
        source_dataset_id=source_dataset_id,
        settings_hash=fingerprint(settings.identity()),
        status="dry_run"
        if dry_run
        else "failed"
        if errors
        else "partial"
        if len(selected) != len(posts)
        or any(r.status in {"failed", "pending"} for r in results)
        else "success",
        selected_ids=[post.post_id for post in selected],
        counts=dict(sorted(counts.items())),
        errors=errors,
        outcomes={item.post_id: item.status for item in results},
        review={item.post_id: item.errors for item in results if item.errors},
        budget=budget.summary(),
        replacements=replacements,
        cache_fingerprints=cache_fingerprints,
    )
    if not dry_run:
        atomic_write(
            data_dir / "intermediate/extractions.json",
            ExtractionArtifact(
                dataset_id=dataset_id,
                generated_at=generated_at,
                source_dataset_id=source_dataset_id,
                settings_hash=report.settings_hash,
                results=results,
            ),
        )
        atomic_write(
            data_dir / "intermediate/candidates.json",
            CandidateArtifact(
                dataset_id=dataset_id,
                generated_at=generated_at,
                source_dataset_id=source_dataset_id,
                rows=rows,
            ),
        )
        atomic_write(data_dir / "reports/extract.json", report)
    return report


def load_extraction_report(data_dir: Path) -> ExtractionReport:
    posts, _, _ = load_normalized(data_dir)
    report = ExtractionReport.model_validate(
        read_json(data_dir / "reports/extract.json")
    )
    extractions = ExtractionArtifact.model_validate(
        read_json(data_dir / "intermediate/extractions.json")
    )
    candidates = CandidateArtifact.model_validate(
        read_json(data_dir / "intermediate/candidates.json")
    )
    if not (report.dataset_id == extractions.dataset_id == candidates.dataset_id):
        raise ValueError("extraction artifact dataset IDs differ; rerun extract")
    if any(
        artifact.source_dataset_id != posts.dataset_id
        for artifact in (report, extractions, candidates)
    ):
        raise ValueError(
            "extraction artifacts refer to a different normalization dataset"
        )
    return report
