from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import aiohttp

from .config import CrawlConfig


async def discover_historical_urls(domain_or_url: str, config: CrawlConfig) -> list[str]:
    netloc = urlparse(domain_or_url).netloc or domain_or_url
    query_domain = netloc.lower().strip()
    if not query_domain:
        return []
    endpoint = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={query_domain}/*&output=json&fl=original&filter=statuscode:200&collapse=urlkey"
    )
    timeout = aiohttp.ClientTimeout(total=config.archive_timeout_seconds)
    headers = {"User-Agent": config.user_agent, **config.request_headers}
    attempts = 0
    while attempts < 3:
        attempts += 1
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(endpoint) as response:
                    if response.status == 429:
                        await asyncio.sleep(1.0 * attempts)
                        continue
                    response.raise_for_status()
                    payload = await response.json()
                    if not isinstance(payload, list):
                        return []
                    urls = [row[0] for row in payload[1:] if isinstance(row, list) and row]
                    deduped = list(dict.fromkeys(urls))
                    return deduped[: config.archive_max_urls]
        except (aiohttp.ClientError, asyncio.TimeoutError):
            await asyncio.sleep(0.5 * attempts)
    return []

