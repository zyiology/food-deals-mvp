"""One deterministic Singapore date evaluator and field-level schedule merger."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .extraction_models import Availability, AvailabilityOverride

DATE_FIELDS = ("start_date", "end_date", "valid_dates", "weekdays")


def singapore_date(value: datetime | None = None) -> date:
    if value is not None and value.tzinfo is None:
        raise ValueError("posting timestamp must be timezone aware")
    return (
        (value or datetime.now(ZoneInfo("Asia/Singapore")))
        .astimezone(ZoneInfo("Asia/Singapore"))
        .date()
    )


def schedule_issues(value: Availability) -> list[str]:
    issues: list[str] = []
    if value.start_date and value.end_date and value.start_date > value.end_date:
        issues.append("start_date is after end_date")
    if value.valid_dates:
        if len(set(value.valid_dates)) != len(value.valid_dates):
            issues.append("duplicate valid_dates")
        if any(
            (value.start_date and day < value.start_date)
            or (value.end_date and day > value.end_date)
            or (value.weekdays and day.isoweekday() not in value.weekdays)
            for day in value.valid_dates
        ):
            issues.append("explicit dates contradict range or weekdays")
    if value.weekdays:
        if len(set(value.weekdays)) != len(value.weekdays):
            issues.append("duplicate weekdays")
        if value.start_date and value.end_date:
            length = (value.end_date - value.start_date).days
            if 0 <= length < 7 and not any(
                (value.start_date + timedelta(days=offset)).isoweekday()
                in value.weekdays
                for offset in range(length + 1)
            ):
                issues.append("range contains no allowed weekday")
    if (
        any(getattr(value, field) is not None for field in DATE_FIELDS)
        and not value.evidence
    ):
        issues.append("asserted dates require evidence")
    return issues


def effective_availability(
    shared: Availability, local: AvailabilityOverride | None = None
) -> tuple[Availability, list[str]]:
    merged = shared.model_dump()
    issues: list[str] = []
    if local is not None:
        for field in DATE_FIELDS:
            if field in local.clear_fields:
                merged[field] = None
            elif getattr(local, field) is not None:
                merged[field] = getattr(local, field)
        if any(
            text not in shared.restrictions_text for text in local.remove_restrictions
        ):
            issues.append("local exception removes an unknown restriction")
        merged["restrictions_text"] = list(
            dict.fromkeys(
                [
                    *[
                        text
                        for text in shared.restrictions_text
                        if text not in local.remove_restrictions
                    ],
                    *local.restrictions_text,
                ]
            )
        )
        merged["evidence"] = list(
            dict.fromkeys(
                [
                    *shared.evidence,
                    *local.evidence,
                    *local.exception_evidence,
                ]
            )
        )
        merged["interpretation"] = (
            "\n".join(filter(None, [shared.interpretation, local.interpretation]))
            or None
        )
        if local.date_status == "needs_review":
            merged["date_status"] = "needs_review"
    value = Availability.model_validate(merged)
    issues.extend(schedule_issues(value))
    if value.date_status == "needs_review" or issues:
        value.date_status = "needs_review"
    else:
        value.date_status = (
            "parsed"
            if any(getattr(value, f) is not None for f in DATE_FIELDS)
            else "unspecified"
        )
    return value, issues


def valid_on(
    value: Availability, posted_at: datetime, reference_date: date
) -> bool | None:
    """None means unknown validity; callers include only an explicit True."""
    if singapore_date(posted_at) > reference_date:
        return False
    if value.date_status == "needs_review" or schedule_issues(value):
        return None
    return bool(
        (value.start_date is None or value.start_date <= reference_date)
        and (value.end_date is None or reference_date <= value.end_date)
        and (value.valid_dates is None or reference_date in value.valid_dates)
        and (value.weekdays is None or reference_date.isoweekday() in value.weekdays)
    )
