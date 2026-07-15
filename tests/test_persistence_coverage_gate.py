"""Ticket 096: critical persistence/frontier/migration/failure-path coverage.

These tests require CRAWLER_CLI_TEST_DSN (same as test_persistence_integration.py).
They exercise branches that unit coverage alone cannot reach: schema migrations
from older shapes, redirect persistence, frontier retry/concurrency, transaction
rollback, compaction/purge safety, and report queries.
"""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

import asyncpg
import pytest
import pytest_asyncio

from crawler_cli.models import CrawlResult, ExtractedContent, RobotsDirectives
from crawler_cli.persistence import AsyncpgStore, CRAWL_TABLES, SCHEMA_STATEMENTS
from crawler_cli.reports import CrawlReports

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


def _extracted(title: str = "T") -> ExtractedContent:
    return ExtractedContent(
        title=title,
        meta_description="md",
        meta_robots=RobotsDirectives(raw=["index"]),
        x_robots_tag=RobotsDirectives(raw=[]),
        canonical=None,
        x_canonical=None,
        hreflang_links=[],
        html_lang="en",
        headings={"h1": [title], "h2": []},
        text="body",
        word_count=10,
        metadata={},
    )


def _page(
    requested: str,
    *,
    final: str | None = None,
    status: int = 200,
    extracted: ExtractedContent | None = None,
    raw_html: str | None = "<html><body>x</body></html>",
) -> CrawlResult:
    final_url = final or requested
    return CrawlResult(
        requested_url=requested,
        final_url=final_url,
        status=status,
        headers={"content-type": "text/html"},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=extracted,
        raw_html=raw_html,
        ttfb_seconds=0.05,
        total_duration_seconds=0.2,
    )


async def _drop_all_crawl_tables(dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        table_list = ", ".join(CRAWL_TABLES)
        await conn.execute(f"DROP TABLE IF EXISTS {table_list} CASCADE")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_initialize_migrates_pre_challenge_page_metadata(dsn: str) -> None:
    """Older page_metadata without challenge/skip_reason columns must migrate."""
    await _drop_all_crawl_tables(dsn)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(SCHEMA_STATEMENTS[0])  # urls
        await conn.execute(
            """
            CREATE TABLE page_metadata (
                url_id INTEGER PRIMARY KEY,
                initial_status_code INTEGER,
                final_status_code INTEGER,
                final_url_id INTEGER,
                fetched_at INTEGER,
                FOREIGN KEY (url_id) REFERENCES urls (id),
                FOREIGN KEY (final_url_id) REFERENCES urls (id)
            )
            """
        )
        url_id = await conn.fetchval(
            """
            INSERT INTO urls (url, kind, classification, first_seen, last_seen)
            VALUES ('https://old-meta.example/', 'html', 'internal', 1, 1)
            RETURNING id
            """
        )
        await conn.execute(
            """
            INSERT INTO page_metadata (url_id, initial_status_code, final_status_code, final_url_id, fetched_at)
            VALUES ($1, 200, 200, $1, 1)
            """,
            int(url_id),
        )
    finally:
        await conn.close()

    store = AsyncpgStore(dsn)
    await store.initialize()
    try:
        assert store.pool is not None
        async with store.pool.acquire() as c:
            cols = {
                r["column_name"]
                for r in await c.fetch(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'page_metadata'
                    """
                )
            }
        assert {"challenge", "skip_reason", "ttfb_seconds", "lcp_ms"} <= cols
        # Pre-existing row survives; challenge columns are nullable.
        await store.persist(
            _page(
                "https://old-meta.example/",
                extracted=None,
                raw_html=None,
                status=403,
            )
        )
        async with store.pool.acquire() as c:
            row = await c.fetchrow(
                """
                SELECT challenge, skip_reason, final_status_code
                FROM page_metadata pm
                JOIN urls u ON u.id = pm.url_id
                WHERE u.url = $1
                """,
                "https://old-meta.example/",
            )
        assert row is not None
        assert row["final_status_code"] == 403
    finally:
        await store.truncate_crawl_tables()
        await store.close()


@pytest.mark.asyncio
async def test_initialize_migrates_metadata_without_run_id(dsn: str) -> None:
    """crawl_metadata without run_id column gains run scoping (ticket 086)."""
    await _drop_all_crawl_tables(dsn)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            """
            CREATE TABLE crawl_metadata (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        await conn.execute(
            """
            INSERT INTO crawl_metadata (key, value_json, updated_at)
            VALUES ('seed', '{"urls":[]}', 1)
            """
        )
    finally:
        await conn.close()

    store = AsyncpgStore(dsn)
    await store.initialize()
    try:
        await store.create_crawl_run(
            "meta-run",
            seed_urls=["https://meta.example/"],
            config_hash="h",
            config={"seed_urls": ["https://meta.example/"]},
        )
        await store.save_metadata("progress", {"done": 1})
        record = await store.get_crawl_run("meta-run")
        assert record is not None
        assert record["status"] == "running"
        await store.update_crawl_run_status("meta-run", "completed")
        updated = await store.get_crawl_run("meta-run")
        assert updated is not None
        assert updated["status"] == "completed"

        assert store.pool is not None
        async with store.pool.acquire() as c:
            run_id = await c.fetchval(
                "SELECT run_id FROM crawl_metadata WHERE key = $1",
                "meta-run:progress",
            )
        assert run_id == "meta-run"
    finally:
        await store.truncate_crawl_tables()
        await store.close()


@pytest.mark.asyncio
async def test_persist_redirect_stores_content_on_final_url(store: AsyncpgStore) -> None:
    requested = "https://redir.example/from"
    final = "https://redir.example/to"
    await store.persist(_page(requested, final=final, extracted=_extracted("Landed"), status=200))

    assert store.pool is not None
    async with store.pool.acquire() as conn:
        requested_meta = await conn.fetchrow(
            """
            SELECT pm.final_status_code, dst.url AS final_url
            FROM page_metadata pm
            JOIN urls src ON src.id = pm.url_id
            JOIN urls dst ON dst.id = pm.final_url_id
            WHERE src.url = $1
            """,
            requested,
        )
        content_title = await conn.fetchval(
            "SELECT c.title FROM content c JOIN urls u ON u.id = c.url_id WHERE u.url = $1",
            final,
        )
        requested_content = await conn.fetchval(
            "SELECT COUNT(*) FROM content c JOIN urls u ON u.id = c.url_id WHERE u.url = $1",
            requested,
        )

    assert requested_meta is not None
    assert requested_meta["final_url"] == final
    assert content_title == "Landed"
    assert requested_content == 0

    chains = await CrawlReports(store).redirect_chains()
    assert any(r["requested_url"] == requested and r["final_url"] == final for r in chains)


@pytest.mark.asyncio
async def test_frontier_retry_defers_until_retry_at(store: AsyncpgStore) -> None:
    url = "https://retry.example/"
    await store.create_crawl_run("retry-run", seed_urls=[url], config_hash="r", config={"seed_urls": [url]})
    assert await store.enqueue_frontier([(url, 0, None)], run_id="retry-run") == 1
    claimed = await store.frontier_next_batch(1, run_id="retry-run")
    assert claimed == [(url, 0, None, 0)]

    await store.frontier_mark_retry(url, retry_count=2, delay_seconds=3600, run_id="retry-run")
    assert await store.frontier_next_batch(1, run_id="retry-run") == []
    assert await store.frontier_stats(run_id="retry-run") == (1, 0, 0)

    # Immediate retry (delay 0) becomes claimable again with updated retry_count.
    await store.frontier_mark_retry(url, retry_count=3, delay_seconds=0, run_id="retry-run")
    claimed_again = await store.frontier_next_batch(1, run_id="retry-run")
    assert claimed_again == [(url, 0, None, 3)]


@pytest.mark.asyncio
async def test_frontier_concurrent_claims_are_exclusive(store: AsyncpgStore) -> None:
    urls = [f"https://concurrent.example/{i}" for i in range(20)]
    await store.create_crawl_run(
        "concurrent-run",
        seed_urls=urls,
        config_hash="c",
        config={"seed_urls": urls},
    )
    await store.enqueue_frontier([(u, 0, None) for u in urls], run_id="concurrent-run")

    batches = await asyncio.gather(
        store.frontier_next_batch(5, run_id="concurrent-run"),
        store.frontier_next_batch(5, run_id="concurrent-run"),
        store.frontier_next_batch(5, run_id="concurrent-run"),
        store.frontier_next_batch(5, run_id="concurrent-run"),
    )
    claimed = [item[0] for batch in batches for item in batch]
    # SKIP LOCKED guarantees exclusivity; concurrent waves may under-fill a batch
    # when peers hold locks, so drain whatever remains.
    assert len(claimed) == len(set(claimed))
    assert len(claimed) >= 1
    while True:
        more = await store.frontier_next_batch(10, run_id="concurrent-run")
        if not more:
            break
        claimed.extend(item[0] for item in more)
    assert len(claimed) == len(set(claimed)) == 20
    assert await store.frontier_stats(run_id="concurrent-run") == (0, 20, 0)


@pytest.mark.asyncio
async def test_persist_transaction_rolls_back_on_mid_write_failure(
    store: AsyncpgStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure after page_metadata write must not leave partial content rows."""
    url = "https://rollback.example/"
    calls = {"n": 0}
    original = store._persist_directives

    async def boom(conn, url_id, result):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        raise RuntimeError("simulated mid-persist failure")

    monkeypatch.setattr(store, "_persist_directives", boom)

    with pytest.raises(RuntimeError, match="simulated mid-persist failure"):
        await store.persist(_page(url, extracted=_extracted("ShouldRollBack")))

    assert calls["n"] == 1
    assert store.pool is not None
    async with store.pool.acquire() as conn:
        meta = await conn.fetchval(
            "SELECT COUNT(*) FROM page_metadata pm JOIN urls u ON u.id = pm.url_id WHERE u.url = $1",
            url,
        )
        content = await conn.fetchval(
            "SELECT COUNT(*) FROM content c JOIN urls u ON u.id = c.url_id WHERE u.url = $1",
            url,
        )
        pages = await conn.fetchval(
            "SELECT COUNT(*) FROM pages p JOIN urls u ON u.id = p.url_id WHERE u.url = $1",
            url,
        )
    assert meta == 0
    assert content == 0
    assert pages == 0

    # Restore and confirm a clean persist still works after rollback.
    monkeypatch.setattr(store, "_persist_directives", original)
    await store.persist(_page(url, extracted=_extracted("After")))
    async with store.pool.acquire() as conn:
        title = await conn.fetchval(
            "SELECT c.title FROM content c JOIN urls u ON u.id = c.url_id WHERE u.url = $1",
            url,
        )
    assert title == "After"


@pytest.mark.asyncio
async def test_compact_purge_and_hash_backfill_safety(dsn: str) -> None:
    """Legacy uncompressed HTML can be compacted; purge clears blobs but keeps hashes."""
    # Dedicated store with compression off so the first persist writes a legacy
    # raw UTF-8 blob (format prefix absent) that compact must rewrite.
    store = AsyncpgStore(dsn, compress_html=False)
    await store.initialize()
    try:
        await store.truncate_crawl_tables()
        url = "https://compact.example/"
        await store.persist(_page(url, extracted=_extracted("Compact"), raw_html="<html>legacy</html>"))

        stats_before = await store.html_storage_stats()
        assert stats_before["pages_with_html"] >= 1
        assert stats_before["pages_legacy_uncompressed"] >= 1

        dry = await store.compact_html_storage(dry_run=True)
        assert dry["rows_updated"] >= 1
        # dry-run must not rewrite the legacy blob
        assert (await store.html_storage_stats())["pages_legacy_uncompressed"] >= 1

        compacted = await store.compact_html_storage(dry_run=False)
        assert compacted["rows_updated"] >= 1
        assert (await store.html_storage_stats())["pages_legacy_uncompressed"] == 0

        assert store.pool is not None
        async with store.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE content SET content_hash_sha256 = NULL, content_hash_simhash = NULL
                WHERE url_id = (SELECT id FROM urls WHERE url = $1)
                """,
                url,
            )
        backfilled = await store.backfill_content_hashes(dry_run=False)
        assert backfilled["rows_updated"] >= 1

        purged = await store.purge_stored_html(drop_headers=False, vacuum=False, dry_run=False)
        assert purged["pages_cleared"] >= 1
        async with store.pool.acquire() as conn:
            html = await conn.fetchval(
                "SELECT html_compressed FROM pages p JOIN urls u ON u.id = p.url_id WHERE u.url = $1",
                url,
            )
            sha = await conn.fetchval(
                "SELECT content_hash_sha256 FROM content c JOIN urls u ON u.id = c.url_id WHERE u.url = $1",
                url,
            )
            title = await conn.fetchval(
                "SELECT title FROM content c JOIN urls u ON u.id = c.url_id WHERE u.url = $1",
                url,
            )
        assert html is None
        assert sha is not None
        assert title == "Compact"

        counts = await store.table_row_counts()
        assert counts["urls"] >= 1
        assert counts["content"] >= 1
    finally:
        await store.truncate_crawl_tables()
        await store.close()


@pytest.mark.asyncio
async def test_reports_indexability_and_slowest_pages(store: AsyncpgStore) -> None:
    url = "https://reports.example/slow"
    await store.persist(
        _page(
            url,
            extracted=ExtractedContent(
                title="Slow",
                meta_description="md",
                meta_robots=RobotsDirectives(noindex=True, raw=["noindex"]),
                x_robots_tag=RobotsDirectives(raw=[]),
                canonical=None,
                x_canonical=None,
                hreflang_links=[],
                html_lang="en",
                headings={"h1": ["Slow"], "h2": []},
                text="body",
                word_count=10,
                metadata={},
            ),
        )
    )

    reports = CrawlReports(store)
    indexability = await reports.indexability_reasons()
    assert any(r["url"] == url and r["overall_indexable"] is False for r in indexability)

    slowest = await reports.slowest_pages(limit=10)
    assert any(r["url"] == url for r in slowest)

    payload = await reports.as_json()
    assert "redirect_chains" in payload
    assert "indexability" in payload


@pytest.mark.asyncio
async def test_create_crawl_run_rejects_duplicate(store: AsyncpgStore) -> None:
    await store.create_crawl_run(
        "dup-run",
        seed_urls=["https://dup.example/"],
        config_hash="a",
        config={"seed_urls": ["https://dup.example/"]},
    )
    with pytest.raises(ValueError, match="already exists"):
        await store.create_crawl_run(
            "dup-run",
            seed_urls=["https://dup.example/"],
            config_hash="b",
            config={"seed_urls": ["https://dup.example/"]},
        )


@pytest.mark.asyncio
async def test_drop_crawl_database_isolated_from_test_dsn(dsn: str) -> None:
    """drop_crawl_database only drops the named DB; recreate for subsequent tests."""
    parsed = urlparse(dsn)
    db_name = "crawler_cli_drop_probe"
    maintenance = f"{parsed.scheme}://{parsed.netloc}/postgres"
    # Preserve query (sslmode) if present on original DSN for admin connects.
    if parsed.query:
        maintenance = f"{maintenance}?{parsed.query}"

    admin = await asyncpg.connect(maintenance)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        await admin.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await admin.close()

    probe_dsn = f"{parsed.scheme}://{parsed.netloc}/{db_name}"
    if parsed.query:
        probe_dsn = f"{probe_dsn}?{parsed.query}"

    store = AsyncpgStore(probe_dsn)
    await store.initialize()
    await store.enqueue_frontier([("https://drop.example/", 0, None)])
    await store.drop_crawl_database(maintenance_dsn=maintenance)

    admin = await asyncpg.connect(maintenance)
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        assert exists is None
    finally:
        await admin.close()


@pytest.mark.asyncio
async def test_run_scoped_metadata_and_frontier_isolation(store: AsyncpgStore) -> None:
    url = "https://isolate.example/"
    await store.create_crawl_run("iso-a", seed_urls=[url], config_hash="a", config={"seed_urls": [url]})
    await store.save_metadata("checkpoint", {"n": 1})
    await store.enqueue_frontier([(url, 0, None)], run_id="iso-a")
    await store.frontier_mark_done([url], run_id="iso-a")

    await store.create_crawl_run("iso-b", seed_urls=[url], config_hash="b", config={"seed_urls": [url]})
    await store.save_metadata("checkpoint", {"n": 2})
    assert await store.enqueue_frontier([(url, 0, None)], run_id="iso-b") == 1

    assert await store.frontier_stats(run_id="iso-a") == (0, 0, 1)
    assert await store.frontier_stats(run_id="iso-b") == (1, 0, 0)

    assert store.pool is not None
    async with store.pool.acquire() as conn:
        keys = {
            r["key"]: r["run_id"]
            for r in await conn.fetch("SELECT key, run_id FROM crawl_metadata WHERE key LIKE '%checkpoint%'")
        }
    assert keys.get("iso-a:checkpoint") == "iso-a"
    assert keys.get("iso-b:checkpoint") == "iso-b"
