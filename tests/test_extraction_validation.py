from datetime import datetime

import pytest

from food_deals_mvp.extraction_models import PostResult
from food_deals_mvp.extraction_validation import expand, supported_excerpt
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


@pytest.mark.parametrize(
    "quote", ["🔹 Tea for $2", "\x01f539 Tea for $2", "Tea for $2"]
)
def test_decorative_evidence_is_accepted(quote):
    assert supported_excerpt(quote, "🔹 Tea for $2 at Example Mall")


@pytest.mark.parametrize(
    "quote", ["Tea for $3", "Not Tea for $2", "2-31 Aug", "🎉", "", "茶免费"]
)
def test_normalization_does_not_erase_facts_or_accept_empty_evidence(quote):
    assert not supported_excerpt(quote, "🎉 Tea for $2. 1-31 Aug. 茶优惠")


@pytest.mark.parametrize(
    "quote", ["\x01F964 Tea for $2", "\x07\x0f Tea for $2", "\x01e Tea for $2"]
)
def test_observed_encoding_noise_is_cosmetic(quote):
    assert supported_excerpt(quote, "🥤 Tea for $2")


@pytest.mark.parametrize("quote", ["\x020% OFF", "\x01, 2 Aug", "🚫 Tea", "🔞 Tea"])
def test_corrupted_facts_and_semantic_symbols_are_not_erased(quote):
    assert not supported_excerpt(quote, "20% OFF Tea. 1, 2 Aug")


def test_decorative_quote_cannot_be_the_only_evidence():
    from food_deals_mvp.extraction_validation import check_evidence

    assert check_evidence({"evidence": ["🎉"]}, "🎉 Tea for $2")
    assert not check_evidence({"evidence": ["🎉", "Tea for $2"]}, "🎉 Tea for $2")


def test_bad_offer_does_not_block_valid_sibling_and_notes_are_advisory():
    value = extraction(
        promotion_kind="uncertain", review_reasons=["Venue may need checking"]
    )
    bad = value.offers[0].model_copy(deep=True)
    bad.title = "Unsupported benefit"
    bad.evidence = ["Free tea for everyone"]
    value.offers.append(bad)
    rows = expand(post(), result(value))
    good = next(row for row in rows if row.title == "$2 tea")
    assert good.status == "candidate" and good.warnings
    assert next(row for row in rows if row.title == bad.title).status == "needs_review"


def test_bad_location_evidence_does_not_block_valid_sibling():
    value = extraction()
    bad = value.offers[0].locations[0].model_copy(deep=True)
    bad.label = "Imaginary Mall"
    bad.evidence = ["Imaginary Mall"]
    value.offers[0].locations.append(bad)
    rows = expand(post(), result(value))
    assert sorted(row.status for row in rows) == ["candidate", "needs_review"]


def test_equivalent_groupings_have_same_effective_location_dates():
    from food_deals_mvp.extraction_models import AvailabilityOverride

    value = extraction()
    first = value.offers[0].locations[0]
    second = first.model_copy(deep=True)
    second.label = "#01-02"
    second.availability_override = AvailabilityOverride.model_validate(
        {
            **value.offers[0].availability.model_dump(mode="json"),
            "start_date": "2026-08-03",
            "evidence": ["3-31 Aug"],
            "clear_fields": [],
            "remove_restrictions": [],
            "exception_evidence": [],
        }
    )
    value.offers[0].locations.append(second)
    source = post(post().text + " 3-31 Aug")
    grouped = expand(source, result(value))
    separate = value.model_copy(deep=True)
    separate.offers[0].locations = [first]
    other = value.offers[0].model_copy(deep=True)
    other.availability.start_date = second.availability_override.start_date
    other.availability.evidence = ["3-31 Aug", "Weekdays only."]
    other.locations = [second.model_copy(update={"availability_override": None})]
    separate.offers.append(other)
    split = expand(source, result(separate))

    def effective(rows):
        return sorted(
            (
                r.location.label,
                r.availability.start_date,
                r.availability.end_date,
                r.availability.weekdays,
            )
            for r in rows
        )

    assert all(r.status == "candidate" for r in grouped + split)
    assert effective(grouped) == effective(split)
