from datetime import date, datetime

import pytest
from pydantic import ValidationError

from food_deals_mvp.availability import effective_availability, singapore_date, valid_on
from food_deals_mvp.extraction_models import AvailabilityOverride
from tests.llm_support import availability

POSTED = datetime.fromisoformat("2026-08-03T10:00:00+08:00")


@pytest.mark.parametrize(
    ("fields", "day", "expected"),
    [
        ({}, "2026-08-02", False),
        ({}, "2026-08-03", True),
        ({}, "2030-01-01", True),
        ({"start_date": "2026-08-05"}, "2026-08-04", False),
        ({"start_date": "2026-08-05"}, "2026-08-05", True),
        ({"end_date": "2026-08-06"}, "2026-08-06", True),
        ({"end_date": "2026-08-06"}, "2026-08-07", False),
        ({"valid_dates": ["2026-08-05", "2026-08-12"]}, "2026-08-06", False),
        ({"valid_dates": ["2026-08-05", "2026-08-12"]}, "2026-08-12", True),
        ({"weekdays": [1, 2]}, "2026-08-04", True),
        ({"weekdays": [1, 2]}, "2026-08-05", False),
        ({"date_status": "needs_review"}, "2026-08-05", None),
        ({"start_date": "2026-08-10", "end_date": "2026-08-05"}, "2026-08-07", None),
        (
            {"start_date": "2026-08-08", "end_date": "2026-08-09", "weekdays": [1]},
            "2026-08-08",
            None,
        ),
        ({"valid_dates": ["2026-08-09"], "weekdays": [1]}, "2026-08-09", None),
    ],
)
def test_selected_date_constraints(fields, day, expected):
    value = availability(evidence=["synthetic schedule"], **fields)
    assert valid_on(value, POSTED, date.fromisoformat(day)) is expected


def test_timezone_and_time_restrictions_are_not_exact_time_evaluation():
    assert singapore_date(datetime.fromisoformat("2026-08-02T17:00:00+00:00")) == date(
        2026, 8, 3
    )
    with pytest.raises(ValueError, match="timezone aware"):
        singapore_date(datetime(2026, 8, 3))  # noqa: DTZ001 -- exercise naive-input rejection
    value = availability(restrictions_text=["11PM-2AM, excluding public holidays"])
    assert valid_on(value, POSTED, date(2026, 8, 9)) is True


def local(**changes):
    return AvailabilityOverride.model_validate(
        {
            **availability().model_dump(),
            "clear_fields": [],
            "remove_restrictions": [],
            "exception_evidence": [],
            **changes,
        }
    )


def test_local_field_inherits_all_unaffected_constraints():
    shared = availability(
        start_date="2026-08-03",
        end_date="2026-08-31",
        weekdays=[1, 2],
        evidence=["Mon-Tue in August"],
        restrictions_text=["Members only", "Until 8pm"],
    )
    override = local(
        end_date="2026-08-18",
        evidence=["Mall closes promo 18 Aug"],
        restrictions_text=["One each"],
    )
    effective, issues = effective_availability(shared, override)
    assert not issues
    assert (effective.start_date, effective.end_date, effective.weekdays) == (
        date(2026, 8, 3),
        date(2026, 8, 18),
        [1, 2],
    )
    assert effective.restrictions_text == ["Members only", "Until 8pm", "One each"]
    assert effective.evidence == ["Mon-Tue in August", "Mall closes promo 18 Aug"]
    assert effective.date_status == "parsed"


def test_evidence_backed_clearing_and_restriction_exception():
    shared = availability(
        weekdays=[1],
        evidence=["Monday"],
        restrictions_text=["Members only", "One each"],
    )
    override = local(
        clear_fields=["weekdays"],
        remove_restrictions=["Members only"],
        exception_evidence=["This outlet: every day, everyone welcome"],
    )
    effective, issues = effective_availability(shared, override)
    assert not issues
    assert effective.weekdays is None
    assert effective.restrictions_text == ["One each"]
    assert effective.date_status == "unspecified"


@pytest.mark.parametrize(
    "fields",
    [
        {"clear_fields": ["end_date"]},
        {
            "clear_fields": ["weekdays"],
            "weekdays": [1],
            "exception_evidence": ["exception"],
        },
        {"clear_fields": ["weekdays", "weekdays"], "exception_evidence": ["exception"]},
        {"weekdays": []},
        {"weekdays": [0]},
        {"valid_dates": []},
        {"start_date": "2026-02-30"},
    ],
)
def test_invalid_schedule_shapes(fields):
    with pytest.raises(ValidationError):
        local(**fields)


def test_local_range_does_not_clear_shared_dates_or_weekdays():
    shared = availability(
        valid_dates=["2026-08-03"], weekdays=[1], evidence=["3 Aug only"]
    )
    effective, issues = effective_availability(
        shared, local(start_date="2026-08-04", evidence=["From 4 Aug"])
    )
    assert issues
    assert effective.valid_dates == [date(2026, 8, 3)]
    assert effective.weekdays == [1]
    assert effective.date_status == "needs_review"


def test_unknown_and_missing_are_distinct_after_merging():
    effective, _ = effective_availability(
        availability(date_status="needs_review"),
        local(end_date="2026-08-31", evidence=["31 Aug"]),
    )
    assert effective.date_status == "needs_review"
    effective, _ = effective_availability(availability(), None)
    assert effective.date_status == "unspecified"
