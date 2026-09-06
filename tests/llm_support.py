"""Synthetic fixtures: never provider calls or copies of the pilot captions."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from food_deals_mvp.extraction_models import Availability, Extraction
from food_deals_mvp.extraction_prompt import post_input
from food_deals_mvp.llm_budget import MODEL
from food_deals_mvp.models import SourcePost
from food_deals_mvp.preprocessing import normalize
from food_deals_mvp.storage import fingerprint, load_normalized

CAPTION = (
    "Tea for $2 at Example Mall, #01-02. 1-31 Aug. Weekdays only. While stocks last."
)


def availability(**changes: Any) -> Availability:
    return Availability.model_validate(
        {
            "start_date": None,
            "end_date": None,
            "valid_dates": None,
            "weekdays": None,
            "restrictions_text": [],
            "date_status": "unspecified",
            "evidence": [],
            "interpretation": None,
            **changes,
        }
    )


def extraction(**changes: Any) -> Extraction:
    return Extraction.model_validate(
        {
            "relevance": "food",
            "promotion_kind": "food_promotion",
            "reason": "Tea discount",
            "evidence": ["Tea for $2"],
            "review_reasons": [],
            "offers": [
                {
                    "title": "$2 tea",
                    "description": "Tea for $2",
                    "merchant": None,
                    "terms": ["While stocks last."],
                    "evidence": ["Tea for $2"],
                    "availability": availability(
                        start_date="2026-08-01",
                        end_date="2026-08-31",
                        weekdays=[1, 2, 3, 4, 5],
                        date_status="parsed",
                        evidence=["1-31 Aug.", "Weekdays only."],
                    ).model_dump(mode="json"),
                    "location_scope": "explicit",
                    "excluded_outlets": [],
                    "incomplete_scope_note": None,
                    "review_reasons": [],
                    "locations": [
                        {
                            "label": "Example Mall",
                            "venue": "Example Mall",
                            "address": None,
                            "unit": "#01-02",
                            "evidence": ["Tea for $2 at Example Mall, #01-02."],
                            "availability_override": None,
                        }
                    ],
                }
            ],
            **changes,
        }
    )


def post(text: str = CAPTION) -> SourcePost:
    value = SourcePost(
        post_id="telegram:101:1",
        channel_id=101,
        message_id=1,
        source_name="Example",
        username="example",
        telegram_url="https://t.me/example/1",
        posted_at=datetime.fromisoformat("2026-08-01T08:00:00+08:00"),
        edited_at=None,
        text=text,
        links=[],
        media_ids=[],
        source_file="export/result.json",
        source_content_hash="source",
        extraction_input_hash="",
        raw_record={},
    )
    value.extraction_input_hash = fingerprint(post_input(value))
    return value


def response(value: Extraction | None = None, **changes: Any) -> dict[str, Any]:
    return {
        "model": MODEL,
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": (value or extraction()).model_dump_json()},
            }
        ],
        "usage": {"cost": 0.01, "prompt_tokens": 100, "completion_tokens": 100},
        **changes,
    }


@dataclass
class FakeClient:
    replies: list[Any] = field(default_factory=list)
    maximum: Decimal = Decimal("0.10")
    calls: list[tuple[str, bool]] = field(default_factory=list)
    preflights: int = 0

    def preflight(self) -> Decimal:
        self.preflights += 1
        return self.maximum

    def complete(self, post: SourcePost, repair: bool = False) -> Any:
        self.calls.append((post.post_id, repair))
        reply = self.replies.pop(0) if self.replies else response()
        if isinstance(reply, BaseException):
            raise reply
        return reply


@dataclass
class LlmBatch:
    data_dir: Path
    state_dir: Path
    pilot_ids: Path
    posts: list[SourcePost]


def make_batch(root: Path) -> LlmBatch:
    sources = []
    for channel in (101, 102, 103):
        export = root / str(channel)
        export.mkdir(parents=True)
        (export / "result.json").write_text(
            json.dumps(
                {
                    "id": channel,
                    "name": "Example",
                    "type": "public_channel",
                    "messages": [
                        {
                            "id": message,
                            "type": "message",
                            "date": "2026-08-01T08:00:00",
                            "text": CAPTION,
                        }
                        for message in range(1, 12)
                    ],
                }
            )
        )
        sources.append(
            {
                "export_root": str(channel),
                "channel_id": channel,
                "name": "Example",
                "username": "example",
                "export_timezone": "Asia/Singapore",
            }
        )
    config = root / "sources.json"
    config.write_text(json.dumps({"sources": sources}))
    data = root / "data"
    assert normalize(config, data).status == "success"
    posts, _, _ = load_normalized(data)
    pilot = root / "pilot.json"
    pilot.write_text(json.dumps([p.post_id for p in posts.posts if p.message_id <= 10]))
    return LlmBatch(data, root / "state", pilot, posts.posts)
