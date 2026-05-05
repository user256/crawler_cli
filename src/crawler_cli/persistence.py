from __future__ import annotations

import asyncpg
import json
import time

from .models import CrawlResult


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

    async def enqueue_frontier(
        self,
        frontier_data: list[tuple[str, int, str | None, float | None] | tuple[str, int, str | None]],
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
                    child_url, _, parent_url = item[0], item[1], item[2]
                    urls_to_resolve.append(child_url)
                    if parent_url:
                        urls_to_resolve.append(parent_url)

                url_to_id: dict[str, int] = {}
                for url in dict.fromkeys(urls_to_resolve):
                    url_to_id[url] = await self._get_or_create_url(conn, url)

                child_ids = [url_to_id[child_url] for child_url, _, _ in frontier_data]
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

    async def frontier_stats(self) -> tuple[int, int, int]:
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            queued = await conn.fetchval("SELECT COUNT(*) FROM frontier WHERE status = 'queued'")
            pending = await conn.fetchval("SELECT COUNT(*) FROM frontier WHERE status = 'pending'")
            done = await conn.fetchval("SELECT COUNT(*) FROM frontier WHERE status = 'done'")
        return int(queued or 0), int(pending or 0), int(done or 0)

    async def persist(self, result: CrawlResult) -> None:
        if result.extracted is None:
            return
        await self.connect()
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                url_id = await self._get_or_create_url(conn, result.requested_url)
                final_url_id = await self._get_or_create_url(conn, result.final_url)

                await conn.execute(
                    """
                    INSERT INTO pages (url_id, headers_json, html_compressed)
                    VALUES ($1, $2, convert_to($3, 'UTF8'))
                    ON CONFLICT (url_id) DO UPDATE
                    SET headers_json = EXCLUDED.headers_json,
                        html_compressed = EXCLUDED.html_compressed
                    """,
                    url_id,
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
                    url_id,
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
                    url_id,
                    result.status,
                    result.status,
                    final_url_id,
                )

                await self._persist_directives(conn, url_id, result)
                await self._persist_canonical(conn, url_id, result)
                await self._persist_hreflang(conn, url_id, result)

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
                    url_id,
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
