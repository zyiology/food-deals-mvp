"""Offline regression coverage using small, synthetic Telegram exports."""

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from food_deals_mvp.cli import main
from food_deals_mvp.models import ImportReport, MediaManifest, Posts
from food_deals_mvp.preprocessing import clickable_url, normalize


@dataclass
class Batch:
    config_path: Path
    export_root: Path
    data_dir: Path
    record: dict[str, Any]

    def write(self, records: list[dict[str, Any]]) -> None:
        (self.export_root / "result.json").write_text(
            json.dumps(
                {
                    "id": 123,
                    "name": "Example",
                    "type": "public_channel",
                    "messages": records,
                }
            ),
            encoding="utf-8",
        )

    def run(self) -> ImportReport:
        return normalize(self.config_path, self.data_dir)

    def posts(self) -> Posts:
        return Posts.model_validate_json(
            (self.data_dir / "intermediate/posts.json").read_bytes()
        )

    def media(self) -> MediaManifest:
        return MediaManifest.model_validate_json(
            (self.data_dir / "intermediate/media.json").read_bytes()
        )


@pytest.fixture
def batch(tmp_path: Path) -> Batch:
    export_root = tmp_path / "export"
    export_root.mkdir()
    config_path = tmp_path / "sources.json"
    config_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "export_root": "export",
                        "channel_id": 123,
                        "name": "Example",
                        "username": "example",
                        "export_timezone": "Asia/Singapore",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    record = {
        "id": 1,
        "type": "message",
        "date": "2026-08-01T08:00:00",
        "date_unixtime": "1785542400",
        "edited": "2026-08-01T08:00:01",
        "edited_unixtime": "1785542401",
        "text": "Tea for $2 ☕\n#03-08 @unrelated",
    }
    result = Batch(config_path, export_root, tmp_path / "output", record)
    result.write([record])
    return result


def test_exact_caption_hidden_links_and_source_identity(batch: Batch) -> None:
    entity = {"type": "text_link", "text": "here", "href": "https://example.org/promo"}
    other_label = {**entity, "text": "details"}
    visible = {"type": "link", "text": "tco.sg/offer"}
    batch.write(
        [
            {
                **batch.record,
                "text": [
                    "☕ $2\n",
                    entity,
                    " / ",
                    other_label,
                    " ",
                    visible,
                    " @unrelated",
                ],
                "text_entities": [entity, other_label, visible],
            }
        ]
    )
    assert batch.run().status == "success"
    post = batch.posts().posts[0]
    assert post.text == "☕ $2\nhere / details tco.sg/offer @unrelated"
    assert post.telegram_url == "https://t.me/example/1"
    assert [
        (link.destination, link.labels, link.clickable_url) for link in post.links
    ] == [
        ("https://example.org/promo", ["here", "details"], "https://example.org/promo"),
        ("tco.sg/offer", ["tco.sg/offer"], "https://tco.sg/offer"),
    ]
    assert post.raw_record["text_entities"] == [entity, other_label, visible]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://example.org/a", "https://example.org/a"),
        ("http://example.org/a", "http://example.org/a"),
        ("tco.sg/promo", "https://tco.sg/promo"),
        ("javascript:alert(1)", None),
        ("data:text/html,test", None),
        ("//example.org", None),
        ("https://user:password@example.org", None),
        ("https://example.org:invalid", None),
        ("https://example.org\n", None),
        ("https://example.org\\evil", None),
    ],
)
def test_clickable_links(value: str, expected: str | None) -> None:
    assert clickable_url(value) == expected


def test_exclusions_keep_non_food_and_omitted_media_captions(batch: Batch) -> None:
    batch.write(
        [
            {
                **batch.record,
                "id": 2,
                "type": "service",
                "action": "pin_message",
                "text": "",
            },
            {**batch.record, "id": 3, "poll": {"question": "Where?"}, "text": ""},
            {
                **batch.record,
                "id": 4,
                "text": "Hair care offer",
                "file": "(File not included. Change data exporting settings to download.)",
            },
            batch.record,
        ]
    )
    report = batch.run()
    assert report.status == "success"
    assert (
        report.counts["raw_records"],
        report.counts["candidates"],
        report.counts["excluded"],
    ) == (4, 2, 2)
    assert [post.message_id for post in batch.posts().posts] == [1, 4]
    assert [post.text for post in batch.posts().posts] == [
        batch.record["text"],
        "Hair care offer",
    ]
    assert [(item.post_id, item.reason) for item in report.exclusions] == [
        ("telegram:123:2", "pin_service"),
        ("telegram:123:3", "empty_poll"),
    ]
    assert [(item.kind, item.status) for item in batch.media().media] == [
        ("file", "omitted"),
        ("thumbnail", "absent"),
    ]


@pytest.mark.parametrize(
    "reference",
    ["photos/present.jpg", "photos/missing.jpg", "../outside.jpg", "escape.jpg"],
)
def test_media_availability_and_containment(batch: Batch, reference: str) -> None:
    photos = batch.export_root / "photos"
    photos.mkdir()
    (photos / "present.jpg").write_bytes(b"synthetic media bytes")
    outside = batch.export_root.parent / "outside.jpg"
    outside.write_bytes(b"must not read")
    (batch.export_root / "escape.jpg").symlink_to(outside)
    batch.write([{**batch.record, "photo": reference}])
    assert batch.run().status == "success"
    item = batch.media().media[0]
    expected = {
        "photos/present.jpg": "available",
        "photos/missing.jpg": "missing",
        "../outside.jpg": "unsafe",
        "escape.jpg": "unsafe",
    }[reference]
    assert item.status == expected
    assert (item.content_hash is not None) == (expected == "available")
    if expected == "unsafe":
        assert item.relative_path is None


def test_timestamps_and_timezone_fallback(batch: Batch) -> None:
    assert batch.run().warnings == []
    post = batch.posts().posts[0]
    assert post.posted_at.isoformat() == "2026-08-01T08:00:00+08:00"
    assert post.edited_at == post.posted_at + timedelta(seconds=1)
    fallback = {
        key: value
        for key, value in batch.record.items()
        if not key.endswith("_unixtime")
    }
    batch.write([fallback])
    report = batch.run()
    assert report.status == "success"
    assert len(report.warnings) == 2
    assert batch.posts().posts[0].posted_at == post.posted_at
    assert batch.posts().posts[0].edited_at == post.edited_at


@pytest.mark.parametrize(
    "changes",
    [
        {"date": "2026-08-02T08:00:00"},
        {"date": None, "date_unixtime": None},
        {"date_unixtime": "invalid"},
        {"edited": "2026-08-01T07:59:59", "edited_unixtime": "1785542399"},
    ],
)
def test_invalid_timestamps_fail(batch: Batch, changes: dict[str, Any]) -> None:
    batch.write([{**batch.record, **changes}])
    report = batch.run()
    assert report.status == "failed"
    assert report.counts["bad_timestamps"] == 1
    assert not (batch.data_dir / "intermediate/posts.json").exists()


@pytest.mark.parametrize(
    "failure",
    [
        "duplicate",
        "invalid_text",
        "unknown_type",
        "invalid_json",
        "wrong_channel",
        "missing_export",
        "missing_config",
    ],
)
def test_failed_import_preserves_previous_snapshot(batch: Batch, failure: str) -> None:
    assert batch.run().status == "success"
    paths = [
        batch.data_dir / f"intermediate/{name}.json" for name in ("posts", "media")
    ]
    before = [path.read_bytes() for path in paths]
    export_path = batch.export_root / "result.json"
    if failure == "duplicate":
        batch.write([batch.record, batch.record])
    elif failure == "invalid_text":
        batch.write([{**batch.record, "text": 23}])
    elif failure == "unknown_type":
        batch.write([{**batch.record, "type": "unknown"}])
    elif failure == "invalid_json":
        export_path.write_text("{broken", encoding="utf-8")
    elif failure == "wrong_channel":
        export = json.loads(export_path.read_text())
        export["id"] = 999
        export_path.write_text(json.dumps(export), encoding="utf-8")
    elif failure == "missing_export":
        export_path.unlink()
    else:
        batch.config_path.unlink()
    report = batch.run()
    assert report.status == "failed"
    assert report.errors
    assert [path.read_bytes() for path in paths] == before
    saved_report = ImportReport.model_validate_json(
        (batch.data_dir / "reports/normalize.json").read_bytes()
    )
    assert saved_report.status == "failed"
    if failure == "duplicate":
        assert report.counts["duplicate_source_keys"] == 1
        assert (
            report.counts["raw_records"]
            == report.counts["candidates"] + report.counts["invalid_records"]
        )


def test_deterministic_reruns(batch: Batch) -> None:
    batch.write([{**batch.record, "id": 2}, batch.record])
    first = batch.run()
    paths = [
        batch.data_dir / name
        for name in (
            "intermediate/posts.json",
            "intermediate/media.json",
            "reports/normalize.json",
        )
    ]
    before = [json.loads(path.read_text()) for path in paths]
    second = batch.run()
    after = [json.loads(path.read_text()) for path in paths]
    assert (
        first.dataset_id
        == second.dataset_id
        == batch.posts().dataset_id
        == batch.media().dataset_id
    )
    for old, new in zip(before, after, strict=True):
        old.pop("generated_at")
        new.pop("generated_at")
        assert old == new
    assert [post.message_id for post in batch.posts().posts] == [1, 2]


def test_hashes_track_relevant_changes_only(batch: Batch) -> None:
    batch.run()
    original = batch.posts().posts[0]
    batch.write([{**batch.record, "reactions": [{"count": 42}]}])
    batch.run()
    reaction = batch.posts().posts[0]
    assert reaction.source_content_hash != original.source_content_hash
    assert reaction.extraction_input_hash == original.extraction_input_hash
    renamed = batch.export_root.with_name("renamed")
    batch.export_root.rename(renamed)
    configuration = json.loads(batch.config_path.read_text())
    configuration["sources"][0]["export_root"] = "renamed"
    batch.config_path.write_text(json.dumps(configuration), encoding="utf-8")
    batch.export_root = renamed
    batch.run()
    assert (
        batch.posts().posts[0].extraction_input_hash == original.extraction_input_hash
    )
    for changes in [
        {"text": "Different caption"},
        {
            "text_entities": [
                {"type": "text_link", "text": "here", "href": "https://example.org/new"}
            ]
        },
        {"edited": "2026-08-01T08:00:02", "edited_unixtime": "1785542402"},
    ]:
        batch.write([{**batch.record, **changes}])
        batch.run()
        changed = batch.posts().posts[0]
        assert changed.extraction_input_hash != original.extraction_input_hash
        assert changed.post_id == original.post_id


def test_cli_success_failure_and_mismatched_artifacts(
    batch: Batch, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "food-deals-mvp",
            "normalize",
            "--sources",
            str(batch.config_path),
            "--data-dir",
            str(batch.data_dir),
        ],
    )
    main()
    assert "normalize: success" in capsys.readouterr().out
    monkeypatch.setattr(
        "sys.argv",
        [
            "food-deals-mvp",
            "report",
            "--stage",
            "normalize",
            "--data-dir",
            str(batch.data_dir),
        ],
    )
    main()
    assert "normalize: success" in capsys.readouterr().out
    manifest_path = batch.data_dir / "intermediate/media.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["dataset_id"] = "different"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SystemExit) as failure:
        main()
    assert failure.value.code == 1
    assert "artifact dataset IDs differ" in capsys.readouterr().err
    batch.write([batch.record, batch.record])
    monkeypatch.setattr(
        "sys.argv",
        [
            "food-deals-mvp",
            "normalize",
            "--sources",
            str(batch.config_path),
            "--data-dir",
            str(batch.data_dir),
        ],
    )
    with pytest.raises(SystemExit) as failure:
        main()
    assert failure.value.code == 1
    assert "duplicate_source_keys" in capsys.readouterr().err


def test_supplied_exports_when_available(tmp_path: Path) -> None:
    project = Path(__file__).resolve().parents[1]
    exports = project / "Telegram_AUG_2026"
    roots = [
        exports / name
        for name in (
            "GoodLobang_AUG_2026",
            "KiasuFoodies_AUG_2026",
            "SGFoodDeals_AUG_2026",
        )
    ]
    if not all((root / "result.json").is_file() for root in roots):
        pytest.skip("Local Telegram exports are not included in the repository")
    before = [(root / "result.json").read_bytes() for root in roots]
    report = normalize(project / "config/sources.json", tmp_path)
    assert report.status == "success"
    assert report.counts["raw_records"] == 139
    assert report.counts["candidates"] == 136
    assert report.counts["pin_service"] == 2
    assert report.counts["empty_poll"] == 1
    assert report.counts["present_photos"] == 132
    assert report.counts["unavailable_attachments"] == 4
    assert report.errors == report.warnings == []
    posts = Posts.model_validate_json(
        (tmp_path / "intermediate/posts.json").read_bytes()
    )
    assert len({post.post_id for post in posts.posts}) == 136
    for post in posts.posts:
        text = post.raw_record["text"]
        if isinstance(text, list):
            flattened = "".join(
                fragment if isinstance(fragment, str) else str(fragment["text"])
                for fragment in text
                if isinstance(fragment, (str, dict))
            )
            assert post.text == flattened
        else:
            assert post.text == text
    assert [(root / "result.json").read_bytes() for root in roots] == before
