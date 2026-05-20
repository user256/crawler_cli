from __future__ import annotations

import asyncpg
import json
import time

from .models import CrawlResult, DiscoveredLink
from .schema import create_schema_content_hash, identify_schema_relationships


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS urls (
        id SERIAL PRIMARY KEY,
        url TEXT UNIQUE NOT NULL,
        kind TEXT CHECK (kind IN ('html','sitemap','sitemap_index','image','asset','other')),
        classification TEXT CHECK (classification IN ('internal','subdomain','network','external','social')),
        discovered_from_id INTEGER,
        is_from_sitemap BOOLEAN DEFAULT FALSE,
        is_from_hreflang BOOLEAN DEFAULT FALSE,
        first_seen INTEGER,
        last_seen INTEGER,
        headers_compressed BYTEA,
        FOREIGN KEY (discovered_from_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pages (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL UNIQUE,
        headers_json TEXT,
        html_compressed BYTEA,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS html_languages (
        id SERIAL PRIMARY KEY,
        language_code TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meta_descriptions (
        id SERIAL PRIMARY KEY,
        description TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS content (
        url_id INTEGER PRIMARY KEY,
        title TEXT,
        meta_description_id INTEGER,
        h1_tags TEXT,
        h2_tags TEXT,
        word_count INTEGER,
        html_lang_id INTEGER,
        content_length INTEGER,
        content_hash_sha256 TEXT,
        content_hash_simhash BIGINT,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (meta_description_id) REFERENCES meta_descriptions (id),
        FOREIGN KEY (html_lang_id) REFERENCES html_languages (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS robots_directive_strings (
        id SERIAL PRIMARY KEY,
        directive TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS robots_directives (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL,
        source TEXT CHECK (source IN ('html_meta', 'http_header')) NOT NULL,
        directive_id INTEGER NOT NULL,
        value TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (directive_id) REFERENCES robots_directive_strings (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_urls (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL,
        canonical_url_id INTEGER NOT NULL,
        source TEXT CHECK (source IN ('html_head', 'http_header')) NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (canonical_url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hreflang_languages (
        id SERIAL PRIMARY KEY,
        language_code TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hreflang_http_header (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL,
        hreflang_id INTEGER NOT NULL,
        href_url_id INTEGER NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (hreflang_id) REFERENCES hreflang_languages (id),
        FOREIGN KEY (href_url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hreflang_html_head (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL,
        hreflang_id INTEGER NOT NULL,
        href_url_id INTEGER NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (hreflang_id) REFERENCES hreflang_languages (id),
        FOREIGN KEY (href_url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hreflang_sitemap (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL,
        hreflang_id INTEGER NOT NULL,
        href_url_id INTEGER NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (hreflang_id) REFERENCES hreflang_languages (id),
        FOREIGN KEY (href_url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS page_metadata (
        url_id INTEGER PRIMARY KEY,
        initial_status_code INTEGER,
        final_status_code INTEGER,
        final_url_id INTEGER,
        fetched_at INTEGER,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (final_url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS indexability (
        url_id INTEGER PRIMARY KEY,
        html_meta_allows BOOLEAN NOT NULL,
        http_header_allows BOOLEAN NOT NULL,
        overall_indexable BOOLEAN NOT NULL,
        FOREIGN KEY (url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS frontier (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL UNIQUE,
        depth INTEGER NOT NULL,
        parent_id INTEGER,
        status TEXT NOT NULL CHECK (status IN ('queued','pending','done')),
        enqueued_at INTEGER,
        updated_at INTEGER,
        priority_score DOUBLE PRECISION DEFAULT 0.0,
        sitemap_priority DOUBLE PRECISION DEFAULT 0.5,
        inlinks_count INTEGER DEFAULT 0,
        content_type_score DOUBLE PRECISION DEFAULT 1.0,
        reset_count INTEGER DEFAULT 0,
        retry_count INTEGER DEFAULT 0,
        retry_at INTEGER DEFAULT 0,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (parent_id) REFERENCES urls (id)
    )
    """,
    """
    ALTER TABLE content ADD COLUMN IF NOT EXISTS content_hash_sha256 TEXT
    """,
    """
    ALTER TABLE content ADD COLUMN IF NOT EXISTS content_hash_simhash BIGINT
    """,
    """
    ALTER TABLE frontier ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0
    """,
    """
    ALTER TABLE frontier ADD COLUMN IF NOT EXISTS retry_at INTEGER DEFAULT 0
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_frontier_status ON frontier(status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_frontier_priority ON frontier(priority_score DESC, enqueued_at ASC)
    """,
    """
    CREATE TABLE IF NOT EXISTS crawl_metadata (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS url_sources (
        url_id INTEGER NOT NULL REFERENCES urls(id),
        source TEXT NOT NULL CHECK (source IN ('seed', 'link', 'sitemap', 'archive_org', 'robots_sitemap')),
        detail TEXT,
        detail_key TEXT GENERATED ALWAYS AS (COALESCE(detail, '')) STORED,
        first_seen_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (url_id, source, detail_key)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_url_sources_source ON url_sources(source)
    """,
    """
    CREATE TABLE IF NOT EXISTS schema_types (
        id SERIAL PRIMARY KEY,
        type_name TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS schema_instances (
        id SERIAL PRIMARY KEY,
        content_hash TEXT UNIQUE NOT NULL,
        schema_type_id INTEGER NOT NULL,
        format TEXT CHECK (format IN ('json-ld', 'microdata', 'rdfa')) NOT NULL,
        raw_data TEXT NOT NULL,
        parsed_data JSONB,
        is_valid BOOLEAN NOT NULL DEFAULT TRUE,
        validation_errors JSONB,
        severity TEXT CHECK (severity IN ('info', 'warning', 'error', 'critical')) DEFAULT 'info',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (schema_type_id) REFERENCES schema_types (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS page_schema_references (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL,
        schema_instance_id INTEGER NOT NULL,
        position INTEGER,
        property_name TEXT,
        is_main_entity BOOLEAN DEFAULT FALSE,
        parent_entity_id INTEGER,
        discovered_at INTEGER NOT NULL,
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (schema_instance_id) REFERENCES schema_instances (id),
        FOREIGN KEY (parent_entity_id) REFERENCES page_schema_references (id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS schema_data (
        id SERIAL PRIMARY KEY,
        url_id INTEGER NOT NULL,
        schema_type_id INTEGER NOT NULL,
        format TEXT CHECK (format IN ('json-ld', 'microdata', 'rdfa')) NOT NULL,
        raw_data TEXT NOT NULL,
        parsed_data JSONB,
        position INTEGER,
        is_valid BOOLEAN NOT NULL DEFAULT TRUE,
        validation_errors JSONB,
        severity TEXT CHECK (severity IN ('info', 'warning', 'error', 'critical')) DEFAULT 'info',
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (url_id, schema_type_id, position),
        FOREIGN KEY (url_id) REFERENCES urls (id),
        FOREIGN KEY (schema_type_id) REFERENCES schema_types (id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_schema_instances_content_hash ON schema_instances(content_hash)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_page_schema_references_url ON page_schema_references(url_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_schema_data_url ON schema_data(url_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS anchor_texts (
        id SERIAL PRIMARY KEY,
        text TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fragments (
        id SERIAL PRIMARY KEY,
        fragment TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS xpaths (
        id SERIAL PRIMARY KEY,
        xpath TEXT UNIQUE NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS internal_links (
        id SERIAL PRIMARY KEY,
        source_url_id INTEGER NOT NULL,
        target_url_id INTEGER,
        anchor_text_id INTEGER,
        xpath_id INTEGER,
        href_url_id INTEGER NOT NULL,
        fragment_id INTEGER,
        url_parameters TEXT,
        discovered_at INTEGER NOT NULL,
        UNIQUE (source_url_id, target_url_id, xpath_id),
        FOREIGN KEY (source_url_id) REFERENCES urls (id),
        FOREIGN KEY (target_url_id) REFERENCES urls (id),
        FOREIGN KEY (anchor_text_id) REFERENCES anchor_texts (id),
        FOREIGN KEY (xpath_id) REFERENCES xpaths (id),
        FOREIGN KEY (href_url_id) REFERENCES urls (id),
        FOREIGN KEY (fragment_id) REFERENCES fragments (id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_internal_links_source ON internal_links(source_url_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_internal_links_target ON internal_links(target_url_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS page_embeddings (
        url_id INTEGER PRIMARY KEY,
        embedding_json JSONB NOT NULL,
        model TEXT NOT NULL,
        text_length INTEGER,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (url_id) REFERENCES urls (id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_page_embeddings_model ON page_embeddings(model)
    """,
    """
    CREATE TABLE IF NOT EXISTS crawl_comparison_sessions (
        id SERIAL PRIMARY KEY,
        baseline_label TEXT NOT NULL,
        candidate_label TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS crawl_comparison_urls (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        path TEXT NOT NULL,
        baseline_url TEXT,
        candidate_url TEXT,
        exists_on_baseline BOOLEAN NOT NULL DEFAULT FALSE,
        exists_on_candidate BOOLEAN NOT NULL DEFAULT FALSE,
        baseline_title TEXT,
        candidate_title TEXT,
        baseline_h1 TEXT,
        candidate_h1 TEXT,
        baseline_meta_description TEXT,
        candidate_meta_description TEXT,
        baseline_word_count INTEGER,
        candidate_word_count INTEGER,
        is_moved_content BOOLEAN NOT NULL DEFAULT FALSE,
        moved_from_path TEXT,
        moved_to_path TEXT,
        redirect_chain TEXT,
        baseline_schema_types JSONB,
        candidate_schema_types JSONB,
        links_added JSONB,
        links_removed JSONB,
        UNIQUE (session_id, path),
        FOREIGN KEY (session_id) REFERENCES crawl_comparison_sessions (id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_crawl_comparison_urls_session ON crawl_comparison_urls(session_id)
    """,
]

COMPARISON_VIEW_STATEMENTS = [
    """
    CREATE OR REPLACE VIEW view_url_moves AS
    SELECT
        cu.session_id,
        s.baseline_label,
        s.candidate_label,
        cu.path,
        cu.moved_from_path,
        cu.moved_to_path,
        cu.redirect_chain,
        'Content moved via redirect' AS move_type
    FROM crawl_comparison_urls cu
    JOIN crawl_comparison_sessions s ON s.id = cu.session_id
    WHERE cu.is_moved_content = TRUE
    """,
    """
    CREATE OR REPLACE VIEW view_content_differences AS
    SELECT
        cu.session_id,
        s.baseline_label,
        s.candidate_label,
        cu.path,
        cu.baseline_title,
        cu.candidate_title,
        cu.baseline_h1,
        cu.candidate_h1,
        cu.baseline_meta_description,
        cu.candidate_meta_description,
        cu.baseline_word_count,
        cu.candidate_word_count,
        CASE WHEN cu.baseline_title IS NOT DISTINCT FROM cu.candidate_title THEN 'Match' ELSE 'Different' END AS title_match,
        CASE WHEN cu.baseline_h1 IS NOT DISTINCT FROM cu.candidate_h1 THEN 'Match' ELSE 'Different' END AS h1_match,
        CASE WHEN cu.baseline_meta_description IS NOT DISTINCT FROM cu.candidate_meta_description THEN 'Match' ELSE 'Different' END AS meta_description_match,
        CASE WHEN cu.baseline_word_count = cu.candidate_word_count THEN 'Match' ELSE 'Different' END AS word_count_match
    FROM crawl_comparison_urls cu
    JOIN crawl_comparison_sessions s ON s.id = cu.session_id
    WHERE cu.exists_on_baseline AND cu.exists_on_candidate
      AND (
        cu.baseline_title IS DISTINCT FROM cu.candidate_title
        OR cu.baseline_h1 IS DISTINCT FROM cu.candidate_h1
        OR cu.baseline_meta_description IS DISTINCT FROM cu.candidate_meta_description
        OR cu.baseline_word_count IS DISTINCT FROM cu.candidate_word_count
      )
    """,
    """
    CREATE OR REPLACE VIEW view_schema_comparison AS
    SELECT
        cu.session_id,
        s.baseline_label,
        s.candidate_label,
        cu.path,
        cu.baseline_schema_types,
        cu.candidate_schema_types,
        CASE
            WHEN cu.baseline_schema_types IS NOT DISTINCT FROM cu.candidate_schema_types THEN 'Match'
            ELSE 'Different'
        END AS schema_match
    FROM crawl_comparison_urls cu
    JOIN crawl_comparison_sessions s ON s.id = cu.session_id
    WHERE cu.exists_on_baseline AND cu.exists_on_candidate
    """,
]


class AsyncpgStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self.pool is None:
            self.pool = await asyncpg.create_pool(dsn=self.dsn)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def initialize(self) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            for statement in SCHEMA_STATEMENTS:
                await conn.execute(statement)

    async def initialize_comparison_views(self) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            for statement in COMPARISON_VIEW_STATEMENTS:
                await conn.execute(statement)

    async def save_metadata(self, key: str, value: dict[str, object]) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO crawl_metadata (key, value_json, updated_at)
                VALUES ($1, $2, $3)
                ON CONFLICT (key) DO UPDATE
                SET value_json = EXCLUDED.value_json,
                    updated_at = EXCLUDED.updated_at
                """,
                key,
                json.dumps(value, sort_keys=True),
                int(time.time()),
            )

    async def _get_or_create_url(
        self,
        conn: asyncpg.Connection,
        url: str,
        *,
        kind: str = "html",
        classification: str = "internal",
        is_from_hreflang: bool = False,
    ) -> int:
        query = """
            INSERT INTO urls (url, kind, classification, is_from_hreflang)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (url) DO UPDATE
            SET kind = EXCLUDED.kind,
                classification = EXCLUDED.classification,
                is_from_hreflang = urls.is_from_hreflang OR EXCLUDED.is_from_hreflang
            RETURNING id
        """
        row = await conn.fetchrow(query, url, kind, classification, is_from_hreflang)
        return int(row["id"])

    async def _get_or_create_lookup(self, conn: asyncpg.Connection, table: str, column: str, value: str) -> int:
        row = await conn.fetchrow(
            f"""
            INSERT INTO {table} ({column})
            VALUES ($1)
            ON CONFLICT ({column}) DO UPDATE SET {column} = EXCLUDED.{column}
            RETURNING id
            """,
            value,
        )
        return int(row["id"])

    async def _bulk_get_or_create_urls(self, conn: asyncpg.Connection, urls: list[str]) -> dict[str, int]:
        if not urls:
            return {}
        unique_urls = list(set(urls))
        rows = await conn.fetch(
            """
            WITH input_urls AS (
                SELECT unnest($1::text[]) AS url
            ),
            inserted AS (
                INSERT INTO urls (url, kind, classification)
                SELECT url, 'html', 'internal' FROM input_urls
                ON CONFLICT (url) DO NOTHING
                RETURNING id, url
            )
            SELECT id, url FROM inserted
            UNION ALL
            SELECT u.id, u.url FROM urls u
            JOIN input_urls i ON u.url = i.url
            """,
            unique_urls,
        )
        return {str(r["url"]): int(r["id"]) for r in rows}

    async def _bulk_get_or_create_lookups(self, conn: asyncpg.Connection, table: str, column: str, values: list[str]) -> dict[str, int]:
        if not values:
            return {}
        unique_values = list(set(values))
        rows = await conn.fetch(
            f"""
            WITH input_vals AS (
                SELECT unnest($1::text[]) AS val
            ),
            inserted AS (
                INSERT INTO {table} ({column})
                SELECT val FROM input_vals
                ON CONFLICT ({column}) DO NOTHING
                RETURNING id, {column} AS val
            )
            SELECT id, val FROM inserted
            UNION ALL
            SELECT t.id, t.{column} AS val FROM {table} t
            JOIN input_vals i ON t.{column} = i.val
            """,
            unique_values,
        )
        return {str(r["val"]): int(r["id"]) for r in rows}

    async def enqueue_frontier(
        self,
        frontier_data: list[tuple[str, int, str | None, float | None] | tuple[str, int, str | None]],
        *,
        source: str | None = None,
        source_detail: str | None = None,
    ) -> int:
        """Lifted in shape from WIP batch_enqueue_frontier, narrowed to asyncpg only."""
        if not frontier_data:
            return 0

        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                urls_to_resolve: list[str] = []
                for item in frontier_data:
                    child_url = item[0]
                    parent_url = item[2] if len(item) > 2 else None
                    urls_to_resolve.append(child_url)
                    if parent_url:
                        urls_to_resolve.append(parent_url)

                url_to_id: dict[str, int] = {}
                for url in dict.fromkeys(urls_to_resolve):
                    url_to_id[url] = await self._get_or_create_url(conn, url)

                child_ids = [url_to_id[item[0]] for item in frontier_data]
                existing_rows = await conn.fetch(
                    """
                    SELECT url_id, status
                    FROM frontier
                    WHERE url_id = ANY($1::int[])
                    """,
                    child_ids,
                )
                existing_ids = {int(row["url_id"]) for row in existing_rows}
                filtered = [
                    item
                    for item in frontier_data
                    if url_to_id[item[0]] not in existing_ids
                ]
                if not filtered:
                    return 0

                current_time = int(time.time())
                batch_data = []
                for item in filtered:
                    child_url, depth, parent_url = item[0], item[1], item[2]
                    priority_score = float(item[3]) if len(item) > 3 and item[3] is not None else 0.0
                    batch_data.append(
                        (
                            url_to_id[child_url],
                            depth,
                            url_to_id[parent_url] if parent_url else None,
                            "queued",
                            current_time,
                            current_time,
                            priority_score,
                            0.5,
                            0,
                            1.0,
                            0,
                            0,
                            0,
                        )
                    )

                await conn.executemany(
                    """
                    INSERT INTO frontier (
                        url_id, depth, parent_id, status, enqueued_at, updated_at,
                        priority_score, sitemap_priority, inlinks_count, content_type_score, reset_count,
                        retry_count, retry_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                    ON CONFLICT (url_id) DO NOTHING
                    """,
                    batch_data,
                )
                if source:
                    source_batch = [
                        (url_to_id[item[0]], source, source_detail)
                        for item in filtered
                    ]
                    await conn.executemany(
                        """
                        INSERT INTO url_sources (url_id, source, detail)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (url_id, source, detail_key) DO NOTHING
                        """,
                        source_batch,
                    )
                return len(batch_data)

    async def frontier_next_batch(self, batch_size: int) -> list[tuple[str, int, str | None, int]]:
        """Lifted from WIP frontier_next_batch: atomically claim queued URLs as pending."""
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    """
                    SELECT f.url_id, u.url, f.depth, p.url AS parent_url, f.retry_count
                    FROM frontier f
                    JOIN urls u ON f.url_id = u.id
                    LEFT JOIN urls p ON f.parent_id = p.id
                    WHERE f.status = 'queued' AND f.retry_at <= $2
                    ORDER BY f.priority_score DESC, f.enqueued_at ASC
                    LIMIT $1
                    FOR UPDATE OF f SKIP LOCKED
                    """,
                    batch_size * 2,
                    int(time.time()),
                )
                if not rows:
                    return []

                unique_rows: list[asyncpg.Record] = []
                seen_urls: set[str] = set()
                for row in rows:
                    url = str(row["url"])
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    unique_rows.append(row)
                    if len(unique_rows) >= batch_size:
                        break

                claimed_ids = [int(row["url_id"]) for row in unique_rows]
                await conn.execute(
                    """
                    UPDATE frontier
                    SET status = 'pending', updated_at = $1
                    WHERE url_id = ANY($2::int[])
                    """,
                    int(time.time()),
                    claimed_ids,
                )
                return [
                    (
                        str(row["url"]),
                        int(row["depth"]),
                        str(row["parent_url"]) if row["parent_url"] else None,
                        int(row["retry_count"] or 0),
                    )
                    for row in unique_rows
                ]

    async def frontier_mark_retry(self, url: str, retry_count: int, delay_seconds: float) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            url_id = await self._get_or_create_url(conn, url)
            retry_at = int(time.time() + max(0.0, delay_seconds))
            await conn.execute(
                """
                UPDATE frontier
                SET status = 'queued',
                    retry_count = $2,
                    retry_at = $3,
                    updated_at = $4
                WHERE url_id = $1
                """,
                url_id,
                retry_count,
                retry_at,
                int(time.time()),
            )

    async def frontier_mark_done(self, urls: list[str]) -> None:
        if not urls:
            return

        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                url_ids = [await self._get_or_create_url(conn, url) for url in urls]
                current_time = int(time.time())
                await conn.execute(
                    """
                    INSERT INTO frontier (url_id, depth, status, enqueued_at, updated_at, priority_score, reset_count)
                    SELECT unnest_id, 0, 'done', $1, $1, 0.0, 0
                    FROM UNNEST($2::int[]) AS unnest_id
                    ON CONFLICT (url_id) DO UPDATE
                    SET status = 'done',
                        updated_at = EXCLUDED.updated_at,
                        reset_count = 0,
                        retry_count = 0,
                        retry_at = 0
                    WHERE frontier.status IN ('pending', 'queued')
                    """,
                    current_time,
                    url_ids,
                )

    async def frontier_reset_pending_to_queued(self, urls: list[str]) -> None:
        if not urls:
            return
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                url_ids = [await self._get_or_create_url(conn, url) for url in urls]
                await conn.execute(
                    """
                    UPDATE frontier
                    SET status = 'queued', updated_at = $1
                    WHERE url_id = ANY($2::int[]) AND status = 'pending'
                    """,
                    int(time.time()),
                    url_ids,
                )

    async def frontier_reset_all_pending_to_queued(self) -> int:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE frontier
                SET status = 'queued', updated_at = $1, reset_count = reset_count + 1
                WHERE status = 'pending'
                """,
                int(time.time()),
            )
        return int(result.split()[-1])

    async def record_source(self, url_id: int, source: str, detail: str | None = None) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO url_sources (url_id, source, detail)
                VALUES ($1, $2, $3)
                ON CONFLICT (url_id, source, detail_key) DO NOTHING
                """,
                url_id,
                source,
                detail,
            )

    async def record_source_by_url(self, url: str, source: str, detail: str | None = None) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            url_id = await self._get_or_create_url(conn, url)
            await conn.execute(
                """
                INSERT INTO url_sources (url_id, source, detail)
                VALUES ($1, $2, $3)
                ON CONFLICT (url_id, source, detail_key) DO NOTHING
                """,
                url_id,
                source,
                detail,
            )

    async def urls_with_source(self, source: str) -> list[str]:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT u.url
                FROM urls u
                JOIN url_sources us ON us.url_id = u.id
                WHERE us.source = $1
                ORDER BY u.url
                """,
                source,
            )
            return [str(row["url"]) for row in rows]

    async def simhash_neighbours(self, target: int, max_distance: int = 8) -> list[tuple[str, int]]:
        """Return URLs whose simhash is within Hamming distance of target."""
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT u.url, c.content_hash_simhash
                FROM content c
                JOIN urls u ON u.id = c.url_id
                WHERE c.content_hash_simhash IS NOT NULL
                """
            )
        results: list[tuple[str, int]] = []
        for row in rows:
            sim = row["content_hash_simhash"]
            if sim is None:
                continue
            try:
                sim_int = int(sim)
            except (ValueError, TypeError):
                continue
            distance = bin(sim_int ^ int(target)).count("1")
            if distance <= max_distance:
                results.append((str(row["url"]), distance))
        results.sort(key=lambda x: x[1])
        return results

    async def frontier_stats(self) -> tuple[int, int, int]:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            queued = await conn.fetchval("SELECT COUNT(*) FROM frontier WHERE status = 'queued'")
            pending = await conn.fetchval("SELECT COUNT(*) FROM frontier WHERE status = 'pending'")
            done = await conn.fetchval("SELECT COUNT(*) FROM frontier WHERE status = 'done'")
        return int(queued or 0), int(pending or 0), int(done or 0)

    async def persist(self, result: CrawlResult) -> None:
        """Persist crawl result to database.
        
        Always stores page_metadata so we know the URL was fetched and what
        status it returned. Only stores content/extracted data when extraction
        succeeded (extracted is not None).
        
        IMPORTANT: When the final URL differs from the requested URL (e.g., JS
        redirect in Playwright), extracted data (canonical, hreflang, robots,
        content) is stored against the FINAL URL — the URL that actually served
        the content. The requested URL only gets page_metadata recording the
        redirect.
        """
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                requested_url_id = await self._get_or_create_url(conn, result.requested_url)
                final_url_id = await self._get_or_create_url(conn, result.final_url)

                # Always store page_metadata for the REQUESTED URL
                # so we know the fetch was attempted and where it landed
                await conn.execute(
                    """
                    INSERT INTO page_metadata (url_id, initial_status_code, final_status_code, final_url_id, fetched_at)
                    VALUES ($1, $2, $3, $4, EXTRACT(EPOCH FROM NOW())::INTEGER)
                    ON CONFLICT (url_id) DO UPDATE
                    SET initial_status_code = EXCLUDED.initial_status_code,
                        final_status_code = EXCLUDED.final_status_code,
                        final_url_id = EXCLUDED.final_url_id,
                        fetched_at = EXCLUDED.fetched_at
                    """,
                    requested_url_id,
                    result.status,
                    result.status,
                    final_url_id,
                )

                if result.extracted is None:
                    # Fetch succeeded/failed but no extractable content
                    return

                # Determine which URL should own the extracted content.
                # If final_url differs from requested_url (JS redirect), the
                # content was served by the final URL, so store against final_url.
                content_url_id = final_url_id if result.final_url != result.requested_url else requested_url_id

                # Also store page_metadata for the final URL if it's different
                # (so it has a metadata record even if never directly crawled)
                if content_url_id != requested_url_id:
                    await conn.execute(
                        """
                        INSERT INTO page_metadata (url_id, initial_status_code, final_status_code, final_url_id, fetched_at)
                        VALUES ($1, $2, $3, $4, EXTRACT(EPOCH FROM NOW())::INTEGER)
                        ON CONFLICT (url_id) DO UPDATE
                        SET initial_status_code = EXCLUDED.initial_status_code,
                            final_status_code = EXCLUDED.final_status_code,
                            final_url_id = EXCLUDED.final_url_id,
                            fetched_at = EXCLUDED.fetched_at
                        """,
                        content_url_id,
                        result.status,
                        result.status,
                        final_url_id,
                    )

                # Store full content against the URL that actually served it
                await conn.execute(
                    """
                    INSERT INTO pages (url_id, headers_json, html_compressed)
                    VALUES ($1, $2, convert_to($3, 'UTF8'))
                    ON CONFLICT (url_id) DO UPDATE
                    SET headers_json = EXCLUDED.headers_json,
                        html_compressed = EXCLUDED.html_compressed
                    """,
                    content_url_id,
                    json.dumps(result.headers, sort_keys=True),
                    result.raw_html or "",
                )

                meta_description_id = None
                if result.extracted.meta_description:
                    meta_description_id = await self._get_or_create_lookup(
                        conn,
                        "meta_descriptions",
                        "description",
                        result.extracted.meta_description,
                    )

                html_lang_id = None
                if result.extracted.html_lang:
                    html_lang_id = await self._get_or_create_lookup(
                        conn,
                        "html_languages",
                        "language_code",
                        result.extracted.html_lang,
                    )

                await conn.execute(
                    """
                    INSERT INTO content (
                        url_id, title, meta_description_id, h1_tags, h2_tags, word_count, html_lang_id, content_length
                        , content_hash_sha256, content_hash_simhash
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    ON CONFLICT (url_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        meta_description_id = EXCLUDED.meta_description_id,
                        h1_tags = EXCLUDED.h1_tags,
                        h2_tags = EXCLUDED.h2_tags,
                        word_count = EXCLUDED.word_count,
                        html_lang_id = EXCLUDED.html_lang_id,
                        content_length = EXCLUDED.content_length,
                        content_hash_sha256 = EXCLUDED.content_hash_sha256,
                        content_hash_simhash = EXCLUDED.content_hash_simhash
                    """,
                    content_url_id,
                    result.extracted.title,
                    meta_description_id,
                    "\n".join(result.extracted.headings["h1"]),
                    "\n".join(result.extracted.headings["h2"]),
                    result.extracted.word_count,
                    html_lang_id,
                    len(result.raw_html or ""),
                    result.content_hash_sha256,
                    result.content_hash_simhash,
                )

                await self._persist_directives(conn, content_url_id, result)
                await self._persist_canonical(conn, content_url_id, result)
                await self._persist_hreflang(conn, content_url_id, result)
                if result.extracted.schema_data:
                    await self._persist_schema(conn, content_url_id, result.extracted.schema_data)
                if result.discovered_links:
                    await self._persist_internal_links(
                        conn,
                        content_url_id,
                        result.discovered_links,
                    )

                overall_indexable = (
                    result.status == 200
                    and not result.extracted.meta_robots.noindex
                    and not result.extracted.x_robots_tag.noindex
                )
                await conn.execute(
                    """
                    INSERT INTO indexability (url_id, html_meta_allows, http_header_allows, overall_indexable)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (url_id) DO UPDATE
                    SET html_meta_allows = EXCLUDED.html_meta_allows,
                        http_header_allows = EXCLUDED.http_header_allows,
                        overall_indexable = EXCLUDED.overall_indexable
                    """,
                    content_url_id,
                    not result.extracted.meta_robots.noindex,
                    not result.extracted.x_robots_tag.noindex,
                    overall_indexable,
                )

    async def _persist_directives(self, conn: asyncpg.Connection, url_id: int, result: CrawlResult) -> None:
        assert result.extracted is not None
        sources = {
            "html_meta": result.extracted.meta_robots.raw,
            "http_header": result.extracted.x_robots_tag.raw,
        }
        for source, directives in sources.items():
            for directive in directives:
                directive_id = await self._get_or_create_lookup(
                    conn,
                    "robots_directive_strings",
                    "directive",
                    directive,
                )
                await conn.execute(
                    """
                    INSERT INTO robots_directives (url_id, source, directive_id, value)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT DO NOTHING
                    """,
                    url_id,
                    source,
                    directive_id,
                    directive,
                )

    async def _persist_canonical(self, conn: asyncpg.Connection, url_id: int, result: CrawlResult) -> None:
        assert result.extracted is not None
        mappings = [
            ("html_head", result.extracted.canonical),
            ("http_header", result.extracted.x_canonical),
        ]
        for source, canonical_url in mappings:
            if not canonical_url:
                continue
            canonical_url_id = await self._get_or_create_url(conn, canonical_url)
            await conn.execute(
                """
                INSERT INTO canonical_urls (url_id, canonical_url_id, source)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                """,
                url_id,
                canonical_url_id,
                source,
            )

    async def _persist_hreflang(self, conn: asyncpg.Connection, url_id: int, result: CrawlResult) -> None:
        assert result.extracted is not None
        for link in result.extracted.hreflang_links:
            hreflang_id = await self._get_or_create_lookup(
                conn,
                "hreflang_languages",
                "language_code",
                link.hreflang,
            )
            href_url_id = await self._get_or_create_url(
                conn,
                link.href,
                classification="network",
                is_from_hreflang=True,
            )
            table_map = {
                "http_header": "hreflang_http_header",
                "html_head": "hreflang_html_head",
                "sitemap": "hreflang_sitemap",
            }
            table = table_map[link.source]
            await conn.execute(
                f"""
                INSERT INTO {table} (url_id, hreflang_id, href_url_id)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                """,
                url_id,
                hreflang_id,
                href_url_id,
            )

    @staticmethod
    def _parse_schema_position(position: object) -> int:
        if position is None:
            return 0
        if isinstance(position, int):
            return position
        if isinstance(position, str):
            try:
                return int(position.split("-")[0])
            except (ValueError, AttributeError):
                return 0
        return 0

    @staticmethod
    def _normalize_schema_format(format_type: str) -> str:
        if format_type in {"json-ld", "microdata", "rdfa"}:
            return format_type
        return "json-ld"

    async def _persist_schema(
        self,
        conn: asyncpg.Connection,
        url_id: int,
        schema_items: list[dict[str, object]],
    ) -> None:
        valid_formats = {"json-ld", "microdata", "rdfa"}
        persistable = [
            item
            for item in schema_items
            if item.get("format") in valid_formats or item.get("format") not in {"meta", "comment"}
        ]
        if not persistable:
            return

        async def get_or_create_schema_type_id(schema_type: str) -> int:
            row = await conn.fetchrow(
                """
                INSERT INTO schema_types (type_name)
                VALUES ($1)
                ON CONFLICT (type_name) DO UPDATE SET type_name = EXCLUDED.type_name
                RETURNING id
                """,
                schema_type,
            )
            return int(row["id"])

        async def get_or_create_schema_instance(schema_data: dict[str, object]) -> int:
            parsed_raw = schema_data.get("parsed_data")
            if parsed_raw:
                parsed_obj = json.loads(parsed_raw) if isinstance(parsed_raw, str) else parsed_raw
            else:
                parsed_obj = {}
            content_hash = schema_data.get("content_hash") or create_schema_content_hash(parsed_obj)
            existing = await conn.fetchrow(
                "SELECT id FROM schema_instances WHERE content_hash = $1",
                content_hash,
            )
            if existing:
                return int(existing["id"])

            schema_type = str(schema_data.get("type", "Unknown"))
            schema_type_id = await get_or_create_schema_type_id(schema_type)
            format_type = self._normalize_schema_format(str(schema_data.get("format", "json-ld")))
            validation_errors = schema_data.get("validation_errors", [])
            row = await conn.fetchrow(
                """
                INSERT INTO schema_instances (
                    content_hash, schema_type_id, format, raw_data, parsed_data,
                    is_valid, validation_errors, severity
                )
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7::jsonb, $8)
                ON CONFLICT (content_hash) DO UPDATE SET content_hash = EXCLUDED.content_hash
                RETURNING id
                """,
                content_hash,
                schema_type_id,
                format_type,
                schema_data.get("raw_data", ""),
                json.dumps(parsed_obj) if parsed_obj else None,
                schema_data.get("is_valid", True),
                json.dumps(validation_errors),
                schema_data.get("severity", "info"),
            )
            return int(row["id"])

        relationships = identify_schema_relationships(persistable)
        main_entity = relationships["main_entity"]
        properties = relationships["properties"]
        related_entities = relationships["related_entities"]
        now_ts = int(time.time())

        async def insert_ref(
            schema_instance_id: int,
            *,
            position: int = 0,
            is_main: bool = False,
            property_name: str | None = None,
            parent_id: int | None = None,
        ) -> int:
            row = await conn.fetchrow(
                """
                INSERT INTO page_schema_references (
                    url_id, schema_instance_id, position, property_name,
                    is_main_entity, parent_entity_id, discovered_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                url_id,
                schema_instance_id,
                position,
                property_name,
                is_main,
                parent_id,
                now_ts,
            )
            return int(row["id"])

        main_ref_id: int | None = None
        if main_entity:
            main_id = await get_or_create_schema_instance(main_entity)
            main_ref_id = await insert_ref(
                main_id,
                position=self._parse_schema_position(main_entity.get("position", 0)),
                is_main=True,
            )

        for prop in properties:
            inst_id = await get_or_create_schema_instance(prop)
            prop_name = str(prop.get("type", "")).lower() if prop.get("type") else None
            await insert_ref(
                inst_id,
                position=self._parse_schema_position(prop.get("position", 0)),
                property_name=prop_name,
                parent_id=main_ref_id,
            )

        for rel in related_entities:
            inst_id = await get_or_create_schema_instance(rel)
            await insert_ref(
                inst_id,
                position=self._parse_schema_position(rel.get("position", 0)),
                parent_id=main_ref_id,
            )

        for item in persistable:
            schema_type = str(item.get("type", "Unknown"))
            schema_type_id = await get_or_create_schema_type_id(schema_type)
            format_type = self._normalize_schema_format(str(item.get("format", "json-ld")))
            parsed_raw = item.get("parsed_data")
            if parsed_raw:
                parsed_json = parsed_raw if isinstance(parsed_raw, str) else json.dumps(parsed_raw)
            else:
                parsed_json = None
            await conn.execute(
                """
                INSERT INTO schema_data (
                    url_id, schema_type_id, format, raw_data, parsed_data,
                    position, is_valid, validation_errors, severity
                )
                VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8::jsonb, $9)
                ON CONFLICT (url_id, schema_type_id, position) DO UPDATE
                SET raw_data = EXCLUDED.raw_data,
                    parsed_data = EXCLUDED.parsed_data,
                    is_valid = EXCLUDED.is_valid,
                    validation_errors = EXCLUDED.validation_errors,
                    severity = EXCLUDED.severity
                """,
                url_id,
                schema_type_id,
                format_type,
                item.get("raw_data", ""),
                parsed_json,
                self._parse_schema_position(item.get("position", 0)),
                item.get("is_valid", True),
                json.dumps(item.get("validation_errors", [])),
                item.get("severity", "info"),
            )

    async def _persist_internal_links(
        self,
        conn: asyncpg.Connection,
        source_url_id: int,
        links: list[DiscoveredLink],
    ) -> None:
        if not links:
            return

        now_ts = int(time.time())
        batch: list[tuple[int, int | None, int | None, int | None, int, int | None, str | None, int]] = []
        seen: set[tuple[int, int, int | None, int | None, int | None, str | None]] = set()

        hrefs = [link.href for link in links]
        anchors = [link.anchor_text for link in links if link.anchor_text]
        xpaths = [link.xpath for link in links if link.xpath]
        fragments = [link.fragment for link in links if link.fragment]

        href_map = await self._bulk_get_or_create_urls(conn, hrefs)
        anchor_map = await self._bulk_get_or_create_lookups(conn, "anchor_texts", "text", anchors)
        xpath_map = await self._bulk_get_or_create_lookups(conn, "xpaths", "xpath", xpaths)
        fragment_map = await self._bulk_get_or_create_lookups(conn, "fragments", "fragment", fragments)

        for link in links:
            href_url_id = href_map.get(link.href)
            if not href_url_id:
                continue
            target_url_id = href_url_id

            anchor_text_id = anchor_map.get(link.anchor_text) if link.anchor_text else None
            xpath_id = xpath_map.get(link.xpath) if link.xpath else None
            fragment_id = fragment_map.get(link.fragment) if link.fragment else None

            dedupe_key = (
                source_url_id,
                href_url_id,
                anchor_text_id,
                xpath_id,
                fragment_id,
                link.url_parameters,
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            batch.append(
                (
                    source_url_id,
                    target_url_id,
                    anchor_text_id,
                    xpath_id,
                    href_url_id,
                    fragment_id,
                    link.url_parameters,
                    now_ts,
                )
            )

        if batch:
            await conn.executemany(
                """
                INSERT INTO internal_links (
                    source_url_id, target_url_id, anchor_text_id, xpath_id,
                    href_url_id, fragment_id, url_parameters, discovered_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (source_url_id, target_url_id, xpath_id) DO NOTHING
                """,
                batch,
            )

    async def fetch_pages_for_embeddings(
        self,
        *,
        urls: list[str] | None = None,
    ) -> list[tuple[int, str, str]]:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            if urls:
                rows = await conn.fetch(
                    """
                    SELECT p.url_id, u.url, convert_from(p.html_compressed, 'UTF8') AS html
                    FROM pages p
                    JOIN urls u ON u.id = p.url_id
                    WHERE u.url = ANY($1::text[]) AND p.html_compressed IS NOT NULL
                    """,
                    urls,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT p.url_id, u.url, convert_from(p.html_compressed, 'UTF8') AS html
                    FROM pages p
                    JOIN urls u ON u.id = p.url_id
                    WHERE p.html_compressed IS NOT NULL
                    """
                )
        return [(int(row["url_id"]), str(row["url"]), str(row["html"])) for row in rows]

    async def embedding_url_ids(self, *, model: str) -> set[int]:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT url_id FROM page_embeddings WHERE model = $1",
                model,
            )
        return {int(row["url_id"]) for row in rows}

    async def store_embedding(
        self,
        url_id: int,
        embedding: list[float],
        *,
        model: str,
        text_length: int,
    ) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO page_embeddings (url_id, embedding_json, model, text_length)
                VALUES ($1, $2::jsonb, $3, $4)
                ON CONFLICT (url_id) DO UPDATE
                SET embedding_json = EXCLUDED.embedding_json,
                    model = EXCLUDED.model,
                    text_length = EXCLUDED.text_length,
                    created_at = CURRENT_TIMESTAMP
                """,
                url_id,
                json.dumps(embedding),
                model,
                text_length,
            )

    async def persist_comparison_session(
        self,
        *,
        baseline_label: str,
        candidate_label: str,
        rows: list[dict[str, object]],
    ) -> int:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                session_id = await conn.fetchval(
                    """
                    INSERT INTO crawl_comparison_sessions (baseline_label, candidate_label)
                    VALUES ($1, $2)
                    RETURNING id
                    """,
                    baseline_label,
                    candidate_label,
                )
                batch = [
                    (
                        session_id,
                        row["path"],
                        row.get("baseline_url"),
                        row.get("candidate_url"),
                        row.get("exists_on_baseline", False),
                        row.get("exists_on_candidate", False),
                        row.get("baseline_title"),
                        row.get("candidate_title"),
                        row.get("baseline_h1"),
                        row.get("candidate_h1"),
                        row.get("baseline_meta_description"),
                        row.get("candidate_meta_description"),
                        row.get("baseline_word_count"),
                        row.get("candidate_word_count"),
                        row.get("is_moved_content", False),
                        row.get("moved_from_path"),
                        row.get("moved_to_path"),
                        row.get("redirect_chain"),
                        json.dumps(row.get("baseline_schema_types", [])),
                        json.dumps(row.get("candidate_schema_types", [])),
                        json.dumps(row.get("links_added", [])),
                        json.dumps(row.get("links_removed", [])),
                    )
                    for row in rows
                ]
                if batch:
                    await conn.executemany(
                        """
                        INSERT INTO crawl_comparison_urls (
                            session_id, path, baseline_url, candidate_url,
                            exists_on_baseline, exists_on_candidate,
                            baseline_title, candidate_title,
                            baseline_h1, candidate_h1,
                            baseline_meta_description, candidate_meta_description,
                            baseline_word_count, candidate_word_count,
                            is_moved_content, moved_from_path, moved_to_path, redirect_chain,
                            baseline_schema_types, candidate_schema_types,
                            links_added, links_removed
                        )
                        VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                            $15, $16, $17, $18, $19::jsonb, $20::jsonb, $21::jsonb, $22::jsonb
                        )
                        ON CONFLICT (session_id, path) DO UPDATE
                        SET baseline_url = EXCLUDED.baseline_url,
                            candidate_url = EXCLUDED.candidate_url,
                            exists_on_baseline = EXCLUDED.exists_on_baseline,
                            exists_on_candidate = EXCLUDED.exists_on_candidate,
                            baseline_title = EXCLUDED.baseline_title,
                            candidate_title = EXCLUDED.candidate_title,
                            baseline_h1 = EXCLUDED.baseline_h1,
                            candidate_h1 = EXCLUDED.candidate_h1,
                            baseline_meta_description = EXCLUDED.baseline_meta_description,
                            candidate_meta_description = EXCLUDED.candidate_meta_description,
                            baseline_word_count = EXCLUDED.baseline_word_count,
                            candidate_word_count = EXCLUDED.candidate_word_count,
                            is_moved_content = EXCLUDED.is_moved_content,
                            moved_from_path = EXCLUDED.moved_from_path,
                            moved_to_path = EXCLUDED.moved_to_path,
                            redirect_chain = EXCLUDED.redirect_chain,
                            baseline_schema_types = EXCLUDED.baseline_schema_types,
                            candidate_schema_types = EXCLUDED.candidate_schema_types,
                            links_added = EXCLUDED.links_added,
                            links_removed = EXCLUDED.links_removed
                        """,
                        batch,
                    )
                return int(session_id)

    async def fetch_pages_for_embeddings(
        self,
        *,
        urls: list[str] | None = None,
    ) -> list[tuple[int, str, str]]:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            if urls:
                rows = await conn.fetch(
                    """
                    SELECT p.url_id, u.url, convert_from(p.html_compressed, 'UTF8') AS html
                    FROM pages p
                    JOIN urls u ON u.id = p.url_id
                    WHERE u.url = ANY($1::text[]) AND p.html_compressed IS NOT NULL
                    """,
                    urls,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT p.url_id, u.url, convert_from(p.html_compressed, 'UTF8') AS html
                    FROM pages p
                    JOIN urls u ON u.id = p.url_id
                    WHERE p.html_compressed IS NOT NULL
                    """
                )
        return [(int(row["url_id"]), str(row["url"]), str(row["html"])) for row in rows]

    async def embedding_url_ids(self, *, model: str) -> set[int]:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT url_id FROM page_embeddings WHERE model = $1",
                model,
            )
        return {int(row["url_id"]) for row in rows}

    async def store_embedding(
        self,
        url_id: int,
        embedding: list[float],
        *,
        model: str,
        text_length: int,
    ) -> None:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO page_embeddings (url_id, embedding_json, model, text_length)
                VALUES ($1, $2::jsonb, $3, $4)
                ON CONFLICT (url_id) DO UPDATE
                SET embedding_json = EXCLUDED.embedding_json,
                    model = EXCLUDED.model,
                    text_length = EXCLUDED.text_length,
                    created_at = CURRENT_TIMESTAMP
                """,
                url_id,
                json.dumps(embedding),
                model,
                text_length,
            )

    async def persist_comparison_session(
        self,
        *,
        baseline_label: str,
        candidate_label: str,
        rows: list[dict[str, object]],
    ) -> int:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                session_id = await conn.fetchval(
                    """
                    INSERT INTO crawl_comparison_sessions (baseline_label, candidate_label)
                    VALUES ($1, $2)
                    RETURNING id
                    """,
                    baseline_label,
                    candidate_label,
                )
                batch = [
                    (
                        session_id,
                        row["path"],
                        row.get("baseline_url"),
                        row.get("candidate_url"),
                        row.get("exists_on_baseline", False),
                        row.get("exists_on_candidate", False),
                        row.get("baseline_title"),
                        row.get("candidate_title"),
                        row.get("baseline_h1"),
                        row.get("candidate_h1"),
                        row.get("baseline_meta_description"),
                        row.get("candidate_meta_description"),
                        row.get("baseline_word_count"),
                        row.get("candidate_word_count"),
                        row.get("is_moved_content", False),
                        row.get("moved_from_path"),
                        row.get("moved_to_path"),
                        row.get("redirect_chain"),
                        json.dumps(row.get("baseline_schema_types", [])),
                        json.dumps(row.get("candidate_schema_types", [])),
                        json.dumps(row.get("links_added", [])),
                        json.dumps(row.get("links_removed", [])),
                    )
                    for row in rows
                ]
                if batch:
                    await conn.executemany(
                        """
                        INSERT INTO crawl_comparison_urls (
                            session_id, path, baseline_url, candidate_url,
                            exists_on_baseline, exists_on_candidate,
                            baseline_title, candidate_title,
                            baseline_h1, candidate_h1,
                            baseline_meta_description, candidate_meta_description,
                            baseline_word_count, candidate_word_count,
                            is_moved_content, moved_from_path, moved_to_path, redirect_chain,
                            baseline_schema_types, candidate_schema_types,
                            links_added, links_removed
                        )
                        VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                            $15, $16, $17, $18, $19::jsonb, $20::jsonb, $21::jsonb, $22::jsonb
                        )
                        ON CONFLICT (session_id, path) DO UPDATE
                        SET baseline_url = EXCLUDED.baseline_url,
                            candidate_url = EXCLUDED.candidate_url,
                            exists_on_baseline = EXCLUDED.exists_on_baseline,
                            exists_on_candidate = EXCLUDED.exists_on_candidate,
                            baseline_title = EXCLUDED.baseline_title,
                            candidate_title = EXCLUDED.candidate_title,
                            baseline_h1 = EXCLUDED.baseline_h1,
                            candidate_h1 = EXCLUDED.candidate_h1,
                            baseline_meta_description = EXCLUDED.baseline_meta_description,
                            candidate_meta_description = EXCLUDED.candidate_meta_description,
                            baseline_word_count = EXCLUDED.baseline_word_count,
                            candidate_word_count = EXCLUDED.candidate_word_count,
                            is_moved_content = EXCLUDED.is_moved_content,
                            moved_from_path = EXCLUDED.moved_from_path,
                            moved_to_path = EXCLUDED.moved_to_path,
                            redirect_chain = EXCLUDED.redirect_chain,
                            baseline_schema_types = EXCLUDED.baseline_schema_types,
                            candidate_schema_types = EXCLUDED.candidate_schema_types,
                            links_added = EXCLUDED.links_added,
                            links_removed = EXCLUDED.links_removed
                        """,
                        batch,
                    )
                return int(session_id)
