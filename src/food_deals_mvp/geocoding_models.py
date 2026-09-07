"""Contracts shared by geocoding, human review, and offline publication."""

from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from .models import Contract, Envelope


class Selection(Contract):
    schema_version: Literal[1] = 1
    dataset_id: str
    row_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len(set(self.row_ids)) != len(self.row_ids):
            raise ValueError("duplicate selected row IDs")
        return self


class GeocodingSettings(Contract):
    endpoint: str = "https://nominatim.openstreetmap.org/search"
    user_agent: str = ""
    interval: float = Field(default=1.1, ge=1, allow_inf_nan=False)
    connect_timeout: float = Field(default=10, gt=0, le=60)
    read_timeout: float = Field(default=30, gt=0, le=60)
    retries: int = Field(default=2, ge=0, le=2)

    @model_validator(mode="after")
    def valid_endpoint(self) -> Self:
        url = urlsplit(self.endpoint)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError(
                "geocoding endpoint must be an HTTPS URL without credentials/query"
            )
        if "\r" in self.user_agent or "\n" in self.user_agent:
            raise ValueError("invalid User-Agent")
        return self


class Query(Contract):
    endpoint: str
    text: str
    format: Literal["jsonv2"] = "jsonv2"
    countrycodes: Literal["sg"] = "sg"
    addressdetails: Literal[1] = 1
    limit: Literal[5] = 5
    language: Literal["en"] = "en"


class QueryCache(Contract):
    schema_version: Literal[1] = 1
    key: str
    query: Query
    retrieved_at: AwareDatetime
    status: Literal["success", "error", "pending"]
    response: list[dict[str, JsonValue]] = Field(default_factory=list)
    error: str | None = None


class Coordinates(Contract):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class Place(Coordinates):
    candidate_id: str
    query_key: str
    response_fingerprint: str
    name: str
    address: str
    category: str
    kind: str
    precision: Literal["building", "outlet"]
    osm_type: str | None = None
    osm_id: str | None = None


class Decision(Contract):
    decision_id: str = Field(min_length=1)
    row_ids: list[str] = Field(min_length=1)
    location_fingerprints: dict[str, str]
    action: Literal["alias", "approve", "manual", "reject"]
    reviewed_at: AwareDatetime
    reviewer: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    source: str = Field(min_length=1)
    alias: str | None = None
    candidate_id: str | None = None
    response_fingerprint: str | None = None
    coordinates: Coordinates | None = None
    precision: Literal["building", "outlet"] | None = None
    resolved_label: str | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if len(set(self.row_ids)) != len(self.row_ids):
            raise ValueError("duplicate decision row IDs")
        if set(self.location_fingerprints) != set(self.row_ids):
            raise ValueError("decision must fingerprint every affected row")
        if self.action == "alias" and not self.alias:
            raise ValueError("alias decision requires an alias")
        if self.action == "approve" and not (
            self.candidate_id and self.response_fingerprint
        ):
            raise ValueError("approval requires candidate and response fingerprints")
        if self.action == "manual" and not (
            self.coordinates and self.precision and self.resolved_label
        ):
            raise ValueError("manual approval requires coordinates, precision, label")
        return self


class Decisions(Contract):
    schema_version: Literal[1] = 1
    decisions: list[Decision] = Field(default_factory=list)


class Resolution(Contract):
    row_id: str
    location_fingerprint: str
    queries: list[str]
    query_texts: dict[str, str] = Field(default_factory=dict)
    cache_fingerprints: dict[str, str]
    outcome: Literal["matched", "ambiguous", "not_found", "error", "not_attempted"]
    reason: str
    candidates: list[Place] = Field(default_factory=list)
    proposed_candidate_id: str | None = None
    review: Literal["pending", "approved", "rejected"] = "pending"
    decision_id: str | None = None
    coordinates: Coordinates | None = None
    precision: Literal["building", "outlet"] | None = None
    resolved_label: str | None = None


class Resolutions(Envelope):
    source_dataset_id: str
    demo_dataset_id: str
    selection_fingerprint: str
    settings_fingerprint: str
    decisions_fingerprint: str
    matching_version: Literal["geocoding-v1"] = "geocoding-v1"
    rows: list[Resolution]


class GeocodingReport(Envelope):
    status: Literal["success", "partial", "failed", "dry_run"]
    source_dataset_id: str
    demo_dataset_id: str
    selection_fingerprint: str
    resolution_fingerprint: str | None = None
    counts: dict[str, int]
    errors: list[str] = Field(default_factory=list)


class ProviderState(Contract):
    last_request_at: float = Field(default=0, ge=0, allow_inf_nan=False)
    not_before: float = Field(default=0, ge=0, allow_inf_nan=False)
    denied: bool = False
