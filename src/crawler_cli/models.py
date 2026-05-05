from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(slots=True)
class FetchResponse:
    url: str
    requested_url: str
    status: int
    headers: dict[str, str]
    body: bytes
    text: str


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
    discovered_links: list[str] = field(default_factory=list)
    allowed_by_robots: bool | None = None
    skip_reason: str | None = None


@dataclass(slots=True)
class CrawlJobResult:
    mode: Literal["list", "open"]
    seed_urls: list[str]
    results: list[CrawlResult]
    saved_to: str | None = None

    @property
    def crawled_count(self) -> int:
        return sum(1 for result in self.results if result.skip_reason is None)

    @property
    def blocked_count(self) -> int:
        return sum(1 for result in self.results if result.skip_reason == "robots_txt_disallow")


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
