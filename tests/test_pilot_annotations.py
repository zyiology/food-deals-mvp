"""Validate draft labels structurally; these checks do not certify factual accuracy."""

import json
from collections import Counter
from pathlib import Path

import pytest

from food_deals_mvp.availability import schedule_issues
from food_deals_mvp.extraction_models import Availability, Extraction
from food_deals_mvp.extraction_prompt import SYSTEM_PROMPT
from food_deals_mvp.storage import fingerprint, load_normalized

PROJECT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT / "tests/fixtures/llm-pilot-annotations.json"


def test_archived_pilot_balance_holdout_coverage_and_original_identity():
    fixture = json.loads(FIXTURE.read_text())
    entries = fixture["entries"]
    ids = json.loads((PROJECT / "config/llm-pilot-post-ids.json").read_text())
    assert len(ids) == len(set(ids)) == len(entries) == 30
    assert set(ids) == {e["post_id"] for e in entries}
    assert set(Counter(e["source_name"] for e in entries).values()) == {10}
    assert set(
        Counter(e["source_name"] for e in entries if e["split"] == "held_out").values()
    ) == {3}
    assert {4623, 4883, 4904, 5257, 4607, 5282}.issubset(
        {e["message_id"] for e in entries if e["mandatory"]}
    )
    coverage = {tag for e in entries for tag in e["coverage"]}
    assert {
        "non_food",
        "online_only",
        "all_outlets",
        "selected_outlets",
        "exclusions",
        "ambiguous_location",
        "offer_splitting",
        "outlet_specific_dates",
        "separate_dates",
        "weekdays",
        "unknown_expiry",
        "pure_listing",
        "mixed_promotion",
    } <= coverage
    # Preserve the initial experiment's identity, not a freeze on future prompts.
    assert (
        fixture["frozen_prompt_hash"]
        == "8b6bb22e62344016c81fe8b96419df678b1de5b5f4b66763e2f5b691599a439b"
    )
    assert fixture["frozen_schema_hash"] == fingerprint(Extraction.model_json_schema())
    assert all(e["caption"] not in SYSTEM_PROMPT for e in entries)
    assert fixture["status"] == "awaiting_user_review"


def test_annotation_evidence_and_effective_schedules():
    fixture = json.loads(FIXTURE.read_text())

    def check(value, caption):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {
                    "evidence",
                    "classification_evidence",
                    "material_restrictions",
                }:
                    assert all(quote and quote in caption for quote in item)
                else:
                    check(item, caption)
        elif isinstance(value, list):
            for item in value:
                check(item, caption)

    for entry in fixture["entries"]:
        expected = entry["expected"]
        check(expected, entry["caption"])
        assert expected["offer_count"] == len(expected["offers"])
        assert expected["explicit_location_count"] == sum(
            len(o["locations"]) for o in expected["offers"]
        )
        for offer in expected["offers"]:
            for schedule in [
                offer["availability"],
                *[loc["effective_availability"] for loc in offer["locations"]],
            ]:
                assert not schedule_issues(
                    Availability.model_validate(
                        {**schedule, "restrictions_text": [], "interpretation": None}
                    )
                )
            if offer["location_scope"] == "online_only":
                assert offer["locations"] == []


def test_annotations_match_local_source_when_available():
    if not (PROJECT / "data/reports/normalize.json").exists():
        pytest.skip("local normalized exports are not present")
    posts, _, _ = load_normalized(PROJECT / "data")
    lookup = {p.post_id: p for p in posts.posts}
    for entry in json.loads(FIXTURE.read_text())["entries"]:
        post = lookup[entry["post_id"]]
        assert entry["caption"] == post.text
        assert entry["input_hash"] == post.extraction_input_hash
        assert entry["links"] == [link.model_dump(mode="json") for link in post.links]
