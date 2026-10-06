from __future__ import annotations

import json
import re
from typing import Any, cast
from urllib.parse import parse_qsl, urljoin, urlparse

from .amp import urls_match
from .hashing import hamming64
from .html_audit import canonical_targets, inspect_stored_html
from .hreflang_audit import hreflang_facts
from .semantic_html_audit import inspect_semantic_html
from .persistence import AsyncpgStore


_TRACKING_PARAMETERS = {
    "_ga",
    "_gl",
    "dclid",
    "fbclid",
    "gclid",
    "gbraid",
    "msclkid",
    "utm_campaign",
    "utm_content",
    "utm_id",
    "utm_medium",
    "utm_source",
    "utm_term",
    "wbraid",
}
_LINK_CANONICAL = re.compile(r"<([^>]+)>[^,]*\brel\s*=\s*\"?canonical\"?", re.IGNORECASE)
_SOFT_404_SIGNATURE = re.compile(r"\b(?:404|page\s+not\s+found|not\s+found|error\s+page)\b", re.IGNORECASE)


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class CrawlReports:
    def __init__(self, store: AsyncpgStore, *, run_id: str | None = None) -> None:
        self.store = store
        self.run_id = run_id

    async def _run_id(self) -> str:
        """Resolve the selected report run without silently choosing one."""
        return await self.store.resolve_reporting_run_id(self.run_id)

    async def technical_audit_context(self) -> dict[str, object]:
        """Return scope, completion and extraction denominators for one run.

        Do not emit the full crawl config or seed URLs: they may contain
        credentials, private route names or query values. The returned scope
        summary is useful for coverage without copying those values into audit
        artifacts.
        """
        run_id = await self._run_id()
        run = await self.store.get_crawl_run(run_id)
        if run is None:
            raise ValueError(f"crawl run not found: {run_id}")
        column_rows = await self._fetch(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = current_schema()
                 AND table_name = 'page_run_snapshots'"""
        )
        snapshot_columns = {str(row["column_name"]) for row in column_rows}
        has_extraction_state = "content_extracted" in snapshot_columns
        has_images = "images_json" in snapshot_columns
        signature_table_rows = await self._fetch(
            """SELECT EXISTS (
                 SELECT 1 FROM information_schema.tables
                 WHERE table_schema = current_schema() AND table_name = 'run_intent_signatures'
               ) AS present"""
        )
        has_signatures = bool(signature_table_rows and signature_table_rows[0].get("present"))
        extraction_true = "s.content_extracted IS TRUE" if has_extraction_state else "FALSE"
        extraction_false = "s.content_extracted IS FALSE" if has_extraction_state else "FALSE"
        extraction_unknown = "s.content_extracted IS NULL" if has_extraction_state else "TRUE"
        image_count = "COALESCE(SUM(jsonb_array_length(s.images_json)), 0)::INT" if has_images else "NULL::INT"
        coverage = await self._fetch(
            f"""
            SELECT
                COUNT(*)::INT AS snapshot_count,
                COUNT(*) FILTER (WHERE u.kind = 'html')::INT AS html_count,
                COUNT(*) FILTER (
                    WHERE u.kind = 'html' AND s.final_status_code BETWEEN 200 AND 299
                )::INT AS successful_html_count,
                COUNT(*) FILTER (
                    WHERE u.kind = 'html' AND {extraction_true}
                )::INT AS parsed_html_count,
                COUNT(*) FILTER (
                    WHERE u.kind = 'html' AND {extraction_false}
                )::INT AS unparsed_html_count,
                COUNT(*) FILTER (
                    WHERE u.kind = 'html' AND {extraction_unknown}
                )::INT AS extraction_state_unknown_html_count,
                COUNT(*) FILTER (
                    WHERE u.kind = 'html' AND s.html_compressed IS NOT NULL
                )::INT AS stored_html_count,
                COUNT(*) FILTER (
                    WHERE u.kind <> 'html'
                      AND lower(regexp_replace(u.url, '[?#].*$', ''))
                            ~ '\\.(pdf|docx?|xlsx?|pptx?)$'
                )::INT AS nonhtml_document_count,
                COUNT(*) FILTER (WHERE s.challenge IS NOT NULL)::INT AS challenged_count,
                COUNT(*) FILTER (WHERE s.final_status_code IN (429, 503))::INT AS rate_limited_count,
                COUNT(*) FILTER (WHERE s.content_hash_simhash IS NOT NULL)::INT AS hashed_count,
                {image_count} AS image_reference_count,
                MAX(s.fetched_at)::BIGINT AS last_snapshot_at
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1
            """,
            run_id,
        )
        stats = dict(coverage[0]) if coverage else {}
        locale_signature_count: int | None = None
        if has_signatures:
            signature_coverage = await self._fetch(
                """
                SELECT COUNT(DISTINCT sig.signature_hash)::INT AS locale_signature_count
                FROM page_run_snapshots s
                JOIN run_intent_signatures sig ON sig.run_id = s.run_id AND sig.url_id = s.url_id
                WHERE s.run_id = $1
                  AND s.overall_indexable IS TRUE
                  AND s.content_extracted IS TRUE
                  AND NULLIF(s.html_lang, '') IS NOT NULL
                  AND jsonb_array_length(s.hreflang_json) > 0
                  AND sig.signature_hash IS NOT NULL
                """,
                run_id,
            )
            locale_signature_count = (
                _int_or_none(signature_coverage[0].get("locale_signature_count")) if signature_coverage else 0
            )
        if not has_extraction_state:
            stats["parsed_html_count"] = None
            stats["unparsed_html_count"] = None
        config = run.get("config") if isinstance(run.get("config"), dict) else {}
        seed_urls = run.get("seed_urls") if isinstance(run.get("seed_urls"), list) else []
        seed_hosts = sorted({parsed.hostname.lower() for seed in seed_urls if (parsed := urlparse(str(seed))).hostname})
        declared_hosts = config.get("allowed_hosts", [])
        if not isinstance(declared_hosts, list):
            declared_hosts = []
        declared_hosts = sorted({str(host).lower() for host in declared_hosts if host})
        frontier = await self.store.frontier_stats(run_id=run_id)
        run_status = str(run.get("status", "unknown"))
        completion_state = "complete" if run_status == "complete" else run_status
        return {
            "run_id": run_id,
            "run_status": run_status,
            "completion_state": completion_state,
            "mode": str(run.get("mode", "unknown")),
            "created_at": run.get("created_at"),
            "updated_at": run.get("updated_at"),
            "config_hash": str(run.get("config_hash", "")),
            "config_keys": sorted(str(key) for key in config),
            "seed_count": len(seed_urls),
            "seed_hosts": seed_hosts,
            "declared_allowed_hosts": declared_hosts,
            "schema_capabilities": {
                "content_extracted": has_extraction_state,
                "images_json": has_images,
                "links_json": "links_json" in snapshot_columns,
                "content_hash_simhash": "content_hash_simhash" in snapshot_columns,
                "run_intent_signatures": has_signatures,
            },
            "frontier_queued": frontier[0],
            "frontier_pending": frontier[1],
            "frontier_done": frontier[2],
            "locale_signature_count": locale_signature_count,
            **stats,
        }

    async def orphan_pages(self) -> list[dict[str, object]]:
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT u.url
            FROM page_run_snapshots s JOIN urls u ON u.id = s.url_id
            LEFT JOIN frontier f ON f.run_id = s.run_id AND f.url_id = u.id
            WHERE s.run_id = $1 AND u.kind = 'html' AND f.parent_id IS NULL
            ORDER BY u.url
            """,
            run_id,
        )

    async def indexability_reasons(self) -> list[dict[str, object]]:
        run_id = await self._run_id()
        column_rows = await self._fetch(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = current_schema()
                 AND table_name = 'page_run_snapshots'"""
        )
        has_extraction_state = any(row["column_name"] == "content_extracted" for row in column_rows)
        extraction_field = "s.content_extracted" if has_extraction_state else "NULL::BOOLEAN"
        return await self._fetch(
            f"""
            SELECT u.url, s.html_meta_allows, s.http_header_allows, s.overall_indexable,
                   {extraction_field} AS content_extracted
            FROM page_run_snapshots s JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1
            ORDER BY u.url
            """,
            run_id,
        )

    async def stored_html_findings(self) -> list[dict[str, object]]:
        """Inspect saved source for raw-markup facts lost by normal extraction."""
        run_id = await self._run_id()
        pages = await self.store.fetch_pages_for_embeddings(run_id=run_id)
        page_state = {
            str(row["url"]): row
            for row in await self._fetch(
                """
                SELECT u.url, s.overall_indexable, s.final_status_code, s.headers_json
                FROM page_run_snapshots s
                JOIN urls u ON u.id = s.url_id
                WHERE s.run_id = $1 AND s.html_compressed IS NOT NULL
                """,
                run_id,
            )
        }
        findings: list[dict[str, object]] = []
        for _url_id, url, html in pages:
            state = page_state.get(url, {})
            headers = state.get("headers_json")
            header_values = headers.values() if isinstance(headers, dict) else ()
            header_canonicals = [
                target
                for value in header_values
                for target in _LINK_CANONICAL.findall(str(value))
            ]
            has_link_canonical = any(
                "rel=canonical" in str(value).replace('"', "").replace("'", "").replace(" ", "").casefold()
                for value in header_values
            )
            for finding in inspect_stored_html(url, html):
                # Either an HTML canonical or an HTTP Link canonical satisfies
                # Q71.  The header/HTML consistency comparison is Q94.
                if finding["kind"] == "missing-canonical" and has_link_canonical:
                    continue
                finding["overall_indexable"] = state.get("overall_indexable")
                finding["final_status_code"] = state.get("final_status_code")
                findings.append(finding)
            html_canonicals = canonical_targets(url, html)
            parsed_url = urlparse(url)
            homepage = f"{parsed_url.scheme}://{parsed_url.netloc}/"
            for canonical in [*html_canonicals, *(urljoin(url, target) for target in header_canonicals)]:
                if not urls_match(url, homepage) and urls_match(canonical, homepage):
                    findings.append(
                        {
                            "url": url,
                            "kind": "canonical-to-homepage",
                            "canonical": canonical,
                            "overall_indexable": state.get("overall_indexable"),
                            "final_status_code": state.get("final_status_code"),
                        }
                    )
            for header_canonical in header_canonicals:
                if html_canonicals and not any(urls_match(header_canonical, html_canonical) for html_canonical in html_canonicals):
                    findings.append(
                        {
                            "url": url,
                            "kind": "html-header-canonical-mismatch",
                            "html_canonicals": html_canonicals,
                            "header_canonical": header_canonical,
                            "overall_indexable": state.get("overall_indexable"),
                            "final_status_code": state.get("final_status_code"),
                        }
                    )
        return findings

    async def duplicate_metadata(self) -> list[dict[str, object]]:
        """Find duplicate titles or H1s among indexable self-canonical pages."""
        run_id = await self._run_id()
        pages = await self._fetch(
            """
            SELECT u.url, s.title, s.h1_tags, s.canonical_urls_json
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1
              AND s.overall_indexable IS TRUE
              AND s.final_status_code = 200
              AND s.content_extracted IS TRUE
            ORDER BY u.url
            """,
            run_id,
        )
        values: dict[tuple[str, str], list[str]] = {}
        for page in pages:
            url = str(page["url"])
            canonicals = page.get("canonical_urls_json")
            if not isinstance(canonicals, list) or not any(urls_match(url, str(item)) for item in canonicals if item):
                continue
            for field, raw_value in (("title", page.get("title")), ("h1", page.get("h1_tags"))):
                value = str(raw_value or "").strip()
                if value:
                    values.setdefault((field, value), []).append(url)
        findings = []
        for (field, value), urls in sorted(values.items()):
            if len(urls) > 1:
                findings.append({"field": field, "value": value, "count": len(urls), "urls": urls, "url": "\n".join(urls)})
        return findings

    async def nonhtml_search_assets(self) -> list[dict[str, object]]:
        """Return fetched office/PDF documents without an index-control header."""
        run_id = await self._run_id()
        rows = await self._fetch(
            """
            SELECT u.url, s.final_status_code, s.headers_json
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1
              AND u.kind <> 'html'
              AND lower(regexp_replace(u.url, '[?#].*$', ''))
                    ~ '\\.(pdf|docx?|xlsx?|pptx?)$'
            ORDER BY u.url
            """,
            run_id,
        )
        findings = []
        for row in rows:
            headers = row.get("headers_json")
            values = headers.values() if isinstance(headers, dict) else ()
            joined_headers = "\n".join(str(value) for value in values).casefold()
            if row.get("final_status_code") == 200 and "x-robots-tag" not in joined_headers and "rel=canonical" not in joined_headers.replace('"', "").replace("'", "").replace(" ", ""):
                findings.append({"url": row["url"], "final_status_code": 200, "headers_present": bool(headers)})
        return findings

    async def hreflang_validation(self) -> list[dict[str, object]]:
        """Validate saved HTML/header hreflang edges against saved targets."""
        run_id = await self._run_id()
        pages = await self._fetch(
            """
            SELECT u.url, s.hreflang_json, s.final_status_code, s.overall_indexable,
                   s.canonical_urls_json, s.html_lang
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1 AND s.content_extracted IS TRUE
            ORDER BY u.url
            """,
            run_id,
        )
        return hreflang_facts(pages)

    async def semantic_html_facts(self) -> list[dict[str, object]]:
        """Return one bounded source-HTML semantic fact row per stored page."""
        run_id = await self._run_id()
        pages = await self.store.fetch_pages_for_embeddings(run_id=run_id)
        return [inspect_semantic_html(url, html).as_dict() for _url_id, url, html in pages]

    async def profile_indexability_pages(self) -> list[dict[str, object]]:
        """Saved page facts for profile policy evaluation; no policy is inferred here."""
        run_id = await self._run_id()
        return await self._fetch(
            """
            WITH page_facts AS (
                SELECT u.id, u.url, u.is_from_sitemap, s.final_status_code AS status,
                       s.overall_indexable AS indexable,
                       (s.html_meta_allows IS FALSE OR s.http_header_allows IS FALSE) AS noindex,
                       s.canonical_urls_json ->> 0 AS canonical, s.word_count,
                       COUNT(f.parent_id)::INT AS inlink_count
                FROM page_run_snapshots s
                JOIN urls u ON u.id = s.url_id
                LEFT JOIN frontier f ON f.run_id = s.run_id AND f.url_id = s.url_id AND f.parent_id IS NOT NULL
                WHERE s.run_id = $1 AND u.kind = 'html' AND s.content_extracted IS TRUE
                GROUP BY u.id, u.url, u.is_from_sitemap, s.final_status_code,
                         s.overall_indexable, s.html_meta_allows, s.http_header_allows,
                         s.canonical_urls_json, s.word_count
            )
            SELECT url, is_from_sitemap AS in_sitemap, status, indexable, noindex,
                   canonical, word_count, inlink_count,
                   percent_rank() OVER (ORDER BY inlink_count)::DOUBLE PRECISION AS inlink_percentile
            FROM page_facts
            ORDER BY url
            """,
            run_id,
        )

    async def soft404_error_routes(self) -> list[dict[str, object]]:
        """Conservative saved-source candidates for 200 error pages."""
        run_id = await self._run_id()
        states = {
            str(row["url"]): row
            for row in await self._fetch(
                """
                SELECT u.url, s.final_status_code, s.title
                FROM page_run_snapshots s JOIN urls u ON u.id = s.url_id
                WHERE s.run_id = $1 AND s.html_compressed IS NOT NULL
                """,
                run_id,
            )
        }
        findings: list[dict[str, object]] = []
        for _url_id, url, html in await self.store.fetch_pages_for_embeddings(run_id=run_id):
            state = states.get(url, {})
            if state.get("final_status_code") != 200:
                continue
            title = str(state.get("title") or "")
            source_text = re.sub(r"<[^>]+>", " ", html)
            title_match = _SOFT_404_SIGNATURE.search(title)
            body_match = _SOFT_404_SIGNATURE.search(source_text)
            if title_match or body_match:
                findings.append(
                    {
                        "url": url,
                        "final_status_code": 200,
                        "title": title,
                        "signature_source": "title" if title_match else "source_text",
                        "signature": (title_match or body_match).group(0),
                    }
                )
        return findings

    async def discovery_source_provenance(self) -> list[dict[str, object]]:
        """Saved sitemap-vs-internal-link discovery differences for review."""
        run_id = await self._run_id()
        return await self._fetch(
            """
            WITH sources AS (
                SELECT u.url, u.is_from_sitemap,
                       EXISTS (
                         SELECT 1 FROM frontier f
                         WHERE f.run_id = $1 AND f.url_id = u.id AND f.parent_id IS NOT NULL
                       ) AS found_from_internal_link
                FROM page_run_snapshots s JOIN urls u ON u.id = s.url_id
                WHERE s.run_id = $1 AND u.kind = 'html'
            )
            SELECT url, is_from_sitemap, found_from_internal_link,
                   CASE WHEN is_from_sitemap THEN 'sitemap_only' ELSE 'internal_link_only' END AS issue
            FROM sources
            WHERE is_from_sitemap <> found_from_internal_link
            ORDER BY url
            """,
            run_id,
        )

    async def redirect_chains(self) -> list[dict[str, object]]:
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT src.url AS requested_url, dst.url AS final_url, pm.initial_status_code, pm.final_status_code
            FROM page_run_snapshots pm
            JOIN urls src ON src.id = pm.url_id
            JOIN urls dst ON dst.id = pm.final_url_id
            WHERE pm.run_id = $1 AND pm.url_id <> pm.final_url_id
            ORDER BY src.url
            """,
            run_id,
        )

    async def site_hub_pages(self, min_outlinks: int = 5) -> list[dict[str, object]]:
        run_id = await self._run_id()
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
            run_id,
            min_outlinks,
        )

    async def slowest_pages(self, limit: int = 50) -> list[dict[str, object]]:
        """Pages ranked by total fetch duration (ticket 029 perf metrics)."""
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT u.url, pm.ttfb_seconds, pm.total_duration_seconds, pm.final_status_code
            FROM page_run_snapshots pm
            JOIN urls u ON u.id = pm.url_id
            WHERE pm.run_id = $1 AND pm.total_duration_seconds IS NOT NULL
            ORDER BY pm.total_duration_seconds DESC
            LIMIT $2
            """,
            run_id,
            limit,
        )

    async def worst_cwv_pages(self, limit: int = 50) -> list[dict[str, object]]:
        """Pages ranked by worst lab Core Web Vitals (ticket 046).

        Ranking is by LCP (the headline metric); CLS and INP are included for
        context. Only pages that recorded at least one CWV value are returned —
        HTTP-backend crawls leave them null and are excluded.
        """
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT u.url, pm.lcp_ms, pm.cls, pm.inp_ms, pm.final_status_code
            FROM page_run_snapshots pm
            JOIN urls u ON u.id = pm.url_id
            WHERE pm.run_id = $1 AND (pm.lcp_ms IS NOT NULL OR pm.cls IS NOT NULL OR pm.inp_ms IS NOT NULL)
            ORDER BY pm.lcp_ms DESC NULLS LAST, pm.cls DESC NULLS LAST
            LIMIT $2
            """,
            run_id,
            limit,
        )

    async def javascript_url_candidates(self) -> list[dict[str, object]]:
        """Static JavaScript URL evidence for the selected crawl run."""
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT source.url AS source_url, candidate.candidate_url,
                   candidate.source_kind, candidate.script_source,
                   NULLIF(candidate.script_index, -1) AS script_index,
                   candidate.literal_kind, candidate.classification,
                   candidate.follow_eligible, candidate.occurrence_count,
                   candidate.confidence, candidate.confidence_weight,
                   candidate.resolution_base
            FROM javascript_url_candidates candidate
            JOIN urls source ON source.id = candidate.source_url_id
            WHERE candidate.run_id = $1
            ORDER BY source.url, candidate.candidate_url, candidate.script_source
            """,
            run_id,
        )

    async def css_url_candidates(self) -> list[dict[str, object]]:
        """Static CSS URL evidence for the selected crawl run."""
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT source.url AS source_url, candidate.candidate_url,
                   candidate.source_kind, candidate.stylesheet_source,
                   NULLIF(candidate.style_index, -1) AS style_index,
                   candidate.token_kind, candidate.classification,
                   candidate.follow_eligible, candidate.occurrence_count,
                   candidate.confidence, candidate.confidence_weight,
                   candidate.resolution_base
            FROM css_url_candidates candidate
            JOIN urls source ON source.id = candidate.source_url_id
            WHERE candidate.run_id = $1
            ORDER BY source.url, candidate.candidate_url, candidate.stylesheet_source
            """,
            run_id,
        )

    async def render_url_candidates(self) -> list[dict[str, object]]:
        """Browser network and hydrated-DOM URL evidence for the selected run."""
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT source.url AS source_url, candidate.candidate_url,
                   candidate.source_kind, candidate.classification,
                   candidate.follow_eligible, candidate.resource_type,
                   candidate.method, candidate.outcome, candidate.status,
                   candidate.occurrence_count, candidate.confidence
            FROM render_url_candidates candidate
            JOIN urls source ON source.id = candidate.source_url_id
            WHERE candidate.run_id = $1
            ORDER BY source.url, candidate.source_kind, candidate.candidate_url
            """,
            run_id,
        )

    async def render_attempts(self) -> list[dict[str, object]]:
        """Gate/completeness evidence for render-discovery decisions."""
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT u.url, snapshot.render_discovery_attempted,
                   snapshot.render_discovery_complete,
                   snapshot.render_discovery_skip_reason
            FROM page_run_snapshots snapshot
            JOIN urls u ON u.id = snapshot.url_id
            WHERE snapshot.run_id = $1
              AND (snapshot.render_discovery_attempted
                   OR snapshot.render_discovery_skip_reason IS NOT NULL)
            ORDER BY u.url
            """,
            run_id,
        )

    async def locale_content_alignment(self) -> list[dict[str, object]]:
        """Return cross-language pages with the same stored primary-content signature.

        The signature is generated from boilerplate-reduced primary text.  A
        match is a reproducible localisation concern, rather than a claim
        that pages are definitely untranslated.
        """
        run_id = await self._run_id()
        rows = await self._fetch(
            """
            SELECT u.url, s.html_lang, sig.signature_hash
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            JOIN run_intent_signatures sig ON sig.run_id = s.run_id AND sig.url_id = s.url_id
            WHERE s.run_id = $1
              AND s.overall_indexable IS TRUE
              AND s.content_extracted IS TRUE
              AND NULLIF(s.html_lang, '') IS NOT NULL
              AND jsonb_array_length(s.hreflang_json) > 0
              AND sig.signature_hash IS NOT NULL
            ORDER BY sig.signature_hash, u.url
            """,
            run_id,
        )
        grouped: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            grouped.setdefault(str(row["signature_hash"]), []).append(dict(row))
        findings: list[dict[str, object]] = []
        for signature, members in grouped.items():
            languages = sorted({str(member["html_lang"]) for member in members if member.get("html_lang")})
            primary_languages = {language.split("-", 1)[0].casefold() for language in languages}
            if len(primary_languages) < 2:
                continue
            urls = [str(member["url"]) for member in members]
            for member in members:
                findings.append(
                    {
                        "url": member["url"],
                        "html_lang": member["html_lang"],
                        "content_signature": signature,
                        "languages": ", ".join(languages),
                        "peer_urls": "\n".join(url for url in urls if url != member["url"]),
                    }
                )
        return findings

    async def image_issues(self) -> list[dict[str, object]]:
        """Run-scoped image accessibility and layout evidence."""
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT u.url AS source_url, image ->> 'url' AS image_url,
                   image ->> 'source' AS source_kind, image ->> 'xpath' AS xpath,
                   issue.name AS issue,
                   image ->> 'alt' AS alt,
                   (image ->> 'width')::INTEGER AS width,
                   (image ->> 'height')::INTEGER AS height,
                   image ->> 'loading' AS loading
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            CROSS JOIN LATERAL jsonb_array_elements(s.images_json) image
            CROSS JOIN LATERAL (VALUES
              ('missing_alt_attribute', COALESCE((image ->> 'alt_present')::BOOLEAN, FALSE) = FALSE),
              ('missing_dimensions', image ->> 'width' IS NULL OR image ->> 'height' IS NULL)
            ) AS issue(name, applies)
            WHERE s.run_id = $1 AND issue.applies
            ORDER BY u.url, image ->> 'url', issue
            """,
            run_id,
        )

    async def internal_link_quality(self) -> list[dict[str, object]]:
        """Internal links carrying weak crawl or consolidation signals."""
        run_id = await self._run_id()
        return await self._fetch(
            """
            WITH edges AS (
                SELECT source.url AS source_url, link ->> 'href' AS target_url,
                       NULLIF(link ->> 'anchor_text', '') AS anchor_text,
                       link ->> 'xpath' AS xpath
                FROM page_run_snapshots snapshot
                JOIN urls source ON source.id = snapshot.url_id
                CROSS JOIN LATERAL jsonb_array_elements(snapshot.links_json) link
                WHERE snapshot.run_id = $1
            )
            SELECT edges.source_url, edges.target_url, edges.anchor_text, edges.xpath,
                   target.final_status_code AS target_status,
                   target.overall_indexable AS target_indexable,
                   target.canonical_urls_json ->> 0 AS target_canonical,
                   final_url.url AS final_url,
                   CASE
                     WHEN edges.anchor_text IS NULL THEN 'empty_anchor'
                     WHEN target.final_status_code BETWEEN 300 AND 399 THEN 'redirect_target'
                     WHEN target.final_status_code >= 400 THEN 'error_target'
                     WHEN target.overall_indexable = FALSE THEN 'non_indexable_target'
                     WHEN target.canonical_urls_json ->> 0 IS NOT NULL
                          AND target.canonical_urls_json ->> 0 <> edges.target_url THEN 'noncanonical_target'
                   END AS issue
            FROM edges
            LEFT JOIN urls target_url ON target_url.url = edges.target_url
            LEFT JOIN page_run_snapshots target
              ON target.run_id = $1 AND target.url_id = target_url.id
            LEFT JOIN urls final_url ON final_url.id = target.final_url_id
            WHERE edges.anchor_text IS NULL
               OR target.final_status_code >= 300
               OR target.overall_indexable = FALSE
               OR (target.canonical_urls_json ->> 0 IS NOT NULL
                   AND target.canonical_urls_json ->> 0 <> edges.target_url)
            ORDER BY edges.source_url, edges.target_url
            """,
            run_id,
        )

    async def tracking_parameter_links(self) -> list[dict[str, object]]:
        """Internal links that publish known analytics/session parameters."""
        run_id = await self._run_id()
        rows = await self._fetch(
            """
            SELECT source.url AS source_url, link ->> 'href' AS target_url,
                   link ->> 'anchor_text' AS anchor_text, link ->> 'xpath' AS xpath
            FROM page_run_snapshots snapshot
            JOIN urls source ON source.id = snapshot.url_id
            CROSS JOIN LATERAL jsonb_array_elements(snapshot.links_json) link
            WHERE snapshot.run_id = $1 AND (link ->> 'href') LIKE '%?%'
            ORDER BY source.url, link ->> 'href'
            """,
            run_id,
        )
        findings: list[dict[str, object]] = []
        for row in rows:
            # The SQL deliberately retains the full link evidence so callers
            # can use it for external-link analysis too. This report's claim
            # is narrower: only first-party links create internal crawl paths.
            if urlparse(str(row["source_url"])).netloc.lower() != urlparse(str(row["target_url"])).netloc.lower():
                continue
            keys = sorted({key.lower() for key, _ in parse_qsl(urlparse(str(row["target_url"])).query)})
            tracking = [key for key in keys if key in _TRACKING_PARAMETERS]
            if tracking:
                findings.append({**row, "tracking_parameters": ",".join(tracking)})
        return findings

    async def near_duplicates(self, threshold: int = 4, limit: int = 5000) -> list[dict[str, object]]:
        """Near-duplicate indexable pages using persisted 64-bit SimHash."""
        run_id = await self._run_id()
        rows = await self._fetch(
            """
            SELECT u.url, s.content_hash_sha256, s.content_hash_simhash
            FROM page_run_snapshots s JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1 AND s.overall_indexable = TRUE
              AND s.content_hash_simhash IS NOT NULL
            ORDER BY u.url LIMIT $2
            """,
            run_id,
            limit,
        )
        findings: list[dict[str, object]] = []
        for index, left in enumerate(rows):
            for right in rows[index + 1 :]:
                if left["content_hash_sha256"] == right["content_hash_sha256"]:
                    continue
                distance = hamming64(
                    int(cast(int, left["content_hash_simhash"])),
                    int(cast(int, right["content_hash_simhash"])),
                )
                if distance <= threshold:
                    findings.append(
                        {"url": left["url"], "near_duplicate_url": right["url"], "simhash_distance": distance}
                    )
        return sorted(findings, key=lambda row: (row["simhash_distance"], row["url"], row["near_duplicate_url"]))

    async def internal_authority(self) -> list[dict[str, object]]:
        """PageRank-like relative authority over indexable run-scoped pages."""
        run_id = await self._run_id()
        pages = await self._fetch(
            """
            SELECT u.url, s.links_json
            FROM page_run_snapshots s JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1 AND s.overall_indexable = TRUE
            ORDER BY u.url
            """,
            run_id,
        )
        urls = {str(row["url"]) for row in pages}
        if not urls:
            return []
        outgoing: dict[str, set[str]] = {}
        for row in pages:
            raw_links = row["links_json"] or []
            if isinstance(raw_links, str):
                raw_links = json.loads(raw_links)
            links = cast(list[dict[str, Any]], raw_links)
            outgoing[str(row["url"])] = {str(link["href"]) for link in links if link.get("href") in urls}
        score = {url: 1.0 / len(urls) for url in urls}
        damping = 0.85
        for _ in range(50):
            sink = sum(score[url] for url, targets in outgoing.items() if not targets)
            updated = {url: (1.0 - damping) / len(urls) + damping * sink / len(urls) for url in urls}
            for source, targets in outgoing.items():
                if targets:
                    contribution = damping * score[source] / len(targets)
                    for target in targets:
                        updated[target] += contribution
            if max(abs(updated[url] - score[url]) for url in urls) < 1e-10:
                score = updated
                break
            score = updated
        inbound = {url: 0 for url in urls}
        for targets in outgoing.values():
            for target in targets:
                inbound[target] += 1
        maximum = max(score.values()) or 1.0
        return [
            {
                "url": url,
                "authority_score": round(100.0 * score[url] / maximum, 4),
                "unique_inlinks": inbound[url],
                "unique_outlinks": len(outgoing[url]),
            }
            for url in sorted(urls, key=lambda value: (score[value], value))
        ]

    async def schema_compatibility(self) -> list[dict[str, object]]:
        """Run-scoped JSON-LD single-unescape compatibility findings."""
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT
                u.url,
                COALESCE(schema_item ->> 'type', 'Unknown') AS schema_type,
                COALESCE(schema_item ->> 'parser_mode', 'legacy-unspecified') AS parser_mode,
                COALESCE((schema_item ->> 'is_valid')::BOOLEAN, FALSE) AS is_valid,
                diagnostic ->> 'code' AS diagnostic_code,
                diagnostic ->> 'severity' AS severity,
                COALESCE((diagnostic ->> 'script_position')::INTEGER, schema_ordinal - 1) AS script_position,
                diagnostic ->> 'json_pointer' AS json_pointer,
                diagnostic ->> 'location_kind' AS location_kind,
                diagnostic ->> 'evidence' AS evidence,
                diagnostic ->> 'source_evidence' AS source_evidence,
                diagnostic ->> 'remediation' AS remediation
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            CROSS JOIN LATERAL jsonb_array_elements(COALESCE(s.schema_json, '[]'::jsonb))
                WITH ORDINALITY AS schema_rows(schema_item, schema_ordinal)
            CROSS JOIN LATERAL jsonb_array_elements(
                COALESCE(schema_item -> 'compatibility_diagnostics', '[]'::jsonb)
            ) AS diagnostics(diagnostic)
            WHERE s.run_id = $1
            ORDER BY u.url, script_position, diagnostic_code, json_pointer
            """,
            run_id,
        )

    async def as_json(self) -> str:
        payload = {
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
        """Snapshot pages with no analytics hit (optionally for one vendor)."""
        run_id = await self._run_id()
        if vendor:
            return await self._fetch(
                """
                SELECT u.url
                FROM page_run_snapshots s
                JOIN urls u ON u.id = s.url_id
                WHERE s.run_id = $1 AND u.kind = 'html'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements(s.analytics_json) hit
                      WHERE hit ->> 'vendor' = $2
                  )
                ORDER BY u.url
                """,
                run_id,
                vendor,
            )
        return await self._fetch(
            """
            SELECT u.url
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1 AND u.kind = 'html'
              AND jsonb_array_length(s.analytics_json) = 0
            ORDER BY u.url
            """,
            run_id,
        )

    async def pages_missing_expected_id(self, expected_id: str) -> list[dict[str, object]]:
        """Pages where the expected identifier is not present."""
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT u.url
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1 AND u.kind = 'html'
              AND NOT EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements(s.analytics_json) hit
                  WHERE hit ->> 'identifier' = $2
              )
            ORDER BY u.url
            """,
            run_id,
            expected_id,
        )

    async def analytics_inventory(self) -> list[dict[str, object]]:
        """Rollup of (vendor, identifier, page_count)."""
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT hit ->> 'vendor' AS vendor, hit ->> 'category' AS category,
                   hit ->> 'identifier' AS identifier, COUNT(DISTINCT s.url_id)::INT AS page_count
            FROM page_run_snapshots s
            CROSS JOIN LATERAL jsonb_array_elements(s.analytics_json) hit
            WHERE s.run_id = $1
            GROUP BY hit ->> 'vendor', hit ->> 'category', hit ->> 'identifier'
            ORDER BY page_count DESC, vendor, identifier
            """,
            run_id,
        )

    async def analytics_per_page(self, url: str) -> list[dict[str, object]]:
        """Full hit list for a single URL."""
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT u.url, hit ->> 'vendor' AS vendor, hit ->> 'category' AS category,
                   hit ->> 'identifier' AS identifier, hit ->> 'evidence_type' AS evidence_type,
                   hit ->> 'evidence_snippet' AS evidence_snippet,
                   (hit ->> 'confidence')::DOUBLE PRECISION AS confidence,
                   s.fetched_at AS detected_at
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            CROSS JOIN LATERAL jsonb_array_elements(s.analytics_json) hit
            WHERE s.run_id = $1 AND u.url = $2
            ORDER BY confidence DESC, vendor
            """,
            run_id,
            url,
        )

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
