from __future__ import annotations

import json

import pytest

from crawler_cli import CrawlConfig, CrawlEngine
from crawler_cli.models import FetchResponse


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
async def test_open_crawl_is_bounded_and_saves_output(tmp_path):
    pages = {
        "https://example.com/": '<html><body><a href="/a">A</a><a href="/b">B</a></body></html>',
        "https://example.com/a": '<html><body><a href="/c">C</a></body></html>',
        "https://example.com/b": '<html><body><a href="/d">D</a></body></html>',
        "https://example.com/c": "<html><body>C</body></html>",
        "https://example.com/d": "<html><body>D</body></html>",
    }
    store = FakeStore()
    engine = CrawlEngine(CrawlConfig(max_concurrency=2, default_open_crawl_limit=3), store=store)
    engine.backend = FakeBackend(pages)
    engine._robots = FakeRobots()

    output_path = tmp_path / "crawl.json"
    job = await engine.crawl_open(["https://example.com/"], save_to=str(output_path))

    assert job.mode == "open"
    assert len(job.results) == 3
    assert output_path.exists()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "open"
    assert payload["crawled_count"] == 3
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

    job = await engine.crawl_open(["https://example.com/stale"], max_urls=1)

    assert len(job.results) == 1
    assert store.frontier["https://example.com/stale"]["status"] == "done"


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
    engine = CrawlEngine(CrawlConfig(max_concurrency=1, default_open_crawl_limit=1, frontier_max_retries=2), store=store)
    engine.backend = FlakyBackend()
    engine._robots = FakeRobots()

    job = await engine.crawl_open(["https://example.com/"], max_urls=1)

    assert len(job.results) >= 1
    assert store.frontier["https://example.com/"]["status"] == "done"
