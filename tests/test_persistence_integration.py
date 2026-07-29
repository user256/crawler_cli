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

import csv
import json
import os
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from crawler_cli.detection.analytics import AnalyticsDetectionResult, AnalyticsHit
from crawler_cli.hashing import sha256_hash, simhash64
from crawler_cli.models import DiscoveredLink, ExtractedContent, HreflangLink, RobotsDirectives
from crawler_cli.models import CrawlResult, FetchResponse
from crawler_cli import CrawlConfig, CrawlEngine
from crawler_cli.intent_overlap import compute_exclusion
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


async def _drop_all_crawl_tables(dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f"DROP TABLE IF EXISTS {', '.join(CRAWL_TABLES)} CASCADE")
    finally:
        await conn.close()


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


@pytest.mark.asyncio
async def test_initialize_is_idempotent(store: AsyncpgStore) -> None:
    """Running initialize() twice must not raise."""
    await store.initialize()
    await store.initialize()


@pytest.mark.asyncio
async def test_initialize_does_not_add_legacy_run_to_run_scoped_database(store: AsyncpgStore) -> None:
    """A later crawl setup must not mirror the first real run into ``legacy``."""
    url = "https://run-scoped.example/"
    result = CrawlResult(
        requested_url=url,
        final_url=url,
        status=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        fetch_backend="test",
        extracted=None,
        raw_html="<html><body>first run</body></html>",
    )
    await store.create_crawl_run("real-run-one", seed_urls=[url], config_hash="one", config={})
    await store.persist(result)

    # This is what a second CLI/GUI crawl does before it creates its own run.
    await store.initialize()
    assert await store.resolve_reporting_run_id() == "real-run-one"

    await store.create_crawl_run("real-run-two", seed_urls=[url], config_hash="two", config={})
    await store.persist(result)
    await store.initialize()

    assert store.pool is not None
    async with store.pool.acquire() as conn:
        runs = await conn.fetch("SELECT run_id FROM crawl_runs ORDER BY run_id")
        legacy_snapshots = await conn.fetchval("SELECT COUNT(*) FROM page_run_snapshots WHERE run_id = 'legacy'")
    assert [row["run_id"] for row in runs] == ["real-run-one", "real-run-two"]
    assert legacy_snapshots == 0


@pytest.mark.asyncio
async def test_initialize_backfills_a_pre_snapshot_database_once(dsn: str) -> None:
    """A genuine pre-095 current-state database still receives its legacy run."""
    await _drop_all_crawl_tables(dsn)
    source = AsyncpgStore(dsn)
    await source.initialize()
    url = "https://pre-snapshot.example/"
    await source.create_crawl_run("temporary-run", seed_urls=[url], config_hash="old", config={})
    await source.persist(
        CrawlResult(
            requested_url=url,
            final_url=url,
            status=200,
            headers={"content-type": "text/html"},
            content_type="text/html",
            fetch_backend="test",
            # A pre-095 current-state database contained extracted page rows;
            # use one so this fixture exercises the legacy snapshot query
            # rather than only a metadata-only fetch.
            extracted=ExtractedContent(
                title="Pre-snapshot state",
                meta_description=None,
                meta_robots=RobotsDirectives(),
                x_robots_tag=RobotsDirectives(),
                canonical=None,
                x_canonical=None,
                hreflang_links=[],
                html_lang="en",
                headings={"h1": ["Pre-snapshot state"], "h2": []},
                text="pre-snapshot state",
                word_count=2,
                metadata={},
            ),
            raw_html="<html><body>pre-snapshot state</body></html>",
        )
    )
    assert source.pool is not None
    async with source.pool.acquire() as conn:
        # Keep the old mutable tables but remove all run-aware structures, as
        # they would be on a database created before ticket 095.
        await conn.execute("TRUNCATE TABLE crawl_runs CASCADE")
        await conn.execute("DROP TABLE page_run_snapshots")
    await source.close()

    upgraded = AsyncpgStore(dsn)
    await upgraded.initialize()
    try:
        assert await upgraded.resolve_reporting_run_id() == "legacy"
        assert upgraded.pool is not None
        async with upgraded.pool.acquire() as conn:
            first_count = await conn.fetchval("SELECT COUNT(*) FROM page_run_snapshots WHERE run_id = 'legacy'")
        await upgraded.initialize()
        async with upgraded.pool.acquire() as conn:
            second_count = await conn.fetchval("SELECT COUNT(*) FROM page_run_snapshots WHERE run_id = 'legacy'")
        assert first_count == 1
        assert second_count == first_count
    finally:
        await upgraded.truncate_crawl_tables()
        await upgraded.close()


@pytest.mark.asyncio
async def test_initialize_migrates_legacy_frontier_to_run_scoped_unique(dsn: str) -> None:
    legacy_url = "https://legacy.example/"
    conn = await asyncpg.connect(dsn)
    try:
        table_list = ", ".join(CRAWL_TABLES)
        await conn.execute(f"DROP TABLE IF EXISTS {table_list} CASCADE")
        await conn.execute(SCHEMA_STATEMENTS[0])
        url_id = await conn.fetchval(
            """
            INSERT INTO urls (url, kind, classification, first_seen, last_seen)
            VALUES ($1, 'html', 'internal', 1, 1)
            RETURNING id
            """,
            legacy_url,
        )
        await conn.execute(
            """
            CREATE TABLE frontier (
                id SERIAL PRIMARY KEY,
                url_id INTEGER NOT NULL UNIQUE REFERENCES urls(id),
                depth INTEGER NOT NULL,
                parent_id INTEGER REFERENCES urls(id),
                status TEXT NOT NULL CHECK (status IN ('queued','pending','done')),
                enqueued_at INTEGER,
                updated_at INTEGER,
                priority_score DOUBLE PRECISION DEFAULT 0.0,
                sitemap_priority DOUBLE PRECISION DEFAULT 0.5,
                inlinks_count INTEGER DEFAULT 0,
                content_type_score DOUBLE PRECISION DEFAULT 1.0,
                reset_count INTEGER DEFAULT 0,
                retry_count INTEGER DEFAULT 0,
                retry_at INTEGER DEFAULT 0
            )
            """
        )
        await conn.execute(
            """
            INSERT INTO frontier (url_id, depth, status, enqueued_at, updated_at)
            VALUES ($1, 0, 'done', 1, 1)
            """,
            int(url_id),
        )
    finally:
        await conn.close()

    store = AsyncpgStore(dsn)
    await store.initialize()
    try:
        assert await store.frontier_stats(run_id="legacy") == (0, 0, 1)
        await store.create_crawl_run(
            "pg-post-migration-run",
            seed_urls=[legacy_url],
            config_hash="post-migration",
            config={"seed_urls": [legacy_url]},
        )
        assert await store.enqueue_frontier([(legacy_url, 0, None)], run_id="pg-post-migration-run") == 1
        assert await store.frontier_stats(run_id="legacy") == (0, 0, 1)
        assert await store.frontier_stats(run_id="pg-post-migration-run") == (1, 0, 0)
    finally:
        await store.truncate_crawl_tables()
        await store.close()


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
async def test_frontier_run_scope_allows_unrelated_new_seed(store: AsyncpgStore) -> None:
    await store.create_crawl_run(
        "pg-old-run",
        seed_urls=["https://old.example/"],
        config_hash="old",
        config={"seed_urls": ["https://old.example/"]},
    )
    await store.enqueue_frontier([("https://old.example/", 0, None)], run_id="pg-old-run")
    await store.frontier_mark_done(["https://old.example/"], run_id="pg-old-run")

    engine = CrawlEngine(
        CrawlConfig(max_concurrency=1, default_open_crawl_limit=1, discover_sitemaps=False, respect_robots_txt=False),
        store=store,
    )
    engine.backend = FakeBackend({"https://new.example/": "<html><body>new</body></html>"})
    job = await engine.crawl_open(["https://new.example/"], max_urls=1, run_id="pg-new-run")

    assert job.run_id == "pg-new-run"
    assert [result.final_url for result in job.results] == ["https://new.example/"]
    assert await store.frontier_stats(run_id="pg-old-run") == (0, 0, 1)
    assert await store.frontier_stats(run_id="pg-new-run") == (0, 0, 1)


@pytest.mark.asyncio
async def test_open_crawl_postgres_valid_resume_selected_run(store: AsyncpgStore) -> None:
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

    first_job = await first.crawl_open(list(pages), max_urls=1, run_id="pg-resume-run")

    assert first_job.run_id == "pg-resume-run"
    assert len(first_job.results) == 1
    assert await store.frontier_stats(run_id="pg-resume-run") == (1, 0, 1)

    second = CrawlEngine(config, store=store)
    second.backend = FakeBackend(pages)
    second_job = await second.crawl_open(list(pages), max_urls=2, run_id="pg-resume-run", resume=True)

    assert second_job.run_id == "pg-resume-run"
    assert len(second_job.results) == 1
    assert await store.frontier_stats(run_id="pg-resume-run") == (0, 0, 2)


@pytest.mark.asyncio
async def test_frontier_same_url_can_be_claimed_in_distinct_runs(store: AsyncpgStore) -> None:
    url = "https://same.example/"
    await store.create_crawl_run("pg-run-a", seed_urls=[url], config_hash="a", config={"seed_urls": [url]})
    await store.create_crawl_run("pg-run-b", seed_urls=[url], config_hash="b", config={"seed_urls": [url]})
    assert await store.enqueue_frontier([(url, 0, None)], run_id="pg-run-a") == 1
    assert await store.enqueue_frontier([(url, 0, None)], run_id="pg-run-b") == 1

    assert await store.frontier_next_batch(1, run_id="pg-run-a") == [(url, 0, None, 0)]
    assert await store.frontier_stats(run_id="pg-run-a") == (0, 1, 0)
    assert await store.frontier_stats(run_id="pg-run-b") == (1, 0, 0)

    await store.frontier_reset_all_pending_to_queued(run_id="pg-run-a")

    assert await store.frontier_stats(run_id="pg-run-a") == (1, 0, 0)
    assert await store.frontier_next_batch(1, run_id="pg-run-b") == [(url, 0, None, 0)]
    assert await store.frontier_stats(run_id="pg-run-a") == (1, 0, 0)
    assert await store.frontier_stats(run_id="pg-run-b") == (0, 1, 0)


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
async def test_web_vitals_round_trip(store: AsyncpgStore) -> None:
    """CWV columns persist and read back via the worst_cwv_pages report (ticket 046)."""
    from crawler_cli.reports import CrawlReports

    result = CrawlResult(
        requested_url="https://example.com/slow",
        final_url="https://example.com/slow",
        status=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        fetch_backend="playwright",
        extracted=None,
        raw_html="<html></html>",
        lcp_ms=2500.0,
        cls=0.12,
        inp_ms=190.0,
    )
    await store.persist(result)

    rows = await CrawlReports(store).worst_cwv_pages(limit=10)
    by_url = {r["url"]: r for r in rows}
    assert "https://example.com/slow" in by_url
    assert by_url["https://example.com/slow"]["lcp_ms"] == 2500.0
    assert by_url["https://example.com/slow"]["cls"] == 0.12
    assert by_url["https://example.com/slow"]["inp_ms"] == 190.0


@pytest.mark.asyncio
async def test_intent_signature_backfill_round_trip(store: AsyncpgStore) -> None:
    """backfill_intent_signatures persists signatures and re-runs write zero (ticket 076)."""
    from crawler_cli.intent_signature import backfill_intent_signatures

    body = "<article><p>" + ("Real widget content here. " * 40) + "</p></article>"
    result = CrawlResult(
        requested_url="https://sig.example/a",
        final_url="https://sig.example/a",
        status=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=ExtractedContent(
            title="Alpha Widgets | Sig Example",
            meta_description="Best widgets around",
            meta_robots=RobotsDirectives(),
            x_robots_tag=RobotsDirectives(),
            canonical=None,
            x_canonical=None,
            hreflang_links=[],
            html_lang="en",
            headings={"h1": ["Alpha Widgets"], "h2": []},
            text="Alpha Widgets body",
            word_count=200,
            metadata={},
        ),
        raw_html=f"<html><head><title>Alpha Widgets | Sig Example</title></head><body>{body}</body></html>",
    )
    await store.persist(result)

    first = await backfill_intent_signatures(store)
    assert first.processed == 1
    assert first.updated == 1

    hashes = await store.existing_signature_hashes()
    assert len(hashes) == 1

    # Re-run on unchanged crawl rewrites zero hashes (ticket-114 zero-re-embed).
    second = await backfill_intent_signatures(store)
    assert second.updated == 0
    assert second.unchanged == 1


@pytest.mark.asyncio
async def test_signature_embedding_hash_gating_round_trip(store: AsyncpgStore) -> None:
    """Local signature embedding gates on signature_hash+model via the real DB join (ticket 077)."""
    from crawler_cli.intent_signature import backfill_intent_signatures
    from crawler_cli.embeddings import generate_signature_embeddings_for_store

    body = "<article><p>" + ("Widget review copy here. " * 40) + "</p></article>"
    result = CrawlResult(
        requested_url="https://emb.example/a",
        final_url="https://emb.example/a",
        status=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=ExtractedContent(
            title="Widgets",
            meta_description="md",
            meta_robots=RobotsDirectives(),
            x_robots_tag=RobotsDirectives(),
            canonical=None,
            x_canonical=None,
            hreflang_links=[],
            html_lang="en",
            headings={"h1": ["Widgets"], "h2": []},
            text="body",
            word_count=200,
            metadata={},
        ),
        raw_html=f"<html><head><title>Widgets</title></head><body>{body}</body></html>",
    )
    await store.persist(result)
    await backfill_intent_signatures(store)

    def fake_encoder(texts):
        return [[1.0, 0.0, 0.0] for _ in texts]

    first = await generate_signature_embeddings_for_store(store, model="local-test", encoder=fake_encoder)
    assert first.processed == 1

    # Vector stored with signature_hash + dim.
    assert await store.embedding_models() == ["local-test"]

    # Unchanged crawl -> zero re-embeds (hash gating through the DB join).
    second = await generate_signature_embeddings_for_store(store, model="local-test", encoder=fake_encoder)
    assert second.processed == 0
    assert second.skipped == 1


@pytest.mark.asyncio
async def test_hreflang_identity_round_trip(store: AsyncpgStore) -> None:
    """build_and_store_identity groups crawler-captured hreflang edges (ticket 078)."""
    from crawler_cli.hreflang_groups import build_and_store_identity

    def _page(url: str, alt: str, alt_code: str, lang: str) -> CrawlResult:
        return CrawlResult(
            requested_url=url,
            final_url=url,
            status=200,
            headers={"content-type": "text/html"},
            content_type="text/html",
            fetch_backend="aiohttp",
            extracted=ExtractedContent(
                title="t",
                meta_description="m",
                meta_robots=RobotsDirectives(),
                x_robots_tag=RobotsDirectives(),
                canonical=None,
                x_canonical=None,
                hreflang_links=[HreflangLink(hreflang=alt_code, href=alt, source="html_head")],
                html_lang=lang,
                headings={"h1": ["h"], "h2": []},
                text="body",
                word_count=120,
                metadata={},
            ),
            raw_html="<html></html>",
        )

    await store.persist(_page("https://hf.example/en", "https://hf.example/fr", "fr", "en"))
    await store.persist(_page("https://hf.example/fr", "https://hf.example/en", "en", "fr"))

    result = await build_and_store_identity(store)
    assert result.groups == 1
    summary = await store.hreflang_group_summary()
    assert summary["groups"] == 1
    assert summary["grouped_urls"] >= 2


@pytest.mark.asyncio
async def test_full_intent_overlap_pipeline(store: AsyncpgStore, tmp_path) -> None:
    """crawl -> signatures -> (fake) embeddings -> groups -> intent-overlap end to end (ticket 079)."""
    from crawler_cli.intent_signature import backfill_intent_signatures
    from crawler_cli.embeddings import generate_signature_embeddings_for_store
    from crawler_cli.hreflang_groups import build_and_store_identity
    from crawler_cli.intent_overlap import run_intent_overlap

    def _page(url: str, title: str, body_word: str) -> CrawlResult:
        body = "<article><p>" + (f"{body_word} content here. " * 40) + "</p></article>"
        return CrawlResult(
            requested_url=url,
            final_url=url,
            status=200,
            headers={"content-type": "text/html"},
            content_type="text/html",
            fetch_backend="aiohttp",
            extracted=ExtractedContent(
                title=title,
                meta_description="m",
                meta_robots=RobotsDirectives(),
                x_robots_tag=RobotsDirectives(),
                canonical=None,
                x_canonical=None,
                hreflang_links=[],
                html_lang="en",
                headings={"h1": [title], "h2": []},
                text="b",
                word_count=200,
                metadata={},
            ),
            raw_html=f"<html><head><title>{title}</title></head><body>{body}</body></html>",
        )

    await store.persist(_page("https://io.example/a", "Alpha", "widget"))
    await store.persist(_page("https://io.example/b", "Beta", "widget"))
    await store.persist(_page("https://io.example/c", "Gamma", "sailboat"))
    await backfill_intent_signatures(store)
    await build_and_store_identity(store)

    # Deterministic fake vectors: a/b identical, c orthogonal.
    vectors = {
        "https://io.example/a": [1.0, 0.0, 0.0],
        "https://io.example/b": [1.0, 0.0, 0.0],
        "https://io.example/c": [0.0, 1.0, 0.0],
    }

    # Encode with url-aware vectors by embedding one page at a time.
    for url, vec in vectors.items():
        await generate_signature_embeddings_for_store(
            store, model="local-test", encoder=lambda texts, v=vec: [v for _ in texts], urls=[url]
        )

    run = await run_intent_overlap(store, out_dir=str(tmp_path), lang_split=False, run_args={"threshold": 0.85})
    # a and b are duplicates; c is alone.
    assert run.result.summary["duplicate_pages"] == 2
    assert run.result.summary["overlap_pairs"] == 1
    assert (tmp_path / "pages.csv").exists()
    assert (tmp_path / "run_manifest.json").exists()
    with open(tmp_path / "pages.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    assert {"main_text_words", "main_text_chars", "signature_words", "signature_chars"} <= set(rows[0])
    assert any(int(row["main_text_words"]) > 0 for row in rows if row["main_text_words"])
    assert any(int(row["signature_chars"]) > 0 for row in rows if row["signature_chars"])


@pytest.mark.asyncio
async def test_urls_fetched_since_staleness(store: AsyncpgStore) -> None:
    """urls_fetched_since returns only successfully-fetched URLs within the window (ticket 080)."""
    import time

    result = CrawlResult(
        requested_url="https://fresh.example/p",
        final_url="https://fresh.example/p",
        status=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=None,
        raw_html="<html></html>",
    )
    await store.persist(result)
    now = int(time.time())

    # Recent cutoff -> the freshly-persisted 200 page is "fresh".
    fresh = await store.urls_fetched_since(["https://fresh.example/p", "https://never.example/x"], now - 86400)
    assert fresh == {"https://fresh.example/p"}

    # Cutoff in the future -> nothing counts as fresh.
    none_fresh = await store.urls_fetched_since(["https://fresh.example/p"], now + 86400)
    assert none_fresh == set()


@pytest.mark.asyncio
async def test_truncate_only_touches_crawl_tables(store: AsyncpgStore) -> None:
    """truncate_crawl_tables must not drop tables that don't belong to it."""
    await store.enqueue_frontier([("https://example.com/", 0, None)], source="seed")
    await store.truncate_crawl_tables()
    queued, pending, done = await store.frontier_stats()
    assert queued == 0 and pending == 0 and done == 0


@pytest.mark.asyncio
async def test_persist_recrawl_replaces_page_scoped_facts(store: AsyncpgStore) -> None:
    first = CrawlResult(
        requested_url="https://example.com/page",
        final_url="https://example.com/page",
        status=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=ExtractedContent(
            title="First",
            meta_description="First description",
            meta_robots=RobotsDirectives(raw=["index", "follow"]),
            x_robots_tag=RobotsDirectives(raw=["max-snippet:50"]),
            canonical="https://example.com/first-canonical",
            x_canonical="https://example.com/first-header-canonical",
            hreflang_links=[
                HreflangLink("en-gb", "https://example.com/uk", "html_head"),
                HreflangLink("en-us", "https://example.com/us", "http_header"),
            ],
            html_lang="en",
            headings={"h1": ["First H1"], "h2": ["First H2"]},
            text="first page",
            word_count=2,
            metadata={},
            schema_data=[
                {
                    "type": "Article",
                    "format": "json-ld",
                    "raw_data": '{"@type":"Article","headline":"First"}',
                    "parsed_data": {"@type": "Article", "headline": "First"},
                    "position": 0,
                    "is_valid": True,
                    "validation_errors": [],
                    "severity": "info",
                }
            ],
        ),
        raw_html="<html><head><title>First</title></head><body>first</body></html>",
        discovered_links=[
            DiscoveredLink(
                href="https://example.com/linked-a",
                anchor_text="Link A",
                xpath="/html/body/a[1]",
                is_image=False,
            )
        ],
        detected_analytics=AnalyticsDetectionResult(
            hits=[
                AnalyticsHit(
                    vendor="gtm",
                    category="tag_manager",
                    identifier="GTM-ONE",
                    evidence_type="script_src",
                    evidence_snippet="googletagmanager one",
                    confidence=1.0,
                )
            ]
        ),
    )
    second = CrawlResult(
        requested_url="https://example.com/page",
        final_url="https://example.com/page",
        status=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=ExtractedContent(
            title="Second",
            meta_description="Second description",
            meta_robots=RobotsDirectives(raw=["noindex"]),
            x_robots_tag=RobotsDirectives(raw=[]),
            canonical="https://example.com/second-canonical",
            x_canonical=None,
            hreflang_links=[
                HreflangLink("fr-fr", "https://example.com/fr", "html_head"),
            ],
            html_lang="fr",
            headings={"h1": ["Second H1"], "h2": []},
            text="second page",
            word_count=2,
            metadata={},
            schema_data=[],
        ),
        raw_html="<html><head><title>Second</title></head><body>second</body></html>",
        discovered_links=[
            DiscoveredLink(
                href="https://example.com/linked-b",
                anchor_text="Link B",
                xpath="/html/body/a[2]",
                is_image=False,
            )
        ],
        detected_analytics=AnalyticsDetectionResult(
            hits=[
                AnalyticsHit(
                    vendor="ga4",
                    category="analytics",
                    identifier="G-SECOND",
                    evidence_type="script_src",
                    evidence_snippet="googletagmanager second",
                    confidence=1.0,
                )
            ]
        ),
    )

    await store.persist(first)
    await store.persist(second)

    assert store.pool is not None
    async with store.pool.acquire() as conn:
        counts = {
            "robots_directives": await conn.fetchval(
                """
                SELECT COUNT(*) FROM robots_directives rd
                JOIN urls u ON u.id = rd.url_id
                WHERE u.url = $1
                """,
                "https://example.com/page",
            ),
            "canonical_urls": await conn.fetchval(
                """
                SELECT COUNT(*) FROM canonical_urls cu
                JOIN urls u ON u.id = cu.url_id
                WHERE u.url = $1
                """,
                "https://example.com/page",
            ),
            "hreflang_html_head": await conn.fetchval(
                """
                SELECT COUNT(*) FROM hreflang_html_head hh
                JOIN urls u ON u.id = hh.url_id
                WHERE u.url = $1
                """,
                "https://example.com/page",
            ),
            "hreflang_http_header": await conn.fetchval(
                """
                SELECT COUNT(*) FROM hreflang_http_header hh
                JOIN urls u ON u.id = hh.url_id
                WHERE u.url = $1
                """,
                "https://example.com/page",
            ),
            "schema_data": await conn.fetchval(
                """
                SELECT COUNT(*) FROM schema_data sd
                JOIN urls u ON u.id = sd.url_id
                WHERE u.url = $1
                """,
                "https://example.com/page",
            ),
            "page_schema_references": await conn.fetchval(
                """
                SELECT COUNT(*) FROM page_schema_references psr
                JOIN urls u ON u.id = psr.url_id
                WHERE u.url = $1
                """,
                "https://example.com/page",
            ),
            "internal_links": await conn.fetchval(
                """
                SELECT COUNT(*) FROM internal_links il
                JOIN urls u ON u.id = il.source_url_id
                WHERE u.url = $1
                """,
                "https://example.com/page",
            ),
            "page_analytics_hits": await conn.fetchval(
                """
                SELECT COUNT(*) FROM page_analytics_hits pah
                JOIN pages p ON p.id = pah.page_id
                JOIN urls u ON u.id = p.url_id
                WHERE u.url = $1
                """,
                "https://example.com/page",
            ),
        }
        canonical_target = await conn.fetchval(
            """
            SELECT target.url
            FROM canonical_urls cu
            JOIN urls source ON source.id = cu.url_id
            JOIN urls target ON target.id = cu.canonical_url_id
            WHERE source.url = $1 AND cu.source = 'html_head'
            """,
            "https://example.com/page",
        )
        analytics_vendor = await conn.fetchval(
            """
            SELECT av.vendor
            FROM page_analytics_hits pah
            JOIN analytics_vendors av ON av.id = pah.vendor_id
            JOIN pages p ON p.id = pah.page_id
            JOIN urls u ON u.id = p.url_id
            WHERE u.url = $1
            """,
            "https://example.com/page",
        )

    assert counts == {
        "robots_directives": 1,
        "canonical_urls": 1,
        "hreflang_html_head": 1,
        "hreflang_http_header": 0,
        "schema_data": 0,
        "page_schema_references": 0,
        "internal_links": 1,
        "page_analytics_hits": 1,
    }
    assert canonical_target == "https://example.com/second-canonical"
    assert analytics_vendor == "ga4"


def _amp_page(url: str, *, amphtml: str | None = None, canonical: str | None = None) -> CrawlResult:
    return CrawlResult(
        requested_url=url,
        final_url=url,
        status=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=ExtractedContent(
            title="t",
            meta_description="m",
            meta_robots=RobotsDirectives(),
            x_robots_tag=RobotsDirectives(),
            canonical=canonical,
            x_canonical=None,
            amphtml=amphtml,
            hreflang_links=[],
            html_lang="en",
            headings={"h1": ["t"], "h2": []},
            text="b",
            word_count=10,
            metadata={},
        ),
        raw_html="<html><head><title>t</title></head><body>b</body></html>",
    )


@pytest.mark.asyncio
async def test_amphtml_edge_persisted(store: AsyncpgStore) -> None:
    """A <link rel=amphtml> edge lands in the amphtml_urls table (ticket 103)."""
    await store.persist(_amp_page("https://amp.example/foo", amphtml="https://amp.example/foo/amp"))
    assert store.pool is not None
    async with store.pool.acquire() as conn:
        target = await conn.fetchval(
            """
            SELECT t.url
            FROM amphtml_urls au
            JOIN urls s ON s.id = au.url_id
            JOIN urls t ON t.id = au.amphtml_url_id
            WHERE s.url = $1 AND au.source = 'html_head'
            """,
            "https://amp.example/foo",
        )
    assert target == "https://amp.example/foo/amp"


@pytest.mark.asyncio
async def test_classify_amp_variants_marks_variant_kind_and_hygiene(store: AsyncpgStore) -> None:
    """classify_amp_variants classifies via positive evidence paths and records
    the canonical-hygiene rows (tickets 103 / 108)."""
    # Base page declaring an amphtml edge to an otherwise unshaped target.
    await store.persist(_amp_page("https://amp.example/base", amphtml="https://amp.example/base/amp"))
    # AMP page confirmed by canonical-to-base (base also crawled).
    await store.persist(_amp_page("https://amp.example/base/amp", canonical="https://amp.example/base"))
    # AMP page confirmed by signature-hash match but with NO canonical -> hygiene.
    await store.persist(_amp_page("https://amp.example/blog"))
    await store.persist(_amp_page("https://amp.example/blog/amp"))
    # Literal /amp with crawled base but no amphtml/canonical/signature evidence.
    await store.persist(_amp_page("https://amp.example/ordinary"))
    await store.persist(_amp_page("https://amp.example/ordinary/amp"))
    # A decoy: slug ends in "amp" but is a real page -> must NOT be classified.
    await store.persist(_amp_page("https://amp.example/revamp"))

    assert store.pool is not None
    async with store.pool.acquire() as conn:
        id_rows = await conn.fetch(
            "SELECT id, url FROM urls WHERE url = ANY($1::text[])",
            [
                "https://amp.example/blog",
                "https://amp.example/blog/amp",
            ],
        )
    ids = {r["url"]: int(r["id"]) for r in id_rows}
    await store.store_intent_signatures_bulk(
        [
            {
                "url_id": ids["https://amp.example/blog"],
                "main_text": "blog body",
                "extraction_method": "test",
                "signal_confidence": "high",
                "signature_hash": "blog-sig",
                "signature_model_input": "test",
            },
            {
                "url_id": ids["https://amp.example/blog/amp"],
                "main_text": "blog body amp",
                "extraction_method": "test",
                "signal_confidence": "high",
                "signature_hash": "blog-sig",
                "signature_model_input": "test",
            },
        ]
    )

    hygiene = await store.classify_amp_variants()
    hygiene_by_url = {row["url"]: row for row in hygiene}

    assert set(hygiene_by_url) == {
        "https://amp.example/base/amp",
        "https://amp.example/blog/amp",
    }
    # Missing-canonical AMP page surfaces with its paired base.
    blog_amp = hygiene_by_url["https://amp.example/blog/amp"]
    assert blog_amp["issue"] == "missing-canonical"
    assert blog_amp["base_url"] == "https://amp.example/blog"
    assert blog_amp["has_canonical"] is False
    assert blog_amp["confirmed_by"] == "signature-hash"
    # AMP page that canonicals to its base is healthy (no issue).
    assert hygiene_by_url["https://amp.example/base/amp"]["issue"] == ""
    assert hygiene_by_url["https://amp.example/base/amp"]["confirmed_by"] in {
        "amphtml-target",
        "canonical-to-base",
    }

    async with store.pool.acquire() as conn:
        amp_kinds = await conn.fetch("SELECT url, variant_kind FROM urls WHERE variant_kind IS NOT NULL ORDER BY url")
    marked = {r["url"]: r["variant_kind"] for r in amp_kinds}
    assert marked == {
        "https://amp.example/base/amp": "amp",
        "https://amp.example/blog/amp": "amp",
    }
    # Base-exists alone and /revamp decoy were never marked.
    assert "https://amp.example/ordinary/amp" not in marked
    assert "https://amp.example/revamp" not in marked


@pytest.mark.asyncio
async def test_snapshot_analysis_excludes_amp_variant_without_canonical(store: AsyncpgStore) -> None:
    """AMP classification survives the snapshot analysis path (ticket 120)."""
    base_url = "https://amp.example/snapshot-base"
    amp_url = f"{base_url}/amp"
    await store.persist(_amp_page(base_url, amphtml=amp_url))
    await store.persist(_amp_page(amp_url))

    hygiene = await store.classify_amp_variants()
    assert {row["url"] for row in hygiene} == {amp_url}
    assert hygiene[0]["issue"] == "missing-canonical"

    rows = await store.fetch_analysis_rows()
    amp_row = next(row for row in rows if row["url"] == amp_url)
    assert amp_row["variant_kind"] == "amp"
    assert compute_exclusion(amp_row) == "amp-variant"


@pytest.mark.asyncio
async def test_classify_amp_variants_clears_stale_labels(store: AsyncpgStore) -> None:
    """Recomputation clears variant_kind when a page no longer classifies (ticket 108)."""
    await store.persist(_amp_page("https://amp.example/stale/amp", canonical="https://amp.example/stale"))
    hygiene = await store.classify_amp_variants()
    assert [row["url"] for row in hygiene] == ["https://amp.example/stale/amp"]

    assert store.pool is not None
    async with store.pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM canonical_urls WHERE url_id = (SELECT id FROM urls WHERE url = $1)",
            "https://amp.example/stale/amp",
        )

    hygiene_after = await store.classify_amp_variants()
    assert hygiene_after == []
    async with store.pool.acquire() as conn:
        kind = await conn.fetchval(
            "SELECT variant_kind FROM urls WHERE url = $1",
            "https://amp.example/stale/amp",
        )
    assert kind is None


@pytest.mark.asyncio
async def test_challenge_persist_records_metadata_without_content(store: AsyncpgStore) -> None:
    """Unresolved bot challenges audit to page_metadata but never write content (ticket 089)."""
    url = "https://challenge.example/"
    result = CrawlResult(
        requested_url=url,
        final_url=url,
        status=403,
        headers={"content-type": "text/html"},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=None,
        raw_html=None,
        skip_reason="bot_challenge",
        challenge="cloudflare",
        ttfb_seconds=0.1,
        total_duration_seconds=0.2,
    )
    await store.persist(result)

    assert store.pool is not None
    async with store.pool.acquire() as conn:
        meta = await conn.fetchrow(
            """
            SELECT pm.initial_status_code, pm.challenge, pm.skip_reason, pm.ttfb_seconds
            FROM page_metadata pm
            JOIN urls u ON u.id = pm.url_id
            WHERE u.url = $1
            """,
            url,
        )
        content_count = await conn.fetchval(
            "SELECT COUNT(*) FROM content c JOIN urls u ON u.id = c.url_id WHERE u.url = $1",
            url,
        )
        pages_count = await conn.fetchval(
            "SELECT COUNT(*) FROM pages p JOIN urls u ON u.id = p.url_id WHERE u.url = $1",
            url,
        )
        links_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM internal_links il
            JOIN urls u ON u.id = il.source_url_id
            WHERE u.url = $1
            """,
            url,
        )

    assert meta is not None
    assert meta["initial_status_code"] == 403
    assert meta["challenge"] == "cloudflare"
    assert meta["skip_reason"] == "bot_challenge"
    assert meta["ttfb_seconds"] == pytest.approx(0.1)
    assert content_count == 0
    assert pages_count == 0
    assert links_count == 0


@pytest.mark.asyncio
async def test_run_snapshots_keep_historical_analysis_values(store: AsyncpgStore) -> None:
    """A selected run reads its own values, never mutable current-state rows."""
    url = "https://history.example/page"

    def page(title: str, canonical: str, alternate: str) -> CrawlResult:
        return CrawlResult(
            requested_url=url,
            final_url=url,
            status=200,
            headers={"content-type": "text/html"},
            content_type="text/html",
            fetch_backend="aiohttp",
            extracted=ExtractedContent(
                title=title,
                meta_description=f"{title} description",
                meta_robots=RobotsDirectives(),
                x_robots_tag=RobotsDirectives(),
                canonical=canonical,
                x_canonical=None,
                hreflang_links=[HreflangLink(hreflang="fr", href=alternate, source="html_head")],
                html_lang="en",
                headings={"h1": [title], "h2": []},
                text=title,
                word_count=10,
                metadata={},
            ),
            raw_html=f"<html><title>{title}</title><body>{title}</body></html>",
        )

    await store.create_crawl_run("snapshot-a", seed_urls=[url], config_hash="a", config={})
    await store.persist(page("before", "https://history.example/old", "https://history.example/fr-old"))
    await store.create_crawl_run("snapshot-b", seed_urls=[url], config_hash="b", config={})
    await store.persist(page("after", "https://history.example/new", "https://history.example/fr-new"))

    a_rows = await store.fetch_analysis_rows(run_id="snapshot-a")
    b_rows = await store.fetch_analysis_rows(run_id="snapshot-b")
    assert a_rows[0]["title"] == "before"
    assert a_rows[0]["canonical_url"] == "https://history.example/old"
    assert b_rows[0]["title"] == "after"
    assert b_rows[0]["canonical_url"] == "https://history.example/new"
    assert await store.fetch_hreflang_edges(run_id="snapshot-a") == [(url, "https://history.example/fr-old", "fr")]
    assert await store.fetch_hreflang_edges(run_id="snapshot-b") == [(url, "https://history.example/fr-new", "fr")]

    with pytest.raises(ValueError, match="multiple crawl runs"):
        await store.resolve_reporting_run_id()
    assert await store.resolve_reporting_run_id("snapshot-a") == "snapshot-a"
    with pytest.raises(ValueError, match="multiple crawl runs"):
        await CrawlReports(store).indexability_reasons()
    a_report_rows = await CrawlReports(store, run_id="snapshot-a").indexability_reasons()
    assert [row["url"] for row in a_report_rows] == [url]


@pytest.mark.asyncio
async def test_analytics_reports_read_the_selected_run_snapshot(store: AsyncpgStore) -> None:
    """Later analytics detection must not rewrite an earlier run's reports."""
    url = "https://analytics-history.example/page"

    def page(identifier: str) -> CrawlResult:
        result = _amp_page(url)
        result.detected_analytics = AnalyticsDetectionResult(
            hits=[
                AnalyticsHit(
                    vendor="ga4",
                    category="analytics",
                    identifier=identifier,
                    evidence_type="script_src",
                    evidence_snippet=identifier,
                    confidence=1.0,
                )
            ]
        )
        return result

    await store.create_crawl_run("analytics-a", seed_urls=[url], config_hash="a", config={})
    await store.persist(page("G-OLD"))
    await store.create_crawl_run("analytics-b", seed_urls=[url], config_hash="b", config={})
    await store.persist(page("G-NEW"))

    reports_a = CrawlReports(store, run_id="analytics-a")
    reports_b = CrawlReports(store, run_id="analytics-b")
    assert [row["identifier"] for row in await reports_a.analytics_per_page(url)] == ["G-OLD"]
    assert [row["evidence_snippet"] for row in await reports_a.analytics_per_page(url)] == ["G-OLD"]
    assert [row["identifier"] for row in await reports_b.analytics_per_page(url)] == ["G-NEW"]
    assert await reports_a.pages_missing_expected_id("G-OLD") == []
    assert [row["url"] for row in await reports_a.pages_missing_expected_id("G-NEW")] == [url]


@pytest.mark.asyncio
async def test_challenge_persist_does_not_overwrite_prior_content(store: AsyncpgStore) -> None:
    """A later challenge must not wipe a previously successful page snapshot (ticket 089)."""
    url = "https://challenge.example/kept"
    first = CrawlResult(
        requested_url=url,
        final_url=url,
        status=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=ExtractedContent(
            title="Keep Me",
            meta_description=None,
            meta_robots=RobotsDirectives(raw=["index"]),
            x_robots_tag=RobotsDirectives(raw=[]),
            canonical=None,
            x_canonical=None,
            hreflang_links=[],
            html_lang="en",
            headings={"h1": ["Keep Me"], "h2": []},
            text="real body",
            word_count=2,
            metadata={},
        ),
        raw_html="<html><head><title>Keep Me</title></head><body><h1>Keep Me</h1></body></html>",
        discovered_links=[
            DiscoveredLink(
                href="https://challenge.example/other",
                anchor_text="Other",
                xpath="/html/body/a[1]",
                is_image=False,
            )
        ],
    )
    await store.persist(first)

    blocked = CrawlResult(
        requested_url=url,
        final_url=url,
        status=403,
        headers={"content-type": "text/html"},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=None,
        raw_html=None,
        skip_reason="bot_challenge",
        challenge="cloudflare",
    )
    await store.persist(blocked)

    assert store.pool is not None
    async with store.pool.acquire() as conn:
        title = await conn.fetchval(
            "SELECT c.title FROM content c JOIN urls u ON u.id = c.url_id WHERE u.url = $1",
            url,
        )
        link_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM internal_links il
            JOIN urls u ON u.id = il.source_url_id
            WHERE u.url = $1
            """,
            url,
        )
        meta = await conn.fetchrow(
            """
            SELECT pm.challenge, pm.skip_reason, pm.final_status_code
            FROM page_metadata pm
            JOIN urls u ON u.id = pm.url_id
            WHERE u.url = $1
            """,
            url,
        )

    assert title == "Keep Me"
    assert link_count == 1
    assert meta is not None
    assert meta["challenge"] == "cloudflare"
    assert meta["skip_reason"] == "bot_challenge"
    assert meta["final_status_code"] == 403


@pytest.mark.asyncio
async def test_engine_challenge_hard_stop_end_to_end(store: AsyncpgStore) -> None:
    """Engine + Postgres: unresolved challenge is blocked, not crawled content (ticket 074/089)."""

    class ChallengedBackend:
        async def fetch(self, url: str) -> FetchResponse:
            html = (
                "<html><head><title>Just a moment...</title></head>"
                "<body>__cf_chl_opt<a href='/next'>n</a></body></html>"
            )
            return FetchResponse(
                url=url,
                requested_url=url,
                status=403,
                headers={"content-type": "text/html"},
                body=html.encode(),
                text=html,
            )

        async def fetch_resilient(self, url: str) -> FetchResponse:
            return await self.fetch(url)

        async def close(self) -> None:
            return None

    engine = CrawlEngine(
        CrawlConfig(
            respect_robots_txt=False,
            detect_challenges=True,
            challenge_escalate_to_browser=False,
            discover_sitemaps=False,
            max_concurrency=1,
        ),
        store=store,
    )
    engine.backend = ChallengedBackend()
    result = await engine.crawl("https://challenge-e2e.example/")

    assert result.challenge == "cloudflare"
    assert result.skip_reason == "bot_challenge"
    assert result.extracted is None
    assert result.discovered_links == []

    assert store.pool is not None
    async with store.pool.acquire() as conn:
        meta = await conn.fetchrow(
            """
            SELECT pm.challenge, pm.skip_reason FROM page_metadata pm
            JOIN urls u ON u.id = pm.url_id WHERE u.url = $1
            """,
            "https://challenge-e2e.example/",
        )
        content_count = await conn.fetchval(
            "SELECT COUNT(*) FROM content c JOIN urls u ON u.id = c.url_id WHERE u.url = $1",
            "https://challenge-e2e.example/",
        )
    assert meta is not None
    assert meta["challenge"] == "cloudflare"
    assert meta["skip_reason"] == "bot_challenge"
    assert content_count == 0


@pytest.mark.asyncio
async def test_fetch_pages_for_comparison_reconstructs_rows(store: AsyncpgStore) -> None:
    """Ticket 122: a stored crawl run can be pulled back as comparison-grade
    CrawlResult rows (final_url, status, title, h1, hashes)."""
    url = "https://cmp.example/page"
    html = "<html><head><title>Page Title</title><link rel='canonical' href='https://cmp.example/page'></head>"
    html += "<body><h1>Main Heading</h1><p>Some body content for hashing here.</p></body></html>"
    config = CrawlConfig(
        max_concurrency=1,
        default_open_crawl_limit=1,
        discover_sitemaps=False,
        respect_robots_txt=False,
        enable_content_hashing=True,
    )
    engine = CrawlEngine(config, store=store)
    engine.backend = FakeBackend({url: html})
    await engine.crawl_open([url], max_urls=1, run_id="cmp-run")

    run_id = await store.resolve_reporting_run_id("cmp-run")
    rows = await store.fetch_pages_for_comparison(run_id=run_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.final_url == url
    assert row.status == 200
    assert row.extracted is not None
    assert row.extracted.title == "Page Title"
    assert row.extracted.headings["h1"] == ["Main Heading"]
    assert row.extracted.canonical == "https://cmp.example/page"
    assert row.content_hash_sha256 is not None
    # Simhash comes back in unsigned form, consistent with fetch-time values.
    assert row.content_hash_simhash is not None and row.content_hash_simhash >= 0

    # URL filtering returns only requested URLs.
    filtered = await store.fetch_pages_for_comparison(urls=["https://cmp.example/absent"], run_id=run_id)
    assert filtered == []


def _load_gui_server():
    """Load crawler_gui/server.py (not an importable package) by path."""
    import importlib.util
    import sys

    path = Path(__file__).resolve().parents[1] / "crawler_gui" / "server.py"
    spec = importlib.util.spec_from_file_location("crawler_gui_server", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclasses resolve field types via sys.modules.
    sys.modules["crawler_gui_server"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_crawler_gui_bridge_serves_run_scoped_paginated_snapshots(store: AsyncpgStore, dsn: str) -> None:
    """Ticket 125: the GUI bridge lists runs, scopes snapshots to the selected
    run, paginates every page of a run, and resolves the internal link graph."""
    gui_server = _load_gui_server()
    base = "https://gui.example/"
    other = "https://gui.example/other"
    pages = {
        base: "<html><head><title>Home</title></head><body><h1>Home</h1>"
        f"<a href='{other}'>Other page</a></body></html>",
        other: "<html><head><title>Other</title></head><body><h1>Other</h1></body></html>",
    }
    config = CrawlConfig(
        max_concurrency=1,
        default_open_crawl_limit=2,
        discover_sitemaps=False,
        respect_robots_txt=False,
    )
    engine = CrawlEngine(config, store=store)
    engine.backend = FakeBackend(pages)
    await engine.crawl_open([base], max_urls=2, run_id="gui-run")

    live = gui_server.LiveStore(dsn)
    await live.connect()
    try:
        assert live.has_run_snapshots is True

        runs = await live.runs()
        run = next(r for r in runs if r["id"] == "gui-run")
        assert run["urls"] == 2  # per-run count, not a global table count
        assert run["runScoped"] is True

        # An unknown run is a 404 rather than a silent fallback to another run.
        with pytest.raises(gui_server.web.HTTPNotFound):
            await live.snapshot("no-such-run", 10)

        # Page one of two: the window is partial and says so.
        first = await live.snapshot("gui-run", 1, 0)
        assert len(first["pages"]) == 1
        assert first["live"]["totalPages"] == 2
        assert first["live"]["hasMore"] is True
        assert first["live"]["offset"] == 0
        assert first["crawl"]["progress"]["total"] == 2
        # The overview describes the whole run, not just the 1-page window, so
        # it stays correct while the grid pages through a large run.
        summary = {row["label"]: row["count"] for row in first["overview"]["summary"]}
        assert summary["Total URLs Crawled"] == 2
        assert first["issues"][0]["count"] == 0  # both pages indexable

        # Page two completes the run: no page is unreachable.
        second = await live.snapshot("gui-run", 1, 1)
        assert len(second["pages"]) == 1
        assert second["live"]["hasMore"] is False
        assert second["pages"][0]["address"] != first["pages"][0]["address"]

        full = await live.snapshot("gui-run", 100, 0)
        assert {page["address"] for page in full["pages"]} == {base, other}
        assert full["live"]["hasMore"] is False

        # Link graph: the seed links to /other, so /other has a real inlink.
        by_url = {page["address"]: page for page in full["pages"]}
        assert by_url[other]["internalInlinks"] == 1
        assert by_url[other]["inlinks"][0]["sourceUrl"] == base
        assert any(link["targetUrl"] == other for link in by_url[base]["outlinks"])
        # The fake backend records no timing, so the field stays absent rather
        # than being fabricated as 0.
        assert by_url[base]["responseTimeMs"] is None

        # With a duration actually stored, it surfaces as milliseconds.
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute("UPDATE page_run_snapshots SET total_duration_seconds = 0.5 WHERE run_id = 'gui-run'")
        finally:
            await conn.close()
        timed = await live.snapshot("gui-run", 100, 0)
        assert all(page["responseTimeMs"] == 500 for page in timed["pages"])
    finally:
        await live.close()


@pytest.mark.asyncio
async def test_fetch_pages_for_comparison_include_html_enables_remap(store: AsyncpgStore) -> None:
    """Ticket 123 B: --replace can only take effect on a store-backed side if the
    loader hands back HTML to re-hash; stored hashes are un-remapped."""
    from crawler_cli.comparison import can_rehash, compare_deep
    from crawler_cli.remap import Remap

    url = "https://dev.cmp.example/page"
    html = (
        "<html><head><title>T</title></head><body><h1>H</h1>"
        "<p>Contact us at dev.cmp.example for details about this page.</p></body></html>"
    )
    config = CrawlConfig(
        max_concurrency=1,
        default_open_crawl_limit=1,
        discover_sitemaps=False,
        respect_robots_txt=False,
        enable_content_hashing=True,
    )
    engine = CrawlEngine(config, store=store)
    engine.backend = FakeBackend({url: html})
    await engine.crawl_open([url], max_urls=1, run_id="remap-run")
    run_id = await store.resolve_reporting_run_id("remap-run")

    # Without include_html the row carries no content, so a remap cannot apply.
    without_html = await store.fetch_pages_for_comparison(run_id=run_id)
    assert without_html[0].raw_html is None
    assert not can_rehash(without_html[0])

    with_html = await store.fetch_pages_for_comparison(run_id=run_id, include_html=True)
    assert with_html[0].raw_html is not None
    assert can_rehash(with_html[0])

    # The remapped store-backed side now hashes identically to the prod page.
    prod_html = html.replace("dev.cmp.example", "cmp.example")
    prod = CrawlResult(
        requested_url="https://cmp.example/page",
        final_url="https://cmp.example/page",
        status=200,
        headers={},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=with_html[0].extracted,
        raw_html=prod_html,
        content_hash_sha256=sha256_hash(prod_html),
        content_hash_simhash=simhash64(prod_html),
    )
    remap = Remap.from_specs(["dev.cmp.example=cmp.example"])
    diff = compare_deep(with_html, [prod], remap=remap)
    assert diff.remap_fallback_paths == []
    assert diff.content_verdicts["/page"] == "identical"

    # ...whereas the HTML-less side silently falls back and is flagged.
    fallback_diff = compare_deep(without_html, [prod], remap=remap)
    assert fallback_diff.remap_fallback_paths == ["/page"]


@pytest.mark.asyncio
async def test_persist_comparison_session_roundtrips_new_columns(store: AsyncpgStore) -> None:
    """Ticket 123 C: the ticket-122 content_verdict / simhash_distance columns
    are actually written and readable."""
    rows = [
        {
            "path": "/a",
            "baseline_url": "https://base/a",
            "candidate_url": "https://cand/a",
            "exists_on_baseline": True,
            "exists_on_candidate": True,
            "content_verdict": "near",
            "simhash_distance": 3,
        },
        {
            "path": "/b",
            "baseline_url": "https://base/b",
            "candidate_url": None,
            "exists_on_baseline": True,
            "exists_on_candidate": False,
            "content_verdict": "missing",
            "simhash_distance": None,
        },
    ]
    session_id = await store.persist_comparison_session(baseline_label="base", candidate_label="cand", rows=rows)
    assert store.pool is not None
    async with store.pool.acquire() as conn:
        persisted = await conn.fetch(
            "SELECT path, content_verdict, simhash_distance FROM crawl_comparison_urls "
            "WHERE session_id = $1 ORDER BY path",
            session_id,
        )
    assert [(r["path"], r["content_verdict"], r["simhash_distance"]) for r in persisted] == [
        ("/a", "near", 3),
        ("/b", "missing", None),
    ]


@pytest.mark.asyncio
async def test_compare_urls_persist_writes_a_session(store: AsyncpgStore, dsn: str, tmp_path) -> None:
    """Ticket 123 C: `compare-urls --persist` is exercised end-to-end."""
    from crawler_cli.__main__ import _build_parser, _dispatch
    from crawler_cli.serialization import serialize_crawl_result

    def _page(requested, final, chain):
        html = "<html><body><p>migrated page body</p></body></html>"
        return CrawlResult(
            requested_url=requested,
            final_url=final,
            status=200,
            headers={},
            content_type="text/html",
            fetch_backend="aiohttp",
            extracted=None,
            raw_html=html,
            content_hash_sha256=sha256_hash(html),
            content_hash_simhash=simhash64(html),
            redirect_chain=chain,
        )

    src = tmp_path / "src.json"
    tgt = tmp_path / "tgt.json"
    pairs = tmp_path / "pairs.csv"
    for path, results in (
        (src, [_page("https://old/a", "https://new/a", [{"url": "https://old/a", "status": 301}])]),
        (tgt, [_page("https://new/a", "https://new/a", [])]),
    ):
        path.write_text(
            json.dumps({"mode": "list", "seed_urls": [], "results": [serialize_crawl_result(r) for r in results]}),
            encoding="utf-8",
        )
    pairs.write_text("source_url,target_url\nhttps://old/a,https://new/a\n", encoding="utf-8")

    args = _build_parser().parse_args(
        [
            "compare-urls",
            "--pairs",
            str(pairs),
            "--source-artifact",
            str(src),
            "--target-artifact",
            str(tgt),
            "--persist",
            "--postgres-dsn",
            dsn,
        ]
    )
    assert await _dispatch(args) == 0

    assert store.pool is not None
    async with store.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT path, candidate_url, redirect_chain, content_verdict FROM crawl_comparison_urls "
            "ORDER BY id DESC LIMIT 1"
        )
    assert row is not None
    assert row["path"] == "https://old/a"
    assert row["candidate_url"] == "https://new/a"
    assert "redirect_ok" in row["redirect_chain"]
    assert row["content_verdict"] == "identical"
