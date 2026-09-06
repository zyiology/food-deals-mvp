"""Durable model-wide spending journal; every dispatch needs a saved reservation."""

import fcntl
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from .models import Contract
from .storage import atomic_write, read_json

MODEL = "meta/muse-spark-1.3-contributor"
CAP = Decimal(5)
# Deliberately independent of cwd, --data-dir, prompts and cache refreshes.
STATE_DIR = Path.home() / ".config/food-deals-mvp/llm" / MODEL.replace("/", "--")
Money = Decimal


class BudgetStop(ValueError):
    pass


class Attempt(Contract):
    attempt_id: str
    cache_key: str
    post_id: str
    reserved: Money = Field(ge=0, allow_inf_nan=False)
    created_at: AwareDatetime
    actual: Money | None = Field(default=None, ge=0, allow_inf_nan=False)
    status: Literal["reserved", "unknown", "settled"] = "reserved"
    pricing_evidence: JsonValue = None

    @model_validator(mode="after")
    def consistent(self):
        if (self.status == "settled") != (self.actual is not None):
            raise ValueError("inconsistent attempt settlement")
        return self


class Ledger(Contract):
    schema_version: Literal[1] = 1
    model: Literal["meta/muse-spark-1.3-contributor"] = MODEL
    cap: Literal["5"] = "5"
    attempts: list[Attempt] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique(self):
        if len({a.attempt_id for a in self.attempts}) != len(self.attempts):
            raise ValueError("duplicate ledger attempt")
        return self


class Receipt(Contract):
    attempt_id: str
    cache_key: str
    raw: JsonValue
    cost: Money | None = Field(ge=0, allow_inf_nan=False)
    error: str | None


def utc_now() -> datetime:
    return datetime.now(UTC)


@contextmanager
def writer_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "writer.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BudgetStop("another extraction writer is running") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class Budget:
    def __init__(self, directory: Path = STATE_DIR):
        self.directory = directory
        self.path = directory / "ledger.json"
        if not self.path.exists() and any(
            (directory / name).exists() for name in ("receipts", "cache")
        ):
            raise BudgetStop(
                "ledger missing but receipts exist; restore accounting before paid work"
            )
        self.ledger = (
            Ledger.model_validate(read_json(self.path))
            if self.path.exists()
            else Ledger()
        )

    def save(self) -> None:
        atomic_write(self.path, self.ledger)

    def summary(self) -> dict[str, str | int]:
        actual = sum((a.actual or Decimal(0) for a in self.ledger.attempts), Decimal(0))
        reserved = sum(
            (a.reserved for a in self.ledger.attempts if a.actual is None), Decimal(0)
        )
        return {
            "cap_usd": str(CAP),
            "charged_usd": str(actual),
            "reserved_usd": str(reserved),
            "remaining_usd": str(CAP - actual - reserved),
            "attempts": len(self.ledger.attempts),
            "unknown_attempts": sum(a.actual is None for a in self.ledger.attempts),
        }

    def reserve(
        self,
        post_id: str,
        cache_key: str,
        maximum: Decimal,
        max_total_attempts: int,
        pricing_evidence: JsonValue = None,
    ) -> Attempt:
        if any(
            a.actual is not None and a.actual > a.reserved for a in self.ledger.attempts
        ):
            raise BudgetStop(
                "reported cost exceeded reservation; reconcile before continuing"
            )
        if len(self.ledger.attempts) >= max_total_attempts:
            raise BudgetStop("cumulative attempt limit reached")
        if not maximum.is_finite() or maximum < 0:
            raise BudgetStop("request maximum cost is unbounded")
        if maximum > Decimal(str(self.summary()["remaining_usd"])):
            raise BudgetStop(
                "remaining budget cannot cover the next maximum-cost reservation"
            )
        attempt = Attempt(
            attempt_id=uuid4().hex,
            cache_key=cache_key,
            post_id=post_id,
            reserved=maximum,
            created_at=utc_now(),
            pricing_evidence=pricing_evidence,
        )
        self.ledger.attempts.append(attempt)
        self.save()  # MUST succeed before dispatch, including retries and repair.
        return attempt

    def record(
        self, attempt: Attempt, raw: JsonValue, cost: Decimal | None, error: str | None
    ) -> None:
        receipt = Receipt(
            attempt_id=attempt.attempt_id,
            cache_key=attempt.cache_key,
            raw=raw,
            cost=cost,
            error=error,
        )
        atomic_write(
            self.directory / "receipts" / f"{attempt.attempt_id}.json", receipt
        )
        self.settle(attempt, receipt)
        self.save()
        if cost is not None and cost > attempt.reserved:
            raise BudgetStop("reported cost exceeded reservation; paid work stopped")

    def settle(self, attempt: Attempt, receipt: Receipt) -> None:
        if (receipt.attempt_id, receipt.cache_key) != (
            attempt.attempt_id,
            attempt.cache_key,
        ):
            raise BudgetStop("receipt identity differs from reservation")
        attempt.actual = receipt.cost
        attempt.status = "settled" if receipt.cost is not None else "unknown"

    def recover(self) -> list[Receipt]:
        receipts: list[Receipt] = []
        for attempt in self.ledger.attempts:
            path = self.directory / "receipts" / f"{attempt.attempt_id}.json"
            if path.exists():
                receipt = Receipt.model_validate(read_json(path))
                if attempt.actual is not None and attempt.actual != receipt.cost:
                    raise BudgetStop("settled charge conflicts with saved receipt")
                self.settle(attempt, receipt)
                receipts.append(receipt)
            elif attempt.actual is None:
                attempt.status = "unknown"  # Missing result never proves no charge.
            else:
                raise BudgetStop("settled attempt is missing its receipt")
        self.save()
        return receipts
