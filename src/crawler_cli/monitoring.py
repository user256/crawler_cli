from __future__ import annotations

from collections.abc import Mapping

from .backends import build_backend
from .config import BackendName, CrawlConfig
from .extract import extract_page_data
from .models import ExtractedContent, FetchResponse


async def fetch_page(
    url: str,
    *,
    user_agent: str = "crawler_cli/0.1",
    headers: Mapping[str, str] | None = None,
    timeout_seconds: float = 30.0,
    follow_redirects: bool = True,
    backend: BackendName = "aiohttp",
    verify_ssl: bool = True,
    max_response_bytes: int = 5_000_000,
) -> FetchResponse:
    """Fetch a single page without invoking CrawlEngine or persistence."""
    config = CrawlConfig(
        backend=backend,
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
        follow_redirects=follow_redirects,
        verify_ssl=verify_ssl,
        max_response_bytes=max_response_bytes,
        request_headers=dict(headers or {}),
    )
    fetch_backend = build_backend(config)
    try:
        return await fetch_backend.fetch(url)
    finally:
        await fetch_backend.close()


def extract_page(
    html: str,
    headers: Mapping[str, str] | None,
    url: str,
) -> ExtractedContent:
    """Extract SEO-relevant fields from a fetched HTML document."""
    return extract_page_data(html, url, dict(headers or {}))
