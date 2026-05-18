from __future__ import annotations

import asyncio
import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from .config import CrawlConfig


@dataclass(slots=True)
class LegacyIssue:
    url: str
    final_status_code: int | None
    redirect_chain_length: int
    redirect_final_status_code: int | None


@dataclass(slots=True)
class ArchiveAuditResult:
    archive_url_count: int
    missing_urls: list[str] = field(default_factory=list)
    legacy_issues: list[LegacyIssue] = field(default_factory=list)


DEFAULT_ARCHIVE_STRIP_EXTENSIONS = (
    ".js", ".css", ".jpg", ".jpeg", ".png", ".gif",
    ".svg", ".webp", ".ico", ".bmp", ".woff", ".woff2",
    ".ttf", ".eot", ".pdf",
)

DEFAULT_ARCHIVE_STRIP_PATHS = (
    "/wp-json",
    "/.well-known",
)


def _normalize_url(url: str) -> str | None:
    """Strip whitespace and basic fix-ups."""
    url = url.strip()
    if not url:
        return None
    # Drop double-prefix artifacts like https://example.com/https://other.com
    if url.count("://") > 1:
        first_scheme = url.find("://")
        second_scheme = url.find("://", first_scheme + 3)
        if second_scheme != -1:
            url = url[second_scheme + 3:]
            if "://" not in url:
                url = "https://" + url
    return url


def _clean_url(
    url: str,
    *,
    strip_extensions: tuple[str, ...] = DEFAULT_ARCHIVE_STRIP_EXTENSIONS,
    strip_paths: tuple[str, ...] = DEFAULT_ARCHIVE_STRIP_PATHS,
    force_https: bool = False,
    force_www: bool = False,
) -> str | None:
    """Filter and normalise a single CDX URL."""
    url = url.strip()
    if not url:
        return None
    if url.startswith("mailto:"):
        return None
    parsed = urlparse(url)
    path = parsed.path or "/"
    lower_path = path.lower()
    for ext in strip_extensions:
        if lower_path.endswith(ext):
            return None
    for sp in strip_paths:
        if lower_path.startswith(sp.lower()):
            return None
    # Strip explicit ports
    netloc = parsed.netloc
    if ":" in netloc:
        host, port = netloc.rsplit(":", 1)
        if port.isdigit():
            netloc = host
    scheme = parsed.scheme or "https"
    if force_https:
        scheme = "https"
    if force_www and not netloc.startswith("www."):
        netloc = "www." + netloc
    rebuilt = f"{scheme}://{netloc}{path}"
    if parsed.query:
        rebuilt += f"?{parsed.query}"
    if parsed.fragment:
        rebuilt += f"#{parsed.fragment}"
    return rebuilt


async def discover_historical_urls(
    domain_or_url: str,
    config: CrawlConfig,
    *,
    strip_extensions: tuple[str, ...] | None = None,
    strip_paths: tuple[str, ...] | None = None,
    force_https: bool = False,
    force_www: bool = False,
) -> list[str]:
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
    raw_urls: list[str] = []
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
                    raw_urls = [row[0] for row in payload[1:] if isinstance(row, list) and row]
                    break
        except (aiohttp.ClientError, asyncio.TimeoutError):
            await asyncio.sleep(0.5 * attempts)

    se = strip_extensions if strip_extensions is not None else DEFAULT_ARCHIVE_STRIP_EXTENSIONS
    sp = strip_paths if strip_paths is not None else DEFAULT_ARCHIVE_STRIP_PATHS

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in raw_urls:
        norm = _normalize_url(raw)
        if norm is None:
            continue
        cleaned_url = _clean_url(
            norm,
            strip_extensions=se,
            strip_paths=sp,
            force_https=force_https,
            force_www=force_www,
        )
        if cleaned_url is None:
            continue
        if cleaned_url in seen:
            continue
        seen.add(cleaned_url)
        cleaned.append(cleaned_url)

    return cleaned[: config.archive_max_urls]


async def audit_archive_urls(
    domain: str,
    store,
    config: CrawlConfig,
    *,
    output_dir: Path | None = None,
    strip_extensions: tuple[str, ...] | None = None,
    strip_paths: tuple[str, ...] | None = None,
    force_https: bool = False,
    force_www: bool = False,
) -> ArchiveAuditResult:
    """Post-crawl archive.org diff: missing URLs + legacy issues."""
    from .persistence import AsyncpgStore

    assert isinstance(store, AsyncpgStore)
    archive_urls = await discover_historical_urls(
        domain,
        config,
        strip_extensions=strip_extensions,
        strip_paths=strip_paths,
        force_https=force_https,
        force_www=force_www,
    )

    await store.connect()
    assert store.pool is not None

    # Chunked lookup against urls table
    batch_size = 500
    found_urls: set[str] = set()
    for i in range(0, len(archive_urls), batch_size):
        batch = archive_urls[i : i + batch_size]
        async with store.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT url FROM urls WHERE url = ANY($1::text[])",
                batch,
            )
            found_urls.update(str(row["url"]) for row in rows)

    missing = [url for url in archive_urls if url not in found_urls]

    # Legacy issues: URLs in DB that now return >=400 or have redirect chains
    legacy: list[LegacyIssue] = []
    to_inspect = list(found_urls)
    for i in range(0, len(to_inspect), batch_size):
        batch = to_inspect[i : i + batch_size]
        async with store.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT u.url, pm.final_status_code, pm.initial_status_code
                FROM urls u
                JOIN page_metadata pm ON pm.url_id = u.id
                WHERE u.url = ANY($1::text[])
                """,
                batch,
            )
            for row in rows:
                url = str(row["url"])
                final_status = row["final_status_code"]
                initial_status = row["initial_status_code"]
                chain_len = 0
                final_redirect_status = final_status
                if initial_status is not None and final_status is not None and initial_status != final_status:
                    chain_len = 1  # At minimum one redirect occurred
                if (final_status is not None and final_status >= 400) or chain_len > 0:
                    legacy.append(
                        LegacyIssue(
                            url=url,
                            final_status_code=final_status,
                            redirect_chain_length=chain_len,
                            redirect_final_status_code=final_redirect_status,
                        )
                    )

    result = ArchiveAuditResult(
        archive_url_count=len(archive_urls),
        missing_urls=missing,
        legacy_issues=legacy,
    )

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_domain = domain.replace("://", "_").replace("/", "_")
        missing_path = output_dir / f"{safe_domain}_archive_missing.csv"
        legacy_path = output_dir / f"{safe_domain}_archive_legacy_issues.csv"

        with missing_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["url"])
            for url in missing:
                writer.writerow([url])

        with legacy_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["url", "final_status_code", "redirect_chain_length", "redirect_final_status_code"])
            for issue in legacy:
                writer.writerow([
                    issue.url,
                    issue.final_status_code,
                    issue.redirect_chain_length,
                    issue.redirect_final_status_code,
                ])

    return result
