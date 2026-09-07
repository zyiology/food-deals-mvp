"""Bounded caption extraction contracts; model output contains no generated IDs."""

from datetime import date
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from .models import Contract, Envelope

Text = Annotated[str, Field(min_length=1, max_length=2000)]
ShortText = Annotated[str, Field(min_length=1, max_length=300)]
Excerpts = Annotated[list[Text], Field(max_length=30)]
DateList = Annotated[list[date], Field(min_length=1, max_length=100)]
Weekdays = Annotated[
    list[Annotated[int, Field(strict=True, ge=1, le=7)]],
    Field(min_length=1, max_length=7),
]
DateField = Literal["start_date", "end_date", "valid_dates", "weekdays"]


class Availability(Contract):
    start_date: date | None
    end_date: date | None
    valid_dates: DateList | None
    weekdays: Weekdays | None
    restrictions_text: Excerpts
    date_status: Literal["parsed", "unspecified", "needs_review"]
    evidence: Excerpts
    interpretation: Text | None


class AvailabilityOverride(Availability):
    # Null inherits. Explicit evidence-backed clearing is separate from absence.
    clear_fields: Annotated[list[DateField], Field(max_length=4)]
    remove_restrictions: Excerpts
    exception_evidence: Excerpts

    @model_validator(mode="after")
    def validate_exceptions(self):
        if len(self.clear_fields) != len(set(self.clear_fields)):
            raise ValueError("duplicate clear_fields")
        if any(getattr(self, name) is not None for name in self.clear_fields):
            raise ValueError("a constraint cannot be both set and cleared")
        if (
            self.clear_fields or self.remove_restrictions
        ) and not self.exception_evidence:
            raise ValueError("clearing requires explicit caption evidence")
        return self


class Location(Contract):
    label: ShortText
    venue: ShortText | None
    address: ShortText | None
    unit: ShortText | None
    evidence: Annotated[list[Text], Field(min_length=1, max_length=20)]
    availability_override: AvailabilityOverride | None


class Offer(Contract):
    title: ShortText
    description: Text
    merchant: ShortText | None
    terms: Excerpts
    evidence: Annotated[list[Text], Field(min_length=1, max_length=30)]
    availability: Availability
    location_scope: Literal[
        "explicit", "all_outlets", "selected_outlets", "online_only", "unspecified"
    ]
    excluded_outlets: Annotated[list[ShortText], Field(max_length=50)]
    incomplete_scope_note: Text | None
    locations: Annotated[list[Location], Field(max_length=50)]
    review_reasons: Excerpts


class Extraction(Contract):
    relevance: Literal["food", "non_food", "uncertain"]
    promotion_kind: Literal[
        "food_promotion", "pure_listing", "mixed_promotion", "uncertain"
    ]
    reason: Text
    evidence: Annotated[list[Text], Field(min_length=1, max_length=30)]
    offers: Annotated[list[Offer], Field(max_length=30)]
    review_reasons: Excerpts


class Candidate(Contract):
    row_id: str
    post_id: str
    offer_id: str
    location_id: str | None
    title: str
    description: str
    merchant: str | None
    terms: list[str]
    location_scope: str
    excluded_outlets: list[str]
    incomplete_scope_note: str | None
    location: Location | None
    availability: Availability
    status: Literal["candidate", "unmapped", "needs_review"]
    reasons: list[str]
    warnings: list[str] = Field(default_factory=list)


class PostResult(Contract):
    post_id: str
    input_hash: str
    cache_key: str
    status: Literal["success", "needs_review", "failed", "not_selected", "pending"]
    extraction: Extraction | None = None
    errors: list[str] = Field(default_factory=list)
    correction_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExtractionArtifact(Envelope):
    source_dataset_id: str
    settings_hash: str
    results: list[PostResult]


class CandidateArtifact(Envelope):
    source_dataset_id: str
    rows: list[Candidate]


class ExtractionReport(Envelope):
    source_dataset_id: str
    status: Literal["success", "partial", "failed", "dry_run"]
    settings_hash: str
    selected_ids: list[str]
    counts: dict[str, int]
    errors: list[str]
    outcomes: dict[str, str]
    review: dict[str, list[str]]
    budget: dict[str, str | int]
    replacements: dict[str, dict[str, list[str]]]
    cache_fingerprints: dict[str, str]


class Correction(Contract):
    correction_id: ShortText
    post_id: str
    input_hash: str
    cache_key: str
    # RFC 6901 pointer into the parsed response; an exact old value guards drift.
    pointer: str
    expected: object
    value: object
    reason: Text
    evidence: Annotated[list[Text], Field(min_length=1, max_length=30)]
    reviewed_at: AwareDatetime


class Corrections(Contract):
    schema_version: Literal[1] = 1
    corrections: list[Correction]
