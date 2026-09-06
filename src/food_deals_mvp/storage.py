"""Canonical hashing and validated, atomic JSON file replacement."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ValidationError


def fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def read_json(path: Path) -> object:
    return parse_json(path.read_bytes())


def parse_json(content: bytes) -> object:
    def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ValueError(f"invalid JSON constant: {value}")

    return json.loads(
        content,
        object_pairs_hook=unique_pairs,
        parse_constant=reject_constant,
    )


def error_detail(error: Exception) -> str:
    """Describe validation failures without dumping source records into logs."""
    if isinstance(error, ValidationError):
        return str(error.errors(include_input=False, include_url=False))
    return str(error)


def atomic_write(path: Path, value: BaseModel) -> None:
    payload = value.model_dump_json(indent=2)
    type(value).model_validate_json(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = stream.name
            stream.write(payload + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
