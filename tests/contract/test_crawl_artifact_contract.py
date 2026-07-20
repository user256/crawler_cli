"""Golden contract: the saved crawl artifact schema (ticket 3344).

Freezes ``crawler-cli/crawl-artifact/1``: the exact field set that
``serialize_crawl_job`` emits (redirect chains included) and the loader's
tolerance for legacy artifacts without ``schema_version``.
"""

from __future__ import annotations

import json
from pathlib import Path

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
    "content_hash_sha256",
    "content_hash_simhash",
    "discovered_links",
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
    assert payload["schema_version"] == CRAWL_ARTIFACT_SCHEMA_VERSION == "crawler-cli/crawl-artifact/1"
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
