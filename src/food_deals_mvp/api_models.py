"""Explicit browser-facing response contracts without extraction review notes."""

from datetime import date
from typing import Literal

from .models import Contract, Envelope
from .public_models import Attribution, DealFields

Validity = Literal["all", "valid"]
ValidityStatus = Literal["valid", "outside_period", "unknown"]


class DisplayAvailability(Contract):
    start_date: date | None
    end_date: date | None
    valid_dates: list[date] | None
    weekdays: list[int] | None
    restrictions_text: list[str]
    date_status: Literal["parsed", "unspecified", "needs_review"]


class DealResponse(DealFields):
    availability: DisplayAvailability
    validity_status: ValidityStatus


class Filters(Contract):
    as_of: date
    validity: Validity
    max_age_days: int


class Counts(Contract):
    matched_rows: int
    mapped_rows: int
    distinct_locations: int
    distinct_offers: int
    distinct_posts: int


class DealsResponse(Envelope):
    source_date_range: tuple[date, date]
    selected_source_date_range: tuple[date, date]
    suggested_reference_date: date
    suggested_validity: Literal["all"]
    dataset_complete: bool
    processing_summary: dict[str, int]
    attribution: list[Attribution]
    filters: Filters
    counts: Counts
    deals: list[DealResponse]


class HealthResponse(Contract):
    ready: Literal[True] = True
    dataset_id: str
