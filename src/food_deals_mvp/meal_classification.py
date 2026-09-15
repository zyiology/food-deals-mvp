"""One-time Gemini meal classification for published deals."""

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import Field

from .meal_models import MealClassifications, MealType
from .models import Contract
from .public_models import PublicDeal, PublishedDataset
from .storage import atomic_write, fingerprint, parse_json, read_json

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
SYSTEM_PROMPT = """Classify each food deal into every meal type it clearly fits.

Allowed labels:
- drink: beverage offers, including coffee, tea, alcohol, and other drinks.
- breakfast: explicitly breakfast/morning offers or standard breakfast foods.
- lunch: substantial meals suitable for lunch or offers explicitly available at lunch.
- dinner: substantial meals suitable for dinner or offers explicitly available at dinner.
- snack: desserts, pastries, small bites, and other light food.

A deal may have multiple labels. Use an empty list only when none fits. Base the
answer only on the supplied deal text. Return every supplied deal_id exactly once.
"""


class GeminiSettings(Contract):
    model: str = Field(default="gemini-3.8-flash", pattern=r"^[A-Za-z0-9._-]+$")
    timeout: float = Field(default=60, gt=0, le=120)

    @classmethod
    def from_env(cls) -> GeminiSettings:
        return cls(model=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"))


class GeminiError(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(
    model: str, key: str, timeout: float, payload: dict[str, Any]
) -> Any:
    request = Request(
        f"{BASE_URL}/{quote(model, safe='')}:generateContent",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        data=json.dumps(payload, ensure_ascii=False).encode(),
        method="POST",
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            content = response.read(4_000_001)
            if len(content) > 4_000_000:
                raise GeminiError("Gemini response exceeds size limit")
            return parse_json(content)
    except HTTPError as exc:
        raise GeminiError(f"Gemini HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError) as exc:
        raise GeminiError("Gemini transport failure or timeout") from exc
    except ValueError as exc:
        if isinstance(exc, GeminiError):
            raise
        raise GeminiError("Gemini returned invalid JSON") from exc


def deal_input(deal: PublicDeal) -> dict[str, object]:
    return {
        "deal_id": deal.deal_id,
        "title": deal.title,
        "description": deal.description,
        "merchant": deal.merchant,
        "terms": deal.terms,
        "source_caption": deal.source_caption,
    }


class GeminiMealClassifier:
    def __init__(self, settings: GeminiSettings):
        self.settings = settings
        self.key = os.environ.get("GEMINI_API_KEY", "")
        if not self.key:
            raise GeminiError("set GEMINI_API_KEY for meal classification")

    def classify(self, deals: list[PublicDeal]) -> MealClassifications:
        if not deals:
            return MealClassifications(classifications=[])
        schema = MealClassifications.model_json_schema()
        response = request_json(
            self.settings.model,
            self.key,
            self.settings.timeout,
            {
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": json.dumps(
                                    [deal_input(deal) for deal in deals],
                                    ensure_ascii=False,
                                )
                            }
                        ],
                    }
                ],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                    "responseJsonSchema": schema,
                },
            },
        )
        try:
            parts = response["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts)
            result = MealClassifications.model_validate_json(text)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GeminiError("Gemini returned an invalid classification") from exc
        expected = [deal.deal_id for deal in deals]
        actual = [item.deal_id for item in result.classifications]
        if len(actual) != len(set(actual)) or set(actual) != set(expected):
            raise GeminiError("Gemini classification IDs do not match the request")
        order = {deal_id: index for index, deal_id in enumerate(expected)}
        result.classifications.sort(key=lambda item: order[item.deal_id])
        return result


class MealClassifier(Protocol):
    def classify(self, deals: list[PublicDeal]) -> MealClassifications: ...


def classify_published_dry_run(
    published_dir: Path, *, limit: int | None = None
) -> MealClassifications:
    snapshot = PublishedDataset.model_validate(read_json(published_dir / "deals.json"))
    deals = snapshot.deals[:limit] if limit is not None else snapshot.deals
    return GeminiMealClassifier(GeminiSettings.from_env()).classify(deals)


def enrich_published_meals(
    published_dir: Path,
    *,
    batch_size: int = 20,
    classifier: MealClassifier | None = None,
) -> tuple[PublishedDataset, Path]:
    if batch_size <= 0:
        raise ValueError("batch size must be positive")
    snapshot_path = published_dir / "deals.json"
    snapshot = PublishedDataset.model_validate(read_json(snapshot_path))
    client = classifier or GeminiMealClassifier(GeminiSettings.from_env())
    labels: dict[str, list[MealType]] = {}
    for start in range(0, len(snapshot.deals), batch_size):
        batch = snapshot.deals[start : start + batch_size]
        result = client.classify(batch)
        for item in result.classifications:
            if item.deal_id in labels:
                raise GeminiError("duplicate classification across batches")
            labels[item.deal_id] = list(item.meal_types)
    expected = {deal.deal_id for deal in snapshot.deals}
    if set(labels) != expected:
        raise GeminiError("classifications do not cover the published dataset")
    snapshot.deals = [
        deal.model_copy(update={"meal_types": labels[deal.deal_id]})
        for deal in snapshot.deals
    ]
    snapshot.generated_at = datetime.now(UTC)
    snapshot.dataset_id = fingerprint(
        snapshot.model_dump(mode="json", exclude={"dataset_id", "generated_at"})
    )
    PublishedDataset.model_validate(snapshot.model_dump(mode="json"))
    backup_dir = published_dir.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"deals.pre-meal-{stamp}.json"
    if backup_path.exists():
        raise ValueError("meal-classification backup already exists")
    shutil.copy2(snapshot_path, backup_path)
    atomic_write(snapshot_path, snapshot)
    return snapshot, backup_path
