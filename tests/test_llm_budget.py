from decimal import Decimal

import pytest

from food_deals_mvp.llm_budget import Budget, BudgetStop, Receipt, writer_lock
from food_deals_mvp.storage import atomic_write


def test_reservations_survive_before_or_after_dispatch(tmp_path):
    budget = Budget(tmp_path)
    attempt = budget.reserve("post", "key", Decimal(2), 10)
    recovered = Budget(tmp_path)
    recovered.recover()
    assert recovered.ledger.attempts[0].attempt_id == attempt.attempt_id
    assert recovered.summary()["reserved_usd"] == "2"
    with pytest.raises(BudgetStop, match="remaining budget"):
        recovered.reserve("post2", "key2", Decimal(4), 10)


def test_saved_response_recovers_without_double_charge(tmp_path):
    budget = Budget(tmp_path)
    attempt = budget.reserve("post", "key", Decimal(2), 10)
    atomic_write(
        tmp_path / "receipts" / f"{attempt.attempt_id}.json",
        Receipt(
            attempt_id=attempt.attempt_id,
            cache_key="key",
            raw={},
            cost=Decimal("0.25"),
            error=None,
        ),
    )
    for _ in range(2):
        recovered = Budget(tmp_path)
        recovered.recover()
        assert recovered.summary()["charged_usd"] == "0.25"
        assert recovered.summary()["remaining_usd"] == "4.75"
        assert recovered.summary()["reserved_usd"] == "0"


def test_unknown_cost_keeps_entire_reservation(tmp_path):
    budget = Budget(tmp_path)
    attempt = budget.reserve("post", "key", Decimal(2), 10)
    budget.record(attempt, {}, None, "timeout")
    recovered = Budget(tmp_path)
    recovered.recover()
    assert recovered.summary()["unknown_attempts"] == 1
    assert recovered.summary()["remaining_usd"] == "3"


def test_over_reservation_charge_stops_future_work(tmp_path):
    budget = Budget(tmp_path)
    attempt = budget.reserve("post", "key", Decimal(1), 10)
    with pytest.raises(BudgetStop, match="exceeded reservation"):
        budget.record(attempt, {}, Decimal(2), None)
    recovered = Budget(tmp_path)
    recovered.recover()
    with pytest.raises(BudgetStop, match="exceeded reservation"):
        recovered.reserve("next", "key2", Decimal(1), 10)
    assert recovered.summary()["charged_usd"] == "2"


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1"])
def test_unbounded_reservation_rejected(tmp_path, amount):
    with pytest.raises(BudgetStop, match="unbounded"):
        Budget(tmp_path).reserve("post", "key", Decimal(amount), 10)
    assert not (tmp_path / "ledger.json").exists()


def test_global_attempt_limit(tmp_path):
    budget = Budget(tmp_path)
    attempt = budget.reserve("post", "key", Decimal(1), 1)
    budget.record(attempt, {}, Decimal(0), None)
    with pytest.raises(BudgetStop, match="attempt limit"):
        Budget(tmp_path).reserve("post", "changed-prompt", Decimal(1), 1)


def test_writer_exclusion_and_release(tmp_path):
    with (
        writer_lock(tmp_path),
        pytest.raises(BudgetStop, match="another extraction writer"),
        writer_lock(tmp_path),
    ):
        pytest.fail("second writer entered")
    with writer_lock(tmp_path):
        pass


def test_missing_ledger_with_receipts_does_not_reset_cap(tmp_path):
    (tmp_path / "receipts").mkdir()
    with pytest.raises(BudgetStop, match="ledger missing"):
        Budget(tmp_path)
