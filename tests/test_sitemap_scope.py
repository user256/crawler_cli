"""Ticket 087: sitemap host scope, frontier budget, and politeness controls."""

from __future__ import annotations

import asyncio

import pytest

from crawler_cli import CrawlConfig, CrawlEngine
from crawler_cli.models import FetchResponse


class TrackingBackend:
    """Backend that serves canned bodies and records every fetch URL."""

    def __init__(self, pages: dict[str, tuple[bytes, str]]) -> None:
        self.pages = pages
        self.fetched: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.per_host_in_flight: dict[str, int] = {}
        self.per_host_max: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def fetch(self, url: str) -> FetchResponse:
        from urllib.parse import urlparse

        host = urlparse(url).netloc.lower()
        async with self._lock:
            self.fetched.append(url)
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            self.per_host_in_flight[host] = self.per_host_in_flight.get(host, 0) + 1
            self.per_host_max[host] = max(self.per_host_max.get(host, 0), self.per_host_in_flight[host])
        try:
            await asyncio.sleep(0.005)
            if url not in self.pages:
                return FetchResponse(
                    url=url,
                    requested_url=url,
                    status=404,
                    headers={"Content-Type": "text/plain"},
                    body=b"missing",
                    text="missing",
                )
            body, content_type = self.pages[url]
            return FetchResponse(
                url=url,
                requested_url=url,
                status=200,
                headers={"Content-Type": content_type},
                body=body,
                text=body.decode("utf-8", errors="replace"),
            )
        finally:
            async with self._lock:
                self.in_flight -= 1
                self.per_host_in_flight[host] -= 1


class FakeRobots:
    def __init__(self, sitemaps: list[str] | None = None, crawl_delay: float | None = None) -> None:
        self._sitemaps = sitemaps or []
        self.crawl_delay = crawl_delay

    async def is_allowed(self, url: str) -> bool:
        return True

    async def get_crawl_delay(self, url: str) -> float | None:
        return self.crawl_delay

    async def sitemaps(self, url: str) -> list[str]:
        return list(self._sitemaps)


class TrackingStore:
    def __init__(self) -> None:
        self.frontier: dict[str, dict[str, object]] = {}
        self.recorded: list[tuple[str, str, str | None]] = []
        self.hreflang_pairs: list = []

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
                self.frontier[url] = {
                    "depth": 0,
                    "parent_url": None,
                    "status": "done",
                    "priority_score": 0.0,
                }

    async def frontier_stats(self) -> tuple[int, int, int]:
        queued = sum(1 for s in self.frontier.values() if s["status"] == "queued")
        pending = sum(1 for s in self.frontier.values() if s["status"] == "pending")
        done = sum(1 for s in self.frontier.values() if s["status"] == "done")
        return queued, pending, done

    async def record_source_by_url(self, url: str, source: str, detail: str | None = None) -> None:
        self.recorded.append((url, source, detail))

    async def record_sources_bulk(
        self,
        url_detail_pairs: list[tuple[str, str | None]],
        source: str,
    ) -> None:
        for url, detail in url_detail_pairs:
            self.recorded.append((url, source, detail))

    async def persist_sitemap_hreflang_bulk(self, page_hreflang_pairs: list) -> None:
        self.hreflang_pairs.extend(page_hreflang_pairs)


def _urlset(*locs: str, hreflang: list[tuple[str, str, str]] | None = None) -> bytes:
    """Build a minimal urlset. hreflang entries are (loc, hreflang, href)."""
    by_loc: dict[str, list[tuple[str, str]]] = {loc: [] for loc in locs}
    for loc, lang, href in hreflang or []:
        by_loc.setdefault(loc, []).append((lang, href))
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
        '        xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ]
    for loc, alts in by_loc.items():
        parts.append("  <url>")
        parts.append(f"    <loc>{loc}</loc>")
        for lang, href in alts:
            parts.append(f'    <xhtml:link rel="alternate" hreflang="{lang}" href="{href}" />')
        parts.append("  </url>")
    parts.append("</urlset>")
    return "\n".join(parts).encode("utf-8")


def _sitemap_index(*children: str) -> bytes:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for child in children:
        parts.append(f"  <sitemap><loc>{child}</loc></sitemap>")
    parts.append("</sitemapindex>")
    return "\n".join(parts).encode("utf-8")


@pytest.mark.asyncio
async def test_sitemap_rejects_external_page_urls_under_same_host():
    """Default same-host crawls must not fetch/enqueue offsite sitemap pages."""
    sitemap_body = _urlset(
        "https://good.example/",
        "https://good.example/about",
        "https://evil.example/private",
    )
    pages = {
        "https://good.example/sitemap.xml": (sitemap_body, "application/xml"),
        "https://good.example/": (b"<html><body>home</body></html>", "text/html; charset=utf-8"),
        "https://good.example/about": (b"<html><body>about</body></html>", "text/html; charset=utf-8"),
        "https://evil.example/private": (b"<html><body>secret</body></html>", "text/html; charset=utf-8"),
    }
    store = TrackingStore()
    backend = TrackingBackend(pages)
    engine = CrawlEngine(
        CrawlConfig(
            max_concurrency=2,
            default_open_crawl_limit=10,
            discover_sitemaps=True,
            same_host_only=True,
            respect_robots_txt=False,
        ),
        store=store,
    )
    engine.backend = backend
    engine._robots = FakeRobots(sitemaps=["https://good.example/sitemap.xml"])

    job = await engine.crawl_open(["https://good.example/"], max_urls=10)

    crawled = {r.final_url for r in job.results if r.skip_reason is None}
    assert "https://evil.example/private" not in crawled
    assert "https://evil.example/private" not in backend.fetched
    assert "https://evil.example/private" not in store.frontier
    assert any(
        url == "https://evil.example/private" and detail == "host_out_of_scope"
        for url, _source, detail in store.recorded
    )


@pytest.mark.asyncio
async def test_sitemap_allowed_hosts_admits_cross_host_entries():
    sitemap_body = _urlset(
        "https://example.com/",
        "https://blog.example.com/post",
    )
    pages = {
        "https://example.com/sitemap.xml": (sitemap_body, "application/xml"),
        "https://example.com/": (b"<html><body>home</body></html>", "text/html; charset=utf-8"),
        "https://blog.example.com/post": (b"<html><body>post</body></html>", "text/html; charset=utf-8"),
    }
    store = TrackingStore()
    backend = TrackingBackend(pages)
    engine = CrawlEngine(
        CrawlConfig(
            max_concurrency=2,
            default_open_crawl_limit=5,
            discover_sitemaps=True,
            same_host_only=True,
            allowed_hosts=["blog.example.com"],
            respect_robots_txt=False,
        ),
        store=store,
    )
    engine.backend = backend
    engine._robots = FakeRobots(sitemaps=["https://example.com/sitemap.xml"])

    job = await engine.crawl_open(["https://example.com/"], max_urls=5)

    crawled = {r.final_url for r in job.results if r.skip_reason is None}
    assert "https://blog.example.com/post" in crawled


@pytest.mark.asyncio
async def test_sitemap_rejects_external_child_indexes():
    index_body = _sitemap_index(
        "https://good.example/sitemap-a.xml",
        "https://evil.example/sitemap-b.xml",
    )
    pages = {
        "https://good.example/sitemap.xml": (index_body, "application/xml"),
        "https://good.example/sitemap-a.xml": (
            _urlset("https://good.example/a"),
            "application/xml",
        ),
        "https://evil.example/sitemap-b.xml": (
            _urlset("https://evil.example/b"),
            "application/xml",
        ),
        "https://good.example/": (b"<html><body>home</body></html>", "text/html; charset=utf-8"),
        "https://good.example/a": (b"<html><body>a</body></html>", "text/html; charset=utf-8"),
        "https://evil.example/b": (b"<html><body>b</body></html>", "text/html; charset=utf-8"),
    }
    store = TrackingStore()
    backend = TrackingBackend(pages)
    engine = CrawlEngine(
        CrawlConfig(
            max_concurrency=2,
            default_open_crawl_limit=10,
            discover_sitemaps=True,
            same_host_only=True,
            respect_robots_txt=False,
        ),
        store=store,
    )
    engine.backend = backend
    engine._robots = FakeRobots(sitemaps=["https://good.example/sitemap.xml"])

    await engine.crawl_open(["https://good.example/"], max_urls=10)

    assert "https://evil.example/sitemap-b.xml" not in backend.fetched
    assert "https://evil.example/b" not in backend.fetched
    assert any(
        url == "https://evil.example/sitemap-b.xml" and detail == "host_out_of_scope"
        for url, _source, detail in store.recorded
    )


@pytest.mark.asyncio
async def test_sitemap_rejects_unsupported_scheme_and_credentials():
    sitemap_body = _urlset(
        "https://example.com/ok",
        "ftp://example.com/file",
        "https://user:pass@example.com/secret",
    )
    pages = {
        "https://example.com/sitemap.xml": (sitemap_body, "application/xml"),
        "https://example.com/": (b"<html><body>home</body></html>", "text/html; charset=utf-8"),
        "https://example.com/ok": (b"<html><body>ok</body></html>", "text/html; charset=utf-8"),
        "https://user:pass@example.com/secret": (
            b"<html><body>secret</body></html>",
            "text/html; charset=utf-8",
        ),
    }
    store = TrackingStore()
    backend = TrackingBackend(pages)
    engine = CrawlEngine(
        CrawlConfig(
            max_concurrency=2,
            default_open_crawl_limit=10,
            discover_sitemaps=True,
            respect_robots_txt=False,
        ),
        store=store,
    )
    engine.backend = backend
    engine._robots = FakeRobots(sitemaps=["https://example.com/sitemap.xml"])

    await engine.crawl_open(["https://example.com/"], max_urls=10)

    assert "ftp://example.com/file" not in backend.fetched
    assert "https://user:pass@example.com/secret" not in backend.fetched
    details = {url: detail for url, _source, detail in store.recorded}
    assert details.get("ftp://example.com/file") == "unsupported_scheme"
    assert details.get("https://user:pass@example.com/secret") == "credential_url"


@pytest.mark.asyncio
async def test_sitemap_enqueue_respects_small_max_pages_budget():
    """Sitemap ingestion must not insert thousands of unconsumable frontier rows."""
    locs = [f"https://example.com/p{i}" for i in range(200)]
    sitemap_body = _urlset(*locs)
    pages: dict[str, tuple[bytes, str]] = {
        "https://example.com/sitemap.xml": (sitemap_body, "application/xml"),
        "https://example.com/": (b"<html><body>home</body></html>", "text/html; charset=utf-8"),
    }
    for loc in locs:
        pages[loc] = (b"<html><body>p</body></html>", "text/html; charset=utf-8")

    store = TrackingStore()
    backend = TrackingBackend(pages)
    engine = CrawlEngine(
        CrawlConfig(
            max_concurrency=2,
            default_open_crawl_limit=10,
            discover_sitemaps=True,
            respect_robots_txt=False,
        ),
        store=store,
    )
    engine.backend = backend
    engine._robots = FakeRobots(sitemaps=["https://example.com/sitemap.xml"])

    job = await engine.crawl_open(["https://example.com/"], max_urls=10)

    assert len(job.results) <= 10
    # Rejected-but-not-enqueued sitemap URLs must not inflate the frontier.
    assert len(store.frontier) <= 10


@pytest.mark.asyncio
async def test_sitemap_duplicate_locs_do_not_consume_frontier_budget():
    """Repeated locs leave the finite sitemap budget for distinct pages."""
    sitemap_body = b"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">
  <url><loc>https://example.com/duplicate</loc></url>
  <url><loc>https://example.com/duplicate</loc></url>
  <url><loc>https://example.com/distinct-a</loc></url>
  <url><loc>https://example.com/distinct-b</loc></url>
</urlset>"""
    page_urls = {
        "https://example.com/",
        "https://example.com/duplicate",
        "https://example.com/distinct-a",
        "https://example.com/distinct-b",
    }
    pages = {
        "https://example.com/sitemap.xml": (sitemap_body, "application/xml"),
        **{url: (b"<html><body>page</body></html>", "text/html; charset=utf-8") for url in page_urls},
    }
    store = TrackingStore()
    backend = TrackingBackend(pages)
    engine = CrawlEngine(
        CrawlConfig(
            max_concurrency=2,
            default_open_crawl_limit=4,
            discover_sitemaps=True,
            respect_robots_txt=False,
        ),
        store=store,
    )
    engine.backend = backend
    engine._robots = FakeRobots(sitemaps=["https://example.com/sitemap.xml"])

    job = await engine.crawl_open(["https://example.com/"], max_urls=4)

    assert len(job.results) == 4
    assert page_urls <= set(store.frontier)


@pytest.mark.asyncio
async def test_sitemap_fetches_respect_per_host_concurrency():
    """Sitemap shard fetches must share per-host concurrency with page fetches."""
    children = [f"https://example.com/sitemap-{i}.xml" for i in range(6)]
    index_body = _sitemap_index(*children)
    pages: dict[str, tuple[bytes, str]] = {
        "https://example.com/sitemap.xml": (index_body, "application/xml"),
        "https://example.com/": (b"<html><body>home</body></html>", "text/html; charset=utf-8"),
    }
    for i, child in enumerate(children):
        loc = f"https://example.com/page-{i}"
        pages[child] = (_urlset(loc), "application/xml")
        pages[loc] = (b"<html><body>p</body></html>", "text/html; charset=utf-8")

    store = TrackingStore()
    backend = TrackingBackend(pages)
    engine = CrawlEngine(
        CrawlConfig(
            max_concurrency=4,
            per_host_concurrency=1,
            default_open_crawl_limit=20,
            discover_sitemaps=True,
            respect_robots_txt=False,
        ),
        store=store,
    )
    engine.backend = backend
    engine._robots = FakeRobots(sitemaps=["https://example.com/sitemap.xml"])

    await engine.crawl_open(["https://example.com/"], max_urls=20)

    assert backend.per_host_max.get("example.com", 0) <= 1
    assert any(url.endswith(".xml") for url in backend.fetched)


@pytest.mark.asyncio
async def test_sitemap_hreflang_targets_respect_host_scope():
    sitemap_body = _urlset(
        "https://example.com/",
        hreflang=[
            ("https://example.com/", "en", "https://example.com/"),
            ("https://example.com/", "fr", "https://evil.example/fr/"),
        ],
    )
    pages = {
        "https://example.com/sitemap.xml": (sitemap_body, "application/xml"),
        "https://example.com/": (b"<html><body>home</body></html>", "text/html; charset=utf-8"),
    }
    store = TrackingStore()
    backend = TrackingBackend(pages)
    engine = CrawlEngine(
        CrawlConfig(
            max_concurrency=1,
            default_open_crawl_limit=5,
            discover_sitemaps=True,
            same_host_only=True,
            respect_robots_txt=False,
        ),
        store=store,
    )
    engine.backend = backend
    engine._robots = FakeRobots(sitemaps=["https://example.com/sitemap.xml"])

    await engine.crawl_open(["https://example.com/"], max_urls=5)

    assert "https://evil.example/fr/" not in backend.fetched
    assert any(
        url == "https://evil.example/fr/" and detail == "host_out_of_scope" for url, _source, detail in store.recorded
    )
    # In-scope alternate retained for persistence; offsite alternate dropped.
    assert store.hreflang_pairs
    persisted_hrefs = {hl.href for _loc, links in store.hreflang_pairs for hl in links}
    assert "https://example.com/" in persisted_hrefs
    assert "https://evil.example/fr/" not in persisted_hrefs
