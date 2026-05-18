from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .archive import audit_archive_urls
from .config import CrawlConfig
from .engine import CrawlEngine
from .persistence import AsyncpgStore


def _env_or_default(prefix: str, key: str, default: str | None = None) -> str | None:
    """Read env var with given prefix, falling back to CRAWLER_CLI_* then PostgreSQLCrawler_*."""
    for p in (prefix, "CRAWLER_CLI", "PostgreSQLCrawler"):
        val = os.environ.get(f"{p}_{key}")
        if val:
            return val
    return default


def _build_dsn(args: argparse.Namespace) -> str:
    """Build PostgreSQL DSN from CLI flags and env vars."""
    if args.postgres_dsn:
        return args.postgres_dsn
    host = args.postgres_host or _env_or_default("CRAWLER_CLI", "POSTGRES_HOST", "localhost")
    port = args.postgres_port or _env_or_default("CRAWLER_CLI", "POSTGRES_PORT", "5432")
    user = args.postgres_user or _env_or_default("CRAWLER_CLI", "POSTGRES_USER", "crawler")
    password = args.postgres_password or _env_or_default("CRAWLER_CLI", "POSTGRES_PASSWORD", "")
    dbname = args.postgres_db or _env_or_default("CRAWLER_CLI", "POSTGRES_DB", "crawler")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def _build_config(args: argparse.Namespace) -> CrawlConfig:
    backend: str = "playwright" if args.js else (args.http_backend or "aiohttp")
    headers: dict[str, str] = {}
    if args.custom_ua:
        headers["User-Agent"] = args.custom_ua

    return CrawlConfig(
        backend=backend,  # type: ignore[arg-type]
        user_agent=args.custom_ua or "crawler_cli/0.1",
        max_concurrency=args.concurrency,
        max_pages=args.max_pages,
        respect_robots_txt=not args.ignore_robots,
        same_host_only=not args.offsite,
        seed_from_archive=args.archive_org_check,
        request_headers=headers,
        discover_sitemaps=not args.skip_sitemaps,
    )


async def _main() -> int:
    parser = argparse.ArgumentParser(
        prog="crawler-cli",
        description="Async SEO crawler with PostgreSQL persistence",
    )
    parser.add_argument("url", help="Seed URL to crawl")
    parser.add_argument("--max-workers", type=int, default=15, help="Max concurrent workers")
    parser.add_argument("--concurrency", type=int, default=10, help="Max concurrent requests")
    parser.add_argument("--max-pages", type=int, default=200, help="Max URLs to crawl")
    parser.add_argument("--js", action="store_true", help="Use Playwright (JS-enabled) backend")
    parser.add_argument("--http-backend", choices=["aiohttp", "curl_cffi"], help="HTTP backend")
    parser.add_argument("--custom-ua", "--user-agent", dest="custom_ua", help="Custom User-Agent")
    parser.add_argument("--ignore-robots", action="store_true", help="Ignore robots.txt")
    parser.add_argument("--offsite", action="store_true", help="Follow off-site links")
    parser.add_argument("--path-restriction", help="Restrict crawl to paths containing this string")
    parser.add_argument("--path-exclude", help="Exclude paths containing this string")
    parser.add_argument("--archive-org-check", action="store_true", help="Seed from archive.org + run audit")
    parser.add_argument("--skip-sitemaps", action="store_true", help="Skip sitemap discovery")
    parser.add_argument("--output-dir", type=Path, help="Directory for CSV/JSON output")
    parser.add_argument("--save-to", help="Path to save crawl JSON results")

    # Postgres connection flags
    pg = parser.add_argument_group("PostgreSQL connection")
    pg.add_argument("--postgres-dsn", help="Full PostgreSQL DSN string")
    pg.add_argument("--postgres-host", help="PostgreSQL host")
    pg.add_argument("--postgres-port", help="PostgreSQL port")
    pg.add_argument("--postgres-user", help="PostgreSQL user")
    pg.add_argument("--postgres-password", help="PostgreSQL password")
    pg.add_argument("--postgres-db", help="PostgreSQL database name")

    args = parser.parse_args()

    dsn = _build_dsn(args)
    config = _build_config(args)
    config.max_concurrency = args.max_workers or args.concurrency
    config.default_open_crawl_limit = args.max_pages
    config.max_pages = args.max_pages

    store = AsyncpgStore(dsn)
    await store.initialize()

    engine = CrawlEngine(config, store=store)

    try:
        job = await engine.crawl_open([args.url], save_to=args.save_to)
        print(f"Crawl complete: {job.crawled_count} crawled, {job.blocked_count} blocked by robots")

        if args.archive_org_check:
            domain = args.url.split("://", 1)[-1].split("/")[0]
            audit = await audit_archive_urls(
                domain,
                store,
                config,
                output_dir=args.output_dir,
            )
            print(f"Archive audit: {audit.archive_url_count} historical URLs")
            print(f"  Missing: {len(audit.missing_urls)}")
            print(f"  Legacy issues: {len(audit.legacy_issues)}")
            if args.output_dir:
                print(f"  CSVs written to {args.output_dir}")
    finally:
        await store.close()

    return 0


def main() -> None:
    try:
        sys.exit(asyncio.run(_main()))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
