from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .detection.analytics import AnalyticsDetectionResult
    from .detection.cms import CMSDetectionResult


@dataclass(slots=True)
class BrowserRuntime:
    provider: Literal["chromium", "cdp", "obscura"]
    cdp_endpoint: str | None = None
    managed: bool | None = None
    stealth: bool | None = None


@dataclass(slots=True)
class FetchResponse:
    url: str
    requested_url: str
    status: int
    headers: dict[str, str]
    body: bytes
    text: str
    ttfb_seconds: float | None = None
    """Time to first byte: request send → first response byte (ticket 029)."""
    elapsed_seconds: float | None = None
    """Total fetch duration: request send → full body received (ticket 029)."""
    body_truncated: bool = False
    """True when the response body was capped at max_response_bytes during streaming."""


@dataclass(slots=True)
class HreflangLink:
    hreflang: str
    href: str
    source: Literal["http_header", "html_head", "sitemap"]


@dataclass(slots=True)
class RobotsDirectives:
    noindex: bool = False
    nofollow: bool = False
    raw: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExtractedContent:
    title: str | None
    meta_description: str | None
    meta_robots: RobotsDirectives
    x_robots_tag: RobotsDirectives
    canonical: str | None
    x_canonical: str | None
    hreflang_links: list[HreflangLink]
    html_lang: str | None
    headings: dict[str, list[str]]
    text: str
    word_count: int
    metadata: dict[str, Any]
    schema_data: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class DiscoveredLink:
    href: str
    anchor_text: str | None
    xpath: str
    is_image: bool
    fragment: str | None = None
    url_parameters: str | None = None
    original_href: str | None = None


@dataclass(slots=True)
class CrawlResult:
    requested_url: str
    final_url: str
    status: int
    headers: dict[str, str]
    content_type: str | None
    fetch_backend: str
    extracted: ExtractedContent | None
    raw_html: str | None
    content_hash_sha256: str | None = None
    content_hash_simhash: int | None = None
    discovered_links: list[DiscoveredLink] = field(default_factory=list)
    allowed_by_robots: bool | None = None
    skip_reason: str | None = None
    persist_error: str | None = None
    detected_cms: "CMSDetectionResult | None" = None
    detected_analytics: "AnalyticsDetectionResult | None" = None
    browser_runtime: BrowserRuntime | None = None
    ttfb_seconds: float | None = None
    total_duration_seconds: float | None = None
    custom_data: dict[str, Any] | None = None


@dataclass(slots=True)
class CrawlJobResult:
    mode: Literal["list", "open"]
    seed_urls: list[str]
    results: list[CrawlResult]
    saved_to: str | None = None
    retry_attempts: int = 0
    """Total transient-error attempts that were retried and do not appear in
    *results* (ticket-062).  Surfaced in the CLI summary."""
    interrupted: bool = False
    """True when the crawl was stopped early via a signal (ticket-064)."""

    @property
    def crawled_count(self) -> int:
        return sum(1 for result in self.results if result.skip_reason is None)

    @property
    def blocked_count(self) -> int:
        return sum(1 for result in self.results if result.skip_reason == "robots_txt_disallow")

    @property
    def persist_error_count(self) -> int:
        return sum(1 for result in self.results if result.persist_error is not None)


@dataclass(slots=True)
class SitemapUrl:
    loc: str
    lastmod: str | None = None
    hreflang_links: list[HreflangLink] = field(default_factory=list)


@dataclass(slots=True)
class SitemapDocument:
    url: str
    kind: Literal["sitemap", "sitemap_index", "text"]
    urls: list[SitemapUrl] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
