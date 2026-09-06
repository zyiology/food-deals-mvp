from datetime import datetime

import pytest

from food_deals_mvp.extraction_models import PostResult
from food_deals_mvp.extraction_validation import expand
from tests.llm_support import extraction, post


def result(value):
    return PostResult(
        post_id="telegram:101:1",
        input_hash="input",
        cache_key="key",
        status="success",
        extraction=value,
    )


@pytest.mark.parametrize(
    "case",
    [
        "invented_quote",
        "invented_address",
        "excluded",
        "online",
        "nonfood",
        "uncertain",
        "missing_date_evidence",
    ],
)
def test_unsupported_or_ineligible_results_never_become_candidates(case):
    value = extraction()
    offer = value.offers[0]
    if case == "invented_quote":
        offer.evidence = ["Free drinks for everyone"]
    elif case == "invented_address":
        offer.locations[0].address = "123 Imaginary Road"
    elif case == "excluded":
        offer.excluded_outlets = ["Example Mall"]
    elif case == "online":
        offer.location_scope = "online_only"
    elif case == "nonfood":
        value.relevance = "non_food"
    elif case == "uncertain":
        value.relevance = "uncertain"
    else:
        offer.availability.evidence = []
    outcome = result(value)
    rows = expand(post(), outcome)
    assert outcome.status == "needs_review"
    assert all(row.status == "needs_review" for row in rows)


def test_offer_and_location_order_do_not_change_ids():
    value = extraction()
    second = value.offers[0].model_copy(deep=True)
    second.title = "Different benefit"
    value.offers.append(second)
    location = value.offers[0].locations[0].model_copy(deep=True)
    location.label = "#01-02"
    value.offers[0].locations.append(location)
    original = expand(post(), result(value))
    value.offers.reverse()
    for offer in value.offers:
        offer.locations.reverse()
        offer.availability.evidence.reverse()
        if offer.availability.weekdays:
            offer.availability.weekdays.reverse()
    reordered = expand(post(), result(value))
    assert {row.row_id for row in original} == {row.row_id for row in reordered}


def test_duplicate_location_marks_both_schedules_for_review():
    value = extraction()
    value.offers[0].locations.append(value.offers[0].locations[0].model_copy(deep=True))
    outcome = result(value)
    rows = expand(post(), outcome)
    assert outcome.status == "needs_review"
    assert all(row.status == "needs_review" for row in rows)


def test_mixed_label_alone_does_not_require_review():
    value = extraction(promotion_kind="mixed_promotion")
    outcome = result(value)
    assert expand(post(), outcome)[0].status == "candidate"
    assert outcome.status == "success"


def test_unmapped_offer_retained_without_location_expansion():
    value = extraction()
    value.offers[0].locations = []
    value.offers[0].location_scope = "all_outlets"
    outcome = result(value)
    rows = expand(post(), outcome)
    assert len(rows) == 1 and rows[0].status == "unmapped"
    assert rows[0].location is None and rows[0].location_id is None
    assert outcome.status == "success"


def test_cross_date_edit_with_relative_wording_goes_to_review():
    source = post("Tea for $2 at Example Mall, #01-02. Today only. While stocks last.")
    source.edited_at = datetime.fromisoformat("2026-08-02T08:00:00+08:00")
    value = extraction()
    value.offers[0].availability.evidence = ["Today only."]
    outcome = result(value)
    rows = expand(source, outcome)
    assert rows[0].availability.date_status == "needs_review"
    assert outcome.status == "needs_review"
