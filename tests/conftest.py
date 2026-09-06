"""All extraction tests use temporary state and blocked network access."""

from pathlib import Path

import pytest

from tests.llm_support import LlmBatch, make_batch


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject(*args, **kwargs):
        pytest.fail("network access is forbidden in unit tests")

    monkeypatch.setattr("socket.socket.connect", reject)
    monkeypatch.setattr("socket.create_connection", reject)


@pytest.fixture
def llm_batch(tmp_path: Path) -> LlmBatch:
    return make_batch(tmp_path)
