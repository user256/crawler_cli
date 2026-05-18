from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from .backends import build_backend
from .config import CrawlConfig
from .engine import CrawlEngine
from .extract import extract_links


@dataclass(slots=True)
class RenderComparison:
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


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().lower()


def _extract_links_set(raw_html: str | None, base_url: str) -> set[str]:
    if not raw_html:
        return set()
    links = extract_links(raw_html, base_url, same_host_only=True)
    return set(links)


def _cluster_paths(paths: set[str]) -> dict[str, int]:
    clusters: dict[str, int] = {}
    for path in paths:
        top = path.strip("/").split("/")[0] if "/" in path else path
        clusters[top] = clusters.get(top, 0) + 1
    return clusters


async def compare_renders(
    url: str,
    *,
    nojs_config: CrawlConfig,
    js_config: CrawlConfig,
) -> RenderComparison:
    """Fetch the same URL with aiohttp and playwright backends and diff SEO signals."""
    nojs_engine = CrawlEngine(nojs_config)
    js_engine = CrawlEngine(js_config)

    nojs_result, js_result = await asyncio.gather(
        nojs_engine.crawl(url),
        js_engine.crawl(url),
    )

    nojs_title = _norm(nojs_result.extracted.title if nojs_result.extracted else None)
    js_title = _norm(js_result.extracted.title if js_result.extracted else None)
    nojs_canonical = _norm(nojs_result.extracted.canonical if nojs_result.extracted else None)
    js_canonical = _norm(js_result.extracted.canonical if js_result.extracted else None)
    nojs_robots = _norm(
        " ".join(nojs_result.extracted.meta_robots.raw) if nojs_result.extracted else None
    )
    js_robots = _norm(
        " ".join(js_result.extracted.meta_robots.raw) if js_result.extracted else None
    )
    nojs_meta = _norm(nojs_result.extracted.meta_description if nojs_result.extracted else None)
    js_meta = _norm(js_result.extracted.meta_description if js_result.extracted else None)

    title_match = nojs_title == js_title
    canonical_match = nojs_canonical == js_canonical
    robots_match = nojs_robots == js_robots
    meta_description_match = nojs_meta == js_meta

    nojs_links = _extract_links_set(nojs_result.raw_html, url)
    js_links = _extract_links_set(js_result.raw_html, url)
    only_in_js = js_links - nojs_links
    only_in_nojs = nojs_links - js_links

    nojs_len = len(nojs_result.raw_html or "")
    js_len = len(js_result.raw_html or "")
    size_delta_pct = 0.0
    if nojs_len > 0:
        size_delta_pct = abs(js_len - nojs_len) / nojs_len * 100

    verdict: Literal["ok", "nav_js_injected", "content_js_only", "meta_drift"] = "ok"
    if not title_match or not canonical_match or not robots_match or not meta_description_match:
        verdict = "meta_drift"
    elif len(only_in_js) > 5:
        clusters = _cluster_paths(only_in_js)
        # If URLs cluster under a small number of top-level paths, looks like nav
        if len(clusters) <= 3:
            verdict = "nav_js_injected"
    elif size_delta_pct > 30 and len(only_in_js) <= 5:
        verdict = "content_js_only"

    return RenderComparison(
        url=url,
        nojs=nojs_result,
        js=js_result,
        title_match=title_match,
        canonical_match=canonical_match,
        robots_match=robots_match,
        meta_description_match=meta_description_match,
        nojs_internal_links=nojs_links,
        js_internal_links=js_links,
        only_in_js=only_in_js,
        only_in_nojs=only_in_nojs,
        size_delta_pct=size_delta_pct,
        verdict=verdict,
    )


async def compare_renders_sampled(
    urls: Iterable[str],
    *,
    nojs_config: CrawlConfig,
    js_config: CrawlConfig,
    max_concurrent_js: int = 2,
) -> list[RenderComparison]:
    """Compare renders for a sample of URLs, bounding playwright concurrency."""
    url_list = list(urls)
    semaphore = asyncio.Semaphore(max_concurrent_js)

    async def _one(url: str) -> RenderComparison:
        async with semaphore:
            return await compare_renders(url, nojs_config=nojs_config, js_config=js_config)

    return await asyncio.gather(*[_one(url) for url in url_list])
