from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal
from urllib.parse import urlsplit

from .config import CrawlConfig
from .engine import CrawlEngine
from .extract import extract_links, extract_page_data
from .intent_signature import extract_main_text
from .models import CrawlResult, ExtractedContent

RENDER_COMPARISON_RULESET_VERSION = "crawler-cli/render-comparison-rules/1"
RenderObservationState = Literal["complete", "partial", "inconclusive", "failed"]
RenderFindingSeverity = Literal["high", "medium", "low"]


@dataclass(slots=True)
class RenderFinding:
    code: str
    severity: RenderFindingSeverity
    field: str
    explanation: str
    remediation: str
    raw_value: object | None = None
    rendered_value: object | None = None
    completeness: RenderObservationState = "complete"
    ruleset_version: str = RENDER_COMPARISON_RULESET_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "field": self.field,
            "explanation": self.explanation,
            "remediation": self.remediation,
            "raw_value": self.raw_value,
            "rendered_value": self.rendered_value,
            "completeness": self.completeness,
            "ruleset_version": self.ruleset_version,
        }


@dataclass(slots=True)
class RenderParityComparison:
    """Raw-response versus hydrated-DOM evidence from one browser navigation."""

    url: str
    final_url: str
    status: int
    state: RenderObservationState
    state_reason: str | None
    raw: ExtractedContent | None
    rendered: ExtractedContent | None
    raw_internal_links: set[str] = field(default_factory=set)
    rendered_internal_links: set[str] = field(default_factory=set)
    only_in_rendered: set[str] = field(default_factory=set)
    only_in_raw: set[str] = field(default_factory=set)
    raw_main_text: str | None = None
    rendered_main_text: str | None = None
    raw_main_text_method: str = "none"
    rendered_main_text_method: str = "none"
    content_similarity: float | None = None
    size_delta_pct: float | None = None
    findings: list[RenderFinding] = field(default_factory=list)
    primary_summary: str = "equivalent"
    crawl_result: CrawlResult | None = field(default=None, repr=False)

    def as_dict(self, *, link_limit: int = 100, excerpt_limit: int = 500) -> dict[str, object]:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status": self.status,
            "state": self.state,
            "state_reason": self.state_reason,
            "primary_summary": self.primary_summary,
            "ruleset_version": RENDER_COMPARISON_RULESET_VERSION,
            "signals": {
                "raw": _extracted_summary(self.raw),
                "rendered": _extracted_summary(self.rendered),
                "raw_main_text_method": self.raw_main_text_method,
                "rendered_main_text_method": self.rendered_main_text_method,
                "raw_main_text_excerpt": (self.raw_main_text or "")[:excerpt_limit] or None,
                "rendered_main_text_excerpt": (self.rendered_main_text or "")[:excerpt_limit] or None,
                "content_similarity": self.content_similarity,
                "size_delta_pct": self.size_delta_pct,
                "raw_internal_link_count": len(self.raw_internal_links),
                "rendered_internal_link_count": len(self.rendered_internal_links),
                "only_in_rendered_count": len(self.only_in_rendered),
                "only_in_raw_count": len(self.only_in_raw),
                "only_in_rendered": sorted(self.only_in_rendered)[:link_limit],
                "only_in_raw": sorted(self.only_in_raw)[:link_limit],
            },
            "findings": [finding.as_dict() for finding in self.findings],
        }


@dataclass(slots=True)
class RenderComparison:
    """Legacy independent-client comparison retained for API compatibility."""

    url: str
    nojs: object
    js: object
    title_match: bool
    canonical_match: bool
    robots_match: bool
    meta_description_match: bool
    nojs_internal_links: set[str] = field(default_factory=set)
    js_internal_links: set[str] = field(default_factory=set)
    only_in_js: set[str] = field(default_factory=set)
    only_in_nojs: set[str] = field(default_factory=set)
    size_delta_pct: float = 0.0
    verdict: Literal["ok", "nav_js_injected", "content_js_only", "meta_drift"] = "ok"
    baseline_source: Literal["independent_http"] = "independent_http"


def _norm(value: str | None) -> str | None:
    return re.sub(r"\s+", " ", value).strip().casefold() if value else None


def _norm_url(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value.strip())
    if not parts.scheme or not parts.netloc:
        return value.strip()
    host = parts.hostname.lower() if parts.hostname else parts.netloc.lower()
    netloc = f"{host}:{parts.port}" if parts.port else host
    return f"{parts.scheme.lower()}://{netloc}{parts.path or '/'}" + (f"?{parts.query}" if parts.query else "")


def _extract_links_set(raw_html: str | None, base_url: str) -> set[str]:
    return {link.href for link in extract_links(raw_html, base_url, same_host_only=True)} if raw_html else set()


def _cluster_paths(urls: set[str]) -> dict[str, int]:
    """Cluster absolute URLs by first path segment, never by URL scheme."""
    clusters: dict[str, int] = {}
    for value in urls:
        path = urlsplit(value).path or "/"
        top = path.strip("/").split("/", 1)[0] or "/"
        clusters[top] = clusters.get(top, 0) + 1
    return clusters


def _directive_set(extracted: ExtractedContent | None) -> set[str]:
    return set(extracted.meta_robots.raw) if extracted else set()


def _hreflang_set(extracted: ExtractedContent | None) -> set[tuple[str, str]]:
    if extracted is None:
        return set()
    return {(item.hreflang.casefold(), _norm_url(item.href) or item.href) for item in extracted.hreflang_links}


def _schema_summary(extracted: ExtractedContent | None) -> list[tuple[str, bool, str]]:
    if extracted is None:
        return []
    return sorted(
        (
            str(item.get("schema_type") or item.get("type") or "unknown"),
            bool(item.get("is_valid", False)),
            json.dumps(item.get("parsed_data") or item.get("data") or {}, sort_keys=True, default=str),
        )
        for item in extracted.schema_data
    )


def _extracted_summary(extracted: ExtractedContent | None) -> dict[str, object] | None:
    if extracted is None:
        return None
    return {
        "title": extracted.title,
        "meta_description": extracted.meta_description,
        "meta_robots": sorted(_directive_set(extracted)),
        "canonical": extracted.canonical,
        "hreflang": sorted(f"{lang}:{href}" for lang, href in _hreflang_set(extracted)),
        "html_lang": extracted.html_lang,
        "h1": extracted.headings.get("h1", []),
        "schema": [{"type": schema_type, "is_valid": valid} for schema_type, valid, _ in _schema_summary(extracted)],
    }


def _finding(
    code: str,
    severity: RenderFindingSeverity,
    field: str,
    explanation: str,
    remediation: str,
    raw_value: object | None,
    rendered_value: object | None,
    state: RenderObservationState,
) -> RenderFinding:
    return RenderFinding(code, severity, field, explanation, remediation, raw_value, rendered_value, state)


def compare_rendered_result(result: CrawlResult) -> RenderParityComparison:
    """Compare the pre-hydration response and final DOM from one navigation."""
    reason: str | None = None
    if result.skip_reason:
        reason = result.skip_reason
    elif result.body_truncated:
        reason = "body_truncated"
    elif result.render_baseline_truncated:
        reason = "render_baseline_truncated"
    elif result.render_raw_html is None:
        reason = "baseline_unavailable"
    elif result.raw_html is None or result.extracted is None:
        reason = "rendered_html_unavailable"
    elif not 200 <= result.status < 300:
        reason = f"http_{result.status}"
    if reason is not None:
        finding = _finding(
            "render_comparison_incomplete",
            "low",
            "navigation",
            "The raw response and hydrated DOM cannot be compared conclusively.",
            "Resolve the stated capture condition and repeat the comparison.",
            None,
            None,
            "inconclusive",
        )
        return RenderParityComparison(
            result.requested_url,
            result.final_url,
            result.status,
            "inconclusive",
            reason,
            None,
            result.extracted,
            findings=[finding],
            primary_summary="inconclusive",
            crawl_result=result,
        )

    raw_html, rendered_html = result.render_raw_html, result.raw_html
    raw = extract_page_data(raw_html, result.final_url, result.headers)
    rendered = result.extracted
    state: RenderObservationState = "complete" if result.render_settled is not False else "partial"
    raw_links = _extract_links_set(raw_html, result.final_url)
    rendered_links = _extract_links_set(rendered_html, result.final_url)
    raw_text, raw_method = extract_main_text(raw_html)
    rendered_text, rendered_method = extract_main_text(rendered_html)
    similarity = (
        round(SequenceMatcher(None, _norm(raw_text) or "", _norm(rendered_text) or "").ratio(), 4)
        if raw_text is not None and rendered_text is not None
        else None
    )
    delta = ((len(rendered_html) - len(raw_html)) / len(raw_html) * 100) if raw_html else None
    comparison = RenderParityComparison(
        result.requested_url,
        result.final_url,
        result.status,
        state,
        "render_settle_timeout" if state == "partial" else None,
        raw,
        rendered,
        raw_links,
        rendered_links,
        rendered_links - raw_links,
        raw_links - rendered_links,
        raw_text,
        rendered_text,
        raw_method,
        rendered_method,
        similarity,
        round(delta, 2) if delta is not None else None,
        crawl_result=result,
    )
    if state == "partial":
        comparison.findings.append(
            _finding(
                "render_comparison_incomplete",
                "low",
                "render_settle",
                "Configured browser settle conditions timed out; observed differences are partial evidence.",
                "Use a page-specific wait selector or investigate long-running browser activity.",
                None,
                None,
                state,
            )
        )

    fields: tuple[tuple[str, str | None, str | None, str, RenderFindingSeverity], ...] = (
        ("title", raw.title, rendered.title, "metadata_render_dependency", "medium"),
        ("meta_description", raw.meta_description, rendered.meta_description, "metadata_render_dependency", "low"),
        ("canonical", raw.canonical, rendered.canonical, "canonical_changed", "high"),
        ("html_lang", raw.html_lang, rendered.html_lang, "metadata_render_dependency", "low"),
    )
    for field_name, raw_value, rendered_value, code, severity in fields:
        normalizer = _norm_url if field_name == "canonical" else _norm
        if normalizer(raw_value) != normalizer(rendered_value):
            comparison.findings.append(
                _finding(
                    code,
                    severity,
                    field_name,
                    f"{field_name.replace('_', ' ')} differs between initial HTML and hydrated DOM.",
                    "Emit the intended signal in initial HTML where possible, then verify a representative URL in Search Console.",
                    raw_value,
                    rendered_value,
                    state,
                )
            )
    if _directive_set(raw) != _directive_set(rendered):
        comparison.findings.append(
            _finding(
                "indexing_directive_changed",
                "high",
                "meta_robots",
                "Robots directives differ after rendering, which can change indexability interpretation.",
                "Keep indexing directives stable in initial HTML and validate the live URL in Search Console.",
                sorted(_directive_set(raw)),
                sorted(_directive_set(rendered)),
                state,
            )
        )
    if _hreflang_set(raw) != _hreflang_set(rendered):
        comparison.findings.append(
            _finding(
                "hreflang_changed",
                "medium",
                "hreflang",
                "Hreflang annotations differ after rendering.",
                "Emit stable hreflang annotations in initial HTML or the sitemap and validate reciprocal alternates.",
                sorted(_hreflang_set(raw)),
                sorted(_hreflang_set(rendered)),
                state,
            )
        )
    if raw.headings.get("h1", []) != rendered.headings.get("h1", []):
        comparison.findings.append(
            _finding(
                "metadata_render_dependency",
                "low",
                "h1",
                "H1 content or count differs after rendering.",
                "Ensure the primary heading is available in initial HTML when practical.",
                raw.headings.get("h1", []),
                rendered.headings.get("h1", []),
                state,
            )
        )
    if _schema_summary(raw) != _schema_summary(rendered):
        comparison.findings.append(
            _finding(
                "structured_data_changed",
                "medium",
                "structured_data",
                "Structured-data blocks or parse validity differ after rendering.",
                "Serve essential JSON-LD in initial HTML and verify feature eligibility with Google's Rich Results Test.",
                (_extracted_summary(raw) or {}).get("schema", []),
                (_extracted_summary(rendered) or {}).get("schema", []),
                state,
            )
        )
    if comparison.only_in_rendered:
        comparison.findings.append(
            _finding(
                "internal_links_added_after_render",
                "medium",
                "internal_links",
                "Internal crawlable links are present only in the hydrated DOM.",
                "Keep important discovery links as ordinary initial-HTML <a href> elements where possible.",
                [],
                sorted(comparison.only_in_rendered)[:100],
                state,
            )
        )
    if comparison.only_in_raw:
        comparison.findings.append(
            _finding(
                "internal_links_removed_after_render",
                "medium",
                "internal_links",
                "Internal crawlable links in the response are absent from the hydrated DOM.",
                "Investigate client-side routing or DOM replacement so important links remain stable after rendering.",
                sorted(comparison.only_in_raw)[:100],
                [],
                state,
            )
        )
    raw_words, rendered_words = len((raw_text or "").split()), len((rendered_text or "").split())
    if similarity is not None and abs(rendered_words - raw_words) >= 30 and similarity < 0.7:
        code, explanation = (
            ("primary_content_render_dependency", "Substantive main content appears only after rendering.")
            if rendered_words > raw_words
            else ("content_removed_after_render", "Substantive initial main content is absent after rendering.")
        )
        content_severity: RenderFindingSeverity = "high" if raw_method == rendered_method == "trafilatura" else "medium"
        comparison.findings.append(
            _finding(
                code,
                content_severity,
                "main_content",
                explanation,
                "Render primary content server-side or ensure it is reliably available to rendering clients; verify in Search Console.",
                (raw_text or "")[:500],
                (rendered_text or "")[:500],
                state,
            )
        )
    header_directives = set(rendered.x_robots_tag.raw)
    if header_directives and header_directives != _directive_set(rendered):
        comparison.findings.append(
            _finding(
                "header_dom_conflict",
                "high",
                "robots_header",
                "X-Robots-Tag conflicts with rendered meta robots directives.",
                "Align HTTP X-Robots-Tag and HTML meta robots directives.",
                sorted(header_directives),
                sorted(_directive_set(rendered)),
                state,
            )
        )
    if state == "partial":
        comparison.primary_summary = "partial"
    elif comparison.findings:
        comparison.primary_summary = next(
            (item.code for item in comparison.findings if item.severity == "high"), comparison.findings[0].code
        )
    return comparison


async def compare_rendered_page(engine: CrawlEngine, url: str) -> RenderParityComparison:
    return compare_rendered_result(await engine.crawl(url))


async def compare_rendered_sample(
    engine: CrawlEngine, urls: Iterable[str], *, max_concurrent: int = 1
) -> list[RenderParityComparison]:
    if max_concurrent < 1 or max_concurrent > 2:
        raise ValueError("max_concurrent must be between 1 and 2")
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _one(url: str) -> RenderParityComparison:
        async with semaphore:
            return await compare_rendered_page(engine, url)

    return await asyncio.gather(*(_one(url) for url in urls))


async def compare_renders(url: str, *, nojs_config: CrawlConfig, js_config: CrawlConfig) -> RenderComparison:
    """Legacy independent-client comparison; prefer same-navigation helpers."""
    nojs_engine, js_engine = CrawlEngine(nojs_config), CrawlEngine(js_config)
    try:
        nojs_result, js_result = await asyncio.gather(nojs_engine.crawl(url), js_engine.crawl(url))
    finally:
        await asyncio.gather(nojs_engine.close(), js_engine.close())
    nojs_title, js_title = (
        _norm(nojs_result.extracted.title if nojs_result.extracted else None),
        _norm(js_result.extracted.title if js_result.extracted else None),
    )
    nojs_canonical = _norm_url(nojs_result.extracted.canonical if nojs_result.extracted else None)
    js_canonical = _norm_url(js_result.extracted.canonical if js_result.extracted else None)
    nojs_robots, js_robots = _directive_set(nojs_result.extracted), _directive_set(js_result.extracted)
    nojs_meta, js_meta = (
        _norm(nojs_result.extracted.meta_description if nojs_result.extracted else None),
        _norm(js_result.extracted.meta_description if js_result.extracted else None),
    )
    nojs_links, js_links = _extract_links_set(nojs_result.raw_html, url), _extract_links_set(js_result.raw_html, url)
    only_in_js, only_in_nojs = js_links - nojs_links, nojs_links - js_links
    nojs_len, js_len = len(nojs_result.raw_html or ""), len(js_result.raw_html or "")
    size_delta_pct = abs(js_len - nojs_len) / nojs_len * 100 if nojs_len else 0.0
    verdict: Literal["ok", "nav_js_injected", "content_js_only", "meta_drift"] = "ok"
    if nojs_title != js_title or nojs_canonical != js_canonical or nojs_robots != js_robots or nojs_meta != js_meta:
        verdict = "meta_drift"
    elif len(only_in_js) > 5 and len(_cluster_paths(only_in_js)) <= 3:
        verdict = "nav_js_injected"
    elif size_delta_pct > 30 and len(only_in_js) <= 5:
        verdict = "content_js_only"
    return RenderComparison(
        url,
        nojs_result,
        js_result,
        nojs_title == js_title,
        nojs_canonical == js_canonical,
        nojs_robots == js_robots,
        nojs_meta == js_meta,
        nojs_links,
        js_links,
        only_in_js,
        only_in_nojs,
        size_delta_pct,
        verdict,
    )


async def compare_renders_sampled(
    urls: Iterable[str], *, nojs_config: CrawlConfig, js_config: CrawlConfig, max_concurrent_js: int = 2
) -> list[RenderComparison]:
    semaphore = asyncio.Semaphore(max_concurrent_js)

    async def _one(url: str) -> RenderComparison:
        async with semaphore:
            return await compare_renders(url, nojs_config=nojs_config, js_config=js_config)

    return await asyncio.gather(*(_one(url) for url in urls))
