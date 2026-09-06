import json
from decimal import Decimal
from email.message import Message
from urllib.error import HTTPError, URLError

import pytest

from food_deals_mvp.llm_budget import MODEL, BudgetStop
from food_deals_mvp.openrouter import (
    OpenRouter,
    ProviderError,
    Settings,
    request_json,
    response_cost,
)
from tests.llm_support import post, response


@pytest.fixture
def endpoint():
    return {
        "tag": "meta",
        "context_length": 100_000,
        "max_completion_tokens": 10_000,
        "supported_parameters": [
            "structured_outputs",
            "response_format",
            "max_tokens",
            "temperature",
        ],
        "pricing": {"prompt": "0.0000001", "completion": "0.0000002"},
    }


def test_preflight_and_request_pin_schema_model_and_price(monkeypatch, endpoint):
    calls = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-secret")

    def fake(path, timeout, key=None, payload=None):
        calls.append((path, key, payload))
        if path == "/key":
            return {"data": {"is_free_tier": False}}
        if path.endswith("/endpoints"):
            return {"data": {"endpoints": [endpoint]}}
        return response()

    monkeypatch.setattr("food_deals_mvp.openrouter.request_json", fake)
    client = OpenRouter(Settings())
    assert client.preflight() == Decimal("0.0112")
    client.complete(post())
    payload = calls[-1][2]
    assert payload["model"] == MODEL
    assert payload["provider"] == {
        "only": ["meta"],
        "allow_fallbacks": False,
        "require_parameters": True,
        "max_price": {"prompt": 0.1, "completion": 0.2, "request": 0.0},
    }
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["plugins"] == [] and not payload.get("tools")
    assert "synthetic-secret" not in json.dumps(payload)
    assert calls[1][1] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("supported_parameters", []),
        ("context_length", None),
        ("pricing", {"prompt": "NaN", "completion": "0.1"}),
        ("pricing", {"prompt": "0.1", "completion": "0.1", "surprise_fee": "1"}),
    ],
)
def test_incompatible_or_unbounded_endpoint_stops_before_post(
    monkeypatch, endpoint, field, value
):
    endpoint[field] = value
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-secret")

    def fake(path, *args):
        assert path != "/chat/completions"
        return (
            {"data": {"is_free_tier": False}}
            if path == "/key"
            else {"data": {"endpoints": [endpoint]}}
        )

    monkeypatch.setattr("food_deals_mvp.openrouter.request_json", fake)
    with pytest.raises((ProviderError, BudgetStop)):
        OpenRouter(Settings()).preflight()


@pytest.mark.parametrize(
    "code,transient", [(401, False), (400, False), (429, True), (503, True)]
)
def test_http_failure_classification_and_retry_after(monkeypatch, code, transient):
    headers = Message()
    headers["Retry-After"] = "7"

    class Opener:
        def open(self, *args, **kwargs):
            raise HTTPError(
                "https://openrouter.ai", code, "secret provider detail", headers, None
            )

    monkeypatch.setattr(
        "food_deals_mvp.openrouter.build_opener", lambda *args: Opener()
    )
    with pytest.raises(ProviderError) as failure:
        request_json("/chat/completions", 1, "synthetic-secret", {})
    assert failure.value.transient is transient
    assert failure.value.retry_after == 7
    assert "secret" not in str(failure.value)


@pytest.mark.parametrize("error", [URLError("secret"), TimeoutError("secret")])
def test_transport_failure_hides_credentials(monkeypatch, error):
    class Opener:
        def open(self, *args, **kwargs):
            raise error

    monkeypatch.setattr(
        "food_deals_mvp.openrouter.build_opener", lambda *args: Opener()
    )
    with pytest.raises(ProviderError, match="transport failure") as failure:
        request_json("/chat/completions", 1, "synthetic-secret", {})
    assert failure.value.transient and "secret" not in str(failure.value)


@pytest.mark.parametrize("cost", [None, "NaN", "Infinity", -1])
def test_missing_cost_is_unknown_invalid_cost_stops(cost):
    if cost is None:
        assert response_cost({}) is None
    else:
        with pytest.raises(BudgetStop):
            response_cost({"usage": {"cost": cost}})
