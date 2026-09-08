"""On-demand Singapore address search, separate from publication geocoding."""

import http.client
import json
import os
from math import cos, radians
from threading import Lock
from time import time
from urllib.parse import urlencode

from pydantic import Field, JsonValue

from .models import Contract
from .storage import parse_json


class LocationResult(Contract):
    label: str
    address: str
    postal_code: str | None
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class LocationResults(Contract):
    results: list[LocationResult]


class LocationSearchError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


_token_lock = Lock()
_cached_token: str | None = None
_cached_expiry = 0.0


def _read_response(response: http.client.HTTPResponse) -> dict[str, JsonValue]:
    body = response.read(1_000_001)
    if len(body) > 1_000_000:
        raise ValueError("oversized OneMap response")
    data = parse_json(body)
    if not isinstance(data, dict):
        raise TypeError("OneMap response must be an object")
    return data


def _new_token() -> str:
    email = os.environ.get("ONEMAP_EMAIL", "").strip()
    password = os.environ.get("ONEMAP_PASSWORD", "")
    if not email or not password:
        raise LocationSearchError(
            503,
            "Location search needs ONEMAP_EMAIL and ONEMAP_PASSWORD.",
        )
    connection = http.client.HTTPSConnection("www.onemap.gov.sg", timeout=5)
    try:
        connection.request(
            "POST",
            "/api/auth/post/getToken",
            body=json.dumps({"email": email, "password": password}),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        response = connection.getresponse()
        data = _read_response(response)
        if response.status in {400, 401, 403, 404}:
            raise LocationSearchError(
                503, "OneMap credentials were rejected."
            )
        if response.status == 429:
            raise LocationSearchError(
                429, "OneMap authentication is busy. Try again shortly."
            )
        if response.status != 200:
            raise LocationSearchError(502, "OneMap authentication is unavailable.")
        token = data.get("access_token")
        expiry = data.get("expiry_timestamp")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("OneMap authentication response has no token")
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float, str)):
            raise TypeError("OneMap authentication response has no expiry")
        try:
            expires_at = float(expiry)
        except (TypeError, ValueError) as exc:
            raise ValueError("OneMap authentication response has no expiry") from exc
        if expires_at <= time():
            raise ValueError("OneMap returned an expired token")
        global _cached_token, _cached_expiry
        _cached_token = token.strip()
        _cached_expiry = expires_at
        return _cached_token
    except LocationSearchError:
        raise
    except (OSError, http.client.HTTPException, TypeError, ValueError) as exc:
        raise LocationSearchError(
            502, "OneMap authentication is unavailable."
        ) from exc
    finally:
        connection.close()


def _access_token(*, refresh: bool = False) -> str:
    """Return a configured token or create one from credentials when needed."""
    with _token_lock:
        if not refresh and _cached_token and _cached_expiry > time() + 60:
            return _cached_token
        email = os.environ.get("ONEMAP_EMAIL", "").strip()
        password = os.environ.get("ONEMAP_PASSWORD", "")
        if email and password:
            return _new_token()
        token = os.environ.get("ONEMAP_TOKEN", "").strip()
        if token and not refresh:
            return token
        if token:
            raise LocationSearchError(
                503,
                "The OneMap token expired; configure ONEMAP_EMAIL and ONEMAP_PASSWORD for automatic renewal.",
            )
        raise LocationSearchError(
            503,
            "Location search needs ONEMAP_EMAIL and ONEMAP_PASSWORD.",
        )


def _provider_request(
    path: str, parameters: dict[str, str], token: str
) -> tuple[int, dict[str, JsonValue]]:
    connection = http.client.HTTPSConnection("www.onemap.gov.sg", timeout=5)
    try:
        connection.request(
            "GET",
            f"{path}?{urlencode(parameters)}",
            headers={"Authorization": token, "Accept": "application/json"},
        )
        response = connection.getresponse()
        return response.status, _read_response(response)
    finally:
        connection.close()


def _request(path: str, parameters: dict[str, str]) -> dict[str, JsonValue]:
    try:
        status, data = _provider_request(path, parameters, _access_token())
        if status == 401:
            # OneMap tokens last three days. Credentials let the server renew once
            # and repeat the original read-only lookup without user involvement.
            status, data = _provider_request(
                path, parameters, _access_token(refresh=True)
            )
        if status in {401, 403}:
            raise LocationSearchError(503, "OneMap authentication failed.")
        if status == 429:
            raise LocationSearchError(
                429, "Location search is busy. Try again shortly."
            )
        if status != 200:
            raise LocationSearchError(502, "Location search is unavailable. Try again.")
        if data.get("error"):
            raise ValueError("invalid search response")
        return data
    except LocationSearchError:
        raise
    except (OSError, http.client.HTTPException, TypeError, ValueError) as exc:
        raise LocationSearchError(
            502, "Location search is unavailable. Try again."
        ) from exc


def search_locations(query: str) -> LocationResults:
    data = _request(
        "/api/common/elastic/search",
        {"searchVal": query, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": "1"},
    )
    try:
        rows = data.get("results")
        if not isinstance(rows, list):
            raise TypeError("missing search results")
        results = []
        for row in rows[:10]:
            if not isinstance(row, dict):
                raise TypeError("invalid search result")
            address = row.get("ADDRESS")
            building = row.get("BUILDING")
            if not isinstance(address, str) or not address.strip():
                raise ValueError("missing address")
            label = (
                building
                if isinstance(building, str) and building.strip() not in {"", "NIL"}
                else address
            )
            postal = row.get("POSTAL")
            results.append(
                LocationResult(
                    label=label,
                    address=address,
                    postal_code=postal
                    if isinstance(postal, str) and postal != "NIL"
                    else None,
                    latitude=row.get("LATITUDE"),
                    longitude=row.get("LONGITUDE"),
                )
            )
        return LocationResults(results=results)
    except (TypeError, ValueError) as exc:
        raise LocationSearchError(
            502, "Location search returned invalid results."
        ) from exc


class DeviceLocation(Contract):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


def _address_field(row: dict[str, JsonValue], key: str) -> str:
    text = row.get(key)
    return (
        text.strip()
        if isinstance(text, str) and text.strip().upper() not in {"", "NIL", "NULL"}
        else ""
    )


def reverse_location(location: DeviceLocation) -> LocationResult | None:
    data = _request(
        "/api/public/revgeocode",
        {
            "location": f"{location.latitude},{location.longitude}",
            "buffer": "500",
            "addressType": "All",
        },
    )
    try:
        rows = data.get("GeocodeInfo")
        if not isinstance(rows, list):
            raise TypeError("missing reverse geocoding results")
        results = []
        for row in rows:
            if not isinstance(row, dict):
                raise TypeError("invalid address")

            street = " ".join(
                filter(
                    None, [_address_field(row, "BLOCK"), _address_field(row, "ROAD")]
                )
            )
            postal = _address_field(row, "POSTALCODE")
            address = ", ".join(filter(None, [street, postal]))
            if not address:
                continue
            results.append(
                LocationResult(
                    label=_address_field(row, "BUILDINGNAME") or street,
                    address=address,
                    postal_code=postal or None,
                    latitude=row.get("LATITUDE"),
                    longitude=row.get("LONGITUDE"),
                )
            )
        # Rank by distance to the device, rather than assuming provider result order.
        if not results:
            return None
        return min(
            results,
            key=lambda result: (
                (result.latitude - location.latitude) ** 2
                + (
                    (result.longitude - location.longitude)
                    * cos(radians(location.latitude))
                )
                ** 2
            ),
        )
    except (TypeError, ValueError) as exc:
        raise LocationSearchError(
            502, "Address lookup returned invalid results."
        ) from exc
