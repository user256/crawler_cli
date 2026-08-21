"""Golden contract: the saved crawl artifact schema (tickets 3344, 3685, 155, 156).

Freezes ``crawler-cli/crawl-artifact/5``: the exact field set that
``serialize_crawl_job`` emits (redirect chains and static URL evidence included)
and the loader's tolerance for legacy artifacts without ``schema_version``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contract_fixtures import assert_matches_golden, compare_urls_source_results

from crawler_cli.__main__ import _load_saved_crawl
from crawler_cli.models import CrawlJobResult
from crawler_cli.serialization import CRAWL_ARTIFACT_SCHEMA_VERSION, serialize_crawl_job

EXPECTED_RESULT_KEYS = {
    "requested_url",
    "final_url",
    "status",
    "headers",
    "content_type",
    "fetch_backend",
    "raw_html",
    "body_truncated",
    "wire_bytes",
    "decoded_bytes",
    "accounted_bytes",
    "body_truncation_reason",
    "content_hash_sha256",
    "content_hash_simhash",
    "discovered_links",
    "javascript_url_candidates",
    "css_url_candidates",
    "speculative_rejection_counts",
    "render_url_candidates",
    "render_discovery_attempted",
    "render_discovery_complete",
    "render_discovery_skip_reason",
    "allowed_by_robots",
    "skip_reason",
    "persist_error",
    "challenge",
    "ttfb_seconds",
    "total_duration_seconds",
    "lcp_ms",
    "cls",
    "inp_ms",
    "redirect_chain",
    "custom_data",
    "detected_cms",
    "detected_analytics",
    "extracted",
}

EXPECTED_JOB_KEYS = {
    "schema_version",
    "mode",
    "run_id",
    "seed_urls",
    "saved_to",
    "crawled_count",
    "blocked_count",
    "challenge_blocked_count",
    "persist_error_count",
    "persist_failed_urls",
    "durability",
    "frontier_mark_done_error_count",
    "frontier_mark_done_failed_urls",
    "crawl_run_status",
    "retry_attempts",
    "interrupted",
    "refresh_skipped_count",
    "budget_requests_started",
    "budget_wire_bytes",
    "budget_decoded_bytes",
    "budget_accounted_bytes",
    "budget_stop_reason",
    "javascript_url_candidate_count",
    "javascript_url_enqueued_count",
    "css_url_candidate_count",
    "css_url_enqueued_count",
    "speculative_capped_count",
    "render_url_candidate_count",
    "render_dom_enqueued_count",
    "render_discovery_attempt_count",
    "authorization_scope",
    "results",
}


def _job() -> CrawlJobResult:
    return CrawlJobResult(
        mode="list",
        seed_urls=["https://old.example/a"],
        results=compare_urls_source_results(),
        run_id="run-3344",
        saved_to="crawl.json",
    )


def test_crawl_artifact_matches_golden() -> None:
    payload = serialize_crawl_job(_job())
    assert payload["schema_version"] == CRAWL_ARTIFACT_SCHEMA_VERSION == "crawler-cli/crawl-artifact/5"
    assert set(payload.keys()) == EXPECTED_JOB_KEYS
    first_result = payload["results"][0]  # type: ignore[index]
    assert set(first_result.keys()) == EXPECTED_RESULT_KEYS
    assert_matches_golden("crawl_artifact.json", json.dumps(payload, indent=2) + "\n")


def test_artifact_round_trips_through_loader(tmp_path) -> None:
    artifact = tmp_path / "crawl.json"
    artifact.write_text(json.dumps(serialize_crawl_job(_job())), encoding="utf-8")
    job = _load_saved_crawl(Path(artifact))
    assert [result.requested_url for result in job.results] == [
        result.requested_url for result in compare_urls_source_results()
    ]
    # Redirect hops survive the round trip — the redirect-capture contract.
    assert job.results[1].redirect_chain == [
        {"url": "https://old.example/b", "status": 301},
        {"url": "https://old.example/b-interim", "status": 301},
    ]
    # Signed simhash BIGINTs survive as stored.
    assert job.results[-1].content_hash_simhash == -6955753827659690935


def test_loader_accepts_legacy_artifact_without_schema_version(tmp_path) -> None:
    payload = serialize_crawl_job(_job())
    del payload["schema_version"]
    artifact = tmp_path / "legacy.json"
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    job = _load_saved_crawl(Path(artifact))
    assert len(job.results) == len(compare_urls_source_results())


def test_jsonl_loader_validates_a_present_summary_schema_version(tmp_path) -> None:
    path = tmp_path / "crawl.jsonl"
    result = {"requested_url": "https://example.test/", "final_url": "https://example.test/", "status": 200}
    summary = {
        "__type": "summary",
        "schema_version": CRAWL_ARTIFACT_SCHEMA_VERSION,
        "mode": "open",
        "seed_urls": ["https://example.test/"],
    }
    path.write_text("\n".join(json.dumps(line) for line in (result, summary)) + "\n", encoding="utf-8")

    job = _load_saved_crawl(path)
    assert job.mode == "open"
    assert job.results[0].requested_url == "https://example.test/"


def test_jsonl_loader_rejects_an_unknown_stamped_summary_schema_version(tmp_path) -> None:
    path = tmp_path / "crawl.jsonl"
    summary = {"__type": "summary", "schema_version": "crawler-cli/crawl-artifact/999"}
    path.write_text(
        json.dumps({"requested_url": "https://example.test/"}) + "\n" + json.dumps(summary) + "\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Unsupported crawl artifact schema version"):
        _load_saved_crawl(path)


def test_saved_json_artifact_rejects_an_unknown_schema_version(tmp_path: Path) -> None:
    """The stamped single-document artifact is gated like the NDJSON summary.

    ``serialize_crawl_job`` is what writes ``schema_version``, so validating
    only the streaming form would leave the stamped format unchecked.
    """
    path = tmp_path / "artifact.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "crawler-cli/crawl-artifact/99",
                "mode": "list",
                "seed_urls": [],
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unsupported crawl artifact schema version"):
        _load_saved_crawl(path)


def test_saved_json_artifact_without_a_schema_version_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"mode": "list", "seed_urls": [], "results": []}), encoding="utf-8")
    assert _load_saved_crawl(path).mode == "list"
