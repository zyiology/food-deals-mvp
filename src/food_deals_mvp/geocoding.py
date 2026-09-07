"""Selected demo location resolution; all published coordinates need human review."""

import re
from collections import Counter
from pathlib import Path

from .demo_review import DemoArtifact
from .extraction import cached as extraction_cache
from .extraction import load_extraction_report
from .extraction_models import Candidate
from .geocoding_models import (
    Coordinates,
    Decision,
    Decisions,
    GeocodingReport,
    GeocodingSettings,
    Place,
    Query,
    QueryCache,
    Resolution,
    Resolutions,
    Selection,
)
from .nominatim import Nominatim, query_key, state_root, utc_now, writer_lock
from .storage import atomic_write, fingerprint, load_normalized, read_json


def selection_hash(selection: Selection) -> str:
    return fingerprint(
        {"dataset_id": selection.dataset_id, "row_ids": sorted(selection.row_ids)}
    )


def location_hash(row: Candidate) -> str:
    return fingerprint(
        {
            "row_id": row.row_id,
            "location": row.location.model_dump(mode="json") if row.location else None,
            "merchant": row.merchant,
            "scope": row.location_scope,
            "excluded": row.excluded_outlets,
        }
    )


def load_inputs(
    data_dir: Path, selection_path: Path
) -> tuple[DemoArtifact, Selection, list[Candidate]]:
    selection = Selection.model_validate(read_json(selection_path))
    demo = DemoArtifact.model_validate(read_json(data_dir / "demo/candidates.json"))
    posts, _, _ = load_normalized(data_dir)
    report = load_extraction_report(data_dir)
    expected = fingerprint(
        {
            "version": demo.validation_version,
            "source": posts.dataset_id,
            "rows": [r.model_dump(mode="json") for r in demo.rows],
            "caches": demo.cache_fingerprints,
        }
    )
    if not (
        demo.validation_version == "demo-v1"
        and expected == demo.dataset_id == selection.dataset_id
        and demo.source_dataset_id == posts.dataset_id
        and demo.extraction_dataset_id == report.dataset_id
        and demo.cache_fingerprints == report.cache_fingerprints
    ):
        raise ValueError("stale or inconsistent demo selection/source provenance")
    post_lookup = {post.post_id: post for post in posts.posts}
    if len({r.post_id for r in demo.results}) != len(demo.results) or {
        r.post_id for r in demo.results
    } != set(report.selected_ids):
        raise ValueError("demo outcomes differ from the original extraction selection")
    for result in demo.results:
        post = post_lookup.get(result.post_id)
        if post is None or post.extraction_input_hash != result.input_hash:
            raise ValueError("demo extraction input changed")
        if not re.fullmatch(r"[0-9a-f]{64}", result.cache_key):
            raise ValueError("invalid original extraction cache key")
        entry = extraction_cache(
            data_dir / f"cache/llm/{result.cache_key}.json", post, result.cache_key
        )
        if entry is None or fingerprint(
            entry.model_dump(mode="json")
        ) != demo.cache_fingerprints.get(result.post_id):
            raise ValueError("original extraction cache changed since demo review")
    rows = {r.row_id: r for r in demo.rows}
    if len(rows) != len(demo.rows):
        raise ValueError("duplicate demo row IDs")
    selected = []
    for row_id in sorted(selection.row_ids):
        row = rows.get(row_id)
        if row is None or row.status != "candidate" or row.location is None:
            raise ValueError(f"unknown or ineligible selected row: {row_id}")
        selected.append(row)
    return demo, selection, selected


def load_decisions(path: Path, rows: list[Candidate]) -> Decisions:
    decisions = (
        Decisions.model_validate(read_json(path)) if path.exists() else Decisions()
    )
    lookup = {r.row_id: location_hash(r) for r in rows}
    seen: set[tuple[str, str]] = set()
    ids = set()
    for decision in decisions.decisions:
        if decision.decision_id in ids:
            raise ValueError("duplicate geocoding decision ID")
        ids.add(decision.decision_id)
        for row_id in decision.row_ids:
            if lookup.get(row_id) != decision.location_fingerprints[row_id]:
                raise ValueError(
                    f"stale or out-of-selection location decision: {row_id}"
                )
            kind = "alias" if decision.action == "alias" else "review"
            if (row_id, kind) in seen:
                raise ValueError(f"conflicting location decisions: {row_id}")
            seen.add((row_id, kind))
    return decisions


def row_decision(
    decisions: Decisions, row_id: str, *, alias: bool = False
) -> Decision | None:
    return next(
        (
            d
            for d in decisions.decisions
            if row_id in d.row_ids and (d.action == "alias") == alias
        ),
        None,
    )


def normalized(text: str) -> str:
    return " ".join(text.casefold().split()).strip(" ,")


def queries_for(
    row: Candidate, settings: GeocodingSettings, alias: Decision | None
) -> list[Query]:
    location = row.location
    if location is None:
        return []

    def clean(text: str | None) -> str:
        value = text or ""
        if location.unit:
            value = re.sub(
                r"(?<!\w)" + re.escape(location.unit.lstrip("#")) + r"(?!\w)",
                "",
                value,
                flags=re.IGNORECASE,
            )
        value = value.replace("#", "")
        return normalized(value)

    if alias and alias.alias:
        texts = [normalized(alias.alias)]
    else:
        label, venue, address = (
            clean(location.label),
            clean(location.venue),
            clean(location.address),
        )
        # Labels often supply a branch where venue contains only the merchant name.
        place = (
            venue
            if venue and (not label or label in venue or label in {"shops", "b2 shops"})
            else label
        )
        if (
            venue
            and place
            and venue not in place
            and place not in venue
            and place not in {"shops", "b2 shops"}
        ):
            primary = f"{venue}, {place}"
        else:
            primary = place or venue
        if address and address not in primary:
            primary = f"{primary}, {address}" if primary else address
        texts = [primary]
        # A road without a street number is context, not a venue fallback.
        fallback = address if address and re.search(r"\d", address) else place
        # Removing a merchant is safe only when it is an explicit extracted field.
        if row.merchant and fallback:
            fallback = re.sub(
                r"(?i)\b" + re.escape(row.merchant) + r"\b", "", fallback
            ).strip(" ,")
        if fallback:
            texts.append(fallback)
    return [
        Query(endpoint=settings.endpoint, text=text + ", singapore")
        for text in dict.fromkeys(normalized(t) for t in texts)
        if text
    ][:2]


def singapore_coordinates(coordinates: Coordinates) -> bool:
    # Sanity check only; country evidence and venue agreement are also required.
    return (
        0.8 <= coordinates.latitude <= 1.7 and 103.4 <= coordinates.longitude <= 104.6
    )


def places(entry: QueryCache) -> list[Place]:
    result = []
    if entry.status != "success":
        return result
    response_hash = fingerprint(entry.model_dump(mode="json"))
    for raw in entry.response:
        address = raw.get("address")
        if not isinstance(address, dict) or address.get("country_code") != "sg":
            continue
        category = str(raw.get("category", raw.get("class", "")))
        kind = str(raw.get("type", ""))
        address_type = str(raw.get("addresstype", ""))
        if category not in {
            "building",
            "shop",
            "amenity",
            "tourism",
            "leisure",
            "office",
            "historic",
            "place",
        }:
            continue
        if category == "place" and kind not in {"house", "building"}:
            continue
        if category == "amenity" and kind not in {
            "restaurant",
            "cafe",
            "fast_food",
            "food_court",
            "bar",
            "pub",
            "ice_cream",
        }:
            continue
        if category == "shop" and kind not in {
            "mall",
            "supermarket",
            "convenience",
            "bakery",
            "confectionery",
            "deli",
            "butcher",
            "greengrocer",
            "tea",
            "coffee",
            "beverages",
        }:
            continue
        if kind in {
            "neighbourhood",
            "suburb",
            "quarter",
            "city",
            "country",
            "island",
            "park",
        } or address_type in {"road", "neighbourhood", "suburb", "city", "country"}:
            continue
        try:
            coordinates = Coordinates.model_validate(
                {"latitude": raw.get("lat"), "longitude": raw.get("lon")}
            )
        except ValueError:
            continue
        if not singapore_coordinates(coordinates):
            continue
        result.append(
            Place(
                **coordinates.model_dump(),
                candidate_id=fingerprint(raw),
                query_key=entry.key,
                response_fingerprint=response_hash,
                name=str(raw.get("name", "")),
                address=str(raw.get("display_name", "")),
                category=category,
                kind=kind,
                precision="building"
                if category == "building" or kind in {"mall", "house", "building"}
                else "outlet",
                osm_type=str(raw["osm_type"]) if "osm_type" in raw else None,
                osm_id=str(raw["osm_id"]) if "osm_id" in raw else None,
            )
        )
    return result


def supported_match(place: Place, query: Query) -> bool:
    def tokens(text: str) -> set[str]:
        return set(re.findall(r"[^\W_]+", text.casefold())) - {"singapore", "the"}

    wanted = tokens(query.text)
    named = tokens(place.name)
    if not wanted:
        return False
    if wanted <= named:
        return True
    if not wanted <= tokens(place.name + " " + place.address):
        return False
    # Street-address queries may identify a building without its name. For an
    # outlet, require its own name as well as the supplied branch/address context.
    if place.precision == "building":
        return any(token.isdigit() for token in wanted)
    return bool(named) and named <= wanted


def apply_decision(resolution: Resolution, decision: Decision | None) -> None:
    if decision is None:
        return
    resolution.decision_id = decision.decision_id
    if decision.action == "reject":
        resolution.review = "rejected"
        return
    if decision.action == "manual":
        if decision.coordinates is None or not singapore_coordinates(
            decision.coordinates
        ):
            raise ValueError("manual coordinates fail Singapore sanity check")
        resolution.coordinates = decision.coordinates
        resolution.precision = decision.precision
        resolution.resolved_label = decision.resolved_label
    elif decision.action == "approve":
        chosen = next(
            (
                p
                for p in resolution.candidates
                if p.candidate_id == decision.candidate_id
                and p.response_fingerprint == decision.response_fingerprint
            ),
            None,
        )
        if chosen is None:
            raise ValueError(f"stale candidate approval: {decision.decision_id}")
        resolution.coordinates = Coordinates(
            latitude=chosen.latitude, longitude=chosen.longitude
        )
        resolution.precision = chosen.precision
        resolution.resolved_label = chosen.name or chosen.address
    else:
        return
    resolution.review = "approved"


def geocode(
    data_dir: Path,
    selection_path: Path,
    settings: GeocodingSettings,
    *,
    decisions_path: Path | None = None,
    dry_run: bool = False,
    offline: bool = False,
    resume: bool = False,
    refresh_query: str | None = None,
) -> GeocodingReport:
    root = state_root()
    if dry_run:
        return _geocode(
            data_dir,
            selection_path,
            settings,
            root,
            decisions_path,
            True,
            offline,
            resume,
            refresh_query,
        )
    with writer_lock(root):
        return _geocode(
            data_dir,
            selection_path,
            settings,
            root,
            decisions_path,
            False,
            offline,
            resume,
            refresh_query,
        )


def _geocode(
    data_dir: Path,
    selection_path: Path,
    settings: GeocodingSettings,
    root: Path,
    decisions_path: Path | None,
    dry_run: bool,
    offline: bool,
    resume: bool,
    refresh_query: str | None,
) -> GeocodingReport:
    demo, selection, rows = load_inputs(data_dir, selection_path)
    decisions = load_decisions(
        decisions_path or data_dir / "overrides/geocoding.json", rows
    )
    plans = {
        r.row_id: (
            []
            if (decision := row_decision(decisions, r.row_id))
            and decision.action in {"manual", "reject"}
            else queries_for(r, settings, row_decision(decisions, r.row_id, alias=True))
        )
        for r in rows
    }
    queries = {query_key(q): q for qs in plans.values() for q in qs}
    if refresh_query is not None and refresh_query not in queries:
        raise ValueError("refresh target is not a query in the selected scope")
    if refresh_query and (offline or resume):
        raise ValueError("refresh cannot be combined with offline/resume")
    client = Nominatim(settings, data_dir, root)
    cached = {key: client.cached(q) for key, q in queries.items()}
    needed = [
        key
        for key, value in cached.items()
        if value is None
        or key == refresh_query
        or (resume and value.status != "success")
    ]
    counts = {
        "selected_rows": len(rows),
        "unique_queries_max": len(queries),
        "first_queries": len({query_key(qs[0]) for qs in plans.values() if qs}),
        "uncached_queries": sum(value is None for value in cached.values()),
        "cached_queries": sum(value is not None for value in cached.values()),
        "max_http_attempts": 0 if offline else len(needed) * (settings.retries + 1),
    }
    identity = {
        "source_dataset_id": demo.source_dataset_id,
        "demo_dataset_id": demo.dataset_id,
        "selection_fingerprint": selection_hash(selection),
    }
    if dry_run:
        return GeocodingReport(
            dataset_id=fingerprint(identity),
            generated_at=utc_now(),
            status="dry_run",
            counts=counts,
            source_dataset_id=demo.source_dataset_id,
            demo_dataset_id=demo.dataset_id,
            selection_fingerprint=selection_hash(selection),
        )
    if needed and not offline and not settings.user_agent.strip():
        raise ValueError("set user_agent in geocoding settings before live requests")
    # A targeted refresh is performed even if an earlier formulation already matches.
    if refresh_query:
        client.get(queries[refresh_query], offline=False, resume=False, refresh=True)
    results = []
    errors = []
    for row in rows:
        decision = row_decision(decisions, row.row_id)
        resolution = Resolution(
            row_id=row.row_id,
            location_fingerprint=location_hash(row),
            queries=[],
            cache_fingerprints={},
            outcome="not_attempted",
            reason="No completed lookup",
        )
        if decision and decision.action in {"manual", "reject"}:
            resolution.reason = "Reviewed manual decision; no provider lookup needed"
            apply_decision(resolution, decision)
            results.append(resolution)
            continue
        matches: list[Place] = []
        raw_count = 0
        missing = False
        for query in plans[row.row_id]:
            key = query_key(query)
            resolution.queries.append(key)
            resolution.query_texts[key] = query.text
            entry = client.get(query, offline=offline, resume=resume, refresh=False)
            if entry is None:
                missing = True
                continue
            resolution.cache_fingerprints[key] = fingerprint(
                entry.model_dump(mode="json")
            )
            if entry.status != "success":
                resolution.outcome = "error"
                resolution.reason = entry.error or "Interrupted query; use --resume"
                break
            raw_count += len(entry.response)
            candidates = places(entry)
            resolution.candidates.extend(candidates)
            matches = [p for p in candidates if supported_match(p, query)]
            if len(matches) == 1:
                break
        if resolution.outcome != "error":
            if len(matches) == 1:
                resolution.outcome = "matched"
                resolution.proposed_candidate_id = matches[0].candidate_id
                resolution.reason = (
                    "Unique name/address agreement; human pin approval required"
                )
            elif resolution.candidates or raw_count:
                resolution.outcome = "ambiguous"
                resolution.reason = "No unique supported venue match; review or omit"
            elif missing:
                resolution.reason = "Uncached queries not attempted"
            else:
                resolution.outcome = "not_found"
                resolution.reason = "All bounded queries returned no results"
        if resolution.outcome == "error":
            errors.append(f"{row.row_id}: {resolution.reason}")
        try:
            apply_decision(resolution, decision)
        except ValueError:
            if decision is None or decision.action != "approve":
                raise
            # Keep refreshed candidates reviewable without reusing stale approval.
            resolution.decision_id = None
            resolution.reason += "; saved approval is stale: choose a current candidate"
            errors.append(f"{row.row_id}: stale candidate approval")
        results.append(resolution)
    counts.update({"http_attempts": client.attempts, "cache_reuses": client.hits})
    counts.update(
        {
            f"outcome_{key}": value
            for key, value in Counter(r.outcome for r in results).items()
        }
    )
    counts.update(
        {
            f"review_{key}": value
            for key, value in Counter(r.review for r in results).items()
        }
    )
    content = dict(
        **identity,
        settings_fingerprint=fingerprint(settings.model_dump(mode="json")),
        decisions_fingerprint=fingerprint(decisions.model_dump(mode="json")),
        rows=results,
    )
    artifact = Resolutions.model_validate(
        {"dataset_id": "pending", "generated_at": utc_now(), **content}
    )
    artifact.dataset_id = resolution_identity(artifact)
    report = GeocodingReport(
        dataset_id=artifact.dataset_id,
        generated_at=utc_now(),
        source_dataset_id=demo.source_dataset_id,
        demo_dataset_id=demo.dataset_id,
        selection_fingerprint=selection_hash(selection),
        resolution_fingerprint=fingerprint(artifact.model_dump(mode="json")),
        status="partial"
        if errors
        or any(r.outcome == "not_attempted" and r.review == "pending" for r in results)
        else "success",
        counts=counts,
        errors=errors,
    )
    from .geocoding_review import write_review

    atomic_write(data_dir / "intermediate/location-resolutions.json", artifact)
    write_review(data_dir / "reports/geocode-review.html", artifact, rows, decisions)
    atomic_write(data_dir / "reports/geocode.json", report)
    return report


def resolution_identity(artifact: Resolutions) -> str:
    return fingerprint(
        artifact.model_dump(mode="json", exclude={"generated_at", "dataset_id"})
    )


def load_geocoding_report(data_dir: Path) -> tuple[GeocodingReport, Resolutions]:
    report = GeocodingReport.model_validate(
        read_json(data_dir / "reports/geocode.json")
    )
    artifact = Resolutions.model_validate(
        read_json(data_dir / "intermediate/location-resolutions.json")
    )
    if (
        report.status not in {"success", "partial"}
        or report.dataset_id != artifact.dataset_id
        or artifact.dataset_id != resolution_identity(artifact)
        or report.resolution_fingerprint
        != fingerprint(artifact.model_dump(mode="json"))
        or any(
            getattr(report, k) != getattr(artifact, k)
            for k in ("source_dataset_id", "demo_dataset_id", "selection_fingerprint")
        )
    ):
        raise ValueError("geocoding report/resolution identity mismatch; rerun geocode")
    return report, artifact
