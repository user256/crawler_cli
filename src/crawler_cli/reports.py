from __future__ import annotations

import json
from typing import Any, cast
from urllib.parse import parse_qsl, urlparse

from .hashing import hamming64
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
        has_directive_evidence = "indexability_evidence_json" in snapshot_columns
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
                COUNT(*) FILTER (WHERE s.challenge IS NOT NULL)::INT AS challenged_count,
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
                "indexability_evidence_json": has_directive_evidence,
                "links_json": "links_json" in snapshot_columns,
                "content_hash_simhash": "content_hash_simhash" in snapshot_columns,
            },
            "frontier_queued": frontier[0],
            "frontier_pending": frontier[1],
            "frontier_done": frontier[2],
            **stats,
        }

    async def orphan_pages(self) -> list[dict[str, object]]:
        run_id = await self._run_id()
        run = await self.store.get_crawl_run(run_id)
        pages = await self._fetch(
            """
            SELECT u.url, u.kind, s.links_json, s.content_extracted,
                   s.render_discovery_attempted, s.render_discovery_complete
            FROM page_run_snapshots s JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1 AND u.kind = 'html'
            ORDER BY u.url
            """,
            run_id,
        )
        graph = _build_link_graph(pages)
        inbound = graph["inbound"]
        complete = graph["complete"] and bool(run and run.get("status") == "complete")
        seeds = set(run.get("seed_urls", [])) if run and isinstance(run.get("seed_urls"), list) else set()
        return [
            {
                "url": str(page["url"]),
                "candidate_type": "crawled_html_zero_observed_inlinks",
                "observed_inlink_count": 0,
                "graph_complete": complete,
                "seed": str(page["url"]) in seeds,
            }
            for page in pages
            if inbound.get(str(page["url"]), 0) == 0
        ]

    async def indexability_reasons(self) -> list[dict[str, object]]:
        run_id = await self._run_id()
        column_rows = await self._fetch(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = current_schema()
                 AND table_name = 'page_run_snapshots'"""
        )
        has_extraction_state = any(row["column_name"] == "content_extracted" for row in column_rows)
        has_directive_evidence = any(row["column_name"] == "indexability_evidence_json" for row in column_rows)
        extraction_field = "s.content_extracted" if has_extraction_state else "NULL::BOOLEAN"
        evidence_field = "s.indexability_evidence_json" if has_directive_evidence else "NULL::JSONB"
        return await self._fetch(
            f"""
            SELECT u.url, s.html_meta_allows, s.http_header_allows, s.overall_indexable,
                   {extraction_field} AS content_extracted,
                   {evidence_field} AS directive_evidence
            FROM page_run_snapshots s JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1
            ORDER BY u.url
            """,
            run_id,
        )

    async def redirect_chains(self) -> list[dict[str, object]]:
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT src.url AS requested_url, dst.url AS final_url,
                   pm.initial_status_code, pm.final_status_code,
                   pm.redirect_chain_json AS ordered_hops
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
        """Run-scoped internal link instances with every applicable issue."""
        run_id = await self._run_id()
        rows = await self._fetch(
            """
            SELECT source.url AS source_url, source_snapshot.overall_indexable AS source_indexable,
                   link AS link_evidence, target_snapshot.initial_status_code AS target_initial_status,
                   target_snapshot.final_status_code AS target_status,
                   target_snapshot.final_url_id AS target_final_url_id,
                   target_snapshot.url_id AS target_url_id,
                   target_snapshot.overall_indexable AS target_indexable,
                   target_snapshot.html_meta_allows, target_snapshot.http_header_allows,
                   target_snapshot.canonical_urls_json, target_snapshot.challenge,
                   target_url.url AS target_saved_url
            FROM page_run_snapshots source_snapshot
            JOIN urls source ON source.id = source_snapshot.url_id
            CROSS JOIN LATERAL jsonb_array_elements(source_snapshot.links_json) link
            LEFT JOIN urls target_url ON target_url.url = link ->> 'href'
            LEFT JOIN page_run_snapshots target_snapshot
              ON target_snapshot.run_id = $1 AND target_snapshot.url_id = target_url.id
            WHERE source_snapshot.run_id = $1
            ORDER BY source.url, link ->> 'href', link ->> 'xpath'
            """,
            run_id,
        )
        graph_hosts = {urlparse(str(row["source_url"])).hostname for row in rows}
        findings: list[dict[str, object]] = []
        for row in rows:
            evidence = _json_object(row.get("link_evidence"))
            target_url = str(evidence.get("href", ""))
            host = urlparse(target_url).hostname
            if not target_url or host not in graph_hosts:
                continue
            issues: list[str] = []
            anchor = evidence.get("anchor_text")
            if not isinstance(anchor, str) or not anchor.strip():
                issues.append("empty_anchor")
            status = row.get("target_status")
            initial_status = row.get("target_initial_status")
            if row.get("target_url_id") is not None and (
                row.get("target_final_url_id") != row.get("target_url_id")
                or (isinstance(initial_status, int) and 300 <= initial_status < 400)
            ):
                issues.append("redirect_target")
            if isinstance(status, int) and status >= 400 and not row.get("challenge"):
                issues.append("error_target")
            if row.get("challenge"):
                issues.append("challenge_target")
            if row.get("html_meta_allows") is False or row.get("http_header_allows") is False:
                issues.append("noindex_target")
            if row.get("target_indexable") is False:
                issues.append("non_indexable_target")
            canonicals = _json_list(row.get("canonical_urls_json"))
            canonical = str(canonicals[0]) if canonicals else None
            if canonical and _without_fragment(canonical) != _without_fragment(target_url):
                issues.append("noncanonical_target")
            if urlparse(target_url).query:
                issues.append("parameter_target")
            if not issues:
                continue
            # Keep the legacy scalar field for ticket-185's live-failure join;
            # issue_list carries simultaneous facts without hiding any.
            legacy_issue = "error_target" if "error_target" in issues else issues[0]
            findings.append(
                {
                    "source_url": row["source_url"],
                    "source_indexable": row.get("source_indexable"),
                    "target_url": target_url,
                    "target_status": status,
                    "target_initial_status": initial_status,
                    "target_indexable": row.get("target_indexable"),
                    "anchor_text": anchor,
                    "xpath": evidence.get("xpath"),
                    "original_href": evidence.get("original_href"),
                    "is_image": evidence.get("is_image", False),
                    "fragment": evidence.get("fragment"),
                    "rel": evidence.get("rel", []),
                    "discovery_source": evidence.get("discovery_source", "legacy_unspecified"),
                    "issues": issues,
                    "issue": legacy_issue,
                }
            )
        return findings

    async def link_graph_metrics(self) -> list[dict[str, object]]:
        """Separate edge counts from qualified depth/reachability claims."""
        run_id = await self._run_id()
        pages = await self._fetch(
            """
            SELECT u.url, s.links_json, s.content_extracted,
                   s.render_discovery_attempted, s.render_discovery_complete
            FROM page_run_snapshots s JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1 AND u.kind = 'html' ORDER BY u.url
            """,
            run_id,
        )
        graph = _build_link_graph(pages)
        run = await self.store.get_crawl_run(run_id)
        graph["complete"] = graph["complete"] and bool(run and run.get("status") == "complete")
        seeds = run.get("seed_urls", []) if run and isinstance(run.get("seed_urls"), list) else []
        adjacency = graph["adjacency"]
        depths: dict[str, int] = {}
        pending = [str(seed) for seed in seeds if str(seed) in adjacency]
        depths.update({seed: 0 for seed in pending})
        while pending:
            source = pending.pop(0)
            for target in sorted(adjacency.get(source, set())):
                if target not in depths:
                    depths[target] = depths[source] + 1
                    pending.append(target)
        return [
            {
                "unique_sources": graph["source_count"],
                "unique_targets": graph["target_count"],
                "link_instances": graph["instance_count"],
                "graph_complete": graph["complete"],
                "reachable_pages": len(depths) if graph["complete"] else None,
                "max_depth": max(depths.values(), default=0) if graph["complete"] else None,
                "depth_qualification": "complete_saved_graph" if graph["complete"] else "unqualified_incomplete_graph",
            }
        ]

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
                DROP MATERIALIZED VIEW IF EXISTS crawler_orphan_pages
                """
            )
            await conn.execute(
                """
                CREATE MATERIALIZED VIEW crawler_orphan_pages AS
                SELECT s.run_id, u.url,
                       'crawled_html_zero_observed_inlinks'::TEXT AS candidate_type,
                       (r.status = 'complete' AND NOT EXISTS (
                           SELECT 1 FROM page_run_snapshots coverage
                           JOIN urls covered_url ON covered_url.id = coverage.url_id
                           WHERE coverage.run_id = s.run_id AND covered_url.kind = 'html'
                             AND (coverage.content_extracted IS DISTINCT FROM TRUE
                                  OR (coverage.render_discovery_attempted
                                      AND coverage.render_discovery_complete IS DISTINCT FROM TRUE))
                       )) AS graph_complete
                FROM page_run_snapshots s
                JOIN urls u ON u.id = s.url_id
                JOIN crawl_runs r ON r.run_id = s.run_id
                WHERE u.kind = 'html'
                  AND NOT EXISTS (
                      SELECT 1 FROM page_run_snapshots source_snapshot
                      JOIN urls source ON source.id = source_snapshot.url_id
                      CROSS JOIN LATERAL jsonb_array_elements(source_snapshot.links_json) link
                      WHERE source_snapshot.run_id = s.run_id
                        AND source.url <> u.url
                        AND link ->> 'href' = u.url
                  )
                """
            )

    async def _fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        await self.store.connect()
        assert self.store.pool is not None
        async with self.store.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def _json_list(value: object) -> list[object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return value if isinstance(value, list) else []


def _without_fragment(value: str) -> str:
    return urlparse(value)._replace(fragment="").geturl()


def _build_link_graph(pages: list[dict[str, object]]) -> dict[str, Any]:
    """Build edges only between same-run HTML snapshot nodes and in-scope hosts."""
    nodes = {str(page["url"]) for page in pages}
    hosts = {urlparse(url).hostname for url in nodes}
    inbound = {url: 0 for url in nodes}
    adjacency: dict[str, set[str]] = {url: set() for url in nodes}
    instances = 0
    sources: set[str] = set()
    targets: set[str] = set()
    complete = bool(pages)
    for page in pages:
        if page.get("content_extracted") is not True:
            complete = False
        if page.get("render_discovery_attempted") is True and page.get("render_discovery_complete") is not True:
            complete = False
        source = str(page["url"])
        for raw_link in _json_list(page.get("links_json")):
            link = raw_link if isinstance(raw_link, dict) else {}
            target = str(link.get("href", ""))
            if target not in nodes or urlparse(target).hostname not in hosts:
                continue
            instances += 1
            sources.add(source)
            targets.add(target)
            adjacency[source].add(target)
            # Self-links are preserved as instances, but do not count as an
            # incoming discovery edge for orphan classification.
            if source != target:
                inbound[target] += 1
    return {
        "inbound": inbound,
        "adjacency": adjacency,
        "complete": complete,
        "source_count": len(sources),
        "target_count": len(targets),
        "instance_count": instances,
    }
