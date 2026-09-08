"""OneMap search, reverse geocoding, and renewable authentication."""

import json
from dataclasses import dataclass
from typing import Any, ClassVar

import pytest

from food_deals_mvp import location_search
from food_deals_mvp.location_search import (
    DeviceLocation,
    LocationSearchError,
    reverse_location,
    search_locations,
)


@pytest.fixture(autouse=True)
def reset_token_cache(monkeypatch):
    monkeypatch.setattr(location_search, "_cached_token", None)
    monkeypatch.setattr(location_search, "_cached_expiry", 0.0)
    monkeypatch.delenv("ONEMAP_TOKEN", raising=False)
    monkeypatch.delenv("ONEMAP_EMAIL", raising=False)
    monkeypatch.delenv("ONEMAP_PASSWORD", raising=False)


@dataclass
class FakeResponse:
    status: int
    payload: object

    def read(self, limit: int) -> bytes:
        return json.dumps(self.payload).encode()


class FakeConnection:
    queued: ClassVar[list[FakeResponse]] = []
    requests: ClassVar[list[tuple[str, str, Any, dict[str, str]]]] = []

    def __init__(self, host: str, timeout: int):
        assert host == "www.onemap.gov.sg"
        assert timeout == 5

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, headers or {}))

    def getresponse(self):
        return self.queued.pop(0)

    def close(self):
        pass


def install_connection(monkeypatch, *responses):
    FakeConnection.queued = list(responses)
    FakeConnection.requests = []
    monkeypatch.setattr(location_search.http.client, "HTTPSConnection", FakeConnection)


def test_credentials_create_and_cache_token(monkeypatch):
    monkeypatch.setenv("ONEMAP_EMAIL", "developer@example.com")
    monkeypatch.setenv("ONEMAP_PASSWORD", "secret")
    install_connection(
        monkeypatch,
        FakeResponse(
            200,
            {"access_token": "renewable-token", "expiry_timestamp": "4102444800"},
        ),
    )

    assert location_search._access_token() == "renewable-token"
    assert location_search._access_token() == "renewable-token"
    assert len(FakeConnection.requests) == 1
    method, path, body, headers = FakeConnection.requests[0]
    assert (method, path) == ("POST", "/api/auth/post/getToken")
    assert json.loads(body) == {
        "email": "developer@example.com",
        "password": "secret",
    }
    assert headers["Content-Type"] == "application/json"


def test_expired_provider_token_is_renewed_and_request_retried(monkeypatch):
    tokens = iter(["expired-token", "renewed-token"])
    calls = []

    def token(*, refresh=False):
        calls.append(refresh)
        return next(tokens)

    responses = iter([(401, {}), (200, {"results": []})])
    monkeypatch.setattr(location_search, "_access_token", token)
    monkeypatch.setattr(
        location_search,
        "_provider_request",
        lambda path, parameters, access_token: next(responses),
    )

    assert search_locations("307987").results == []
    assert calls == [False, True]


def test_missing_configuration_has_actionable_error():
    with pytest.raises(LocationSearchError, match="ONEMAP_EMAIL") as error:
        location_search._access_token()
    assert error.value.status_code == 503


def test_search_maps_onemap_fields(monkeypatch):
    monkeypatch.setenv("ONEMAP_TOKEN", "temporary-token")
    install_connection(
        monkeypatch,
        FakeResponse(
            200,
            {
                "results": [
                    {
                        "BUILDING": "REVENUE HOUSE",
                        "ADDRESS": "55 NEWTON ROAD SINGAPORE 307987",
                        "POSTAL": "307987",
                        "LATITUDE": "1.3195",
                        "LONGITUDE": "103.8421",
                    }
                ]
            },
        ),
    )

    result = search_locations("307987").results[0]
    assert result.label == "REVENUE HOUSE"
    assert result.postal_code == "307987"
    assert result.latitude == 1.3195
    assert "searchVal=307987" in FakeConnection.requests[0][1]
    assert FakeConnection.requests[0][3]["Authorization"] == "temporary-token"


def test_reverse_location_returns_closest_address(monkeypatch):
    monkeypatch.setenv("ONEMAP_TOKEN", "temporary-token")
    install_connection(
        monkeypatch,
        FakeResponse(
            200,
            {
                "GeocodeInfo": [
                    {
                        "BUILDINGNAME": "FARTHER PLACE",
                        "BLOCK": "2",
                        "ROAD": "OTHER ROAD",
                        "POSTALCODE": "100002",
                        "LATITUDE": "1.31",
                        "LONGITUDE": "103.81",
                    },
                    {
                        "BUILDINGNAME": "NEARBY PLACE",
                        "BLOCK": "1",
                        "ROAD": "CLOSE ROAD",
                        "POSTALCODE": "100001",
                        "LATITUDE": "1.3001",
                        "LONGITUDE": "103.8001",
                    },
                ]
            },
        ),
    )

    result = reverse_location(DeviceLocation(latitude=1.3, longitude=103.8))
    assert result is not None
    assert result.label == "NEARBY PLACE"
    assert result.address == "1 CLOSE ROAD, 100001"
    assert "buffer=500" in FakeConnection.requests[0][1]
