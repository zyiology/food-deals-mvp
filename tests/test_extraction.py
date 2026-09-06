import json
from decimal import Decimal
from shutil import copytree

import pytest

from food_deals_mvp.extraction import (
    CacheEntry,
    PilotReview,
    cache_key,
    extract,
    load_extraction_report,
    select_posts,
)
from food_deals_mvp.extraction_models import (
    CandidateArtifact,
    Corrections,
    ExtractionArtifact,
)
from food_deals_mvp.extraction_prompt import post_input
from food_deals_mvp.llm_budget import Budget, Receipt, utc_now
from food_deals_mvp.openrouter import ProviderError, Settings
from food_deals_mvp.storage import atomic_write, fingerprint, read_json
from tests.llm_support import FakeClient, response


def run(batch, client=None, **options):
    return extract(
        batch.data_dir,
        options.pop("settings", Settings()),
        post_ids=batch.pilot_ids,
        state_dir=batch.state_dir,
        client=client or FakeClient(),
        **options,
    )


def test_dry_run_no_network_no_writes(llm_batch):
    client = FakeClient()
    report = run(llm_batch, client, dry_run=True)
    assert report.counts["selected"] == report.counts["cache_misses"] == 30
    assert report.counts["status_not_selected"] == 3
    assert not client.calls and not client.preflights
    assert not llm_batch.state_dir.exists()
    assert not (llm_batch.data_dir / "reports/extract.json").exists()


@pytest.mark.parametrize(
    "corruption",
    ["missing_report", "failed_report", "mismatched_media", "mismatched_posts"],
)
@pytest.mark.parametrize("dry", [True, False])
def test_source_completion_required_before_any_work(llm_batch, corruption, dry):
    report_path = llm_batch.data_dir / "reports/normalize.json"
    if corruption == "missing_report":
        report_path.unlink()
    else:
        path = (
            report_path
            if corruption == "failed_report"
            else llm_batch.data_dir
            / f"intermediate/{'media' if corruption == 'mismatched_media' else 'posts'}.json"
        )
        data = json.loads(path.read_text())
        data["status" if corruption == "failed_report" else "dataset_id"] = "failed"
        path.write_text(json.dumps(data))
    client = FakeClient()
    with pytest.raises((ValueError, OSError)):
        run(llm_batch, client, dry_run=dry)
    assert not client.calls and not client.preflights
    assert not llm_batch.state_dir.exists()


def test_pilot_selection_rejects_duplicates_unknown_and_unbalanced(llm_batch):
    ids = json.loads(llm_batch.pilot_ids.read_text())
    for bad in [ids + ids[:1], ids[:-1] + ["telegram:404:1"], ids[:-1]]:
        llm_batch.pilot_ids.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            select_posts(llm_batch.posts, llm_batch.pilot_ids, None)
    llm_batch.pilot_ids.write_text(json.dumps(ids))
    with pytest.raises(ValueError, match="truncate"):
        select_posts(llm_batch.posts, llm_batch.pilot_ids, 29)


def test_success_cache_reuse_expansion_and_full_batch_gate(llm_batch):
    client = FakeClient()
    first = run(llm_batch, client)
    assert first.status == "partial" and len(client.calls) == 30
    assert first.counts["row_candidate"] == 30
    assert first.counts["attempts_this_run"] == first.counts["cache_misses"] == 30
    assert first.counts["cache_hits"] == 0
    assert load_extraction_report(llm_batch.data_dir) == first
    second = run(llm_batch, client, resume=True)
    assert second.dataset_id == first.dataset_id
    assert len(client.calls) == 30 and second.counts["cache_hits"] == 30
    assert second.budget["charged_usd"] == "0.30"
    with pytest.raises(ValueError, match="pilot-review"):
        extract(
            llm_batch.data_dir, Settings(), state_dir=llm_batch.state_dir, client=client
        )
    approval = llm_batch.data_dir / "approval.json"
    atomic_write(
        approval,
        PilotReview(
            reviewed_at=utc_now(),
            accepted=True,
            settings_hash=first.settings_hash,
            cache_fingerprints=first.cache_fingerprints,
        ),
    )
    full = extract(
        llm_batch.data_dir,
        Settings(),
        state_dir=llm_batch.state_dir,
        client=client,
        pilot_review=approval,
    )
    assert full.status == "success" and len(client.calls) == 33
    assert full.counts["cache_hits"] == 30 and full.counts["cache_misses"] == 3


def test_budget_survives_output_directory_and_prompt_changes(llm_batch, tmp_path):
    first = run(llm_batch, settings=Settings(max_attempts=1))
    assert first.status == "failed" and first.budget["attempts"] == 1
    other = tmp_path / "other-data"
    copytree(llm_batch.data_dir, other)
    report = extract(
        other,
        Settings(prompt_version="v2", max_attempts=1),
        post_ids=llm_batch.pilot_ids,
        state_dir=llm_batch.state_dir,
        client=FakeClient(),
    )
    assert report.budget["attempts"] == 2
    assert report.budget["charged_usd"] == "0.02"


def test_cache_keys_change_only_for_relevant_inputs(llm_batch):
    post = llm_batch.posts[0].model_copy(deep=True)
    original = cache_key(post, Settings())
    post.raw_record["reactions"] = ["like"]
    post.source_content_hash = "different"
    assert cache_key(post, Settings()) == original
    for settings in [
        Settings(prompt_version="v2"),
        Settings(model="other"),
        Settings(provider="other"),
        Settings(max_tokens=7000),
        Settings(schema_version="v2"),
    ]:
        assert cache_key(post, settings) != original
    post.text += " New caption fact"
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        cache_key(post, Settings())
    post.extraction_input_hash = fingerprint(post_input(post))
    assert cache_key(post, Settings()) != original


@pytest.mark.parametrize(
    "reply",
    [
        response(choices=[{"finish_reason": "length", "message": {"content": "{}"}}]),
        response(
            choices=[{"finish_reason": "stop", "message": {"content": "{invalid"}}]
        ),
        response(choices=[{"finish_reason": "stop", "message": {"content": "{}"}}]),
    ],
)
def test_one_schema_repair_and_failure_is_not_empty_success(llm_batch, reply):
    client = FakeClient(replies=[reply, reply])
    report = run(llm_batch, client, settings=Settings(max_attempts=2))
    assert client.calls[:2] == [
        (llm_batch.posts[0].post_id, False),
        (llm_batch.posts[0].post_id, True),
    ]
    assert report.counts["status_failed"] == 1
    assert report.counts.get("offers", 0) == 0
    assert report.budget["charged_usd"] == "0.02"


def test_timeout_retry_honors_delay_and_retains_charge(llm_batch, monkeypatch):
    delays = []
    monkeypatch.setattr("food_deals_mvp.extraction.time.sleep", delays.append)
    client = FakeClient(
        replies=[ProviderError("timeout", transient=True, retry_after=3)]
    )
    report = run(llm_batch, client, settings=Settings(max_attempts=2))
    assert len(client.calls) == 2 and delays == [3]
    assert report.budget["reserved_usd"] == "0.10"
    assert report.budget["charged_usd"] == "0.01"


def test_auth_failure_stops_batch_and_is_resumable(llm_batch):
    client = FakeClient(replies=[ProviderError("OpenRouter HTTP 401")])
    report = run(llm_batch, client)
    assert len(client.calls) == 1 and report.status == "failed"
    assert report.counts["status_failed"] == 1
    assert report.counts["status_pending"] == 29
    resumed = run(llm_batch, resume=True)
    assert resumed.counts["status_success"] == 30
    assert resumed.budget["unknown_attempts"] == 1


def test_failed_reservation_prevents_dispatch(llm_batch, monkeypatch):
    original = Budget.save

    def fail_on_attempt(self):
        if self.ledger.attempts:
            raise OSError("simulated fsync failure")
        original(self)

    monkeypatch.setattr(Budget, "save", fail_on_attempt)
    client = FakeClient()
    report = run(llm_batch, client)
    assert report.status == "failed" and not client.calls
    assert "fsync failure" in report.errors[0]


def test_unaffordable_request_prevents_dispatch(llm_batch):
    client = FakeClient(maximum=Decimal(6))
    report = run(llm_batch, client)
    assert report.status == "failed" and not client.calls
    assert report.budget["attempts"] == 0


def test_recover_response_before_checkpoint(llm_batch):
    post = llm_batch.posts[0]
    key = cache_key(post, Settings())
    budget = Budget(llm_batch.state_dir)
    attempt = budget.reserve(post.post_id, key, Decimal(1), 300)
    atomic_write(
        llm_batch.state_dir / "receipts" / f"{attempt.attempt_id}.json",
        Receipt(
            attempt_id=attempt.attempt_id,
            cache_key=key,
            raw=response(),
            cost=Decimal("0.01"),
            error=None,
        ),
    )
    client = FakeClient()
    report = run(llm_batch, client)
    assert len(client.calls) == 29
    assert post.post_id not in {id_ for id_, _ in client.calls}
    assert report.budget["charged_usd"] == "0.30"


def test_interrupted_refresh_does_not_resurrect_old_success(llm_batch):
    run(llm_batch)
    post = llm_batch.posts[0]
    budget = Budget(llm_batch.state_dir)
    budget.reserve(post.post_id, cache_key(post, Settings()), Decimal(1), 300)
    report = run(llm_batch)
    assert report.outcomes[post.post_id] == "failed"
    assert report.counts["status_success"] == 29
    assert report.budget["reserved_usd"] == "1"
    assert report.replacements[post.post_id]["removed"]


def test_correction_preserves_raw_cache_and_rejects_stale_targets(llm_batch):
    first = run(llm_batch)
    post = llm_batch.posts[0]
    key = cache_key(post, Settings())
    path = llm_batch.data_dir / "corrections.json"
    values = {
        "corrections": [
            {
                "correction_id": "review-1",
                "post_id": post.post_id,
                "input_hash": post.extraction_input_hash,
                "cache_key": key,
                "pointer": "/offers/0/availability/end_date",
                "expected": "2026-08-31",
                "value": "2026-08-30",
                "reason": "Synthetic reviewer correction",
                "evidence": ["1-31 Aug."],
                "reviewed_at": utc_now().isoformat(),
            }
        ]
    }
    atomic_write(path, Corrections.model_validate(values))
    client = FakeClient()
    corrected = run(llm_batch, client, corrections_path=path)
    assert not client.calls
    assert corrected.dataset_id != first.dataset_id
    assert (
        corrected.replacements[post.post_id]["removed"]
        and corrected.replacements[post.post_id]["added"]
    )
    saved = CacheEntry.model_validate(
        read_json(llm_batch.state_dir / "cache" / f"{key}.json")
    )
    assert saved.extraction is not None
    assert str(saved.extraction.offers[0].availability.end_date) == "2026-08-31"
    values["corrections"][0]["input_hash"] = "stale"
    atomic_write(path, Corrections.model_validate(values))
    with pytest.raises(ValueError, match="stale correction"):
        run(llm_batch, client, corrections_path=path)
    assert not client.calls


def test_report_rejects_mismatched_completion_artifacts(llm_batch):
    run(llm_batch)
    path = llm_batch.data_dir / "intermediate/candidates.json"
    artifact = CandidateArtifact.model_validate(read_json(path))
    artifact.dataset_id = "interrupted"
    atomic_write(path, artifact)
    with pytest.raises(ValueError, match="dataset IDs differ"):
        load_extraction_report(llm_batch.data_dir)


def test_successful_empty_response_is_distinct_from_failure(llm_batch):
    from tests.llm_support import extraction

    result = response(
        extraction(relevance="food", promotion_kind="pure_listing", offers=[])
    )
    client = FakeClient(replies=[result] * 30)
    report = run(llm_batch, client)
    assert report.counts["status_success"] == 30
    assert report.counts["offers"] == 0
    artifact = ExtractionArtifact.model_validate(
        read_json(llm_batch.data_dir / "intermediate/extractions.json")
    )
    assert artifact.results[0].extraction is not None


def test_dry_run_does_not_count_interrupted_refresh_as_success(llm_batch):
    run(llm_batch)
    post = llm_batch.posts[0]
    budget = Budget(llm_batch.state_dir)
    budget.reserve(post.post_id, cache_key(post, Settings()), Decimal(1), 300)
    before = {str(p): p.read_bytes() for p in llm_batch.state_dir.rglob("*.json")}
    report = run(llm_batch, dry_run=True)
    assert report.counts["cache_hits"] == 29
    assert report.outcomes[post.post_id] == "failed"
    assert before == {
        str(p): p.read_bytes() for p in llm_batch.state_dir.rglob("*.json")
    }


@pytest.mark.parametrize(
    "choices", [[None], [{"finish_reason": "stop", "message": None}]]
)
def test_malformed_provider_envelope_is_recorded_without_crashing(llm_batch, choices):
    bad = response(choices=choices)
    report = run(
        llm_batch, FakeClient(replies=[bad, bad]), settings=Settings(max_attempts=2)
    )
    assert report.counts["status_failed"] == 1
    assert report.budget["charged_usd"] == "0.02"


def test_crash_after_dispatch_keeps_reservation_on_restart(llm_batch):
    client = FakeClient(replies=[KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        run(llm_batch, client)
    assert len(client.calls) == 1
    recovered = run(llm_batch)
    assert recovered.counts["status_failed"] == 1
    assert recovered.budget["reserved_usd"] == "0.10"
    assert recovered.budget["charged_usd"] == "0.29"


def test_cli_dry_run_and_mutually_exclusive_rerun_flags(llm_batch, monkeypatch, capsys):
    from food_deals_mvp.cli import main

    def isolated_extract(data_dir, settings, **kwargs):
        return extract(data_dir, settings, state_dir=llm_batch.state_dir, **kwargs)

    monkeypatch.setattr("food_deals_mvp.cli.extract", isolated_extract)
    command = [
        "food-deals-mvp",
        "extract",
        "--data-dir",
        str(llm_batch.data_dir),
        "--post-ids",
        str(llm_batch.pilot_ids),
        "--dry-run",
    ]
    monkeypatch.setattr("sys.argv", command)
    main()
    assert "extract: dry_run" in capsys.readouterr().out
    assert not llm_batch.state_dir.exists()
    monkeypatch.setattr("sys.argv", [*command, "--resume", "--refresh"])
    with pytest.raises(SystemExit) as failure:
        main()
    assert failure.value.code == 2
