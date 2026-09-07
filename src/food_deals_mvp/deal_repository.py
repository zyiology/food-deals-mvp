"""Validated startup snapshot and deterministic, read-only deal queries."""

from datetime import date

from .api_models import (
    Counts,
    DealResponse,
    DealsResponse,
    DisplayAvailability,
    Filters,
    Validity,
    ValidityStatus,
)
from .api_settings import ApiSettings
from .availability import singapore_date, valid_on
from .public_models import PublishedDataset, safe_url
from .storage import file_hash, fingerprint, read_json


class DealRepository:
    """Own one startup snapshot; never expose or mutate its internal models."""

    def __init__(self, settings: ApiSettings):
        snapshot = PublishedDataset.model_validate(
            read_json(settings.published_dir / "deals.json")
        )
        if snapshot.dataset_id != fingerprint(
            snapshot.model_dump(mode="json", exclude={"dataset_id", "generated_at"})
        ):
            raise ValueError("published dataset fingerprint mismatch")
        if (
            snapshot.source_date_range[0] > snapshot.source_date_range[1]
            or not (
                snapshot.source_date_range[0]
                <= snapshot.selected_source_date_range[0]
                <= snapshot.selected_source_date_range[1]
                <= snapshot.source_date_range[1]
            )
            or snapshot.suggested_reference_date
            != snapshot.selected_source_date_range[1]
            or any(value < 0 for value in snapshot.processing_summary.values())
        ):
            raise ValueError("inconsistent published metadata")
        for row in snapshot.deals:
            if not (
                snapshot.selected_source_date_range[0]
                <= singapore_date(row.posted_at)
                <= snapshot.selected_source_date_range[1]
            ):
                raise ValueError("posting date outside selected source range")
            if row.telegram_url is not None and safe_url(row.telegram_url) is None:
                raise ValueError("unsafe source link")
            if any(safe_url(url) is None for url in row.information_links):
                raise ValueError("unsafe information link")
            expected_image = f"/media/{row.media_ids[0]}" if row.media_ids else None
            if row.image_url != expected_image:
                raise ValueError("image URL does not match media allowlist")
        for media in snapshot.media:
            extension = "jpg" if media.mime_type == "image/jpeg" else "png"
            if media.filename != f"{media.content_hash}.{extension}":
                raise ValueError("media filename/hash/type mismatch")
        self._snapshot = snapshot
        self._rows = tuple(
            sorted(
                snapshot.deals,
                key=lambda row: (-row.posted_at.timestamp(), row.deal_id),
            )
        )
        self._media = {media.media_id: media for media in snapshot.media}
        self._media_dir = (settings.published_dir / "media").absolute()
        self._max_age_days = settings.max_age_days

    @property
    def dataset_id(self) -> str:
        return self._snapshot.dataset_id

    def query(self, as_of: date | None, validity: Validity) -> DealsResponse:
        snapshot = self._snapshot
        reference = as_of or snapshot.suggested_reference_date
        deals = []
        for row in self._rows:
            age = (reference - singapore_date(row.posted_at)).days
            if not 0 <= age < self._max_age_days:
                continue
            valid = valid_on(row.availability, row.posted_at, reference)
            if validity == "valid" and valid is not True:
                continue
            status: ValidityStatus = (
                "unknown" if valid is None else "valid" if valid else "outside_period"
            )
            deals.append(
                DealResponse(
                    **row.model_dump(exclude={"availability"}),
                    availability=DisplayAvailability.model_validate(
                        row.availability.model_dump(
                            exclude={"evidence", "interpretation"}
                        )
                    ),
                    validity_status=status,
                )
            )
        return DealsResponse(
            schema_version=snapshot.schema_version,
            dataset_id=snapshot.dataset_id,
            generated_at=snapshot.generated_at,
            timezone=snapshot.timezone,
            source_date_range=snapshot.source_date_range,
            selected_source_date_range=snapshot.selected_source_date_range,
            suggested_reference_date=snapshot.suggested_reference_date,
            suggested_validity=snapshot.suggested_validity,
            dataset_complete=snapshot.dataset_complete,
            processing_summary=snapshot.processing_summary.copy(),
            attribution=[item.model_copy(deep=True) for item in snapshot.attribution],
            filters=Filters(
                as_of=reference, validity=validity, max_age_days=self._max_age_days
            ),
            counts=Counts(
                matched_rows=len(deals),
                mapped_rows=len(deals),
                distinct_locations=len(
                    {(row.latitude, row.longitude) for row in deals}
                ),
                distinct_offers=len({row.offer_id for row in deals}),
                distinct_posts=len({row.post_id for row in deals}),
            ),
            deals=deals,
        )

    def image(self, media_id: str) -> tuple[bytes, str, str] | None:
        media = self._media.get(media_id)
        if media is None:
            return None
        path = self._media_dir / media.filename
        try:
            # Never serve a redirected directory or file. Hash the bytes actually
            # read as well, so a concurrent replacement cannot expose other files.
            if (
                self._media_dir.is_symlink()
                or path.is_symlink()
                or path.resolve().parent != self._media_dir.resolve()
                or not path.is_file()
            ):
                return None
            content = path.read_bytes()
        except OSError, RuntimeError:
            return None
        if file_hash(content) != media.content_hash:
            return None
        signature = (
            b"\xff\xd8\xff" if media.mime_type == "image/jpeg" else b"\x89PNG\r\n\x1a\n"
        )
        if not content.startswith(signature):
            return None
        return content, media.mime_type, media.content_hash
