from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
import pytest

from crawler_cli.__main__ import _load_saved_crawl
from crawler_cli.config import CrawlConfig
from crawler_cli.engine import CrawlEngine
from crawler_cli.models import CrawlResult, FetchResponse
from crawler_cli.run_metadata import (
    CRAWL_RUN_METADATA_SCHEMA_VERSION,
    compute_file_sha256,
    read_run_metadata,
    resolve_sidecar_path,
    sidecar_path_for,
)


class FixtureBackend:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    async def fetch(self, url: str) -> FetchResponse:
        html = self.pages.get(url, "<html><body>Not Found</body></html>")
        status = 200 if url in self.pages else 404
        return FetchResponse(
            url=url,
            requested_url=url,
            status=status,
            headers={"Content-Type": "text/html; charset=utf-8"},
            body=html.encode("utf-8"),
            text=html,
            elapsed_seconds=0.01,
        )


class FixtureRobots:
    def __init__(self, disallowed: set[str] | None = None) -> None:
        self.disallowed = disallowed or set()

    async def is_allowed(self, url: str) -> bool:
        return url not in self.disallowed

    async def sitemaps(self, seed: str) -> list[str]:
        return []

    async def get_crawl_delay(self, domain: str) -> float | None:
        return None


class FixtureStore:
    def __init__(self) -> None:
        self.saved_pages: list[Any] = []
        self.saved_metadata: dict[str, dict] = {}
        self.frontier: dict[str, dict] = {}

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def persist(self, result: CrawlResult) -> None:
        self.saved_pages.append(result)

    async def save_metadata(self, key: str, metadata: dict) -> None:
        self.saved_metadata[key] = metadata

    async def enqueue_frontier(
        self,
        urls: list[tuple[str, int, str | None]],
        source: str = "link",
        source_detail: str | None = None,
    ) -> int:
        enqueued = 0
        for item in urls:
            url = item[0]
            depth = item[1]
            parent = item[2] if len(item) > 2 else None
            if url not in self.frontier:
                self.frontier[url] = {"status": "queued", "depth": depth, "parent_url": parent}
                enqueued += 1
        return enqueued

    async def frontier_next_batch(self, batch_size: int) -> list[tuple[str, int, str | None, int]]:
        batch = []
        for url, state in self.frontier.items():
            if state["status"] == "queued":
                state["status"] = "pending"
                batch.append((url, int(state["depth"]), state["parent_url"], 0))
                if len(batch) >= batch_size:
                    break
        return batch

    async def frontier_mark_retry(self, url: str, retry_count: int, delay_seconds: float) -> None:
        if url in self.frontier:
            self.frontier[url]["status"] = "queued"

    async def frontier_mark_done(self, urls: list[str]) -> None:
        for url in urls:
            if url in self.frontier:
                self.frontier[url]["status"] = "done"

    async def frontier_stats(self) -> tuple[int, int, int]:
        queued = sum(1 for s in self.frontier.values() if s["status"] == "queued")
        pending = sum(1 for s in self.frontier.values() if s["status"] == "pending")
        done = sum(1 for s in self.frontier.values() if s["status"] == "done")
        return queued, pending, done

    async def record_source_by_url(self, url: str, source: str, detail: str | None = None) -> None:
        pass

    async def record_sources_bulk(self, pairs: list[tuple[str, str | None]], source: str) -> None:
        pass

    async def persist_sitemap_hreflang_bulk(self, pairs: list) -> None:
        pass


@pytest.mark.asyncio
async def test_completed_fixture_crawl_creates_ndjson_and_matching_sidecar(tmp_path: Path):
    """Acceptance check 1: completed fixture crawl creates an NDJSON artifact

    and metadata sidecar with matching run ID and checksum (ticket 400).
    """
    pages = {
        "https://example.test/": '<html><body><a href="https://example.test/page1">Link 1</a></body></html>',
        "https://example.test/page1": "<html><body><h1>Page 1</h1></body></html>",
    }
    config = CrawlConfig(
        max_concurrency=1,
        discover_sitemaps=False,
        respect_robots_txt=True,
        destination_guard="off",
    )
    store: Any = FixtureStore()
    engine: Any = CrawlEngine(config, store=store)
    engine.backend = FixtureBackend(pages)
    engine._robots = FixtureRobots()

    artifact_path = tmp_path / "crawl.ndjson"
    run_id = "test-run-400-clean"
    job = await engine.crawl_open(
        ["https://example.test/"],
        run_id=run_id,
        save_to=str(artifact_path),
        max_urls=10,
    )

    # 1. Artifact exists and is non-empty NDJSON
    assert artifact_path.is_file()
    lines = [json.loads(line) for line in artifact_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 2  # at least 1 result line + 1 terminal summary line
    summary_line = lines[-1]
    assert summary_line.get("__type") == "summary"

    # 2. Sidecar exists
    sidecar_path = sidecar_path_for(artifact_path)
    assert sidecar_path.is_file()
    assert sidecar_path.name == "crawl.meta.json"
    assert resolve_sidecar_path(artifact_path) == sidecar_path

    # 3. Sidecar content verification
    metadata = read_run_metadata(artifact_path)
    assert metadata["schema_version"] == CRAWL_RUN_METADATA_SCHEMA_VERSION == "crawler-cli/run-metadata/1"
    assert metadata["run_id"] == run_id == job.run_id
    assert metadata["seed_urls"] == ["https://example.test/"]
    assert metadata["crawl_mode"] == "open"
    assert metadata["completion_state"] == "complete"
    assert metadata["clean"] is True
    assert metadata["is_clean"] is True
    assert metadata["result_count"] == len(job.results) == 2
    assert metadata["crawled_count"] == 2

    # 4. Checksum matches artifact file exactly
    expected_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    assert metadata["sha256"] == expected_sha256
    assert metadata["artifact_sha256"] == expected_sha256
    assert compute_file_sha256(artifact_path) == expected_sha256

    # 5. Robots policy and limits are self-describing
    assert metadata["robots"]["policy"] == "respect"
    assert metadata["robots"]["respect_robots_txt"] is True
    assert metadata["robots"]["blocked_count"] == 0
    assert metadata["limits"]["max_pages"] == 10
    assert metadata["limits"]["concurrency"] == 1

    # 6. Timestamps
    assert metadata["started_at"] is not None
    assert metadata["ended_at"] is not None
    assert isinstance(metadata["duration_seconds"], (int, float))


@pytest.mark.asyncio
async def test_interrupted_crawl_is_unambiguously_marked_non_clean(tmp_path: Path):
    """Acceptance check 2: an interrupted crawl is unambiguously marked non-clean."""
    pages = {
        "https://example.test/": '<html><body><a href="https://example.test/page1">Link 1</a></body></html>',
        "https://example.test/page1": "<html><body><h1>Page 1</h1></body></html>",
    }
    config = CrawlConfig(
        max_concurrency=1,
        discover_sitemaps=False,
        destination_guard="off",
    )
    store: Any = FixtureStore()
    engine: Any = CrawlEngine(config, store=store)
    engine.backend = FixtureBackend(pages)
    engine._robots = FixtureRobots()
    # Request stop early to simulate interruption
    engine.request_stop()

    artifact_path = tmp_path / "interrupted.ndjson"
    run_id = "test-run-400-interrupted"
    job = await engine.crawl_open(
        ["https://example.test/"],
        run_id=run_id,
        save_to=str(artifact_path),
        max_urls=10,
    )

    assert job.interrupted is True
    assert job.crawl_run_status == "interrupted"

    metadata = read_run_metadata(artifact_path)
    assert metadata["completion_state"] == "interrupted"
    assert metadata["clean"] is False
    assert metadata["is_clean"] is False
    assert metadata["interrupted"] is True
    assert metadata["run_id"] == run_id
    assert metadata["sha256"] == compute_file_sha256(artifact_path)


@pytest.mark.asyncio
async def test_complete_with_errors_crawl_is_unambiguously_marked_non_clean(tmp_path: Path):
    """Acceptance check 2: complete_with_errors is unambiguously marked non-clean."""
    pages = {
        "https://example.test/": '<html><body><a href="https://example.test/page1">Link 1</a></body></html>',
    }
    config = CrawlConfig(
        max_concurrency=1,
        discover_sitemaps=False,
        destination_guard="off",
    )

    class ErrorStore(FixtureStore):
        async def persist(self, result: CrawlResult) -> None:
            raise RuntimeError("Database write error")

    error_store: Any = ErrorStore()
    engine: Any = CrawlEngine(config, store=error_store)
    engine.backend = FixtureBackend(pages)
    engine._robots = FixtureRobots()

    artifact_path = tmp_path / "errors.ndjson"
    run_id = "test-run-400-errors"
    job = await engine.crawl_open(
        ["https://example.test/"],
        run_id=run_id,
        save_to=str(artifact_path),
        max_urls=1,
    )

    assert job.crawl_run_status == "complete_with_errors"
    assert job.persist_error_count > 0

    metadata = read_run_metadata(artifact_path)
    assert metadata["completion_state"] == "complete_with_errors"
    assert metadata["clean"] is False
    assert metadata["is_clean"] is False
    assert metadata["error_counts"]["persist_error_count"] > 0
    assert metadata["persist_error_count"] > 0
    assert metadata["sha256"] == compute_file_sha256(artifact_path)


def test_existing_artifact_readers_accept_prior_json_files(tmp_path: Path):
    """Acceptance check 3: existing artifact readers still accept prior .json files."""
    # 1. Single-document legacy JSON artifact
    legacy_json = tmp_path / "legacy_single.json"
    legacy_json.write_text(
        json.dumps(
            {
                "schema_version": "crawler-cli/crawl-artifact/8",
                "mode": "list",
                "seed_urls": ["https://legacy.test/"],
                "results": [
                    {
                        "requested_url": "https://legacy.test/",
                        "final_url": "https://legacy.test/",
                        "status": 200,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    job1 = _load_saved_crawl(legacy_json)
    assert job1.mode == "list"
    assert len(job1.results) == 1
    assert job1.results[0].requested_url == "https://legacy.test/"

    # 2. NDJSON saved with .json extension (Wentworth/Align style)
    wentworth_style = tmp_path / "wentworth.json"
    result_line = json.dumps(
        {"requested_url": "https://wentworth.test/", "final_url": "https://wentworth.test/", "status": 200}
    )
    summary_line = json.dumps(
        {
            "__type": "summary",
            "schema_version": "crawler-cli/crawl-artifact/8",
            "mode": "open",
            "run_id": "wentworth-run-1",
            "seed_urls": ["https://wentworth.test/"],
        }
    )
    wentworth_style.write_text(f"{result_line}\n{summary_line}\n", encoding="utf-8")

    job2 = _load_saved_crawl(wentworth_style)
    assert job2.mode == "open"
    assert job2.run_id == "wentworth-run-1"
    assert len(job2.results) == 1


def test_loader_populates_sidecar_metadata_when_present(tmp_path: Path):
    """Loading an artifact automatically attaches the companion run-metadata."""
    artifact = tmp_path / "crawl.ndjson"
    result_line = json.dumps(
        {"requested_url": "https://example.test/", "final_url": "https://example.test/", "status": 200}
    )
    summary_line = json.dumps(
        {
            "__type": "summary",
            "schema_version": "crawler-cli/crawl-artifact/8",
            "mode": "open",
            "run_id": "run-sidecar-test",
        }
    )
    artifact.write_text(f"{result_line}\n{summary_line}\n", encoding="utf-8")

    sidecar = tmp_path / "crawl.meta.json"
    sidecar.write_text(
        json.dumps(
            {
                "schema_version": CRAWL_RUN_METADATA_SCHEMA_VERSION,
                "run_id": "run-sidecar-test",
                "seed_urls": ["https://example.test/"],
                "completion_state": "complete",
                "clean": True,
                "sha256": compute_file_sha256(artifact),
            }
        ),
        encoding="utf-8",
    )

    loaded = _load_saved_crawl(artifact)
    assert loaded.run_id == "run-sidecar-test"
    assert loaded.run_metadata is not None
    assert loaded.run_metadata["schema_version"] == "crawler-cli/run-metadata/1"
    assert loaded.run_metadata["clean"] is True
    assert loaded.sidecar_path == str(sidecar)


@pytest.mark.asyncio
async def test_save_to_without_extension_names_ndjson(tmp_path: Path):
    """When save_to has no extension, it defaults to .ndjson."""
    pages = {"https://example.test/": "<html><body>Home</body></html>"}
    config = CrawlConfig(discover_sitemaps=False, destination_guard="off")
    fixture_store: Any = FixtureStore()
    engine: Any = CrawlEngine(config, store=fixture_store)
    engine.backend = FixtureBackend(pages)
    engine._robots = FixtureRobots()

    out_base = tmp_path / "portable_crawl"
    job = await engine.crawl_open(["https://example.test/"], save_to=str(out_base), max_urls=1)

    ndjson_path = tmp_path / "portable_crawl.ndjson"
    sidecar_path = tmp_path / "portable_crawl.meta.json"

    assert ndjson_path.is_file()
    assert sidecar_path.is_file()
    assert job.saved_to == str(ndjson_path)
    assert job.sidecar_path == str(sidecar_path)
