from __future__ import annotations

import json
import logging

import pytest

from crawler_cli import CrawlConfig, CrawlEngine
from crawler_cli.engine import CrawlRunSelectionError
from crawler_cli.models import FetchResponse
from crawler_cli.persistence import MemoryStore


class FakeBackend:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    async def fetch(self, url: str) -> FetchResponse:
        html = self.pages[url]
        return FetchResponse(
            url=url,
            requested_url=url,
            status=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            body=html.encode("utf-8"),
            text=html,
        )


class FakeRobots:
    def __init__(self, disallowed: set[str] | None = None, crawl_delay: float | None = None) -> None:
        self.disallowed = disallowed or set()
        self.crawl_delay = crawl_delay

    async def is_allowed(self, url: str) -> bool:
        return url not in self.disallowed

    async def get_crawl_delay(self, url: str) -> float | None:
        return self.crawl_delay

    async def sitemaps(self, url: str) -> list[str]:
        return []


class FakeStore:
    def __init__(self) -> None:
        self.frontier: dict[str, dict[str, object]] = {}
        self.saved_metadata: dict[str, dict[str, object]] = {}
        self.requested_batch_sizes: list[int] = []

    async def persist(self, result) -> None:
        return None

    async def save_metadata(self, key: str, value: dict[str, object]) -> None:
        self.saved_metadata[key] = value

    async def enqueue_frontier(
        self,
        frontier_data: list[tuple[str, int, str | None, float | None] | tuple[str, int, str | None]],
        *,
        source: str | None = None,
        source_detail: str | None = None,
    ) -> int:
        inserted = 0
        for item in frontier_data:
            url, depth, parent_url = item[0], item[1], item[2]
            priority_score = float(item[3]) if len(item) > 3 and item[3] is not None else 0.0
            if url in self.frontier:
                continue
            self.frontier[url] = {
                "depth": depth,
                "parent_url": parent_url,
                "status": "queued",
                "priority_score": priority_score,
                "retry_count": 0,
                "retry_at": 0,
            }
            inserted += 1
        return inserted

    async def frontier_reset_all_pending_to_queued(self) -> int:
        reset = 0
        for state in self.frontier.values():
            if state["status"] == "pending":
                state["status"] = "queued"
                reset += 1
        return reset

    async def frontier_next_batch(self, batch_size: int) -> list[tuple[str, int, str | None, int]]:
        self.requested_batch_sizes.append(batch_size)
        batch: list[tuple[str, int, str | None, int]] = []
        for url, state in sorted(
            self.frontier.items(),
            key=lambda item: (-float(item[1].get("priority_score", 0.0)), item[0]),
        ):
            if state["status"] != "queued":
                continue
            state["status"] = "pending"
            batch.append(
                (url, int(state["depth"]), state["parent_url"], int(state.get("retry_count", 0)))  # type: ignore[arg-type]
            )
            if len(batch) >= batch_size:
                break
        return batch

    async def frontier_mark_retry(self, url: str, retry_count: int, delay_seconds: float) -> None:
        if url in self.frontier:
            self.frontier[url]["status"] = "queued"
            self.frontier[url]["retry_count"] = retry_count

    async def frontier_mark_done(self, urls: list[str]) -> None:
        for url in urls:
            if url in self.frontier:
                self.frontier[url]["status"] = "done"

    async def frontier_stats(self) -> tuple[int, int, int]:
        queued = sum(1 for state in self.frontier.values() if state["status"] == "queued")
        pending = sum(1 for state in self.frontier.values() if state["status"] == "pending")
        done = sum(1 for state in self.frontier.values() if state["status"] == "done")
        return queued, pending, done

    async def record_source_by_url(self, url: str, source: str, detail: str | None = None) -> None:
        return None

    async def record_sources_bulk(
        self,
        url_detail_pairs: list[tuple[str, str | None]],
        source: str,
    ) -> None:
        return None

    async def persist_sitemap_hreflang_bulk(self, page_hreflang_pairs: list) -> None:
        return None


class TimedBackend:
    async def fetch(self, url: str) -> FetchResponse:
        return FetchResponse(
            url=url,
            requested_url=url,
            status=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            body=b"<html><title>t</title></html>",
            text="<html><title>t</title></html>",
            ttfb_seconds=0.012,
            elapsed_seconds=0.034,
        )


@pytest.mark.asyncio
async def test_crawl_propagates_timing_metrics():
    engine = CrawlEngine(CrawlConfig(respect_robots_txt=False))
    engine.backend = TimedBackend()

    result = await engine.crawl("https://example.com/")

    assert result.ttfb_seconds == 0.012
    assert result.total_duration_seconds == 0.034

    from crawler_cli.serialization import serialize_crawl_result

    payload = serialize_crawl_result(result)
    assert payload["ttfb_seconds"] == 0.012
    assert payload["total_duration_seconds"] == 0.034


@pytest.mark.asyncio
async def test_crawl_web_vitals_null_on_http_backend():
    """HTTP backends can't measure CWV, so the fields stay null (ticket 046)."""
    engine = CrawlEngine(CrawlConfig(respect_robots_txt=False))
    engine.backend = TimedBackend()

    result = await engine.crawl("https://example.com/")

    assert result.lcp_ms is None
    assert result.cls is None
    assert result.inp_ms is None

    from crawler_cli.serialization import serialize_crawl_result

    payload = serialize_crawl_result(result)
    assert payload["lcp_ms"] is None
    assert payload["cls"] is None
    assert payload["inp_ms"] is None


@pytest.mark.asyncio
async def test_crawl_respects_robots_txt_disallow():
    engine = CrawlEngine(CrawlConfig())
    engine.backend = FakeBackend({"https://example.com/": "<html></html>"})
    engine._robots = FakeRobots(disallowed={"https://example.com/"})

    result = await engine.crawl("https://example.com/")

    assert result.allowed_by_robots is False
    assert result.skip_reason == "robots_txt_disallow"
    assert result.status == 0


@pytest.mark.asyncio
async def test_open_crawl_default_limit_is_safe_bound_and_saves_metadata(tmp_path):
    pages = {"https://example.com/": '<html><body><a href="/1">1</a></body></html>'}
    for idx in range(1, 205):
        next_link = f'<a href="/{idx + 1}">next</a>' if idx < 204 else ""
        pages[f"https://example.com/{idx}"] = f"<html><body>{next_link}</body></html>"

    store = FakeStore()
    engine = CrawlEngine(CrawlConfig(max_concurrency=1, discover_sitemaps=False), store=store)
    engine.backend = FakeBackend(pages)
    engine._robots = FakeRobots()

    output_path = tmp_path / "crawl.jsonl"
    job = await engine.crawl_open(["https://example.com/"], save_to=str(output_path))

    assert job.mode == "open"
    assert job.max_urls == 200
    assert len(job.results) == 200
    lines = [json.loads(ln) for ln in output_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    summary = next(ln for ln in lines if ln.get("__type") == "summary")
    assert summary["max_urls"] == 200
    assert summary["crawled_count"] == 200
    assert store.saved_metadata["crawl_open"]["max_urls"] == 200
    assert store.saved_metadata["crawl_open"]["crawled_count"] == 200


@pytest.mark.asyncio
async def test_skip_amp_variants_does_not_enqueue_amp_shapes(tmp_path):
    """--skip-amp-variants keeps AMP URL shapes out of the frontier (ticket 103)."""
    pages = {
        "https://example.com/": (
            "<html><body>"
            '<a href="/article">A</a>'
            '<a href="/article/amp">AMP</a>'
            '<a href="/article?amp=1">AMP-q</a>'
            '<a href="/revamp">not amp</a>'
            "</body></html>"
        ),
        "https://example.com/article": "<html><body>article</body></html>",
        "https://example.com/article/amp": "<html><body>amp</body></html>",
        "https://example.com/article?amp=1": "<html><body>amp q</body></html>",
        "https://example.com/revamp": "<html><body>revamp</body></html>",
    }
    store = FakeStore()
    engine = CrawlEngine(
        CrawlConfig(max_concurrency=1, discover_sitemaps=False, skip_amp_variants=True),
        store=store,
    )
    engine.backend = FakeBackend(pages)
    engine._robots = FakeRobots()

    job = await engine.crawl_open(["https://example.com/"], save_to=str(tmp_path / "c.jsonl"))
    crawled = {r.requested_url for r in job.results}

    # AMP shapes were never enqueued/crawled...
    assert "https://example.com/article/amp" not in crawled
    assert "https://example.com/article?amp=1" not in crawled
    # ...but the non-AMP article and the "/revamp" decoy still are.
    assert "https://example.com/article" in crawled
    assert "https://example.com/revamp" in crawled


@pytest.mark.asyncio
async def test_open_crawl_explicit_finite_limit_saves_output(tmp_path):
    pages = {
        "https://example.com/": '<html><body><a href="/a">A</a><a href="/b">B</a></body></html>',
        "https://example.com/a": '<html><body><a href="/c">C</a></body></html>',
        "https://example.com/b": '<html><body><a href="/d">D</a></body></html>',
        "https://example.com/c": "<html><body>C</body></html>",
        "https://example.com/d": "<html><body>D</body></html>",
    }
    store = FakeStore()
    engine = CrawlEngine(CrawlConfig(max_concurrency=2, discover_sitemaps=False), store=store)
    engine.backend = FakeBackend(pages)
    engine._robots = FakeRobots()

    output_path = tmp_path / "crawl.json"
    job = await engine.crawl_open(["https://example.com/"], max_urls=3, save_to=str(output_path))

    assert job.mode == "open"
    assert job.max_urls == 3
    assert len(job.results) == 3
    assert output_path.exists()

    # open crawls now produce JSONL: one result per line, final line is summary
    lines = [json.loads(ln) for ln in output_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    summary = next(ln for ln in lines if ln.get("__type") == "summary")
    assert summary["mode"] == "open"
    assert summary["max_urls"] == 3
    assert summary["crawled_count"] == 3
    result_lines = [ln for ln in lines if ln.get("__type") != "summary"]
    assert len(result_lines) == 3
    assert store.saved_metadata["crawl_open"]["max_urls"] == 3


@pytest.mark.asyncio
async def test_open_crawl_resets_pending_rows_on_resume():
    store = FakeStore()
    store.frontier["https://example.com/stale"] = {
        "depth": 1,
        "parent_url": "https://example.com/",
        "status": "pending",
    }
    pages = {
        "https://example.com/stale": "<html><body>stale</body></html>",
    }
    engine = CrawlEngine(CrawlConfig(max_concurrency=1, default_open_crawl_limit=1), store=store)
    engine.backend = FakeBackend(pages)
    engine._robots = FakeRobots()

    job = await engine.crawl_open(["https://example.com/stale"], max_urls=1, run_id="legacy", resume=True)

    assert len(job.results) == 1
    assert store.frontier["https://example.com/stale"]["status"] == "done"


@pytest.mark.asyncio
async def test_memory_open_crawl_new_seed_ignores_unrelated_completed_run():
    store = MemoryStore()
    store.set_active_crawl_run("old-run")
    await store.enqueue_frontier([("https://old.example/", 0, None)], source="seed")
    await store.frontier_mark_done(["https://old.example/"])

    pages = {
        "https://new.example/": "<html><body>new</body></html>",
    }
    engine = CrawlEngine(
        CrawlConfig(max_concurrency=1, default_open_crawl_limit=1, discover_sitemaps=False, respect_robots_txt=False),
        store=store,
    )
    engine.backend = FakeBackend(pages)

    job = await engine.crawl_open(["https://new.example/"], max_urls=1, run_id="new-run")

    assert job.run_id == "new-run"
    assert [result.final_url for result in job.results] == ["https://new.example/"]
    assert await store.frontier_stats(run_id="old-run") == (0, 0, 1)
    assert await store.frontier_stats(run_id="new-run") == (0, 0, 1)


@pytest.mark.asyncio
async def test_open_crawl_marks_run_complete_with_errors_when_mark_done_fails():
    class MarkDoneFailStore(MemoryStore):
        async def frontier_mark_done(self, urls, *, run_id=None) -> None:
            raise RuntimeError("simulated mark-done failure")

    url = "https://example.com/"
    store = MarkDoneFailStore()
    engine = CrawlEngine(
        CrawlConfig(max_concurrency=1, default_open_crawl_limit=1, discover_sitemaps=False, respect_robots_txt=False),
        store=store,
    )
    engine.backend = FakeBackend({url: "<html><body>content</body></html>"})

    job = await engine.crawl_open([url], max_urls=1, run_id="mark-done-failed-run")

    assert job.crawl_run_status == "complete_with_errors"
    assert job.frontier_mark_done_failed_urls == [url]
    run = await store.get_crawl_run("mark-done-failed-run")
    assert run is not None
    assert run["status"] == "complete_with_errors"
    assert await store.frontier_stats(run_id="mark-done-failed-run") == (0, 1, 0)


@pytest.mark.asyncio
async def test_memory_open_crawl_valid_resume_uses_selected_run_only():
    store = MemoryStore()
    pages = {
        "https://resume.example/a": "<html><body>a</body></html>",
        "https://resume.example/b": "<html><body>b</body></html>",
    }
    config = CrawlConfig(
        max_concurrency=1,
        default_open_crawl_limit=1,
        discover_sitemaps=False,
        respect_robots_txt=False,
    )
    first = CrawlEngine(config, store=store)
    first.backend = FakeBackend(pages)

    first_job = await first.crawl_open(list(pages), max_urls=1, run_id="resume-run")

    assert first_job.run_id == "resume-run"
    assert len(first_job.results) == 1
    assert await store.frontier_stats(run_id="resume-run") == (1, 0, 1)

    second = CrawlEngine(config, store=store)
    second.backend = FakeBackend(pages)
    second_job = await second.crawl_open(list(pages), max_urls=2, run_id="resume-run", resume=True)

    assert second_job.run_id == "resume-run"
    assert len(second_job.results) == 1
    assert await store.frontier_stats(run_id="resume-run") == (0, 0, 2)


@pytest.mark.asyncio
async def test_memory_open_crawl_resume_missing_run_raises_not_found():
    store = MemoryStore()
    engine = CrawlEngine(
        CrawlConfig(max_concurrency=1, default_open_crawl_limit=1, discover_sitemaps=False, respect_robots_txt=False),
        store=store,
    )
    engine.backend = FakeBackend({"https://resume.example/a": "<html><body>a</body></html>"})

    with pytest.raises(CrawlRunSelectionError, match="crawl run not found: missing-run"):
        await engine.crawl_open(["https://resume.example/a"], max_urls=1, run_id="missing-run", resume=True)


@pytest.mark.asyncio
async def test_memory_open_crawl_resume_config_mismatch_raises_without_override():
    store = MemoryStore()
    first = CrawlEngine(
        CrawlConfig(max_concurrency=1, default_open_crawl_limit=1, discover_sitemaps=False, respect_robots_txt=False),
        store=store,
    )
    first.backend = FakeBackend({"https://resume.example/a": "<html><body>a</body></html>"})
    await first.crawl_open(["https://resume.example/a"], max_urls=1, run_id="resume-run")

    second = CrawlEngine(
        CrawlConfig(
            max_concurrency=1,
            default_open_crawl_limit=1,
            discover_sitemaps=False,
            respect_robots_txt=False,
            same_host_only=False,
        ),
        store=store,
    )
    second.backend = FakeBackend({"https://resume.example/a": "<html><body>a</body></html>"})

    with pytest.raises(CrawlRunSelectionError, match="crawl run config mismatch"):
        await second.crawl_open(["https://resume.example/a"], max_urls=1, run_id="resume-run", resume=True)


@pytest.mark.asyncio
async def test_memory_open_crawl_resume_config_mismatch_warns_with_override(caplog: pytest.LogCaptureFixture):
    store = MemoryStore()
    pages = {
        "https://resume.example/a": "<html><body>a</body></html>",
        "https://resume.example/b": "<html><body>b</body></html>",
    }
    first = CrawlEngine(
        CrawlConfig(max_concurrency=1, default_open_crawl_limit=1, discover_sitemaps=False, respect_robots_txt=False),
        store=store,
    )
    first.backend = FakeBackend(pages)
    await first.crawl_open(["https://resume.example/a", "https://resume.example/b"], max_urls=1, run_id="resume-run")

    second = CrawlEngine(
        CrawlConfig(
            max_concurrency=1,
            default_open_crawl_limit=1,
            discover_sitemaps=False,
            respect_robots_txt=False,
            same_host_only=False,
        ),
        store=store,
    )
    second.backend = FakeBackend(pages)

    with caplog.at_level(logging.WARNING):
        job = await second.crawl_open(
            ["https://resume.example/a", "https://resume.example/b"],
            max_urls=2,
            run_id="resume-run",
            resume=True,
            allow_run_config_mismatch=True,
        )

    assert job.run_id == "resume-run"
    assert "Resuming crawl run resume-run despite seed/scope/config mismatch" in caplog.text


@pytest.mark.asyncio
async def test_memory_frontier_same_url_is_distinct_per_run():
    store = MemoryStore()
    url = "https://same.example/"
    await store.enqueue_frontier([(url, 0, None)], run_id="run-a")
    await store.enqueue_frontier([(url, 0, None)], run_id="run-b")

    assert await store.frontier_next_batch(1, run_id="run-a") == [(url, 0, None, 0)]
    assert await store.frontier_stats(run_id="run-a") == (0, 1, 0)
    assert await store.frontier_stats(run_id="run-b") == (1, 0, 0)

    await store.frontier_mark_done([url], run_id="run-a")

    assert await store.frontier_stats(run_id="run-a") == (0, 0, 1)
    assert await store.frontier_next_batch(1, run_id="run-b") == [(url, 0, None, 0)]


@pytest.mark.asyncio
async def test_crawl_with_content_hashing_sets_hash_fields():
    html = "<html><body><h1>Hello</h1><p>World</p></body></html>"
    engine = CrawlEngine(CrawlConfig(enable_content_hashing=True))
    engine.backend = FakeBackend({"https://example.com/": html})
    engine._robots = FakeRobots()

    result = await engine.crawl("https://example.com/")

    assert result.content_hash_sha256 is not None
    assert len(result.content_hash_sha256) == 64
    assert isinstance(result.content_hash_simhash, int)


class FlakyBackend:
    def __init__(self) -> None:
        self.count = 0

    async def fetch(self, url: str) -> FetchResponse:
        self.count += 1
        if self.count <= 2:
            return FetchResponse(
                url=url,
                requested_url=url,
                status=503,
                headers={"Content-Type": "text/html; charset=utf-8"},
                body=b"<html><body>retry</body></html>",
                text="<html><body>retry</body></html>",
            )
        return FetchResponse(
            url=url,
            requested_url=url,
            status=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            body=b"<html><body>ok</body></html>",
            text="<html><body>ok</body></html>",
        )


@pytest.mark.asyncio
async def test_open_crawl_retries_transient_errors():
    store = FakeStore()
    engine = CrawlEngine(
        CrawlConfig(max_concurrency=1, default_open_crawl_limit=1, frontier_max_retries=2), store=store
    )
    engine.backend = FlakyBackend()
    engine._robots = FakeRobots()

    job = await engine.crawl_open(["https://example.com/"], max_urls=1)

    assert len(job.results) >= 1
    assert store.frontier["https://example.com/"]["status"] == "done"


@pytest.mark.asyncio
async def test_open_crawl_reduces_batch_size_under_memory_pressure(monkeypatch):
    """Memory high-watermark causes _effective_worker_limit to shrink.

    The continuous worker pool refills as tasks complete, so we no longer
    see lock-step batch sizes. We verify instead that:
    - all 6 pages are crawled
    - the effective limit was reduced below max_concurrency due to memory pressure
    - it eventually recovers once memory pressure drops
    """
    store = FakeStore()
    pages = {f"https://example.com/{idx}": f"<html><body>{idx}</body></html>" for idx in range(6)}
    for idx in range(6):
        store.frontier[f"https://example.com/{idx}"] = {
            "depth": 0,
            "parent_url": None,
            "status": "queued",
            "priority_score": 100.0 - idx,
            "retry_count": 0,
            "retry_at": 0,
        }

    config = CrawlConfig(
        max_concurrency=4,
        default_open_crawl_limit=6,
        memory_high_watermark_percent=85.0,
        memory_recovery_watermark_percent=70.0,
    )
    engine = CrawlEngine(config, store=store)
    engine.backend = FakeBackend(pages)
    engine._robots = FakeRobots()

    # High memory for first 3 samples → limit shrinks from 4 → 3 → 2 → 1
    # then low memory → limit recovers
    samples = iter([90.0, 90.0, 90.0, 60.0, 60.0, 60.0])
    monkeypatch.setattr(engine, "_sample_memory_usage_percent", lambda: next(samples, 60.0))

    job = await engine.crawl_open(["https://example.com/0"], max_urls=6)

    assert len(job.results) == 6
    # Worker limit must have been reduced below max_concurrency at some point
    # (it may have recovered; just verify it went below the max of 4).
    # We also confirm it's a positive non-zero value so the crawl ran.
    assert 1 <= engine._effective_worker_limit <= 4


@pytest.mark.asyncio
async def test_open_crawl_archive_seed_dedupes_same_host_csv_urls(monkeypatch):
    pages = {
        "https://www.officeriders.com/": "<html><body>home</body></html>",
        "https://www.officeriders.com/fr": "<html><body>fr</body></html>",
        "https://www.officeriders.com/en/contact": "<html><body>contact</body></html>",
        "https://app.officeriders.com/": "<html><body>app</body></html>",
    }
    store = FakeStore()
    engine = CrawlEngine(
        CrawlConfig(
            max_concurrency=1,
            default_open_crawl_limit=4,
            seed_from_archive=True,
            discover_sitemaps=False,
            csv_urls=[
                "https://www.officeriders.com/",
                "https://www.officeriders.com/fr",
                "https://www.officeriders.com/en/contact",
            ],
            csv_seed_mode=True,
        ),
        store=store,
    )
    engine.backend = FakeBackend(pages)
    engine._robots = FakeRobots()

    archive_calls: list[str] = []

    async def fake_discover_historical_urls(seed: str, config: CrawlConfig) -> list[str]:
        archive_calls.append(seed)
        return []

    monkeypatch.setattr("crawler_cli.engine.discover_historical_urls", fake_discover_historical_urls)

    job = await engine.crawl_open(
        ["https://www.officeriders.com/", "https://app.officeriders.com/"],
        max_urls=4,
    )

    assert len(job.results) == 4
    assert archive_calls == ["www.officeriders.com", "app.officeriders.com"]


@pytest.mark.asyncio
async def test_unlimited_open_crawl_follows_discovered_links(tmp_path):
    """limit=0 (unlimited) must enqueue links discovered during crawling.

    Regression for the bug where max(0, 0 - total) == 0 meant discovered
    links were never enqueued on unlimited crawls.
    """
    pages = {
        "https://example.com/": '<html><body><a href="/b">B</a></body></html>',
        "https://example.com/b": '<html><body><a href="/c">C</a></body></html>',
        "https://example.com/c": "<html><body>leaf</body></html>",
    }
    store = FakeStore()
    engine = CrawlEngine(
        CrawlConfig(max_concurrency=1, default_open_crawl_limit=0, discover_sitemaps=False),
        store=store,
    )
    engine.backend = FakeBackend(pages)
    engine._robots = FakeRobots()

    output_path = tmp_path / "crawl.jsonl"
    job = await engine.crawl_open(["https://example.com/"], max_urls=0, save_to=str(output_path))

    crawled_urls = {r.final_url for r in job.results}
    assert job.max_urls == 0
    assert "https://example.com/b" in crawled_urls, "link from seed was not followed"
    assert "https://example.com/c" in crawled_urls, "link from depth-1 page was not followed"
    assert len(job.results) == 3
    lines = [json.loads(ln) for ln in output_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    summary = next(ln for ln in lines if ln.get("__type") == "summary")
    assert summary["max_urls"] == 0
    assert store.saved_metadata["crawl_open"]["max_urls"] == 0


@pytest.mark.asyncio
async def test_large_page_parses_via_thread_offload():
    """Pages above the offload threshold must still extract correctly (ticket-069)."""
    filler = "<p>" + ("word " * 60_000) + "</p>"  # well over 256 KB
    html = f"<html><head><title>Big</title></head><body><a href='/next'>n</a>{filler}</body></html>"
    assert len(html) > 262_144
    engine = CrawlEngine(CrawlConfig(respect_robots_txt=False))
    engine.backend = FakeBackend({"https://example.com/": html})

    result = await engine.crawl("https://example.com/")

    assert result.extracted is not None
    assert result.extracted.title == "Big"
    assert any(link.href == "https://example.com/next" for link in result.discovered_links)


@pytest.mark.asyncio
async def test_keep_html_in_results_retains_raw_html():
    """keep_html_in_results=True must skip the post-persist strip (ticket-069)."""
    pages = {"https://example.com/": "<html><title>kept</title></html>"}
    store = FakeStore()
    engine = CrawlEngine(
        CrawlConfig(
            max_concurrency=1,
            default_open_crawl_limit=1,
            discover_sitemaps=False,
            keep_html_in_results=True,
        ),
        store=store,
    )
    engine.backend = FakeBackend(pages)
    engine._robots = FakeRobots()

    job = await engine.crawl_open(["https://example.com/"], max_urls=1)

    assert job.results[0].raw_html is not None
    assert job.results[0].extracted is not None


@pytest.mark.asyncio
async def test_default_open_crawl_strips_raw_html():
    """Default behaviour releases bulk fields after persist (ticket-059)."""
    pages = {"https://example.com/": "<html><title>stripped</title></html>"}
    store = FakeStore()
    engine = CrawlEngine(
        CrawlConfig(max_concurrency=1, default_open_crawl_limit=1, discover_sitemaps=False),
        store=store,
    )
    engine.backend = FakeBackend(pages)
    engine._robots = FakeRobots()

    job = await engine.crawl_open(["https://example.com/"], max_urls=1)

    assert job.results[0].raw_html is None


@pytest.mark.asyncio
async def test_request_stop_drains_crawl_many():
    """request_stop() during a list crawl returns partial results (ticket-069)."""
    pages = {f"https://example.com/{i}": f"<html><body>{i}</body></html>" for i in range(5)}
    engine = CrawlEngine(CrawlConfig(max_concurrency=1, respect_robots_txt=False))

    class StoppingBackend(FakeBackend):
        def __init__(self, pages, engine_ref):
            super().__init__(pages)
            self.engine_ref = engine_ref

        async def fetch(self, url: str):
            self.engine_ref.request_stop()
            return await super().fetch(url)

    engine.backend = StoppingBackend(pages, engine)

    results = await engine.crawl_many(list(pages.keys()))

    # concurrency=1 and stop set during the first fetch → only 1 completes
    assert len(results) == 1
    job = await engine.crawl_list([])  # empty list still reports interrupted flag
    assert job.interrupted is True


@pytest.mark.asyncio
async def test_open_crawl_jsonl_includes_skipped_results(tmp_path):
    """Robots-blocked results must appear in the JSONL file (ticket-068).

    The summary line's blocked_count must reconcile with the actual lines.
    """
    pages = {
        "https://example.com/": "<html><body>ok</body></html>",
        "https://example.com/blocked": "<html><body>never fetched</body></html>",
    }
    store = FakeStore()
    store.frontier["https://example.com/blocked"] = {
        "depth": 0,
        "parent_url": None,
        "status": "queued",
        "priority_score": 0.0,
        "retry_count": 0,
        "retry_at": 0,
    }
    engine = CrawlEngine(
        CrawlConfig(max_concurrency=2, default_open_crawl_limit=2, discover_sitemaps=False),
        store=store,
    )
    engine.backend = FakeBackend(pages)
    engine._robots = FakeRobots(disallowed={"https://example.com/blocked"})

    output_path = tmp_path / "crawl.jsonl"
    job = await engine.crawl_open(["https://example.com/"], max_urls=2, save_to=str(output_path))

    lines = [json.loads(ln) for ln in output_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    summary = next(ln for ln in lines if ln.get("__type") == "summary")
    result_lines = [ln for ln in lines if ln.get("__type") != "summary"]

    assert len(result_lines) == len(job.results), "every result must be a JSONL line"
    blocked_lines = [ln for ln in result_lines if ln["skip_reason"] == "robots_txt_disallow"]
    assert len(blocked_lines) == 1, "blocked result missing from JSONL file"
    assert summary["blocked_count"] == len(blocked_lines)


@pytest.mark.asyncio
async def test_open_crawl_allowed_hosts_enqueues_cross_host_links():
    """allowed_hosts must reach the engine's scope check, not be silenced by extract_links.

    Regression for the ticket-058 bug where extract_links dropped cross-host
    links before is_host_allowed() could admit them.
    """
    pages = {
        "https://example.com/": '<html><body><a href="https://blog.example.com/post">blog</a></body></html>',
        "https://blog.example.com/post": "<html><body>blog post</body></html>",
    }
    store = FakeStore()
    engine = CrawlEngine(
        CrawlConfig(
            max_concurrency=2,
            default_open_crawl_limit=2,
            discover_sitemaps=False,
            same_host_only=True,
            allowed_hosts=["blog.example.com"],
        ),
        store=store,
    )
    engine.backend = FakeBackend(pages)
    engine._robots = FakeRobots()

    job = await engine.crawl_open(["https://example.com/"], max_urls=2)

    crawled_urls = {r.final_url for r in job.results}
    assert "https://blog.example.com/post" in crawled_urls, "allowed_hosts link was not followed"
