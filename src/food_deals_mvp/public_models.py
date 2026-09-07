"""Published snapshot contracts shared by the offline publisher and read-only API."""

from datetime import date
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field, model_validator

from .extraction_models import Availability
from .geocoding_models import Coordinates
from .models import Contract, Envelope


class PublicMedia(Contract):
    media_id: str
    filename: str = Field(pattern=r"^[0-9a-f]{64}\.(jpg|png)$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    mime_type: Literal["image/jpeg", "image/png"]


class DealFields(Coordinates):
    deal_id: str
    post_id: str
    offer_id: str
    source_name: str
    title: str
    description: str
    merchant: str | None
    terms: list[str]
    posted_at: AwareDatetime
    source_caption: str
    telegram_url: str | None
    information_links: list[str]
    location_label: str
    unit: str | None
    location_scope: str
    resolved_label: str
    mapping_status: Literal["mapped"] = "mapped"
    precision: Literal["building", "outlet"]
    media_ids: list[str]
    image_url: str | None


class PublicDeal(DealFields):
    availability: Availability


class Attribution(Contract):
    text: str = "© OpenStreetMap contributors"
    url: str = "https://www.openstreetmap.org/copyright"
    licence: str = "ODbL 1.0"


class PublishedDataset(Envelope):
    source_dataset_id: str
    demo_dataset_id: str
    selection_fingerprint: str
    resolution_dataset_id: str
    source_date_range: tuple[date, date]
    selected_source_date_range: tuple[date, date]
    suggested_reference_date: date
    suggested_validity: Literal["all"] = "all"
    dataset_complete: bool
    processing_summary: dict[str, int]
    attribution: list[Attribution]
    media: list[PublicMedia]
    deals: list[PublicDeal] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        ids = [r.deal_id for r in self.deals]
        media_ids = [m.media_id for m in self.media]
        if len(set(ids)) != len(ids) or len(set(media_ids)) != len(media_ids):
            raise ValueError("duplicate public deal/media IDs")
        if any(set(r.media_ids) - set(media_ids) for r in self.deals):
            raise ValueError("unknown public media reference")
        if self.processing_summary.get("published_rows") != len(self.deals):
            raise ValueError("public row count mismatch")
        if self.processing_summary.get("selected_rows") != len(
            self.deals
        ) + self.processing_summary.get("omitted_rows", 0):
            raise ValueError("selected row count mismatch")
        return self


def safe_url(value: str | None) -> str | None:
    if not value:
        return None
    url = urlsplit(value)
    return (
        value
        if url.scheme in {"http", "https"}
        and url.netloc
        and not url.username
        and not url.password
        else None
    )
