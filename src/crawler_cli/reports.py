from __future__ import annotations

import json
import re
from typing import Any, cast
from urllib.parse import parse_qsl, urljoin, urlparse

from .amp import urls_match
from bs4 import BeautifulSoup

from .extract import generate_xpath, parse_html, wraps_heading
from .hashing import hamming64
from .html_audit import canonical_targets, inspect_stored_html
from .hreflang_audit import hreflang_facts
from .semantic_html_audit import inspect_semantic_html
from .persistence import AsyncpgStore
from .technical_audit_evidence import HEADING_LINK_XPATH_PATTERN, HEADING_WRAPPING_LINK_FIELD


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
_LINK_CANONICAL = re.compile(r"<([^>]+)>[^,]*\brel\s*=\s*[\"']?canonical\b", re.IGNORECASE)
_SOFT_404_SIGNATURE = re.compile(r"\b(?:404|page\s+not\s+found|not\s+found|error\s+page)\b", re.IGNORECASE)
_H1 = re.compile(r"<h1\b[^>]*>(.*?)</h1\s*>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_HOMEPAGE_PATHS = frozenset({"", "/", "/index.html", "/index.htm", "/index.php"})
_MAX_CLUSTER_URLS = 50

# page_run_snapshots columns added by migrations after the table first
# shipped.  A database crawled by an older version can lack any of them, so
# technical_audit_context reports each one in ``schema_capabilities``.
SNAPSHOT_OPTIONAL_COLUMNS = (
    "amphtml_url",
    "analytics_json",
    "canonical_evidence_json",
    "canonical_urls_json",
    "cls",
    "content_extracted",
    "hreflang_json",
    "images_json",
    "indexability_evidence_json",
    "inp_ms",
    "lcp_ms",
    "links_json",
    "redirect_chain_json",
    "render_discovery_attempted",
    "render_discovery_complete",
    "render_discovery_skip_reason",
    "robots_json",
    "schema_json",
    "total_duration_seconds",
    "ttfb_seconds",
    "variant_kind",
)

# Capabilities each technical-audit report's SQL needs.  The audit skips a
# report whose capabilities are missing, so its checks read as unavailable
# instead of the run crashing on an older snapshot table.  A report absent
# from this map reads only columns every snapshot table has, or guards its
# own.  tests/test_technical_audit_legacy_schema.py keeps the map in step
# with the SQL each report issues.
TECHNICAL_AUDIT_REPORT_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "orphans": (
        "canonical_urls_json",
        "content_extracted",
        "links_json",
        "render_discovery_attempted",
        "render_discovery_complete",
    ),
    "schema-compatibility": ("schema_json",),
    "image-issues": ("images_json",),
    "internal-link-quality": ("canonical_urls_json", "links_json"),
    "tracking-parameter-links": ("links_json",),
    "near-duplicates": ("content_hash_simhash",),
    "internal-authority": ("links_json",),
    "locale-content-alignment": ("content_extracted", "hreflang_json", "run_intent_signatures"),
    "render-attempts": (
        "render_discovery_attempted",
        "render_discovery_complete",
        "render_discovery_skip_reason",
    ),
    "metadata-duplicates": ("canonical_urls_json", "content_extracted"),
    "hreflang-validation": ("canonical_urls_json", "content_extracted", "hreflang_json"),
    "profile-indexability-pages": ("canonical_urls_json", "content_extracted", "links_json"),
    "discovery-source-provenance": ("links_json",),
    "performance-pages": ("ttfb_seconds",),
}


def _json_value(value: object) -> object:
    """Decode a JSONB column: asyncpg returns it as text unless a codec is set."""
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def _header_map(value: object) -> dict[str, str]:
    headers = _json_value(value)
    if not isinstance(headers, dict):
        return {}
    return {str(name).casefold(): str(item) for name, item in headers.items()}


def _link_canonicals(headers: dict[str, str]) -> list[str]:
    return _LINK_CANONICAL.findall(headers.get("link", ""))


def _is_homepage_variant(url: str, homepage: str) -> bool:
    """The homepage, or the root path with any query string or index file, on the same host."""
    parsed = urlparse(url)
    return (
        parsed.netloc.casefold() == urlparse(homepage).netloc.casefold() and parsed.path.casefold() in _HOMEPAGE_PATHS
    )


def _stored_html_rows(url: str, html: str, state: dict[str, object]) -> list[dict[str, object]]:
    headers = _header_map(state.get("headers_json"))
    header_canonicals = [urljoin(url, target) for target in _link_canonicals(headers)]
    context = {"overall_indexable": state.get("overall_indexable"), "final_status_code": state.get("final_status_code")}
    rows: list[dict[str, object]] = []
    for finding in inspect_stored_html(url, html):
        # Either an HTML canonical or an HTTP Link canonical satisfies Q71.
        if finding["kind"] == "missing-canonical" and header_canonicals:
            continue
        rows.append({**finding, **context})
    html_canonicals = canonical_targets(url, html)
    parsed = urlparse(url)
    homepage = f"{parsed.scheme}://{parsed.netloc}/"
    if not _is_homepage_variant(url, homepage):
        for canonical in dict.fromkeys([*html_canonicals, *header_canonicals]):
            if urls_match(canonical, homepage):
                rows.append({"url": url, "kind": "canonical-to-homepage", "canonical": canonical, **context})
    for header_canonical in header_canonicals:
        if html_canonicals and not any(urls_match(header_canonical, item) for item in html_canonicals):
            rows.append(
                {
                    "url": url,
                    "kind": "html-header-canonical-mismatch",
                    "html_canonicals": html_canonicals,
                    "header_canonical": header_canonical,
                    **context,
                }
            )
    return rows


def _soft_404_candidate(url: str, html: str, state: dict[str, object]) -> dict[str, object] | None:
    if state.get("final_status_code") != 200:
        return None
    title = str(state.get("title") or "")
    h1 = _H1.search(html)
    heading = " ".join(_TAG.sub(" ", h1.group(1)).split()) if h1 else ""
    for source, text in (("title", title), ("h1", heading)):
        match = _SOFT_404_SIGNATURE.search(text)
        if match:
            return {
                "url": url,
                "final_status_code": 200,
                "title": title,
                "h1": heading[:200],
                "signature_source": source,
                "signature": match.group(0),
            }
    return None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


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


def _canonical_state(url: str, value: object) -> str:
    canonicals = _json_list(value)
    if not canonicals and isinstance(value, str) and value and value != "[]":
        canonicals = [value]
    if not canonicals:
        return "implicit_self"
    return "declared_self" if _without_fragment(str(canonicals[0])) == _without_fragment(url) else "noncanonical"


def _build_link_graph(
    pages: list[dict[str, object]], *, known_urls: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    """Build edges only between same-run HTML snapshot nodes and in-scope hosts."""
    nodes = {str(page["url"]) for page in pages}
    hosts = {urlparse(url).hostname for url in nodes}
    known_targets = {
        item["url"] for item in (known_urls or []) if item.get("url") and urlparse(item["url"]).hostname in hosts
    }
    all_targets = nodes | known_targets
    inbound = {url: 0 for url in all_targets}
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
            if target not in all_targets or urlparse(target).hostname not in hosts:
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


_EMPTY_ANCHORS_PER_PAGE = 100


def _heading_wrapping_links(url: str, soup: BeautifulSoup, base_url: str | None = None) -> list[dict[str, object]]:
    """Internal links on one page that wrap an H2/H3 (``a > h2|h3`` or ``a > * > h2|h3``), for Q39.

    Targets are normalised as ``extract_links`` does (resolved against the
    page's final URL, fragment dropped), so they join to the run's saved
    targets and to the ``internal-link-quality`` rows of the same page.  The
    XPath is the anchor's own, from the crawler's ``generate_xpath``.
    """
    base = base_url or url
    base_host = urlparse(base).netloc.casefold()
    rows: list[dict[str, object]] = []
    for anchor in soup.find_all("a", href=True):
        if not wraps_heading(anchor):
            continue
        parsed = urlparse(urljoin(base, str(anchor.get("href", "")).strip()))
        if parsed.scheme not in {"http", "https"} or parsed.netloc.casefold() != base_host:
            continue
        rows.append(
            {"source_url": url, "target_url": parsed._replace(fragment="").geturl(), "xpath": generate_xpath(anchor)}
        )
    return rows


def mark_heading_wrapping_links(
    rows: list[dict[str, object]], wrapping: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Flag link rows whose page links to the same target from a heading-wrapping anchor.

    Matched on (source, target), not XPath: ``links_json`` keeps one link per
    target per page, so the saved row often carries the XPath of a card's
    image link rather than of its heading link.  The target is the same.
    """
    pairs = {(str(row["source_url"]), str(row["target_url"])) for row in wrapping}
    if not pairs:
        return rows
    return [
        {**row, HEADING_WRAPPING_LINK_FIELD: True}
        if (str(row.get("source_url")), str(row.get("target_url"))) in pairs
        else row
        for row in rows
    ]


def _empty_anchor_page_row(url: str, html: str, soup: BeautifulSoup | None = None) -> dict[str, object]:
    """Count a page's internal anchors and list only those with no text, capped per page."""
    source_host = urlparse(url).netloc.casefold()
    soup = soup if soup is not None else parse_html(html)
    total = 0
    empty: list[dict[str, object]] = []
    truncated = False
    for anchor in soup.find_all("a", href=True):
        target_url = urljoin(url, str(anchor.get("href", "")).strip())
        parsed = urlparse(target_url)
        if parsed.scheme not in {"http", "https"} or parsed.netloc.casefold() != source_host:
            continue
        total += 1
        anchor_text = anchor.get_text(" ", strip=True) or anchor.get("aria-label") or anchor.get("title")
        if isinstance(anchor_text, str) and anchor_text.strip():
            continue
        if len(empty) >= _EMPTY_ANCHORS_PER_PAGE:
            truncated = True
            continue
        empty.append(
            {
                "target_url": target_url.split("#", 1)[0],
                "anchor_text": str(anchor_text) if anchor_text is not None else None,
                "linked_image_alt_texts": [
                    str(image.get("alt", "")).strip() if image.has_attr("alt") else None
                    for image in anchor.find_all("img")
                ],
            }
        )
    return {
        "source_url": url,
        "internal_anchor_count": total,
        "empty_anchors": empty,
        "empty_anchors_truncated": truncated,
    }


class CrawlReports:
    def __init__(self, store: AsyncpgStore, *, run_id: str | None = None) -> None:
        self.store = store
        self.run_id = run_id
        self._stored_html_cache: dict[str, list[dict[str, object]]] | None = None

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
        sitemap_sources = await self._fetch(
            """SELECT COUNT(*)::INT AS n FROM run_url_sources
               WHERE run_id = $1 AND source IN ('sitemap', 'robots_sitemap')""",
            run_id,
        )
        stats["run_sitemap_source_count"] = _int_or_none(sitemap_sources[0].get("n")) if sitemap_sources else 0
        # Q81: did the origin slow down while the run read it?  Compare the
        # median TTFB of the first and last tenth of timed fetches.
        # Snapshot tables older than the timing columns have no TTFB to compare.
        if "ttfb_seconds" in snapshot_columns:
            drift = await self._fetch(
                """
                WITH timed AS (
                    SELECT ttfb_seconds, ntile(10) OVER (ORDER BY fetched_at) AS decile
                    FROM page_run_snapshots WHERE run_id = $1 AND ttfb_seconds IS NOT NULL
                )
                SELECT COUNT(*)::INT AS ttfb_sample_count,
                       (percentile_cont(0.5) WITHIN GROUP (ORDER BY ttfb_seconds) FILTER (WHERE decile = 1) * 1000)::DOUBLE PRECISION
                           AS ttfb_early_median_ms,
                       (percentile_cont(0.5) WITHIN GROUP (ORDER BY ttfb_seconds) FILTER (WHERE decile = 10) * 1000)::DOUBLE PRECISION
                           AS ttfb_late_median_ms
                FROM timed
                """,
                run_id,
            )
            if drift:
                stats.update(drift[0])
        locale_signature_count: int | None = None
        if has_signatures and has_extraction_state and "hreflang_json" in snapshot_columns:
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
                **{column: column in snapshot_columns for column in SNAPSHOT_OPTIONAL_COLUMNS},
                "content_hash_simhash": "content_hash_simhash" in snapshot_columns,
                "run_intent_signatures": has_signatures,
            },
            "frontier_queued": frontier[0],
            "frontier_pending": frontier[1],
            "frontier_done": frontier[2],
            "locale_signature_count": locale_signature_count,
            **stats,
        }

    async def accept_language_probes(self) -> list[dict[str, object]]:
        """Return persisted language evidence or an explicit no-session state."""
        rows = await self.store.latest_language_probe_evidence(await self._run_id())
        if rows:
            return rows
        # Not a "coverage" record: the audit treats a coverage row as a probe that ran.
        return [
            {
                "record_type": "not_recorded",
                "state": "not_recorded",
                "complete": False,
                "qualification": "no_explicit_accept_language_probe_session_for_selected_run",
            }
        ]

    async def source_reconciliation_inventory(self) -> dict[str, list[dict[str, object]]]:
        """Return run-scoped snapshots and crawl sitemap provenance for ``reconcile-sources``.

        ``pages`` covers every snapshot kind so non-HTML sitemap or backlink
        targets still carry an HTTP status; only HTML rows feed the link graph.
        ``crawl_sitemap_urls`` reads ticket 013's ``url_sources`` rows. That
        table is database-wide, so it is intersected with the selected run's
        frontier to avoid importing sitemap memberships seen only by other runs.
        """
        run_id = await self._run_id()
        pages = await self._fetch(
            """
            SELECT u.url, u.kind, s.links_json, s.content_extracted,
                   s.render_discovery_attempted, s.render_discovery_complete,
                   s.initial_status_code, s.final_status_code, s.overall_indexable,
                   s.canonical_urls_json
            FROM page_run_snapshots s JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1
            ORDER BY u.url
            """,
            run_id,
        )
        crawl_sitemap_urls = await self._fetch(
            """
            SELECT DISTINCT u.url, COALESCE(us.detail, '') AS detail
            FROM url_sources us
            JOIN urls u ON u.id = us.url_id
            JOIN frontier f ON f.url_id = us.url_id AND f.run_id = $1
            WHERE us.source = 'sitemap'
            ORDER BY u.url, detail
            """,
            run_id,
        )
        return {"pages": pages, "crawl_sitemap_urls": crawl_sitemap_urls}

    async def current_site_join_inventory(self) -> list[dict[str, object]]:
        """Return safe run-scoped facts used to join current sitemaps to history."""
        run_id = await self._run_id()
        column_rows = await self._fetch(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema = current_schema()
                 AND table_name = 'page_run_snapshots'"""
        )
        snapshot_columns = {str(row["column_name"]) for row in column_rows}
        extraction_field = "s.content_extracted" if "content_extracted" in snapshot_columns else "NULL::BOOLEAN"
        rows = await self._fetch(
            f"""
            SELECT u.url, u.kind, s.final_status_code, s.overall_indexable,
                   {extraction_field} AS content_extracted,
                   s.html_lang, s.custom_data ->> 'template' AS template,
                   s.canonical_urls_json, s.links_json
            FROM page_run_snapshots s JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1
            ORDER BY s.url_id
            """,
            run_id,
        )
        return [dict(row) for row in rows]

    @staticmethod
    def _source_value(observations: list[dict[str, str]], field: str) -> str | None:
        return next((item[field] for item in observations if item.get(field)), None)

    @staticmethod
    def _source_bool(observations: list[dict[str, str]], field: str) -> bool | None:
        value = next((item[field].lower() for item in observations if item.get(field)), None)
        if value in {"true", "1", "yes"}:
            return True
        if value in {"false", "0", "no"}:
            return False
        return None

    @staticmethod
    def _source_int(observations: list[dict[str, str]], field: str) -> int | None:
        value = next((item[field] for item in observations if item.get(field)), None)
        try:
            return int(value) if value is not None else None
        except ValueError:
            return None

    async def https_response_headers(self) -> list[dict[str, object]]:
        """Final response identity, status and headers of every stored HTTPS response (ticket 414).

        ``headers_json`` and ``final_status_code`` describe the *final*
        response after redirects, so the row is selected and attributed by
        ``final_url`` (the snapshot's ``final_url_id``), not by the requested
        URL. ``requested_url`` is kept only as provenance. A snapshot with no
        retained final URL has no known response identity and is not
        returned. An HTTP seed that finished on HTTPS is included; an HTTPS
        seed that finished on HTTP is not HTTPS evidence and is excluded.
        """
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT u.url AS requested_url, fu.url AS final_url, s.final_status_code, s.headers_json
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            JOIN urls fu ON fu.id = s.final_url_id
            WHERE s.run_id = $1 AND lower(fu.url) LIKE 'https://%'
            ORDER BY fu.url, u.url
            """,
            run_id,
        )

    async def orphan_pages(self, *, known_urls: list[dict[str, str]] | None = None) -> list[dict[str, object]]:
        run_id = await self._run_id()
        run = await self.store.get_crawl_run(run_id)
        pages = await self._fetch(
            """
            SELECT u.url, u.kind, s.links_json, s.content_extracted,
                   s.render_discovery_attempted, s.render_discovery_complete,
                   s.final_status_code, s.overall_indexable, s.canonical_urls_json
            FROM page_run_snapshots s JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1 AND u.kind = 'html'
            ORDER BY u.url
            """,
            run_id,
        )
        graph = _build_link_graph(pages, known_urls=known_urls or [])
        inbound = graph["inbound"]
        complete = graph["complete"] and bool(run and run.get("status") == "complete")
        seeds = set(run.get("seed_urls", [])) if run and isinstance(run.get("seed_urls"), list) else set()
        page_urls = {str(page["url"]) for page in pages}
        source_urls: dict[str, list[dict[str, str]]] = {}
        for item in known_urls or []:
            url = item.get("url", "").strip()
            source = item.get("source", "").strip()
            if url and source:
                observation = {"source": source}
                observed_at = item.get("observed_at", "").strip()
                if observed_at:
                    observation["observed_at"] = observed_at
                for field in (
                    "source_sitemap",
                    "historical_status",
                    "historical_indexable",
                    "historical_canonical_state",
                ):
                    value = item.get(field, "").strip()
                    if value:
                        observation[field] = value
                source_urls.setdefault(url, []).append(observation)
        candidates = [
            {
                "url": str(page["url"]),
                "candidate_type": "crawled_html_zero_observed_inlinks",
                "observed_inlink_count": 0,
                "graph_complete": complete,
                "seed": str(page["url"]) in seeds,
                "is_crawled": True,
                "http_status": page.get("final_status_code"),
                "overall_indexable": page.get("overall_indexable"),
                "canonical_state": _canonical_state(str(page["url"]), page.get("canonical_urls_json")),
                "source_labels": sorted({item["source"] for item in source_urls.get(str(page["url"]), [])}),
                "source_observations": sorted(
                    source_urls.get(str(page["url"]), []),
                    key=lambda item: (item["source"], item.get("observed_at", "")),
                ),
                "live_validation_state": "not_requested",
            }
            for page in pages
            if inbound.get(str(page["url"]), 0) == 0
        ]
        for url, observations in sorted(source_urls.items()):
            if url in page_urls and inbound.get(url, 0) == 0:
                # The crawled-orphan row above already carries these source labels.
                continue
            sources = {item["source"] for item in observations}
            in_scope = url in inbound
            count = inbound.get(url)
            candidates.append(
                {
                    "url": url,
                    "candidate_type": (
                        "source_inventory_out_of_scope"
                        if not in_scope
                        else (
                            "source_known_zero_observed_inlinks" if count == 0 else "source_known_with_observed_inlinks"
                        )
                    ),
                    "observed_inlink_count": count,
                    "graph_complete": complete if in_scope else False,
                    "is_crawled": url in page_urls,
                    "http_status": self._source_int(observations, "historical_status"),
                    "overall_indexable": self._source_bool(observations, "historical_indexable"),
                    "canonical_state": self._source_value(observations, "historical_canonical_state") or "unknown",
                    "source_sitemaps": sorted(
                        {item["source_sitemap"] for item in observations if item.get("source_sitemap")}
                    ),
                    "source_labels": sorted(sources),
                    "source_observations": sorted(
                        observations, key=lambda item: (item["source"], item.get("observed_at", ""))
                    ),
                    "live_validation_state": "not_requested",
                }
            )
        return candidates

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

    async def _stored_html_pass(self) -> dict[str, list[dict[str, object]]]:
        """Scan the run's stored HTML once for every stored-source report.

        Pages are streamed from the store, so memory does not grow with the
        total HTML of the run, and each page is decompressed once however many
        of these reports a caller asks for.
        """
        if self._stored_html_cache is not None:
            return self._stored_html_cache
        run_id = await self._run_id()
        page_state = {
            str(row["url"]): row
            for row in await self._fetch(
                """
                SELECT u.url, s.overall_indexable, s.final_status_code, s.headers_json, s.title,
                       final_url.url AS final_url
                FROM page_run_snapshots s
                JOIN urls u ON u.id = s.url_id
                LEFT JOIN urls final_url ON final_url.id = s.final_url_id
                WHERE s.run_id = $1 AND s.html_compressed IS NOT NULL
                """,
                run_id,
            )
        }
        findings: list[dict[str, object]] = []
        semantic: list[dict[str, object]] = []
        soft_404: list[dict[str, object]] = []
        anchors: list[dict[str, object]] = []
        heading_wrapping: list[dict[str, object]] = []
        async for url, html in self.store.iter_run_html(run_id=run_id):
            state = page_state.get(url, {})
            findings.extend(_stored_html_rows(url, html, state))
            semantic.append(inspect_semantic_html(url, html).as_dict())
            candidate = _soft_404_candidate(url, html, state)
            if candidate is not None:
                soft_404.append(candidate)
            soup = parse_html(html)
            anchors.append(_empty_anchor_page_row(url, html, soup))
            final_url = state.get("final_url")
            heading_wrapping.extend(_heading_wrapping_links(url, soup, str(final_url) if final_url else None))
        self._stored_html_cache = {
            "stored-html": findings,
            "semantic-html": semantic,
            "soft404": soft_404,
            "empty-anchor-links": anchors,
            "heading-wrapping-links": heading_wrapping,
        }
        return self._stored_html_cache

    async def stored_html_findings(self) -> list[dict[str, object]]:
        """Inspect saved source for raw-markup facts lost by normal extraction."""
        return (await self._stored_html_pass())["stored-html"]

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
            canonicals = _json_value(page.get("canonical_urls_json"))
            if not isinstance(canonicals, list) or not any(urls_match(url, str(item)) for item in canonicals if item):
                continue
            for field, raw_value in (("title", page.get("title")), ("h1", page.get("h1_tags"))):
                value = str(raw_value or "").strip()
                if value:
                    values.setdefault((field, value), []).append(url)
        findings = []
        for (field, value), urls in sorted(values.items()):
            if len(urls) > 1:
                listed = urls[:_MAX_CLUSTER_URLS]
                more = f"\n(+{len(urls) - len(listed):,} more)" if len(urls) > len(listed) else ""
                findings.append(
                    {
                        "field": field,
                        "value": value,
                        "count": len(urls),
                        "urls": listed,
                        "url": "\n".join(listed) + more,
                    }
                )
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
            headers = _header_map(row.get("headers_json"))
            if row.get("final_status_code") == 200 and "x-robots-tag" not in headers and not _link_canonicals(headers):
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
        for page in pages:
            page["hreflang_json"] = _json_value(page.get("hreflang_json")) or []
            page["canonical_urls_json"] = _json_value(page.get("canonical_urls_json")) or []
        return hreflang_facts(pages)

    async def semantic_html_facts(self) -> list[dict[str, object]]:
        """Return one bounded source-HTML semantic fact row per stored page."""
        return (await self._stored_html_pass())["semantic-html"]

    async def profile_indexability_pages(self) -> list[dict[str, object]]:
        """Run-scoped page facts for profile policy evaluation; no policy is inferred here.

        Sitemap membership comes from this run's recorded sources and is NULL
        (unknown) when the run recorded none.  Inlinks count distinct linking
        pages in the run's link graph; a navigation target is linked from a
        header or nav element.
        """
        run_id = await self._run_id()
        return await self._fetch(
            """
            WITH run_sitemaps AS (
                SELECT DISTINCT url_id FROM run_url_sources
                WHERE run_id = $1 AND source IN ('sitemap', 'robots_sitemap')
            ),
            sitemap_evidence AS (SELECT EXISTS (SELECT 1 FROM run_sitemaps) AS present),
            edges AS (
                SELECT DISTINCT s.url_id AS source_id, link ->> 'href' AS href,
                       (link ->> 'xpath') ~* '/(header|nav)(\\[[0-9]+\\])?(/|$)' AS in_navigation
                FROM page_run_snapshots s
                JOIN urls src ON src.id = s.url_id
                CROSS JOIN LATERAL jsonb_array_elements(s.links_json) link
                WHERE s.run_id = $1 AND link ->> 'href' <> src.url
            ),
            inlinks AS (
                SELECT href, COUNT(DISTINCT source_id)::INT AS inlink_count, bool_or(in_navigation) AS in_navigation
                FROM edges GROUP BY href
            )
            SELECT u.url,
                   CASE WHEN evidence.present THEN sm.url_id IS NOT NULL END AS in_sitemap,
                   s.final_status_code AS status,
                   s.overall_indexable AS indexable,
                   (s.html_meta_allows IS FALSE OR s.http_header_allows IS FALSE) AS noindex,
                   s.canonical_urls_json ->> 0 AS canonical, s.word_count,
                   COALESCE(i.inlink_count, 0) AS inlink_count,
                   COALESCE(i.in_navigation, FALSE) AS is_navigation_target,
                   percent_rank() OVER (ORDER BY COALESCE(i.inlink_count, 0))::DOUBLE PRECISION AS inlink_percentile
            FROM page_run_snapshots s
            JOIN urls u ON u.id = s.url_id
            CROSS JOIN sitemap_evidence evidence
            LEFT JOIN run_sitemaps sm ON sm.url_id = s.url_id
            LEFT JOIN inlinks i ON i.href = u.url
            WHERE s.run_id = $1 AND u.kind = 'html' AND s.content_extracted IS TRUE
            ORDER BY u.url
            """,
            run_id,
        )

    async def soft404_error_routes(self) -> list[dict[str, object]]:
        """Conservative candidates for 200 pages whose title or H1 reads as an error page."""
        return (await self._stored_html_pass())["soft404"]

    async def discovery_source_provenance(self) -> list[dict[str, object]]:
        """Run-scoped sitemap-vs-internal-link discovery differences for review.

        Returns no rows when the run recorded no sitemap sources; the audit
        context's ``run_sitemap_source_count`` makes that unavailable rather
        than clean.
        """
        run_id = await self._run_id()
        return await self._fetch(
            """
            WITH run_sitemaps AS (
                SELECT DISTINCT url_id FROM run_url_sources
                WHERE run_id = $1 AND source IN ('sitemap', 'robots_sitemap')
            ),
            linked AS (
                SELECT DISTINCT link ->> 'href' AS href
                FROM page_run_snapshots s
                JOIN urls src ON src.id = s.url_id
                CROSS JOIN LATERAL jsonb_array_elements(s.links_json) link
                WHERE s.run_id = $1 AND link ->> 'href' <> src.url
            ),
            sources AS (
                SELECT u.url, sm.url_id IS NOT NULL AS in_sitemap, l.href IS NOT NULL AS internally_linked
                FROM page_run_snapshots s
                JOIN urls u ON u.id = s.url_id
                LEFT JOIN run_sitemaps sm ON sm.url_id = s.url_id
                LEFT JOIN linked l ON l.href = u.url
                WHERE s.run_id = $1 AND u.kind = 'html' AND EXISTS (SELECT 1 FROM run_sitemaps)
            )
            SELECT url, in_sitemap, internally_linked,
                   CASE WHEN in_sitemap THEN 'sitemap_only' ELSE 'internal_link_only' END AS issue
            FROM sources
            WHERE in_sitemap <> internally_linked
            ORDER BY url
            """,
            run_id,
        )

    async def crawl_depth_pages(self) -> list[dict[str, object]]:
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT u.url, f.depth AS crawl_depth
            FROM frontier f JOIN urls u ON u.id = f.url_id
            WHERE f.run_id = $1 AND f.discovery_kind <> 'speculative'
            ORDER BY u.url
            """,
            run_id,
        )

    async def performance_pages(self) -> list[dict[str, object]]:
        run_id = await self._run_id()
        return await self._fetch(
            """
            SELECT u.url, s.final_status_code, s.ttfb_seconds
            FROM page_run_snapshots s JOIN urls u ON u.id = s.url_id
            WHERE s.run_id = $1 AND u.kind = 'html'
            ORDER BY u.url
            """,
            run_id,
        )

    async def empty_anchor_links(self) -> list[dict[str, object]]:
        """One bounded row per stored page: internal anchor count plus its text-less anchors.

        Collected in the shared stored-HTML pass (ticket 379), so the audit JSON
        grows with pages, not with every internal link on the site.
        """
        return (await self._stored_html_pass())["empty-anchor-links"]

    async def heading_link_population(self, *, has_links_json: bool) -> dict[str, int | None]:
        """Count Q39's heading-link population: links inside an H2/H3 and links that wrap one.

        The internal-link-quality report keeps only failing links, so the
        population is counted here.  A link is a heading link when its saved
        XPath lies inside an H2/H3 (``links_json``) or when its anchor wraps
        an H2/H3 (``a > h2|h3`` or ``a > * > h2|h3``, from the stored HTML;
        ticket 421).  Links are distinct by source, target and XPath, and a
        link is tested when its target has a saved status in this run.

        ``heading_link_wrapping_count`` is None when the run stored no HTML,
        so the wrapping form could not be checked; all three are None without
        ``links_json``.
        """
        if not has_links_json:
            return {"heading_link_count": None, "heading_link_tested_count": None, "heading_link_wrapping_count": None}
        run_id = await self._run_id()
        stored = await self._stored_html_pass()
        # The pass yields one semantic-html row per stored page.
        html_checked = bool(stored["semantic-html"])
        wrapping = sorted(
            {
                (str(row["source_url"]), str(row["target_url"]), str(row["xpath"]))
                for row in stored["heading-wrapping-links"]
            }
        )
        heading = await self._fetch(
            """
            WITH heading_links AS (
                SELECT source.url AS source_url, link ->> 'href' AS target_url, link ->> 'xpath' AS xpath
                FROM page_run_snapshots s
                JOIN urls source ON source.id = s.url_id
                CROSS JOIN LATERAL jsonb_array_elements(s.links_json) link
                WHERE s.run_id = $1 AND (link ->> 'xpath') ~* $2
                UNION
                SELECT wrapping.source_url, wrapping.target_url, wrapping.xpath
                FROM unnest($3::TEXT[], $4::TEXT[], $5::TEXT[]) AS wrapping(source_url, target_url, xpath)
            )
            SELECT COUNT(*)::INT AS heading_link_count,
                   COUNT(*) FILTER (WHERE target.final_status_code IS NOT NULL)::INT AS heading_link_tested_count
            FROM heading_links h
            LEFT JOIN urls target_url ON target_url.url = h.target_url
            LEFT JOIN page_run_snapshots target ON target.run_id = $1 AND target.url_id = target_url.id
            """,
            run_id,
            HEADING_LINK_XPATH_PATTERN,
            [row[0] for row in wrapping],
            [row[1] for row in wrapping],
            [row[2] for row in wrapping],
        )
        return {
            "heading_link_count": _int_or_none(heading[0].get("heading_link_count")) if heading else 0,
            "heading_link_tested_count": _int_or_none(heading[0].get("heading_link_tested_count")) if heading else 0,
            "heading_link_wrapping_count": len(wrapping) if html_checked else None,
        }

    async def heading_wrapping_links(self) -> list[dict[str, object]]:
        """Internal links that wrap an H2/H3, one row per anchor, from the shared stored-HTML pass."""
        return (await self._stored_html_pass())["heading-wrapping-links"]

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
        """Internal links carrying weak crawl or consolidation signals, one row per issue.

        A target redirects when its saved final URL differs from the URL
        requested: a followed redirect stores its destination's status, so a
        3xx final status is not a usable signal.  Canonicals are compared
        without a trailing slash.
        """
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
            ),
            states AS (
                SELECT edges.*, target.final_status_code AS target_status,
                       target.overall_indexable AS target_indexable,
                       target.canonical_urls_json ->> 0 AS target_canonical,
                       final_url.url AS final_url,
                       target.final_url_id IS NOT NULL AND target.final_url_id <> target.url_id AS redirected
                FROM edges
                LEFT JOIN urls target_url ON target_url.url = edges.target_url
                LEFT JOIN page_run_snapshots target
                  ON target.run_id = $1 AND target.url_id = target_url.id
                LEFT JOIN urls final_url ON final_url.id = target.final_url_id
            )
            SELECT states.source_url, states.target_url, states.anchor_text, states.xpath,
                   states.target_status, states.target_indexable, states.target_canonical,
                   states.final_url, issue.name AS issue
            FROM states
            CROSS JOIN LATERAL (VALUES
              ('empty_anchor', states.anchor_text IS NULL),
              ('redirect_target', states.redirected OR states.target_status BETWEEN 300 AND 399),
              ('error_target', states.target_status >= 400),
              ('non_indexable_target', states.target_indexable = FALSE),
              ('noncanonical_target', NOT states.redirected
                 AND states.target_canonical IS NOT NULL
                 AND rtrim(states.target_canonical, '/') <> rtrim(states.target_url, '/'))
            ) AS issue(name, applies)
            WHERE issue.applies
            ORDER BY states.source_url, states.target_url, issue.name
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
