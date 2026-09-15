"""Gemini meal classification contract tests."""

import json

import pytest

from food_deals_mvp.meal_classification import (
    GeminiError,
    GeminiMealClassifier,
    GeminiSettings,
    enrich_published_meals,
)
from food_deals_mvp.meal_models import MealClassification, MealClassifications
from food_deals_mvp.public_models import PublicDeal, PublishedDataset
from food_deals_mvp.storage import fingerprint


def deal(deal_id: str) -> PublicDeal:
    return PublicDeal.model_validate(
        {
            "deal_id": deal_id,
            "post_id": f"post-{deal_id}",
            "offer_id": f"offer-{deal_id}",
            "source_name": "Test",
            "title": "Coffee and cake",
            "description": "A drink with a small dessert",
            "merchant": "Cafe",
            "terms": [],
            "posted_at": "2026-09-01T00:00:00Z",
            "source_caption": "Coffee and cake deal",
            "telegram_url": None,
            "information_links": [],
            "location_label": "Test Mall",
            "unit": None,
            "location_scope": "explicit",
            "resolved_label": "Test Mall",
            "precision": "building",
            "latitude": 1.3,
            "longitude": 103.8,
            "media_ids": [],
            "image_url": None,
            "availability": {
                "start_date": None,
                "end_date": None,
                "valid_dates": None,
                "weekdays": None,
                "restrictions_text": [],
                "date_status": "unspecified",
                "evidence": [],
                "interpretation": "No dates stated",
            },
        }
    )


def test_classifier_sends_structured_request_without_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-secret")
    calls = []

    def fake(model, key, timeout, payload):
        calls.append((model, key, timeout, payload))
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "classifications": [
                                            {
                                                "deal_id": "a",
                                                "meal_types": ["drink", "snack"],
                                            }
                                        ]
                                    }
                                )
                            }
                        ]
                    }
                }
            ]
        }

    monkeypatch.setattr("food_deals_mvp.meal_classification.request_json", fake)
    result = GeminiMealClassifier(GeminiSettings()).classify([deal("a")])
    assert result.classifications[0].meal_types == ["drink", "snack"]
    model, key, _, payload = calls[0]
    assert model == "gemini-3.8-flash"
    assert key == "synthetic-secret"
    assert payload["generationConfig"]["responseMimeType"] == "application/json"
    assert "responseJsonSchema" in payload["generationConfig"]
    assert "synthetic-secret" not in json.dumps(payload)


@pytest.mark.parametrize(
    "classifications",
    [
        [{"deal_id": "a", "meal_types": ["drink"]}],
        [
            {"deal_id": "a", "meal_types": ["drink"]},
            {"deal_id": "a", "meal_types": ["snack"]},
        ],
        [
            {"deal_id": "a", "meal_types": ["drink"]},
            {"deal_id": "b", "meal_types": ["brunch"]},
        ],
    ],
)
def test_classifier_rejects_missing_duplicate_or_invalid_results(
    monkeypatch, classifications
):
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-secret")
    monkeypatch.setattr(
        "food_deals_mvp.meal_classification.request_json",
        lambda *args: {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {"classifications": classifications}
                                )
                            }
                        ]
                    }
                }
            ]
        },
    )
    with pytest.raises(GeminiError):
        GeminiMealClassifier(GeminiSettings()).classify([deal("a"), deal("b")])


def test_enrichment_backs_up_and_atomically_rewrites_snapshot(tmp_path):
    published = tmp_path / "published"
    published.mkdir()
    deals = [deal("a"), deal("b")]
    snapshot = PublishedDataset.model_validate(
        {
            "dataset_id": "pending",
            "generated_at": "2026-09-01T00:00:00Z",
            "source_dataset_id": "source",
            "demo_dataset_id": "demo",
            "selection_fingerprint": "selection",
            "resolution_dataset_id": "resolution",
            "source_date_range": ["2026-09-01", "2026-09-01"],
            "selected_source_date_range": ["2026-09-01", "2026-09-01"],
            "suggested_reference_date": "2026-09-01",
            "suggested_validity": "all",
            "dataset_complete": True,
            "processing_summary": {
                "selected_rows": 2,
                "published_rows": 2,
                "omitted_rows": 0,
            },
            "attribution": [],
            "media": [],
            "deals": [item.model_dump(mode="json") for item in deals],
        }
    )
    snapshot.dataset_id = fingerprint(
        snapshot.model_dump(mode="json", exclude={"dataset_id", "generated_at"})
    )
    original = snapshot.model_dump_json(indent=2) + "\n"
    (published / "deals.json").write_text(original)

    class FakeClassifier:
        def classify(self, deals):
            return MealClassifications(
                classifications=[
                    MealClassification(deal_id=item.deal_id, meal_types=["lunch"])
                    for item in deals
                ]
            )

    enriched, backup = enrich_published_meals(
        published, batch_size=1, classifier=FakeClassifier()
    )
    assert backup.read_text() == original
    assert [item.meal_types for item in enriched.deals] == [["lunch"], ["lunch"]]
    saved = PublishedDataset.model_validate_json((published / "deals.json").read_text())
    assert saved.dataset_id == fingerprint(
        saved.model_dump(mode="json", exclude={"dataset_id", "generated_at"})
    )
