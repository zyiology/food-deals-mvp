"""Protect persisted snapshots against malformed input and interrupted writes."""

from pathlib import Path

import pytest

from food_deals_mvp.models import Sources
from food_deals_mvp.storage import atomic_write, parse_json


@pytest.mark.parametrize(
    "content",
    [b'{"id":1,"id":2}', b'{"value":NaN}', b'{"value":Infinity}', b"{invalid"],
)
def test_reject_ambiguous_or_invalid_json(content: bytes) -> None:
    with pytest.raises(ValueError):
        parse_json(content)


def test_failed_replacement_preserves_file_and_cleans_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "sources.json"
    original = b'{"original":true}\n'
    path.write_bytes(original)
    value = Sources.model_validate(
        {
            "sources": [
                {
                    "channel_id": 123,
                    "name": "Example",
                    "export_root": "export",
                    "export_timezone": "Asia/Singapore",
                }
            ]
        }
    )

    def fail_replace(source: str, target: Path) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr("food_deals_mvp.storage.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated disk failure"):
        atomic_write(path, value)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
