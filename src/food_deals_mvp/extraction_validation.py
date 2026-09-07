"""Grounding checks, reviewed field patches, and deterministic offer/location rows."""

import re
from collections import Counter

from .availability import DATE_FIELDS, effective_availability, singapore_date
from .extraction_models import Candidate, Corrections, Extraction, PostResult
from .models import SourcePost
from .storage import fingerprint


def canonical(value: object) -> object:
    """Semantic collections are unordered; provider array order cannot change IDs."""
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return sorted((canonical(item) for item in value), key=fingerprint)
    return value


def semantic_hash(value: object) -> str:
    return fingerprint(canonical(value))


def normalized_evidence(text: str) -> str:
    """Repair the observed malformed emoji encoding; ignore decoration, not facts."""
    text = re.sub(
        "\x01[fF][0-9a-fA-F]{3}",
        lambda match: chr(int("1" + match[0][1:], 16)),
        text,
    )
    # Food/presentation emoji are not factual evidence. Keep negation symbols,
    # currency, keycap digits, non-Latin words, and punctuation intact.
    text = re.sub(
        r"[\U0001f300-\U0001faff]",
        lambda m: m[0] if m[0] in "🚫🔞🚭🚷📵🚯🚳🚱" else "",
        text,
    )
    text = re.sub("\x00(?:23[bBfF]0|[fF][eE]0[fF])", "", text)
    # Only standalone control noise: controls fused with numbers/words may have
    # corrupted actual facts and must still fail the evidence check.
    text = re.sub(r"(?<!\S)[\x00-\x08\x0b\x0c\x0e-\x1f]+e?(?!\S)", "", text)
    return " ".join(text.translate(str.maketrans("", "", "✨⏰⏱➡👉❗️︎")).split())


def supported_excerpt(quote: str, caption: str) -> bool:
    normalized = normalized_evidence(quote)
    return bool(normalized) and normalized in normalized_evidence(caption)


def check_evidence(value: object, caption: str) -> list[str]:
    issues: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {
                "evidence",
                "exception_evidence",
                "restrictions_text",
                "remove_restrictions",
                "terms",
            }:
                if isinstance(item, list):
                    textual = [
                        q for q in item if isinstance(q, str) and normalized_evidence(q)
                    ]
                    if (
                        any(not isinstance(q, str) or not q.strip() for q in item)
                        or (item and not textual)
                        or any(not supported_excerpt(q, caption) for q in textual)
                    ):
                        issues.append(f"{key} contains unsupported caption excerpts")
            else:
                issues.extend(check_evidence(item, caption))
    elif isinstance(value, list):
        for item in value:
            issues.extend(check_evidence(item, caption))
    return list(dict.fromkeys(issues))


def expand(post: SourcePost, result: PostResult) -> list[Candidate]:
    extraction = result.extraction
    if extraction is None:
        return []
    global_issues: list[str] = []
    result.warnings = list(extraction.review_reasons)
    result.warnings.extend(check_evidence({"evidence": extraction.evidence}, post.text))
    if extraction.promotion_kind == "uncertain":
        result.warnings.append("uncertain promotion taxonomy")
    if extraction.relevance == "uncertain":
        global_issues.append("uncertain classification")
    if extraction.relevance == "non_food":
        if extraction.offers:
            global_issues.append("non-food response contains offers")
        result.errors = list(dict.fromkeys([*result.errors, *global_issues]))
        result.status = "needs_review" if result.errors else "success"
        return []
    rows: list[Candidate] = []
    seen_offers: set[str] = set()
    for offer in extraction.offers:
        identity = offer.model_dump(
            mode="json", exclude={"locations", "evidence", "review_reasons"}
        )
        offer_id = f"{post.post_id}:offer:{semantic_hash(identity)[:24]}"
        if offer_id in seen_offers:
            global_issues.append("duplicate semantic offers")
        seen_offers.add(offer_id)
        issues = [
            *global_issues,
            *check_evidence(
                offer.model_dump(mode="json", exclude={"locations"}), post.text
            ),
        ]
        if (
            any(getattr(offer.availability, field) is not None for field in DATE_FIELDS)
            and not offer.availability.evidence
        ):
            issues.append("shared asserted dates lack their own evidence")
        if offer.location_scope == "online_only" and offer.locations:
            issues.append("online-only offer contains physical locations")
        if offer.location_scope == "explicit" and not offer.locations:
            issues.append("explicit scope has no location")
        if (
            offer.locations
            and offer.location_scope in {"all_outlets", "selected_outlets"}
            and not offer.incomplete_scope_note
        ):
            issues.append(
                "partially enumerated outlet scope lacks an incompleteness note"
            )
        relative = re.search(
            r"\b(today|tomorrow|tonight|now)\b",
            " ".join(
                [
                    *offer.availability.evidence,
                    *[
                        quote
                        for loc in offer.locations
                        if loc.availability_override
                        for quote in loc.availability_override.evidence
                    ],
                ]
            ),
            re.IGNORECASE,
        )
        if (
            relative
            and post.edited_at
            and singapore_date(post.edited_at) != singapore_date(post.posted_at)
        ):
            issues.append("edited post has ambiguous relative date wording")
        seen_locations: set[str] = set()
        for location in offer.locations or [None]:
            local_issues = list(issues)
            if location:
                local_issues.extend(
                    check_evidence(location.model_dump(mode="json"), post.text)
                )
            override = location.availability_override if location else None
            if (
                override
                and any(getattr(override, field) is not None for field in DATE_FIELDS)
                and not override.evidence
            ):
                local_issues.append("local asserted dates lack their own evidence")
            availability, date_issues = effective_availability(
                offer.availability, override
            )
            local_issues.extend(date_issues)
            if (
                relative
                and post.edited_at
                and singapore_date(post.edited_at) != singapore_date(post.posted_at)
            ):
                availability.date_status = "needs_review"
            if availability.date_status == "needs_review":
                local_issues.append("availability needs review")
            location_id = None
            if location:
                for name in ("label", "venue", "address", "unit"):
                    text = getattr(location, name)
                    if text and text not in post.text:
                        local_issues.append(
                            f"location {name} is not a caption substring"
                        )
                if not any(location.label in quote for quote in location.evidence):
                    local_issues.append("location label lacks association evidence")
                fields = [location.label, location.venue, location.address]
                if any(
                    excluded.casefold() in field.casefold()
                    for excluded in offer.excluded_outlets
                    for field in fields
                    if field
                ):
                    local_issues.append("excluded outlet appears as a participant")
                loc_identity = location.model_dump(
                    mode="json", exclude={"evidence", "availability_override"}
                )
                location_id = f"{offer_id}:location:{semantic_hash(loc_identity)[:24]}"
                if location_id in seen_locations:
                    local_issues.append("duplicate location in offer")
                seen_locations.add(location_id)
            row_id = f"{location_id or offer_id}:row:{semantic_hash(availability.model_dump(mode='json'))[:24]}"
            status = (
                "needs_review"
                if local_issues
                else "candidate"
                if location
                else "unmapped"
            )
            rows.append(
                Candidate(
                    row_id=row_id,
                    post_id=post.post_id,
                    offer_id=offer_id,
                    location_id=location_id,
                    title=offer.title,
                    description=offer.description,
                    merchant=offer.merchant,
                    terms=offer.terms,
                    location_scope=offer.location_scope,
                    excluded_outlets=offer.excluded_outlets,
                    incomplete_scope_note=offer.incomplete_scope_note,
                    location=location,
                    availability=availability,
                    status=status,
                    reasons=list(
                        dict.fromkeys(
                            local_issues
                            or (
                                []
                                if location
                                else [f"no explicit location: {offer.location_scope}"]
                            )
                        )
                    ),
                    warnings=list(
                        dict.fromkeys([*result.warnings, *offer.review_reasons])
                    ),
                )
            )
    # Duplicate offers or invalid global evidence taint all rows, including earlier rows.
    location_counts = Counter(row.location_id for row in rows if row.location_id)
    for row in rows:
        if row.location_id and location_counts[row.location_id] > 1:
            row.status = "needs_review"
            row.reasons = list(
                dict.fromkeys([*row.reasons, "duplicate location in offer"])
            )
    if global_issues:
        for row in rows:
            row.status = "needs_review"
            row.reasons = list(dict.fromkeys([*row.reasons, *global_issues]))
    result.errors = list(
        dict.fromkeys(
            [
                *result.errors,
                *global_issues,
                *[
                    issue
                    for row in rows
                    if row.status == "needs_review"
                    for issue in row.reasons
                ],
            ]
        )
    )
    result.status = "needs_review" if result.errors else "success"
    return sorted(
        {row.row_id: row for row in rows}.values(), key=lambda row: row.row_id
    )


def apply_corrections(
    post: SourcePost, result: PostResult, corrections: Corrections
) -> None:
    selected = [
        item for item in corrections.corrections if item.post_id == post.post_id
    ]
    if not selected:
        return
    if result.extraction is None:
        raise ValueError(f"correction requires a parsed extraction: {post.post_id}")
    data = result.extraction.model_dump(mode="json")
    for item in selected:
        if (
            item.input_hash != post.extraction_input_hash
            or item.cache_key != result.cache_key
        ):
            raise ValueError(f"stale correction {item.correction_id}")
        if any(quote not in post.text for quote in item.evidence):
            raise ValueError(f"unsupported correction evidence {item.correction_id}")
        if not item.pointer.startswith("/"):
            raise ValueError("correction pointer must target a field")
        parts = [
            part.replace("~1", "/").replace("~0", "~")
            for part in item.pointer[1:].split("/")
        ]
        target = data
        try:
            for part in parts[:-1]:
                target = target[int(part)] if isinstance(target, list) else target[part]
            key = int(parts[-1]) if isinstance(target, list) else parts[-1]
            if isinstance(key, int) and key < 0:
                raise ValueError("negative correction indices are invalid")
            if target[key] != item.expected:
                raise ValueError(
                    f"correction expected value differs: {item.correction_id}"
                )
            target[key] = item.value
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(f"invalid correction target {item.correction_id}") from exc
        result.correction_ids.append(item.correction_id)
    result.extraction = Extraction.model_validate(data)
