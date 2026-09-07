"""Read-only HTTP contract against synthetic snapshots and temporary media."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from food_deals_mvp import api_settings
from food_deals_mvp.api import create_app
from food_deals_mvp.api_settings import ApiSettings
from food_deals_mvp.public_models import PublishedDataset
from food_deals_mvp.storage import file_hash, fingerprint

PHOTO = b"\xff\xd8\xffsynthetic image"


def write_snapshot(directory, payload):
    payload["dataset_id"] = fingerprint(
        {k: v for k, v in payload.items() if k not in {"dataset_id", "generated_at"}}
    )
    (directory / "deals.json").write_text(json.dumps(payload))


@pytest.fixture
def published(tmp_path):
    availability = {
        "start_date": None,
        "end_date": None,
        "valid_dates": None,
        "weekdays": None,
        "restrictions_text": ["While stocks last"],
        "date_status": "unspecified",
        "evidence": ["caption evidence"],
        "interpretation": "private extraction interpretation",
    }
    rows: list[dict[str, Any]] = []
    for key in "dcba":  # Deliberately unsorted, including equal timestamps.
        rows.append(
            {
                "deal_id": key,
                "post_id": "post-" + ("a" if key == "b" else key),
                "offer_id": "offer-" + ("a" if key == "b" else key),
                "source_name": "Synthetic channel",
                "title": "Offer " + key,
                "description": "Example offer",
                "merchant": "Example merchant",
                "terms": [],
                "posted_at": "2026-08-24T00:00:00Z"
                if key == "d"
                else "2026-08-25T16:00:00Z",
                "source_caption": "<script>alert('caption')</script>",
                "telegram_url": "https://t.me/example/1",
                "information_links": [],
                "location_label": "Example Mall",
                "unit": None,
                "location_scope": "explicit",
                "resolved_label": "Example Mall, Singapore",
                "mapping_status": "mapped",
                "precision": "building",
                "latitude": 1.3 if key in "ab" else 1.4,
                "longitude": 103.8,
                "media_ids": ["photo-1"] if key in "ab" else [],
                "image_url": "/media/photo-1" if key in "ab" else None,
                "availability": {**availability},
            }
        )
    by_id = {row["deal_id"]: row for row in rows}
    by_id["b"]["availability"].update(end_date="2026-08-25", date_status="parsed")
    by_id["c"]["availability"]["date_status"] = "needs_review"
    by_id["d"]["availability"].update(
        start_date="2026-08-26",
        end_date="2026-08-28",
        valid_dates=["2026-08-26", "2026-08-28"],
        weekdays=[3, 5],
        date_status="parsed",
    )
    digest = file_hash(PHOTO)
    payload = {
        "schema_version": 1,
        "dataset_id": "pending",
        "generated_at": "2026-09-07T00:00:00Z",
        "timezone": "Asia/Singapore",
        "source_dataset_id": "source",
        "demo_dataset_id": "demo",
        "selection_fingerprint": "selection",
        "resolution_dataset_id": "resolution",
        "source_date_range": ["2026-08-01", "2026-08-31"],
        "selected_source_date_range": ["2026-08-24", "2026-08-26"],
        "suggested_reference_date": "2026-08-26",
        "suggested_validity": "all",
        "dataset_complete": False,
        "processing_summary": {
            "source_posts": 10,
            "selected_rows": 5,
            "published_rows": 4,
            "omitted_rows": 1,
        },
        "attribution": [
            {
                "text": "© OpenStreetMap contributors",
                "url": "https://www.openstreetmap.org/copyright",
                "licence": "ODbL 1.0",
            }
        ],
        "media": [
            {
                "media_id": "photo-1",
                "filename": f"{digest}.jpg",
                "content_hash": digest,
                "mime_type": "image/jpeg",
            }
        ],
        "deals": rows,
    }
    # Normalize exactly as the publisher does before computing its fingerprint.
    payload = PublishedDataset.model_validate(payload).model_dump(mode="json")
    write_snapshot(tmp_path, payload)
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / f"{digest}.jpg").write_bytes(PHOTO)
    return tmp_path, payload


def test_default_contract_counts_sorting_and_public_projection(published, monkeypatch):
    directory, payload = published
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with TestClient(create_app(ApiSettings(published_dir=directory))) as client:
        response = client.get("/api/deals")
        assert response.status_code == 200
        data = response.json()
        assert data["filters"] == {
            "as_of": "2026-08-26",
            "validity": "all",
            "max_age_days": 60,
        }
        assert [row["deal_id"] for row in data["deals"]] == list("abcd")
        assert [row["validity_status"] for row in data["deals"]] == [
            "valid",
            "outside_period",
            "unknown",
            "valid",
        ]
        assert data["counts"] == {
            "matched_rows": 4,
            "mapped_rows": 4,
            "distinct_locations": 2,
            "distinct_offers": 3,
            "distinct_posts": 3,
        }
        assert data["processing_summary"]["selected_rows"] == 5
        assert data["dataset_complete"] is False
        assert data["attribution"] == payload["attribution"]
        for row in data["deals"]:
            assert set(row["availability"]) == {
                "start_date",
                "end_date",
                "valid_dates",
                "weekdays",
                "restrictions_text",
                "date_status",
            }
            assert row["source_caption"] == "<script>alert('caption')</script>"
        assert "private extraction" not in response.text
        assert str(directory) not in response.text
        assert "selection_fingerprint" not in data
        assert client.get("/api/health").json() == {
            "ready": True,
            "dataset_id": data["dataset_id"],
        }
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("validity=valid", "ad"),
        ("as_of=2026-08-27&validity=valid", "a"),  # Explicit-date gap / weekday.
        ("as_of=2026-08-28&validity=valid", "ad"),  # Inclusive end.
        ("as_of=2026-08-29&validity=valid", "a"),
        ("as_of=2026-08-25", "d"),  # UTC Aug 25 posts belong to SG Aug 26.
        ("as_of=2026-08-23", ""),
        ("as_of=2026-10-24", "abc"),  # Age 59 included, older row excluded.
        ("as_of=2026-10-25", ""),  # Age 60 excluded, including unknown expiry.
    ],
)
def test_date_and_age_filters(published, query, expected):
    with TestClient(create_app(ApiSettings(published_dir=published[0]))) as client:
        response = client.get("/api/deals?" + query)
        assert response.status_code == 200
        data = response.json()
        assert [row["deal_id"] for row in data["deals"]] == list(expected)
        assert (
            data["counts"]["matched_rows"]
            == data["counts"]["mapped_rows"]
            == len(expected)
        )
        if not expected:
            assert all(value == 0 for value in data["counts"].values())


@pytest.mark.parametrize(
    "query",
    [
        "as_of=2026-02-30",
        "as_of=20260826",
        "as_of=2026-08-26T00:00:00",
        "as_of=1787673600",
        "as_of=",
        "validity=unknown",
        "mapping=all",
        "max_age_days=1",
    ],
)
def test_invalid_queries(published, query):
    with TestClient(create_app(ApiSettings(published_dir=published[0]))) as client:
        assert client.get("/api/deals?" + query).status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("deals", []),
        ("dataset_id", "wrong"),
        ("source_date_range", ["2026-09-01", "2026-08-01"]),
        ("processing_summary", {"published_rows": 99, "selected_rows": 5}),
    ],
)
def test_invalid_snapshots_fail_closed(published, field, value):
    directory, payload = published
    payload[field] = value
    write_snapshot(directory, payload)
    if field == "dataset_id":
        payload[field] = value
        (directory / "deals.json").write_text(json.dumps(payload))
    with TestClient(create_app(ApiSettings(published_dir=directory))) as client:
        for route in ["/api/health", "/api/deals"]:
            response = client.get(route)
            assert response.status_code == 503
            assert response.json() == {"detail": "Published dataset is invalid"}
        assert client.get("/").status_code == 200


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("latitude", None),
        ("longitude", 181),
        ("deal_id", "a"),
        ("media_ids", ["unknown"]),
        ("image_url", "/etc/passwd"),
        ("telegram_url", "javascript:alert(1)"),
        ("information_links", ["file:///secret"]),
    ],
)
def test_invalid_rows_fail_closed(published, field, value):
    directory, payload = published
    payload["deals"][0][field] = value
    write_snapshot(directory, payload)
    with TestClient(create_app(ApiSettings(published_dir=directory))) as client:
        assert client.get("/api/deals").status_code == 503


def test_missing_corrupt_and_restart_to_reload(published):
    directory, payload = published
    settings = ApiSettings(published_dir=directory)
    app = create_app(settings)
    with TestClient(app) as client:
        original = client.get("/api/deals").json()
        payload["deals"][0]["title"] = "New title"
        write_snapshot(directory, payload)
        assert client.get("/api/deals").json() == original
    with TestClient(app) as client:
        updated = client.get("/api/deals").json()
        assert updated["dataset_id"] != original["dataset_id"]
        assert updated["deals"][-1]["title"] == "New title"
        (directory / "deals.json").write_text("broken JSON")
        assert client.get("/api/deals").json() == updated
    with TestClient(app) as client:
        assert client.get("/api/deals").status_code == 503
    (directory / "deals.json").unlink()
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"detail": "Prepare a dataset first"}
        assert client.get("/api/deals").status_code == 503
        assert client.get("/").status_code == 200
        assert client.get("/media/photo-1").status_code == 404


def test_static_media_and_conditional_cache(published):
    directory, _ = published
    with TestClient(create_app(ApiSettings(published_dir=directory))) as client:
        for route in ["/", "/static/app.js", "/static/app.css"]:
            assert client.get(route).status_code == 200
        for route in [
            "/media/missing",
            "/media/%2e%2e%2f%2e%2e%2fsecret",
            "/static/%2e%2e/api.py",
            "/static/%2fetc/passwd",
        ]:
            assert client.get(route).status_code == 404
        response = client.get("/media/photo-1")
        assert response.content == PHOTO
        assert response.headers["content-type"] == "image/jpeg"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-cache"
        etag = response.headers["etag"]
        assert (
            client.get(
                "/media/photo-1", headers={"If-None-Match": f'"other", W/{etag}'}
            ).status_code
            == 304
        )
        assert (
            client.get("/media/photo-1", headers={"If-None-Match": '"old"'}).status_code
            == 200
        )
        # Unlisted files cannot be fetched by guessing their hash filename.
        assert client.get("/media/" + file_hash(PHOTO) + ".jpg").status_code == 404


@pytest.mark.parametrize(
    "damage", ["missing", "changed", "file_symlink", "directory_symlink"]
)
def test_missing_or_unsafe_media_does_not_break_deals(published, damage):
    directory, payload = published
    path = directory / "media" / payload["media"][0]["filename"]
    outside = directory / "outside.jpg"
    outside.write_bytes(PHOTO)
    with TestClient(create_app(ApiSettings(published_dir=directory))) as client:
        if damage == "directory_symlink":
            (directory / "media").rename(directory / "old-media")
            (directory / "media").symlink_to(
                directory / "old-media", target_is_directory=True
            )
        elif damage == "changed":
            path.write_bytes(b"private content")
        else:
            path.unlink()
            if damage == "file_symlink":
                path.symlink_to(outside)
        assert client.get("/media/photo-1").status_code == 404
        assert client.get("/api/deals").status_code == 200


def test_env_settings_ignore_cwd_and_apply_cutoff(published, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FOOD_DEALS_PUBLISHED_DIR", raising=False)
    monkeypatch.delenv("FOOD_DEALS_MAX_AGE_DAYS", raising=False)
    project = Path(api_settings.__file__).resolve().parents[2]
    assert ApiSettings.from_env().published_dir == project / "data/published"
    monkeypatch.setenv("FOOD_DEALS_PUBLISHED_DIR", "custom/published")
    assert ApiSettings.from_env().published_dir == project / "custom/published"
    monkeypatch.setenv("FOOD_DEALS_PUBLISHED_DIR", str(published[0]))
    monkeypatch.setenv("FOOD_DEALS_MAX_AGE_DAYS", "1")
    with TestClient(create_app()) as client:
        data = client.get("/api/deals").json()
        assert data["filters"]["max_age_days"] == 1
        assert [row["deal_id"] for row in data["deals"]] == list("abc")


@pytest.mark.parametrize("value", ["0", "-1", "3651", "two months", ""])
def test_invalid_environment_keeps_shell_available(tmp_path, monkeypatch, value):
    monkeypatch.setenv("FOOD_DEALS_PUBLISHED_DIR", str(tmp_path))
    monkeypatch.setenv("FOOD_DEALS_MAX_AGE_DAYS", value)
    with TestClient(create_app()) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/deals").status_code == 503
        assert client.get("/api/health").json() == {
            "detail": "Application configuration is invalid"
        }


def test_installed_package_requires_absolute_data_path(tmp_path, monkeypatch):
    monkeypatch.setattr(
        api_settings, "__file__", str(tmp_path / "lib/pkg/api_settings.py")
    )
    monkeypatch.delenv("FOOD_DEALS_PUBLISHED_DIR", raising=False)
    monkeypatch.delenv("FOOD_DEALS_MAX_AGE_DAYS", raising=False)
    with pytest.raises(ValueError, match="Set FOOD_DEALS_PUBLISHED_DIR"):
        ApiSettings.from_env()
    monkeypatch.setenv("FOOD_DEALS_PUBLISHED_DIR", "relative")
    with pytest.raises(ValueError, match="must be absolute"):
        ApiSettings.from_env()
    monkeypatch.setenv("FOOD_DEALS_PUBLISHED_DIR", str(tmp_path))
    assert ApiSettings.from_env().published_dir == tmp_path


def test_api_import_does_not_load_pipeline():
    # A fresh process is necessary because other test modules import the pipeline.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import food_deals_mvp.api; "
                "assert not any('food_deals_mvp.' + name in sys.modules for name in "
                "['cli', 'publishing', 'geocoding', 'extraction', 'openrouter', 'nominatim'])"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
