"""Integration tests for AsyncpgStore against a real PostgreSQL database.

These tests are skipped when CRAWLER_CLI_TEST_DSN is not set.  In CI they
run against a postgres:16 service container.

Local usage:
    docker run -d -e POSTGRES_USER=crawler -e POSTGRES_PASSWORD=crawler \
        -e POSTGRES_DB=crawler_test -p 5432:5432 postgres:16
    CRAWLER_CLI_TEST_DSN=postgresql://crawler:crawler@localhost:5432/crawler_test \
        pytest tests/test_persistence_integration.py -v
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

from crawler_cli.models import CrawlResult
from crawler_cli.persistence import AsyncpgStore


_DSN = os.environ.get("CRAWLER_CLI_TEST_DSN", "")

pytestmark = pytest.mark.integration


@pytest.fixture
def dsn() -> str:
    if not _DSN:
        pytest.skip("CRAWLER_CLI_TEST_DSN not set")
    return _DSN


@pytest_asyncio.fixture
async def store(dsn: str) -> AsyncpgStore:
    s = AsyncpgStore(dsn)
    await s.initialize()
    yield s
    await s.truncate_crawl_tables()
    await s.close()


@pytest.mark.asyncio
async def test_initialize_is_idempotent(store: AsyncpgStore) -> None:
    """Running initialize() twice must not raise."""
    await store.initialize()
    await store.initialize()


@pytest.mark.asyncio
async def test_frontier_round_trip(store: AsyncpgStore) -> None:
    inserted = await store.enqueue_frontier(
        [("https://example.com/a", 0, None), ("https://example.com/b", 1, "https://example.com/a")],
        source="seed",
    )
    assert inserted == 2

    batch = await store.frontier_next_batch(10)
    assert len(batch) == 2
    urls = {item[0] for item in batch}
    assert "https://example.com/a" in urls
    assert "https://example.com/b" in urls

    await store.frontier_mark_done(["https://example.com/a", "https://example.com/b"])
    queued, pending, done = await store.frontier_stats()
    assert done == 2
    assert queued == 0
    assert pending == 0


@pytest.mark.asyncio
async def test_persist_crawl_result_basic(store: AsyncpgStore) -> None:
    result = CrawlResult(
        requested_url="https://example.com/",
        final_url="https://example.com/",
        status=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=None,
        raw_html="<html><title>Test</title></html>",
    )
    await store.persist(result)


@pytest.mark.asyncio
async def test_record_sources_bulk_deduplicates(store: AsyncpgStore) -> None:
    pairs = [
        ("https://example.com/p1", "sitemap_a.xml"),
        ("https://example.com/p2", "sitemap_a.xml"),
        ("https://example.com/p1", "sitemap_a.xml"),  # duplicate
    ]
    await store.record_sources_bulk(pairs, source="sitemap")
    urls = await store.urls_with_source("sitemap")
    assert "https://example.com/p1" in urls
    assert "https://example.com/p2" in urls


@pytest.mark.asyncio
async def test_truncate_only_touches_crawl_tables(store: AsyncpgStore) -> None:
    """truncate_crawl_tables must not drop tables that don't belong to it."""
    await store.enqueue_frontier([("https://example.com/", 0, None)], source="seed")
    await store.truncate_crawl_tables()
    queued, pending, done = await store.frontier_stats()
    assert queued == 0 and pending == 0 and done == 0
