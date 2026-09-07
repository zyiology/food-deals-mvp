"""Bounded, single-machine Nominatim transport and durable query cache."""

import fcntl
import http.client
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from .geocoding_models import (
    GeocodingSettings,
    ProviderState,
    Query,
    QueryCache,
)
from .storage import atomic_write, fingerprint, parse_json, read_json


def utc_now() -> datetime:
    return datetime.now(UTC)


def state_root() -> Path:
    return Path.home() / ".config/food-deals-mvp/geocoding"


@contextmanager
def writer_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "writer.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("another geocoding/publication writer is running") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def query_key(query: Query) -> str:
    return fingerprint(query.model_dump(mode="json"))


def load_cache(path: Path, query: Query) -> QueryCache | None:
    if not path.exists():
        return None
    entry = QueryCache.model_validate(read_json(path))
    if entry.query != query or entry.key != query_key(query):
        raise ValueError("geocoding cache identity mismatch")
    return entry


def retry_after(value: str | None, now: float) -> float:
    if value is None:
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - now)
        except ValueError, TypeError, OverflowError:
            return 0


class Nominatim:
    """Call only while holding the application-wide writer lock."""

    def __init__(self, settings: GeocodingSettings, data_dir: Path, root: Path):
        self.settings = settings
        self.local = data_dir / "cache/geocoding"
        self.shared = root / "cache"
        self.state_path = root / (fingerprint(settings.endpoint) + ".json")
        self.state = (
            ProviderState.model_validate(read_json(self.state_path))
            if self.state_path.exists()
            else ProviderState()
        )
        self.attempts = 0
        self.hits = 0
        self.stopped = False
        self.completed: dict[str, QueryCache] = {}

    def cached(self, query: Query) -> QueryCache | None:
        key = query_key(query)
        # Shared checkpoints win over an older local mirror after a refresh/crash.
        return load_cache(self.shared / f"{key}.json", query) or load_cache(
            self.local / f"{key}.json", query
        )

    def save(self, entry: QueryCache) -> None:
        atomic_write(self.shared / f"{entry.key}.json", entry)
        atomic_write(self.local / f"{entry.key}.json", entry)
        self.completed[entry.key] = entry

    def get(
        self, query: Query, *, offline: bool, resume: bool, refresh: bool
    ) -> QueryCache | None:
        key = query_key(query)
        if key in self.completed and not refresh:
            self.hits += 1
            return self.completed[key]
        entry = self.cached(query)
        if (
            entry
            and not refresh
            and (entry.status == "success" or not resume or offline)
        ):
            self.hits += 1
            atomic_write(self.local / f"{entry.key}.json", entry)
            return entry
        if offline or self.stopped:
            return entry
        if self.state.denied:
            self.stopped = True
            raise ValueError(
                "Nominatim access was denied; resolve provider access before retrying"
            )
        if not self.settings.user_agent.strip():
            raise ValueError(
                "configure an application-identifying geocoding User-Agent"
            )
        entry = QueryCache(
            key=query_key(query), query=query, retrieved_at=utc_now(), status="pending"
        )
        # Invalidate an old successful response before dispatching refresh work.
        self.save(entry)
        for attempt in range(self.settings.retries + 1):
            now = time.time()
            delay = (
                max(
                    self.state.not_before,
                    self.state.last_request_at + self.settings.interval,
                )
                - now
            )
            if delay > 60:
                entry.status = "error"
                entry.error = "provider cooldown exceeds 60 seconds; resume later"
                self.stopped = True
                break
            if delay > 0:
                time.sleep(delay)
            self.state.last_request_at = time.time()
            atomic_write(self.state_path, self.state)
            self.attempts += 1
            try:
                status, headers, body = self.request(query)
                if status == 200:
                    raw = parse_json(body)
                    if not isinstance(raw, list) or any(
                        not isinstance(x, dict) for x in raw
                    ):
                        raise ValueError(
                            "provider response must be an array of objects"
                        )
                    entry = QueryCache.model_validate(
                        {
                            **entry.model_dump(mode="json"),
                            "status": "success",
                            "response": raw,
                            "retrieved_at": utc_now(),
                            "error": None,
                        }
                    )
                    self.save(entry)
                    return entry
                entry.error = f"provider HTTP {status}"
                if status in (401, 403):
                    self.state.denied = True
                    self.stopped = True
                elif status == 429 or 500 <= status <= 599:
                    delay = max(
                        2**attempt, retry_after(headers.get("retry-after"), time.time())
                    )
                    self.state.not_before = max(
                        self.state.not_before, time.time() + delay
                    )
                    self.stopped = delay > 60
                else:
                    self.stopped = True
                atomic_write(self.state_path, self.state)
                if self.stopped:
                    break
            except (OSError, http.client.HTTPException) as exc:
                entry.error = f"transport error: {type(exc).__name__}"
                self.state.not_before = time.time() + 2**attempt
                atomic_write(self.state_path, self.state)
            except ValueError as exc:
                entry.error = f"malformed response: {exc}"
                break
        entry.status = "error"
        entry.retrieved_at = utc_now()
        self.save(entry)
        return entry

    def request(self, query: Query) -> tuple[int, dict[str, str], bytes]:
        url = urlsplit(query.endpoint)
        params = {
            "q": query.text,
            "format": query.format,
            "countrycodes": query.countrycodes,
            "addressdetails": query.addressdetails,
            "limit": query.limit,
            "accept-language": query.language,
        }
        if url.hostname is None:
            raise ValueError("provider endpoint has no hostname")
        connection = http.client.HTTPSConnection(
            url.hostname, port=url.port, timeout=self.settings.connect_timeout
        )
        try:
            connection.connect()
            if connection.sock is None:
                raise OSError("provider connection unavailable")
            connection.sock.settimeout(self.settings.read_timeout)
            connection.request(
                "GET",
                (url.path or "/search") + "?" + urlencode(params),
                headers={
                    "User-Agent": self.settings.user_agent,
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError("provider response exceeds size limit")
            return (
                response.status,
                {k.lower(): v for k, v in response.getheaders()},
                body,
            )
        finally:
            connection.close()
