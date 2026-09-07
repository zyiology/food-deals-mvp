"""Synthetic Phase 3 checks; no public requests, real state, or pilot copying."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime

import pytest

from food_deals_mvp.demo_review import DemoArtifact, build_demo_review
from food_deals_mvp.extraction import extract
from food_deals_mvp.geocoding import (
    geocode,
    load_decisions,
    load_geocoding_report,
    load_inputs,
    location_hash,
    places,
    queries_for,
)
from food_deals_mvp.geocoding_models import (
    Decision,
    Decisions,
    GeocodingSettings,
    Query,
    QueryCache,
    Selection,
)
from food_deals_mvp.nominatim import Nominatim, query_key, retry_after, writer_lock
from food_deals_mvp.openrouter import Settings
from food_deals_mvp.publishing import PublishedDataset, publish
from food_deals_mvp.storage import atomic_write, read_json
from tests.llm_support import FakeClient


@dataclass
class Clock:
    now: float = 1_800_000_000

    def time(self):
        return self.now

    def sleep(self, delay):
        assert 0 <= delay <= 60
        self.now += delay


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setattr("food_deals_mvp.nominatim.time.time", value.time)
    monkeypatch.setattr("food_deals_mvp.nominatim.time.sleep", value.sleep)
    return value


def raw_place(**changes):
    return {
        "lat": "1.31",
        "lon": "103.85",
        "name": "Example Mall",
        "display_name": "Example Mall, 12 Sample Road, Singapore",
        "category": "shop",
        "type": "mall",
        "addresstype": "shop",
        "address": {"country_code": "sg", "house_number": "12", "road": "Sample Road"},
        "osm_type": "way",
        "osm_id": 123,
        **changes,
    }


def cache(query=None, response=None):
    query = query or Query(
        endpoint=GeocodingSettings().endpoint, text="example mall, singapore"
    )
    return QueryCache(
        key=query_key(query),
        query=query,
        retrieved_at=datetime.now(UTC),
        status="success",
        response=[raw_place()] if response is None else response,
    )


@pytest.fixture
def demo(llm_batch, monkeypatch, tmp_path):
    root = tmp_path / "geo-state"
    monkeypatch.setattr("food_deals_mvp.geocoding.state_root", lambda: root)
    monkeypatch.setattr("food_deals_mvp.publishing.state_root", lambda: root)
    extract(
        llm_batch.data_dir,
        Settings(),
        post_ids=llm_batch.pilot_ids,
        state_dir=llm_batch.state_dir,
        client=FakeClient(),
    )
    build_demo_review(llm_batch.data_dir, tmp_path / "sources.json")
    data = DemoArtifact.model_validate(
        read_json(llm_batch.data_dir / "demo/candidates.json")
    )
    selection = Selection(
        dataset_id=data.dataset_id, row_ids=[r.row_id for r in data.rows[:2]]
    )
    path = llm_batch.data_dir / "demo-selection.json"
    atomic_write(path, selection)
    return llm_batch.data_dir, path, root, tmp_path / "sources.json"


@pytest.fixture
def settings():
    return GeocodingSettings(user_agent="food-deals-mvp-tests/0.1")


def approve(data_dir, selection_path):
    _, _, rows = load_inputs(data_dir, selection_path)
    _, resolutions = load_geocoding_report(data_dir)
    chosen = resolutions.rows[0].candidates[0]
    decision = Decision(
        decision_id="review-1",
        row_ids=[rows[0].row_id],
        location_fingerprints={rows[0].row_id: location_hash(rows[0])},
        action="approve",
        candidate_id=chosen.candidate_id,
        response_fingerprint=chosen.response_fingerprint,
        reviewer="synthetic reviewer",
        reviewed_at=datetime.now(UTC),
        source="synthetic fixture",
        reason="test review",
    )
    atomic_write(data_dir / "overrides/geocoding.json", Decisions(decisions=[decision]))
    return decision


def fake_response(monkeypatch, response=None):
    calls = []

    def request(self, query):
        calls.append(query.text)
        return (
            200,
            {},
            json.dumps([raw_place()] if response is None else response).encode(),
        )

    monkeypatch.setattr(Nominatim, "request", request)
    return calls


def test_selection_dry_run_and_alias_do_not_approve_or_write(demo, settings):
    data, selection, root, _ = demo
    _, _, rows = load_inputs(data, selection)
    alias = Decision(
        decision_id="alias-1",
        row_ids=[rows[0].row_id],
        location_fingerprints={rows[0].row_id: location_hash(rows[0])},
        action="alias",
        reviewer="owner",
        reviewed_at=datetime.now(UTC),
        reason="Owner clarified the mall",
        source="owner statement",
        alias="Bugis Junction",
    )
    atomic_write(data / "overrides/geocoding.json", Decisions(decisions=[alias]))
    before = {p: p.read_bytes() for p in data.rglob("*") if p.is_file()}
    report = geocode(data, selection, settings, dry_run=True)
    assert report.counts["unique_queries_max"] == 2
    assert not root.exists()
    assert before == {p: p.read_bytes() for p in data.rglob("*") if p.is_file()}
    geocode(data, selection, settings, offline=True)
    _, output = load_geocoding_report(data)
    assert all(r.review == "pending" for r in output.rows)
    assert "bugis junction, singapore" in output.rows[0].query_texts.values()


@pytest.mark.parametrize(
    "change", ["stale", "duplicate", "unknown", "empty", "ineligible"]
)
def test_bad_selection_fails_before_network(demo, settings, change):
    data, path, root, _ = demo
    selected = json.loads(path.read_text())
    if change == "stale":
        selected["dataset_id"] = "old"
    if change == "duplicate":
        selected["row_ids"] *= 2
    if change == "unknown":
        selected["row_ids"] = ["missing"]
    if change == "empty":
        selected["row_ids"] = []
    if change == "ineligible":
        artifact_path = data / "demo/candidates.json"
        artifact = json.loads(artifact_path.read_text())
        artifact["rows"][0]["status"] = "needs_review"
        artifact_path.write_text(json.dumps(artifact))
    path.write_text(json.dumps(selected))
    with pytest.raises(ValueError):
        geocode(data, path, settings, dry_run=True)
    assert not root.exists()


def test_shared_cache_offline_repeat_and_review_publication(
    demo, settings, clock, monkeypatch
):
    data, selection, root, sources = demo
    calls = fake_response(monkeypatch)
    report = geocode(data, selection, settings)
    assert calls == ["example mall, singapore"]
    assert report.counts["outcome_matched"] == 2
    assert report.counts["review_pending"] == 2
    with pytest.raises(ValueError, match="no approved pins"):
        publish(data, selection, allow_partial=True, sources_path=sources)
    approve(data, selection)
    with pytest.raises(ValueError, match="stale selection/decisions"):
        publish(data, selection, allow_partial=True, sources_path=sources)
    geocode(data, selection, settings, offline=True)
    with pytest.raises(ValueError, match="allow-partial"):
        publish(data, selection, sources_path=sources)
    snapshot = publish(data, selection, allow_partial=True, sources_path=sources)
    assert len(snapshot.deals) == 1 and not snapshot.dataset_complete
    assert snapshot.processing_summary["omitted_rows"] == 1
    assert snapshot.deals[0].availability.weekdays == [1, 2, 3, 4, 5]
    assert snapshot.deals[0].image_url is None
    assert snapshot.suggested_validity == "all"
    first = snapshot.model_dump(mode="json", exclude={"generated_at"})
    geocode(data, selection, settings, offline=True)
    repeat = publish(data, selection, allow_partial=True, sources_path=sources)
    assert first == repeat.model_dump(mode="json", exclude={"generated_at"})
    assert len(calls) == 1
    assert (
        PublishedDataset.model_validate(read_json(data / "published/deals.json"))
        == repeat
    )
    # A refresh in the shared cache invalidates this dataset's old mirror and approval.
    key = next(root.glob("cache/*.json")).stem
    changed = QueryCache.model_validate(read_json(root / f"cache/{key}.json"))
    changed.response[0]["lat"] = "1.32"
    atomic_write(root / f"cache/{key}.json", changed)
    before = (data / "published/deals.json").read_bytes()
    with pytest.raises(ValueError, match="query response changed"):
        publish(data, selection, allow_partial=True, sources_path=sources)
    geocode(data, selection, settings, offline=True)
    _, resolutions = load_geocoding_report(data)
    assert resolutions.rows[0].review == "pending"
    assert "stale" in resolutions.rows[0].reason
    assert (data / "published/deals.json").read_bytes() == before


def test_original_cache_mutation_blocks_geocoding(demo, settings):
    data, selection, _, _ = demo
    path = next(data.glob("cache/llm/*.json"))
    value = json.loads(path.read_text())
    value["raw"]["usage"]["cost"] = 99
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="original extraction cache changed"):
        geocode(data, selection, settings, dry_run=True)


@pytest.mark.parametrize(
    "raw",
    [
        raw_place(lat="NaN"),
        raw_place(lat="103.85", lon="1.31"),
        raw_place(lat="91"),
        raw_place(address={"country_code": "my"}),
        raw_place(category="place", type="suburb", addresstype="suburb"),
        raw_place(category="highway", type="steps", addresstype="road"),
        raw_place(category="amenity", type="taxi"),
        raw_place(type="clothes"),
    ],
)
def test_unsuitable_provider_candidates_are_not_reviewable(raw):
    assert places(cache(response=[raw])) == []


def test_queries_use_branch_and_never_strip_address_substrings(demo, settings):
    _, _, rows = load_inputs(demo[0], demo[1])
    row = rows[0].model_copy(deep=True)
    assert row.location is not None
    row.location.label = "Hillion Mall"
    row.location.venue = "Kei Kaisendon"
    assert (
        queries_for(row, settings, None)[0].text
        == "kei kaisendon, hillion mall, singapore"
    )
    row.location.label = "B2 shops"
    row.location.venue = "City Square Mall"
    row.location.unit = "B2"
    assert [q.text for q in queries_for(row, settings, None)] == [
        "city square mall, singapore"
    ]
    row.location.label = "Example Mall"
    row.location.venue = "Example Mall"
    row.location.unit = "01"
    row.location.address = "101 Sample Road"
    assert "101 sample road" in queries_for(row, settings, None)[0].text


@pytest.mark.parametrize("reply", [[], [raw_place(name="Different Mall")]])
def test_negative_and_ambiguous_results_are_cached(
    demo, settings, clock, monkeypatch, reply
):
    calls = fake_response(monkeypatch, reply)
    first = geocode(demo[0], demo[1], settings)
    second = geocode(demo[0], demo[1], settings)
    assert (
        first.counts.get("outcome_not_found", first.counts.get("outcome_ambiguous"))
        == 2
    )
    assert second.counts["http_attempts"] == 0 and len(calls) == 1


def test_lock_is_exclusive_across_data_directories(tmp_path):
    with (
        writer_lock(tmp_path / "shared"),
        pytest.raises(ValueError, match="another geocoding"),
        writer_lock(tmp_path / "shared"),
    ):
        pass


def test_throttle_retry_after_and_cross_directory_cache(
    tmp_path, settings, clock, monkeypatch
):
    starts = []

    def request(self, query):
        starts.append(clock.time())
        if len(starts) == 1:
            return 429, {"retry-after": "5"}, b""
        return 200, {}, b"[]"

    monkeypatch.setattr(Nominatim, "request", request)
    query = Query(endpoint=settings.endpoint, text="example mall, singapore")
    root = tmp_path / "shared"
    with writer_lock(root):
        client = Nominatim(settings, tmp_path / "one", root)
        result = client.get(query, offline=False, resume=False, refresh=False)
        assert result is not None and result.status == "success"
    with writer_lock(root):
        client = Nominatim(settings, tmp_path / "two", root)
        result = client.get(query, offline=False, resume=False, refresh=False)
        assert result is not None and result.status == "success"
        client.get(
            query.model_copy(update={"text": "another mall, singapore"}),
            offline=False,
            resume=False,
            refresh=False,
        )
    assert len(starts) == 3 and starts[1] - starts[0] >= 5
    assert starts[2] - starts[1] >= 1
    assert starts[2] - starts[1] == pytest.approx(settings.interval)


def test_long_retry_after_survives_resume(tmp_path, settings, clock, monkeypatch):
    calls = []

    def request(self, query):
        calls.append(query)
        return 429, {"retry-after": "120"}, b""

    monkeypatch.setattr(Nominatim, "request", request)
    query = Query(endpoint=settings.endpoint, text="example mall, singapore")
    with writer_lock(tmp_path):
        client = Nominatim(settings, tmp_path / "one", tmp_path)
        result = client.get(query, offline=False, resume=False, refresh=False)
        assert result is not None and result.status == "error"
        next_client = Nominatim(settings, tmp_path / "two", tmp_path)
        result = next_client.get(query, offline=False, resume=True, refresh=False)
        assert result is not None and result.status == "error"
    assert len(calls) == 1
    value = format_datetime(datetime.fromtimestamp(clock.time() + 45, UTC), usegmt=True)
    assert retry_after(value, clock.time()) == 45


@pytest.mark.parametrize("failure", [403, 500, "timeout", "malformed"])
def test_failures_are_bounded_and_do_not_become_no_results(
    demo, settings, clock, monkeypatch, failure
):
    calls = []

    def request(self, query):
        calls.append(query)
        if failure == "timeout":
            raise TimeoutError()
        if failure == "malformed":
            return 200, {}, b"{bad json"
        return failure, {}, b""

    monkeypatch.setattr(Nominatim, "request", request)
    report = geocode(demo[0], demo[1], settings)
    assert report.counts["outcome_error"] == 2
    assert len(calls) == (3 if failure in {500, "timeout"} else 1)
    assert report.status == "partial"
    if failure != 403:
        geocode(demo[0], demo[1], settings)
        assert len(calls) == (3 if failure in {500, "timeout"} else 1)


def test_stale_location_alias_is_rejected(demo):
    data, selection, _, _ = demo
    _, _, rows = load_inputs(data, selection)
    decision = Decision(
        decision_id="stale",
        row_ids=[rows[0].row_id],
        location_fingerprints={rows[0].row_id: "old"},
        action="alias",
        alias="Bugis Junction",
        reviewer="test",
        reviewed_at=datetime.now(UTC),
        reason="test",
        source="test",
    )
    path = data / "overrides/geocoding.json"
    atomic_write(path, Decisions(decisions=[decision]))
    with pytest.raises(ValueError, match="stale"):
        load_decisions(path, rows)


def test_review_html_escapes_provider_content(demo, settings, clock, monkeypatch):
    payload = '</script><img src=x onerror="alert(1)">'
    fake_response(monkeypatch, [raw_place(name=payload)])
    geocode(demo[0], demo[1], settings)
    page = (demo[0] / "reports/geocode-review.html").read_text()
    assert payload not in page
    assert "&lt;/script&gt;" in page and "\\u003c/script" in page


def test_missing_cache_and_tampered_resolution_preserve_snapshot(
    demo, settings, clock, monkeypatch
):
    data, selection, _, sources = demo
    fake_response(monkeypatch)
    geocode(data, selection, settings)
    approve(data, selection)
    geocode(data, selection, settings, offline=True)
    publish(data, selection, allow_partial=True, sources_path=sources)
    target = data / "published/deals.json"
    before = target.read_bytes()
    path = data / "intermediate/location-resolutions.json"
    artifact = json.loads(path.read_text())
    artifact["rows"][0]["coordinates"]["latitude"] = 1.6
    path.write_text(json.dumps(artifact))
    with pytest.raises(ValueError, match="identity mismatch"):
        publish(data, selection, allow_partial=True, sources_path=sources)
    assert target.read_bytes() == before


def test_manual_coordinate_approval_skips_provider(demo, settings, monkeypatch):
    from food_deals_mvp.geocoding_models import Coordinates

    data, selection, _, sources = demo
    _, _, rows = load_inputs(data, selection)
    decisions = Decisions(
        decisions=[
            Decision(
                decision_id=f"manual-{i}",
                row_ids=[row.row_id],
                location_fingerprints={row.row_id: location_hash(row)},
                action="manual",
                coordinates=Coordinates(latitude=1.31, longitude=103.85),
                precision="building",
                resolved_label="Example Mall",
                reviewer="synthetic reviewer",
                reviewed_at=datetime.now(UTC),
                reason="Reviewed synthetic building",
                source="synthetic fixture",
            )
            for i, row in enumerate(rows)
        ]
    )
    atomic_write(data / "overrides/geocoding.json", decisions)
    calls = fake_response(monkeypatch)
    dry = geocode(data, selection, settings, dry_run=True)
    assert dry.counts["max_http_attempts"] == 0
    geocode(data, selection, settings)
    result = publish(data, selection, allow_partial=True, sources_path=sources)
    assert len(result.deals) == 2 and not calls


def test_media_containment_hashes_placeholders_and_copy(demo, tmp_path):
    from food_deals_mvp.models import Media, MediaManifest
    from food_deals_mvp.publishing import copy_media
    from food_deals_mvp.storage import file_hash
    from tests.llm_support import post

    data, _, _, sources = demo
    photo = tmp_path / "101/photo.jpg"
    content = b"\xff\xd8\xffsynthetic-image-content"
    photo.write_bytes(content)
    record = Media(
        media_id="image-1",
        post_id=post().post_id,
        kind="photo",
        original_reference="photo.jpg",
        relative_path="photo.jpg",
        status="available",
        content_hash=file_hash(content),
    )
    manifest = MediaManifest(
        dataset_id="fixture", generated_at=datetime.now(UTC), media=[record]
    )
    assets, by_post = copy_media(data, sources, manifest, [post()])
    target = data / "published/media" / assets[0].filename
    assert target.read_bytes() == content
    assert by_post[post().post_id] == ["image-1"]
    photo.write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash changed"):
        copy_media(data, sources, manifest, [post()])
    assert target.read_bytes() == content
    photo.unlink()
    assert copy_media(data, sources, manifest, [post()])[0] == []
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(content)
    photo.symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        copy_media(data, sources, manifest, [post()])
    record.status = "unsafe"
    with pytest.raises(ValueError, match="unsafe"):
        copy_media(data, sources, manifest, [post()])


def test_publication_failure_preserves_previous_json(
    demo, settings, clock, monkeypatch
):
    data, selection, _, sources = demo
    fake_response(monkeypatch)
    geocode(data, selection, settings)
    approve(data, selection)
    geocode(data, selection, settings, offline=True)
    publish(data, selection, allow_partial=True, sources_path=sources)
    path = data / "published/deals.json"
    before = path.read_bytes()

    def fail_write(*args):
        raise OSError("synthetic publication failure")

    monkeypatch.setattr("food_deals_mvp.publishing.atomic_write", fail_write)
    with pytest.raises(OSError, match="synthetic"):
        publish(data, selection, allow_partial=True, sources_path=sources)
    assert path.read_bytes() == before


def test_targeted_refresh_is_bounded_and_invalidates_approval(
    demo, settings, clock, monkeypatch
):
    data, selection, _, _ = demo
    calls = fake_response(monkeypatch)
    geocode(data, selection, settings)
    approve(data, selection)
    geocode(data, selection, settings, offline=True)
    _, artifact = load_geocoding_report(data)
    key = artifact.rows[0].queries[0]
    report = geocode(data, selection, settings, refresh_query=key)
    assert len(calls) == 2 and report.counts["http_attempts"] == 1
    assert report.errors and "stale" in report.errors[0]
    with pytest.raises(ValueError, match="not a query"):
        geocode(data, selection, settings, refresh_query="not-a-query")
    assert len(calls) == 2
