"""Small synchronous OpenRouter adapter with bounded, pinned provider routing."""

import json
import os
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import Field, JsonValue

from .extraction_models import Extraction
from .extraction_prompt import PROMPT_VERSION, SCHEMA_VERSION, SYSTEM_PROMPT, post_input
from .llm_budget import MODEL, BudgetStop
from .models import Contract, SourcePost
from .storage import fingerprint, parse_json

BASE_URL = "https://openrouter.ai/api/v1"


class Settings(Contract):
    model: str = MODEL
    provider: str = "meta"
    prompt_version: str = PROMPT_VERSION
    schema_version: str = SCHEMA_VERSION
    timeout: float = Field(default=60, gt=0, le=120)
    max_tokens: int = Field(default=6000, ge=512, le=16000)
    temperature: float = Field(default=0, ge=0, le=2)
    max_attempts: int = Field(default=60, ge=1, le=500)
    max_total_attempts: int = Field(default=300, ge=1, le=1000)
    retries: int = Field(default=2, ge=0, le=3)

    def identity(self) -> dict[str, JsonValue]:
        return {
            "model": self.model,
            "provider": self.provider,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "prompt_hash": fingerprint(SYSTEM_PROMPT),
            "schema_hash": fingerprint(Extraction.model_json_schema()),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "require_parameters": True,
            "allow_fallbacks": False,
            "request_policy_version": 1,
        }


class ProviderError(ValueError):
    def __init__(
        self, message: str, *, transient: bool = False, retry_after: float = 0
    ):
        super().__init__(message)
        self.transient = transient
        self.retry_after = retry_after


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward credentials or repeat a paid POST via redirects.


def request_json(
    path: str,
    timeout: float,
    key: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = Request(
        BASE_URL + path,
        headers=headers,
        data=json.dumps(payload).encode() if payload is not None else None,
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            content = response.read(4_000_001)
            if len(content) > 4_000_000:
                raise ProviderError("provider response exceeds size limit")
            return parse_json(content)
    except HTTPError as exc:
        delay = 0.0
        retry_after = exc.headers.get("Retry-After", "0")
        try:
            delay = max(0, float(retry_after))
        except ValueError:
            try:
                delay = max(
                    0,
                    (
                        parsedate_to_datetime(retry_after) - datetime.now(UTC)
                    ).total_seconds(),
                )
            except TypeError, ValueError, OverflowError:
                pass
        raise ProviderError(
            f"OpenRouter HTTP {exc.code}",
            transient=exc.code in {408, 429, 500, 502, 503, 504},
            retry_after=delay,
        ) from None
    except (URLError, TimeoutError, OSError) as exc:
        raise ProviderError(
            "OpenRouter transport failure or timeout", transient=True
        ) from exc
    except ValueError as exc:
        if isinstance(exc, ProviderError):
            raise
        raise ProviderError("OpenRouter returned invalid JSON") from exc


def decimal_price(value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise BudgetStop("endpoint price/cost is missing or invalid") from exc
    if not amount.is_finite() or amount < 0:
        raise BudgetStop("endpoint price/cost is not a finite nonnegative value")
    return amount


class OpenRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.key = os.environ.get("OPENROUTER_API_KEY", "")
        if not self.key:
            raise ProviderError("set OPENROUTER_API_KEY for live extraction")
        if settings.model != MODEL:
            raise ProviderError(
                "model change requires review; only the agreed model is enabled"
            )

    def preflight(self) -> Decimal:
        settings = self.settings
        account = request_json("/key", settings.timeout, self.key)
        if not isinstance(account, dict) or not isinstance(account.get("data"), dict):
            raise ProviderError("invalid OpenRouter key preflight")
        if account["data"].get("is_free_tier") is True:
            raise ProviderError("paid model requires a funded OpenRouter account")
        data = request_json(f"/models/{settings.model}/endpoints", settings.timeout)
        required = {
            "structured_outputs",
            "response_format",
            "max_tokens",
            "temperature",
        }
        endpoints = [
            entry
            for entry in data["data"]["endpoints"]
            if entry.get("tag") == settings.provider
        ]
        if not endpoints or any(
            not required.issubset(entry.get("supported_parameters", []))
            for entry in endpoints
        ):
            raise ProviderError(
                "pinned provider lacks required structured-output parameters"
            )
        maxima: list[Decimal] = []
        prompt_prices: list[Decimal] = []
        completion_prices: list[Decimal] = []
        request_prices: list[Decimal] = []
        for entry in endpoints:
            pricing = entry["pricing"]
            # Context capacity is a conservative input-token bound; do not guess a tokenizer.
            context = entry.get("context_length")
            if type(context) is not int or context <= 0:
                raise BudgetStop("endpoint context/token bound is unavailable")
            if settings.max_tokens > (entry.get("max_completion_tokens") or context):
                raise ProviderError(
                    "configured output limit exceeds endpoint capability"
                )
            prompt = decimal_price(pricing.get("prompt"))
            completion = decimal_price(pricing.get("completion"))
            request_fee = decimal_price(pricing.get("request", "0"))
            # No browsing, images, audio, tools or paid plugins are sent.
            allowed = {
                "prompt",
                "completion",
                "request",
                "input_cache_read",
                "input_cache_write",
                "web_search",
                "image",
                "image_output",
                "audio",
                "audio_output",
                "internal_reasoning",
                "discount",
            }
            if any(
                name not in allowed and decimal_price(value) != 0
                for name, value in pricing.items()
            ):
                raise BudgetStop("unrecognized endpoint pricing component")
            prompt = max(
                prompt,
                decimal_price(pricing.get("input_cache_write", "0")),
                decimal_price(pricing.get("input_cache_read", "0")),
            )
            completion += decimal_price(pricing.get("internal_reasoning", "0"))
            prompt_prices.append(prompt)
            completion_prices.append(completion)
            request_prices.append(request_fee)
            maxima.append(
                Decimal(context) * prompt
                + Decimal(settings.max_tokens) * completion
                + request_fee
            )
        self.max_price = {
            "prompt": float(max(prompt_prices) * 1_000_000),
            "completion": float(max(completion_prices) * 1_000_000),
            "request": float(max(request_prices)),
        }
        self.maximum = max(maxima)
        self.pricing_evidence = {
            "verified_at": datetime.now(UTC).isoformat(),
            "endpoints": endpoints,
            "max_price": self.max_price,
            "max_output_tokens": settings.max_tokens,
            "maximum_usd": str(self.maximum),
            "input_bound": "full advertised endpoint context capacity",
        }
        return self.maximum

    def complete(self, post: SourcePost, repair: bool = False) -> Any:
        settings = self.settings
        prompt = SYSTEM_PROMPT
        if repair:
            prompt += "\nThe preceding attempt failed local schema validation. Carefully return complete, valid JSON matching every required schema field."
        return request_json(
            "/chat/completions",
            settings.timeout,
            self.key,
            {
                "model": settings.model,
                "provider": {
                    "only": [settings.provider],
                    "allow_fallbacks": False,
                    "require_parameters": True,
                    "max_price": self.max_price,
                },
                "messages": [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": json.dumps(post_input(post), ensure_ascii=False),
                    },
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "food_offers",
                        "strict": True,
                        "schema": Extraction.model_json_schema(),
                    },
                },
                "max_tokens": settings.max_tokens,
                "temperature": settings.temperature,
                "stream": False,
                "plugins": [],
            },
        )


def response_cost(raw: Any) -> Decimal | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("usage"), dict):
        return None
    cost = raw["usage"].get("cost")
    return decimal_price(cost) if cost is not None else None


def parse_response(raw: Any) -> Extraction:
    if not isinstance(raw, dict) or raw.get("error"):
        raise ValueError("provider returned an error response")
    if raw.get("model") not in {MODEL, "meta/muse-spark-1.3-contributor-20260902"}:
        raise ValueError("response model differs from requested model")
    choices = raw.get("choices")
    if (
        not isinstance(choices, list)
        or len(choices) != 1
        or not isinstance(choices[0], dict)
    ):
        raise ValueError("expected exactly one response choice")
    if choices[0].get("finish_reason") != "stop":
        raise ValueError("response truncated or did not finish normally")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise TypeError("response message must be an object")
    content = message.get("content")
    if not isinstance(content, str):
        raise TypeError("response has no JSON text content")
    return Extraction.model_validate(parse_json(content.encode()))
