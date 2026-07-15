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
import os

import asyncpg
import pytest
import pytest_asyncio

from crawler_cli.detection.analytics import AnalyticsDetectionResult, AnalyticsHit
from crawler_cli.models import DiscoveredLink, ExtractedContent, HreflangLink, RobotsDirectives
from crawler_cli.models import CrawlResult, FetchResponse
from crawler_cli import CrawlConfig, CrawlEngine
from crawler_cli.persistence import AsyncpgStore, CRAWL_TABLES, SCHEMA_STATEMENTS


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
    """classify_amp_variants classifies via every evidence path and records the
    canonical-hygiene rows (ticket 103)."""
    # Base page declaring an amphtml edge to an otherwise unshaped target.
    await store.persist(_amp_page("https://amp.example/base", amphtml="https://amp.example/base/amp"))
    # AMP page confirmed by canonical-to-base (base also crawled).
    await store.persist(_amp_page("https://amp.example/base/amp", canonical="https://amp.example/base"))
    # AMP page confirmed by base-exists but with NO canonical -> hygiene issue.
    await store.persist(_amp_page("https://amp.example/blog"))
    await store.persist(_amp_page("https://amp.example/blog/amp"))
    # A decoy: slug ends in "amp" but is a real page -> must NOT be classified.
    await store.persist(_amp_page("https://amp.example/revamp"))

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
    # AMP page that canonicals to its base is healthy (no issue).
    assert hygiene_by_url["https://amp.example/base/amp"]["issue"] == ""

    assert store.pool is not None
    async with store.pool.acquire() as conn:
        amp_kinds = await conn.fetch("SELECT url, variant_kind FROM urls WHERE variant_kind IS NOT NULL ORDER BY url")
    marked = {r["url"]: r["variant_kind"] for r in amp_kinds}
    assert marked == {
        "https://amp.example/base/amp": "amp",
        "https://amp.example/blog/amp": "amp",
    }
    # The /revamp decoy was never marked.
    assert "https://amp.example/revamp" not in marked
