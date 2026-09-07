import json

import pytest

from food_deals_mvp.demo_review import build_demo_review
from food_deals_mvp.extraction import extract
from food_deals_mvp.openrouter import Settings
from tests.llm_support import FakeClient


def initial(batch):
    return extract(
        batch.data_dir,
        Settings(),
        post_ids=batch.pilot_ids,
        state_dir=batch.state_dir,
        client=FakeClient(),
    )


def test_offline_review_preserves_sources_caches_and_ledger(llm_batch, monkeypatch):
    original = initial(llm_batch)
    original_prompt = Settings().prompt_version
    # The offline route must remain valid even after live prompt identity changes.
    monkeypatch.setattr("food_deals_mvp.openrouter.SYSTEM_PROMPT", "A future prompt")
    paths = [
        *llm_batch.state_dir.rglob("*.json"),
        *llm_batch.data_dir.glob("cache/llm/*.json"),
        *llm_batch.data_dir.glob("intermediate/*.json"),
        llm_batch.data_dir / "reports/extract.json",
    ]
    before = {path: path.read_bytes() for path in paths}
    page = build_demo_review(llm_batch.data_dir)
    assert page.exists() and "Original caption" in page.read_text()
    demo = json.loads((page.parent / "candidates.json").read_text())
    assert len(demo["rows"]) == 30
    assert demo["cache_fingerprints"] == original.cache_fingerprints
    assert all(path.read_bytes() == content for path, content in before.items())
    assert all(
        v["prompt_version"] == original_prompt
        for v in demo["original_settings"].values()
    )


def test_offline_review_rejects_changed_raw_cache(llm_batch):
    initial(llm_batch)
    path = next(llm_batch.data_dir.glob("cache/llm/*.json"))
    data = json.loads(path.read_text())
    data["raw"]["usage"]["cost"] = 2
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="fingerprint"):
        build_demo_review(llm_batch.data_dir)
    assert not (llm_batch.data_dir / "demo/review.html").exists()


def test_explicit_demo_continuation_reuses_cache_and_keeps_budget(llm_batch):
    initial(llm_batch)
    client = FakeClient()
    report = extract(
        llm_batch.data_dir,
        Settings(),
        accept_demo=True,
        client=client,
        state_dir=llm_batch.state_dir,
    )
    assert len(client.calls) == 3
    assert report.budget["charged_usd"] == "0.33"
    assert report.budget["cap_usd"] == "5"


def test_review_escapes_model_html(llm_batch):
    from tests.llm_support import extraction, response

    payload = '</script><img src=x onerror="alert(1)">'
    value = extraction()
    value.offers[0].description = payload
    extract(
        llm_batch.data_dir,
        Settings(),
        post_ids=llm_batch.pilot_ids,
        state_dir=llm_batch.state_dir,
        client=FakeClient(replies=[response(value)]),
    )
    page = build_demo_review(llm_batch.data_dir).read_text()
    assert payload not in page
    assert "&lt;/script&gt;&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in page
