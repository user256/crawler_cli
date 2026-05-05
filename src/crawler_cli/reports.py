from __future__ import annotations

import json

from .persistence import AsyncpgStore


class CrawlReports:
    def __init__(self, store: AsyncpgStore) -> None:
        self.store = store

    async def orphan_pages(self) -> list[dict[str, object]]:
        return await self._fetch(
            """
            SELECT u.url
            FROM urls u
            LEFT JOIN frontier f ON f.url_id = u.id
            WHERE u.kind = 'html' AND f.parent_id IS NULL
            ORDER BY u.url
            """
        )

    async def indexability_reasons(self) -> list[dict[str, object]]:
        return await self._fetch(
            """
            SELECT u.url, i.html_meta_allows, i.http_header_allows, i.overall_indexable
            FROM indexability i
            JOIN urls u ON u.id = i.url_id
            ORDER BY u.url
            """
        )

    async def redirect_chains(self) -> list[dict[str, object]]:
        return await self._fetch(
            """
            SELECT src.url AS requested_url, dst.url AS final_url, pm.initial_status_code, pm.final_status_code
            FROM page_metadata pm
            JOIN urls src ON src.id = pm.url_id
            JOIN urls dst ON dst.id = pm.final_url_id
            WHERE pm.url_id <> pm.final_url_id
            ORDER BY src.url
            """
        )

    async def site_hub_pages(self, min_outlinks: int = 5) -> list[dict[str, object]]:
        return await self._fetch(
            """
            SELECT p.url AS parent_url, COUNT(*)::INT AS outlinks
            FROM frontier f
            JOIN urls p ON p.id = f.parent_id
            WHERE f.parent_id IS NOT NULL
            GROUP BY p.url
            HAVING COUNT(*) >= $1
            ORDER BY outlinks DESC, p.url
            """,
            min_outlinks,
        )

    async def as_json(self) -> str:
        payload = {
            "orphans": await self.orphan_pages(),
            "indexability": await self.indexability_reasons(),
            "redirect_chains": await self.redirect_chains(),
            "hub_pages": await self.site_hub_pages(),
        }
        return json.dumps(payload, indent=2, sort_keys=True)

    async def create_materialized_views(self) -> None:
        await self.store.connect()
        assert self.store.pool is not None
        async with self.store.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE MATERIALIZED VIEW IF NOT EXISTS crawler_orphan_pages AS
                SELECT u.url
                FROM urls u
                LEFT JOIN frontier f ON f.url_id = u.id
                WHERE u.kind = 'html' AND f.parent_id IS NULL
                """
            )

    async def _fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        await self.store.connect()
        assert self.store.pool is not None
        async with self.store.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]

