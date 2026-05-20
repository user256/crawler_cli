from __future__ import annotations

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
    async def is_allowed(self, url: str) -> bool:
        return True

    async def get_crawl_delay(self, url: str) -> float | None:
        return None

    async def sitemaps(self, url: str) -> list[str]:
        return []


class FakeStore:
    def __init__(self) -> None:
        self.frontier: dict[str, dict[str, object]] = {}

    async def persist(self, result) -> None:
        return None

    async def save_metadata(self, key: str, value: dict[str, object]) -> None:
        return None

    async def enqueue_frontier(self, frontier_data, *, source=None, source_detail=None) -> int:
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
            }
            inserted += 1
        return inserted

    async def frontier_reset_all_pending_to_queued(self) -> int:
        return 0

    async def frontier_next_batch(self, batch_size: int):
        batch = []
        for url, state in sorted(
            self.frontier.items(),
            key=lambda item: (-float(item[1].get("priority_score", 0.0)), item[0]),
        ):
            if state["status"] != "queued":
                continue
            state["status"] = "pending"
            batch.append((url, int(state["depth"]), state["parent_url"], int(state.get("retry_count", 0))))
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
            else:
                self.frontier[url] = {"depth": 0, "parent_url": None, "status": "done", "priority_score": 0.0}

    async def frontier_stats(self) -> tuple[int, int, int]:
        queued = sum(1 for s in self.frontier.values() if s["status"] == "queued")
        pending = sum(1 for s in self.frontier.values() if s["status"] == "pending")
        done = sum(1 for s in self.frontier.values() if s["status"] == "done")
        return queued, pending, done


class TrackingStore(FakeStore):
    def __init__(self) -> None:
        super().__init__()
        self.recorded: list[tuple[str, str, str | None]] = []

    async def record_source_by_url(self, url: str, source: str, detail: str | None = None) -> None:
        self.recorded.append((url, source, detail))


@pytest.mark.asyncio
async def test_path_restriction_skips_fetch_but_records_discovered_links():
    pages = {
        "https://example.com/blog/": '<html><body><a href="/blog/post-1">Post</a><a href="/about">About</a></body></html>',
        "https://example.com/blog/post-1": "<html><body>Post 1</body></html>",
    }
    store = TrackingStore()
    config = CrawlConfig(
        max_concurrency=2,
        default_open_crawl_limit=10,
        path_restriction="/blog/",
    )
    engine = CrawlEngine(config, store=store)
    engine.backend = FakeBackend(pages)
    engine._robots = FakeRobots()

    job = await engine.crawl_open(["https://example.com/blog/"], max_urls=5)

    fetched_urls = {result.final_url for result in job.results}
    assert "https://example.com/blog/" in fetched_urls
    assert "https://example.com/blog/post-1" in fetched_urls
    assert "https://example.com/about" not in fetched_urls

    recorded_urls = {item[0] for item in store.recorded}
    assert "https://example.com/about" in recorded_urls
    assert store.frontier["https://example.com/about"]["status"] == "done"


@pytest.mark.asyncio
async def test_path_exclude_prevents_fetch():
    pages = {
        "https://example.com/": '<html><body><a href="/news/item">News</a><a href="/ok">OK</a></body></html>',
        "https://example.com/ok": "<html><body>OK page</body></html>",
    }
    store = TrackingStore()
    config = CrawlConfig(
        max_concurrency=2,
        default_open_crawl_limit=10,
        path_exclude=["/news"],
    )
    engine = CrawlEngine(config, store=store)
    engine.backend = FakeBackend(pages)
    engine._robots = FakeRobots()

    job = await engine.crawl_open(["https://example.com/"], max_urls=5)

    fetched_urls = {result.final_url for result in job.results}
    assert "https://example.com/ok" in fetched_urls
    assert "https://example.com/news/item" not in fetched_urls
    assert store.frontier["https://example.com/news/item"]["status"] == "done"


def test_should_crawl_url_config_helpers():
    config = CrawlConfig(path_restriction="/blog/", path_exclude=["/admin"])
    assert config.should_crawl_url("https://example.com/blog/post")
    assert not config.should_crawl_url("https://example.com/about")
    assert not config.should_crawl_url("https://example.com/admin/settings")
    assert config.path_skip_detail("https://example.com/admin/x") == "path_exclude"
