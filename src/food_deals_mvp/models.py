"""Versioned contracts for the offline normalization stage."""

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(Contract):
    export_root: str = Field(min_length=1)
    channel_id: int = Field(strict=True, gt=0)
    name: str = Field(min_length=1)
    username: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
    export_timezone: str


class Sources(Contract):
    schema_version: Literal[1] = 1
    sources: list[Source] = Field(min_length=1)


class Link(Contract):
    destination: str
    labels: list[str]
    clickable_url: str | None


class Media(Contract):
    media_id: str
    post_id: str
    kind: Literal["photo", "file", "thumbnail"]
    original_reference: str | None
    relative_path: str | None
    status: Literal["available", "omitted", "missing", "absent", "unsafe"]
    content_hash: str | None = None


class SourcePost(Contract):
    post_id: str
    channel_id: int
    message_id: int
    source_name: str
    username: str | None
    telegram_url: str | None
    posted_at: AwareDatetime
    edited_at: AwareDatetime | None
    text: str
    links: list[Link]
    media_ids: list[str]
    source_file: str
    source_content_hash: str
    extraction_input_hash: str
    raw_record: dict[str, JsonValue]


class Issue(Contract):
    code: str
    source: str
    message_id: int | None = None
    detail: str


class Exclusion(Contract):
    post_id: str
    reason: Literal["pin_service", "empty_poll"]
    raw_record: dict[str, JsonValue]


class InputFile(Contract):
    channel_id: int
    source_file: str
    content_hash: str


class Envelope(Contract):
    schema_version: Literal[1] = 1
    dataset_id: str
    generated_at: AwareDatetime
    timezone: Literal["Asia/Singapore"] = "Asia/Singapore"


class Posts(Envelope):
    posts: list[SourcePost]


class MediaManifest(Envelope):
    media: list[Media]


class ImportReport(Envelope):
    status: Literal["success", "failed"]
    config_hash: str
    inputs: list[InputFile]
    counts: dict[str, int]
    exclusions: list[Exclusion]
    errors: list[Issue]
    warnings: list[Issue]
