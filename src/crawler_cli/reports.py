from __future__ import annotations

import json

from .persistence import AsyncpgStore


class CrawlReports:
    """SQL reports scoped to a single crawl run (ticket 095).

    Frontier-derived metrics always filter by ``run_id``. Page-level metrics
    read ``page_run_snapshots`` so historical values stay distinguishable when
    the same URL is crawled in multiple runs.
    """

    def __init__(self, store: AsyncpgStore, *, run_id: str) -> None:
        self.store = store
        self.run_id = run_id

    async def orphan_pages(self) -> list[dict[str, object]]:
        return await self._fetch(
            """
            SELECT u.url
            FROM urls u
            JOIN frontier f ON f.url_id = u.id AND f.run_id = $1
            WHERE u.kind = 'html' AND f.parent_id IS NULL
            ORDER BY u.url
            """,
            self.run_id,
        )

    async def indexability_reasons(self) -> list[dict[str, object]]:
        return await self._fetch(
            """
            SELECT u.url, s.html_meta_allows, s.http_header_allows, s.overall_indexable
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1
            ORDER BY u.url
            """,
            self.run_id,
        )

    async def redirect_chains(self) -> list[dict[str, object]]:
        return await self._fetch(
            """
            SELECT src.url AS requested_url, dst.url AS final_url,
                   s.initial_status_code, s.final_status_code
            FROM page_run_snapshots s
            JOIN urls src ON src.id = s.url_id
            JOIN urls dst ON dst.id = s.final_url_id
            WHERE s.run_id = $1 AND s.url_id <> s.final_url_id
            ORDER BY src.url
            """,
            self.run_id,
        )

    async def site_hub_pages(self, min_outlinks: int = 5) -> list[dict[str, object]]:
        return await self._fetch(
            """
            SELECT p.url AS parent_url, COUNT(*)::INT AS outlinks
            FROM frontier f
            JOIN urls p ON p.id = f.parent_id
            WHERE f.run_id = $1 AND f.parent_id IS NOT NULL
            GROUP BY p.url
            HAVING COUNT(*) >= $2
            ORDER BY outlinks DESC, p.url
            """,
            self.run_id,
            min_outlinks,
        )

    async def slowest_pages(self, limit: int = 50) -> list[dict[str, object]]:
        """Pages ranked by total fetch duration (ticket 029 perf metrics)."""
        return await self._fetch(
            """
            SELECT u.url, s.ttfb_seconds, s.total_duration_seconds, s.final_status_code
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1 AND s.total_duration_seconds IS NOT NULL
            ORDER BY s.total_duration_seconds DESC
            LIMIT $2
            """,
            self.run_id,
            limit,
        )

    async def worst_cwv_pages(self, limit: int = 50) -> list[dict[str, object]]:
        """Pages ranked by worst lab Core Web Vitals (ticket 046).

        Ranking is by LCP (the headline metric); CLS and INP are included for
        context. Only pages that recorded at least one CWV value are returned —
        HTTP-backend crawls leave them null and are excluded.
        """
        return await self._fetch(
            """
            SELECT u.url, s.lcp_ms, s.cls, s.inp_ms, s.final_status_code
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1
              AND (s.lcp_ms IS NOT NULL OR s.cls IS NOT NULL OR s.inp_ms IS NOT NULL)
            ORDER BY s.lcp_ms DESC NULLS LAST, s.cls DESC NULLS LAST
            LIMIT $2
            """,
            self.run_id,
            limit,
        )

    async def as_json(self) -> str:
        payload = {
            "run_id": self.run_id,
            "orphans": await self.orphan_pages(),
            "indexability": await self.indexability_reasons(),
            "redirect_chains": await self.redirect_chains(),
            "hub_pages": await self.site_hub_pages(),
        }
        return json.dumps(payload, indent=2, sort_keys=True)

    async def comparison_summary(self, session_id: int) -> dict[str, object]:
        return {
            "url_moves": await self.view_url_moves(session_id),
            "content_differences": await self.view_content_differences(session_id),
            "schema_comparison": await self.view_schema_comparison(session_id),
        }

    async def view_url_moves(self, session_id: int) -> list[dict[str, object]]:
        return await self._fetch(
            """
            SELECT path, moved_from_path, moved_to_path, redirect_chain
            FROM crawl_comparison_urls
            WHERE session_id = $1 AND is_moved_content = TRUE
            ORDER BY path
            """,
            session_id,
        )

    async def view_content_differences(self, session_id: int) -> list[dict[str, object]]:
        return await self._fetch(
            """
            SELECT path, baseline_title, candidate_title, baseline_h1, candidate_h1,
                   baseline_meta_description, candidate_meta_description,
                   baseline_word_count, candidate_word_count
            FROM crawl_comparison_urls
            WHERE session_id = $1
              AND exists_on_baseline AND exists_on_candidate
              AND (
                baseline_title IS DISTINCT FROM candidate_title
                OR baseline_h1 IS DISTINCT FROM candidate_h1
                OR baseline_meta_description IS DISTINCT FROM candidate_meta_description
                OR baseline_word_count IS DISTINCT FROM candidate_word_count
              )
            ORDER BY path
            """,
            session_id,
        )

    async def view_schema_comparison(self, session_id: int) -> list[dict[str, object]]:
        return await self._fetch(
            """
            SELECT path, baseline_schema_types, candidate_schema_types
            FROM crawl_comparison_urls
            WHERE session_id = $1
              AND exists_on_baseline AND exists_on_candidate
              AND baseline_schema_types IS DISTINCT FROM candidate_schema_types
            ORDER BY path
            """,
            session_id,
        )

    async def pages_missing_analytics(self, vendor: str | None = None) -> list[dict[str, object]]:
        """Pages with zero analytics hits (optionally filtered to a specific vendor)."""
        if vendor:
            return await self._fetch(
                """
                SELECT u.url
                FROM page_run_snapshots s
                JOIN urls u ON u.id = s.url_id
                WHERE s.run_id = $1
                  AND u.kind = 'html'
                  AND (
                      s.analytics_json IS NULL
                      OR NOT EXISTS (
                          SELECT 1
                          FROM jsonb_array_elements(s.analytics_json) hit
                          WHERE hit->>'vendor' = $2
                      )
                  )
                ORDER BY u.url
                """,
                self.run_id,
                vendor,
            )
        return await self._fetch(
            """
            SELECT u.url
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1
              AND u.kind = 'html'
              AND (
                  s.analytics_json IS NULL
                  OR jsonb_array_length(s.analytics_json) = 0
              )
            ORDER BY u.url
            """,
            self.run_id,
        )

    async def pages_missing_expected_id(self, expected_id: str) -> list[dict[str, object]]:
        """Pages where the expected identifier is not present."""
        return await self._fetch(
            """
            SELECT u.url
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1
              AND u.kind = 'html'
              AND (
                  s.analytics_json IS NULL
                  OR NOT EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements(s.analytics_json) hit
                      WHERE hit->>'identifier' = $2
                  )
              )
            ORDER BY u.url
            """,
            self.run_id,
            expected_id,
        )

    async def analytics_inventory(self) -> list[dict[str, object]]:
        """Rollup of (vendor, identifier, page_count) for this run."""
        return await self._fetch(
            """
            SELECT hit->>'vendor' AS vendor,
                   hit->>'category' AS category,
                   hit->>'identifier' AS identifier,
                   COUNT(DISTINCT s.url_id)::INT AS page_count
            FROM page_run_snapshots s
            CROSS JOIN LATERAL jsonb_array_elements(COALESCE(s.analytics_json, '[]'::jsonb)) hit
            WHERE s.run_id = $1
            GROUP BY hit->>'vendor', hit->>'category', hit->>'identifier'
            ORDER BY page_count DESC, vendor, identifier
            """,
            self.run_id,
        )

    async def analytics_per_page(self, url: str) -> list[dict[str, object]]:
        """Full hit list for a single URL within this run."""
        return await self._fetch(
            """
            SELECT u.url,
                   hit->>'vendor' AS vendor,
                   hit->>'category' AS category,
                   hit->>'identifier' AS identifier,
                   hit->>'evidence_type' AS evidence_type,
                   NULL::text AS evidence_snippet,
                   (hit->>'confidence')::real AS confidence,
                   NULL::timestamptz AS detected_at
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            CROSS JOIN LATERAL jsonb_array_elements(COALESCE(s.analytics_json, '[]'::jsonb)) hit
            WHERE s.run_id = $1 AND u.url = $2
            ORDER BY confidence DESC NULLS LAST, vendor
            """,
            self.run_id,
            url,
        )

    async def create_materialized_views(self) -> None:
        await self.store.connect()
        assert self.store.pool is not None
        async with self.store.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE MATERIALIZED VIEW IF NOT EXISTS crawler_orphan_pages AS
                SELECT u.url, f.run_id
                FROM urls u
                JOIN frontier f ON f.url_id = u.id
                WHERE u.kind = 'html' AND f.parent_id IS NULL
                """
            )

    async def _fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        await self.store.connect()
        assert self.store.pool is not None
        async with self.store.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]
