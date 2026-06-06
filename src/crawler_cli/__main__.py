from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .archive import audit_archive_urls
from .auth import AuthConfig
from .comparison import compare_deep, comparison_rows
from .config import CrawlConfig
from .csv_urls import load_urls_from_csv
from .embeddings import generate_embeddings_for_store
from .engine import CrawlEngine
from .persistence import AsyncpgStore, database_name_from_dsn
from .reports import CrawlReports


def _env_or_default(prefix: str, key: str, default: str | None = None) -> str | None:
    for p in (prefix, "CRAWLER_CLI", "PostgreSQLCrawler"):
        val = os.environ.get(f"{p}_{key}")
        if val:
            return val
    return default


def _build_dsn(args: argparse.Namespace) -> str:
    if getattr(args, "postgres_dsn", None):
        return args.postgres_dsn
    host = args.postgres_host or _env_or_default("CRAWLER_CLI", "POSTGRES_HOST", "localhost")
    port = args.postgres_port or _env_or_default("CRAWLER_CLI", "POSTGRES_PORT", "5432")
    user = args.postgres_user or _env_or_default("CRAWLER_CLI", "POSTGRES_USER", "crawler")
    password = args.postgres_password or _env_or_default("CRAWLER_CLI", "POSTGRES_PASSWORD", "")
    dbname = args.postgres_db or _env_or_default("CRAWLER_CLI", "POSTGRES_DB", "crawler")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def _build_auth(args: argparse.Namespace) -> AuthConfig | None:
    auth_type = getattr(args, "auth_type", "") or ""
    username = getattr(args, "auth_username", "") or ""
    token = getattr(args, "auth_token", "") or ""
    password = getattr(args, "auth_password", "") or token
    if not auth_type and not username and not token:
        return None
    if not auth_type:
        auth_type = "basic" if username else "bearer"
    return AuthConfig(
        auth_type=auth_type,  # type: ignore[arg-type]
        username=username,
        password=password,
        token=token,
    )


def _collect_seed_urls(args: argparse.Namespace) -> list[str]:
    seeds: list[str] = []
    primary = getattr(args, "url", None)
    if primary:
        seeds.append(primary)
    extra = getattr(args, "seed_urls", None) or []
    seeds.extend(extra)
    return list(dict.fromkeys(seeds))


def _store_from_args(args: argparse.Namespace) -> AsyncpgStore:
    compress_html = not getattr(args, "no_html_compression", False)
    store_html = not getattr(args, "no_store_html", False)
    return AsyncpgStore(
        _build_dsn(args),
        compress_html=compress_html,
        store_html=store_html,
    )


def _add_confirm_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--confirm",
        metavar="DATABASE",
        help="Must match the database name in --postgres-dsn before mutating data",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without writing",
    )


def _require_confirm(args: argparse.Namespace, dsn: str) -> int | None:
    db_name = database_name_from_dsn(dsn)
    if args.dry_run:
        return None
    if getattr(args, "confirm", None) != db_name:
        print(
            f"Refusing to modify database {db_name!r} without "
            f"--confirm {db_name}",
            file=sys.stderr,
        )
        return 2
    return None


def _validate_obscura_args(args: argparse.Namespace) -> None:
    """Validate Obscura-related CLI arguments and raise SystemExit on errors."""
    has_obscura = getattr(args, "obscura", False)
    has_obscura_port = hasattr(args, "obscura_port")
    has_obscura_host = hasattr(args, "obscura_host")
    has_obscura_binary = hasattr(args, "obscura_binary")
    has_obscura_proxy = hasattr(args, "obscura_proxy")
    has_obscura_workers = hasattr(args, "obscura_workers")
    has_obscura_stealth = getattr(args, "obscura_stealth", False)
    has_no_obscura_stealth = getattr(args, "no_obscura_stealth", False)
    has_obscura_unmanaged = getattr(args, "obscura_unmanaged", False)

    any_obscura_flag = (
        has_obscura_port
        or has_obscura_host
        or has_obscura_binary
        or has_obscura_proxy
        or has_obscura_workers
        or has_obscura_stealth
        or has_no_obscura_stealth
        or has_obscura_unmanaged
    )

    if not has_obscura and any_obscura_flag:
        print("Error: --obscura-* flags require --obscura", file=sys.stderr)
        sys.exit(2)

    if has_obscura_stealth and has_no_obscura_stealth:
        print("Error: --obscura-stealth and --no-obscura-stealth are mutually exclusive", file=sys.stderr)
        sys.exit(2)

    if has_obscura and getattr(args, "playwright_cdp_endpoint", None):
        print("Error: --playwright-cdp-endpoint and --obscura are mutually exclusive", file=sys.stderr)
        sys.exit(2)


def _resolve_obscura_stealth(args: argparse.Namespace) -> bool | None:
    """Resolve explicit stealth flags into tri-state."""
    if getattr(args, "obscura_stealth", False):
        return True
    if getattr(args, "no_obscura_stealth", False):
        return False
    return None


def _build_config(args: argparse.Namespace) -> CrawlConfig:
    _validate_obscura_args(args)
    backend: str = "playwright" if args.js else (args.http_backend or "aiohttp")
    headers: dict[str, str] = {}
    if args.custom_ua:
        headers["User-Agent"] = args.custom_ua

    allowed_hosts = [h.strip() for h in args.allowed_hosts.split(",") if h.strip()] if args.allowed_hosts else []
    path_exclude = (
        [p.strip() for p in args.path_exclude.split(",") if p.strip()]
        if getattr(args, "path_exclude", None)
        else []
    )
    csv_urls: list[str] = []
    if getattr(args, "csv_file", None):
        csv_urls = load_urls_from_csv(args.csv_file, column=args.csv_column)

    obscura_enabled = getattr(args, "obscura", False)
    obscura_stealth = _resolve_obscura_stealth(args)

    if obscura_enabled:
        backend = "playwright"
        args.js = True
        analytics = getattr(args, "analytics_detection", False)
        if analytics and obscura_stealth is None:
            print(
                "Error: --obscura --analytics-detection requires an explicit stealth choice "
                "(--obscura-stealth or --no-obscura-stealth)",
                file=sys.stderr,
            )
            sys.exit(2)

    return CrawlConfig(
        backend=backend,  # type: ignore[arg-type]
        user_agent=args.custom_ua or "crawler_cli/0.1",
        max_concurrency=args.concurrency,
        max_requests_per_context=args.max_requests_per_context,
        max_pages=args.max_pages,
        timeout_seconds=args.timeout,
        playwright_network_idle_timeout_seconds=args.playwright_network_idle_timeout,
        playwright_cdp_endpoint=getattr(args, "playwright_cdp_endpoint", "") or "",
        memory_high_watermark_percent=args.memory_high_watermark,
        memory_recovery_watermark_percent=args.memory_recovery_watermark,
        respect_robots_txt=not args.ignore_robots,
        same_host_only=not args.offsite,
        seed_from_archive=args.archive_org_check,
        request_headers=headers,
        discover_sitemaps=not args.skip_sitemaps,
        allowed_hosts=allowed_hosts,
        path_restriction=getattr(args, "path_restriction", "") or "",
        path_exclude=path_exclude,
        auth=_build_auth(args),
        csv_urls=csv_urls,
        csv_seed_mode=bool(getattr(args, "csv_seed", False)),
        cms_detection=getattr(args, "cms_detection", False),
        analytics_detection=getattr(args, "analytics_detection", False),
        analytics_expected_ids=getattr(args, "analytics_expected_id", []) or [],
        enable_content_hashing=getattr(args, "content_hashing", False),
        compress_html=not getattr(args, "no_html_compression", False),
        store_html=not getattr(args, "no_store_html", False),
        obscura_enabled=obscura_enabled,
        obscura_binary=getattr(args, "obscura_binary", "obscura"),
        obscura_host=getattr(args, "obscura_host", "127.0.0.1"),
        obscura_port=getattr(args, "obscura_port", 9222),
        obscura_proxy=getattr(args, "obscura_proxy", ""),
        obscura_workers=getattr(args, "obscura_workers", 1),
        obscura_managed=not getattr(args, "obscura_unmanaged", False),
        obscura_stealth=obscura_stealth,
    )


def _add_postgres_args(parser: argparse.ArgumentParser) -> None:
    pg = parser.add_argument_group("PostgreSQL connection")
    pg.add_argument("--postgres-dsn", help="Full PostgreSQL DSN string")
    pg.add_argument("--postgres-host", help="PostgreSQL host")
    pg.add_argument("--postgres-port", help="PostgreSQL port")
    pg.add_argument("--postgres-user", help="PostgreSQL user")
    pg.add_argument("--postgres-password", help="PostgreSQL password")
    pg.add_argument("--postgres-db", help="PostgreSQL database name")


def _add_crawl_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("url", nargs="?", help="Seed URL to crawl")
    parser.add_argument(
        "--seed-url",
        dest="seed_urls",
        action="append",
        default=[],
        help="Additional seed URL. Repeat to crawl multiple hosts in one run.",
    )
    parser.add_argument("--max-workers", type=int, default=15, help="Max concurrent workers")
    parser.add_argument("--concurrency", type=int, default=10, help="Max concurrent requests")
    parser.add_argument("--max-pages", type=int, default=0, help="Max URLs to crawl (0 = unlimited)")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout in seconds")
    parser.add_argument("--js", action="store_true", help="Use Playwright (JS-enabled) backend")
    parser.add_argument(
        "--max-requests-per-context",
        type=int,
        default=50,
        help="Recycle Playwright browser contexts after this many page loads (0 disables recycling)",
    )
    parser.add_argument(
        "--playwright-network-idle-timeout",
        type=float,
        default=5.0,
        help="Additional Playwright network-idle settle timeout in seconds",
    )
    parser.add_argument(
        "--playwright-cdp-endpoint",
        help="Connect Playwright to an existing CDP browser such as Obscura",
    )
    parser.add_argument(
        "--memory-high-watermark",
        type=float,
        default=85.0,
        help="Reduce worker concurrency when system memory usage reaches this percent",
    )
    parser.add_argument(
        "--memory-recovery-watermark",
        type=float,
        default=70.0,
        help="Restore worker concurrency once system memory usage drops to this percent",
    )
    parser.add_argument("--http-backend", choices=["aiohttp", "curl_cffi"], help="HTTP backend")
    parser.add_argument("--custom-ua", "--user-agent", dest="custom_ua", help="Custom User-Agent")
    parser.add_argument("--ignore-robots", action="store_true", help="Ignore robots.txt")
    parser.add_argument("--offsite", action="store_true", help="Follow off-site links")
    parser.add_argument("--allowed-hosts", default="", help="Comma-separated additional hosts")
    parser.add_argument("--path-restriction", help="Restrict crawl to paths containing this string")
    parser.add_argument(
        "--path-exclude",
        help="Comma-separated path prefixes to exclude (e.g. /news/,/admin/)",
    )
    parser.add_argument("--archive-org-check", action="store_true", help="Seed from archive.org + run audit")
    parser.add_argument("--skip-sitemaps", action="store_true", help="Skip sitemap discovery")
    parser.add_argument("--cms-detection", action="store_true", help="Enable CMS platform detection")
    parser.add_argument("--analytics-detection", action="store_true", help="Enable analytics / tag manager / pixel detection")
    parser.add_argument(
        "--analytics-expected-id",
        action="append",
        default=[],
        help="Expected analytics identifier (e.g. GTM-ABC123, G-XYZ). Repeatable.",
    )
    obscura = parser.add_argument_group("Obscura browser backend")
    obscura.add_argument("--obscura", action="store_true", help="Use Obscura as the JS backend (implies --js)")
    obscura.add_argument("--obscura-binary", default=argparse.SUPPRESS, help="Path to the obscura binary")
    obscura.add_argument("--obscura-host", default=argparse.SUPPRESS, help="Obscura host")
    obscura.add_argument("--obscura-port", type=int, default=argparse.SUPPRESS, help="Obscura port")
    obscura.add_argument("--obscura-proxy", default=argparse.SUPPRESS, help="Proxy URL for Obscura")
    obscura.add_argument("--obscura-workers", type=int, default=argparse.SUPPRESS, help="Obscura worker count")
    obscura.add_argument(
        "--obscura-stealth",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Explicitly enable Obscura stealth",
    )
    obscura.add_argument(
        "--no-obscura-stealth",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Explicitly disable Obscura stealth",
    )
    obscura.add_argument(
        "--obscura-unmanaged",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Connect to an already-running Obscura instance; do not spawn/kill it",
    )
    parser.add_argument("--output-dir", type=Path, help="Directory for CSV/JSON output")
    parser.add_argument("--save-to", help="Path to save crawl JSON results")
    parser.add_argument("--csv-file", help="CSV file containing URLs to crawl")
    parser.add_argument("--csv-column", default="url", help="CSV column containing URLs")
    parser.add_argument(
        "--csv-seed",
        action="store_true",
        help="Treat CSV URLs as seeds for an open crawl (follow links/sitemaps)",
    )
    parser.add_argument(
        "--content-hashing",
        action="store_true",
        help="Store SHA256 + SimHash fingerprints of normalized page text in content table",
    )
    parser.add_argument(
        "--no-html-compression",
        action="store_true",
        help="Store page HTML as raw UTF-8 bytes instead of gzip",
    )
    parser.add_argument(
        "--no-store-html",
        action="store_true",
        help="Skip persisting raw HTML (structured extraction + hashes still stored)",
    )
    auth = parser.add_argument_group("HTTP authentication")
    auth.add_argument("--auth-type", choices=["basic", "digest", "bearer"], help="Authentication type")
    auth.add_argument("--auth-username", help="Username for basic/digest auth")
    auth.add_argument("--auth-password", help="Password for basic/digest auth")
    auth.add_argument("--auth-token", help="Bearer token or password fallback")
    _add_postgres_args(parser)


async def _run_crawl(args: argparse.Namespace) -> int:
    seeds = _collect_seed_urls(args)
    if not seeds and not args.csv_file:
        print("Error: provide a seed URL, one or more --seed-url values, or --csv-file", file=sys.stderr)
        return 2
    if args.csv_file and not seeds and not args.csv_seed:
        args.url = load_urls_from_csv(args.csv_file, column=args.csv_column)[0]
        seeds = _collect_seed_urls(args)

    dsn = _build_dsn(args)
    config = _build_config(args)
    config.max_concurrency = args.max_workers or args.concurrency
    config.default_open_crawl_limit = args.max_pages
    config.max_pages = args.max_pages

    store = _store_from_args(args)
    await store.initialize()
    engine = CrawlEngine(config, store=store)

    try:
        if config.csv_urls and not config.csv_seed_mode:
            job = await engine.crawl_list(config.csv_urls, save_to=args.save_to)
        else:
            job = await engine.crawl_open(seeds, save_to=args.save_to)
        print(f"Crawl complete: {job.crawled_count} crawled, {job.blocked_count} blocked by robots")

        if args.archive_org_check and seeds:
            seen_domains: set[str] = set()
            for seed in seeds:
                domain = seed.split("://", 1)[-1].split("/")[0].lower()
                if not domain or domain in seen_domains:
                    continue
                seen_domains.add(domain)
                audit = await audit_archive_urls(domain, store, config, output_dir=args.output_dir)
                print(f"Archive audit [{domain}]: {audit.archive_url_count} historical URLs")
                print(f"  Missing: {len(audit.missing_urls)}")
                print(f"  Legacy issues: {len(audit.legacy_issues)}")
                if args.output_dir:
                    print(f"  CSVs written to {args.output_dir}")
    finally:
        await engine.close()
        await store.close()
    return 0


async def _run_embeddings(args: argparse.Namespace) -> int:
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: set --api-key or OPENAI_API_KEY", file=sys.stderr)
        return 2

    store = _store_from_args(args)
    await store.initialize()

    try:
        urls = None
        if args.urls:
            urls = args.urls
        result = await generate_embeddings_for_store(
            store,
            api_key=api_key,
            model=args.model,
            batch_size=args.batch_size,
            delay_seconds=args.delay,
            skip_existing=not args.force,
            urls=urls,
        )
        print(
            f"Embeddings complete: processed={result.processed} "
            f"skipped={result.skipped} failed={result.failed}"
        )
        if result.errors:
            print("Errors:")
            for error in result.errors[:10]:
                print(f"  - {error}")
    finally:
        await store.close()
    return 0


async def _run_compare(args: argparse.Namespace) -> int:
    baseline_path = Path(args.baseline_json)
    candidate_path = Path(args.candidate_json)
    baseline_job = json.loads(baseline_path.read_text(encoding="utf-8"))
    candidate_job = json.loads(candidate_path.read_text(encoding="utf-8"))

    from .models import CrawlJobResult, CrawlResult

    def _load_results(payload: dict) -> list[CrawlResult]:
        results = []
        for item in payload.get("results", []):
            browser_runtime = None
            br = item.get("browser_runtime")
            if br:
                from .models import BrowserRuntime

                browser_runtime = BrowserRuntime(
                    provider=br.get("provider", "chromium"),
                    cdp_endpoint=br.get("cdp_endpoint"),
                    managed=br.get("managed"),
                    stealth=br.get("stealth"),
                )
            results.append(
                CrawlResult(
                    requested_url=item["requested_url"],
                    final_url=item["final_url"],
                    status=item["status"],
                    headers=item.get("headers", {}),
                    content_type=item.get("content_type"),
                    fetch_backend=item.get("fetch_backend", "aiohttp"),
                    extracted=None,
                    raw_html=item.get("raw_html"),
                    content_hash_sha256=item.get("content_hash_sha256"),
                    content_hash_simhash=item.get("content_hash_simhash"),
                    discovered_links=[],
                    detected_cms=None,
                    detected_analytics=None,
                    browser_runtime=browser_runtime,
                )
            )
        return results

    diff = compare_deep(
        CrawlJobResult(mode="list", seed_urls=[], results=_load_results(baseline_job)),
        CrawlJobResult(mode="list", seed_urls=[], results=_load_results(candidate_job)),
        compare_links=args.compare_links,
    )

    if args.output:
        Path(args.output).write_text(json.dumps(comparison_rows(diff), indent=2), encoding="utf-8")
        print(f"Wrote comparison rows to {args.output}")

    if args.persist:
        store = _store_from_args(args)
        await store.initialize()
        try:
            session_id = await store.persist_comparison_session(
                baseline_label=args.baseline_label,
                candidate_label=args.candidate_label,
                rows=comparison_rows(diff),
            )
            await store.initialize_comparison_views()
            reports = CrawlReports(store)
            summary = await reports.comparison_summary(session_id)
            print(json.dumps(summary, indent=2))
        finally:
            await store.close()
    else:
        print(
            json.dumps(
                {
                    "missing_urls": diff.missing_urls,
                    "new_urls": diff.new_urls,
                    "title_changes": len(diff.title_changes),
                    "url_moves": len(diff.url_moves),
                    "schema_changes": len(diff.schema_changes),
                    "link_changes": len(diff.link_changes),
                },
                indent=2,
            )
        )
    return 0


async def _run_compact_html(args: argparse.Namespace) -> int:
    dsn = _build_dsn(args)
    store = _store_from_args(args)
    await store.initialize()
    try:
        stats = await store.html_storage_stats()
        print(f"Pages with HTML: {stats['pages_with_html']}")
        print(f"Legacy uncompressed rows: {stats['pages_legacy_uncompressed']}")
        if (code := _require_confirm(args, dsn)) is not None:
            return code
        result = await store.compact_html_storage(
            batch_size=args.batch_size,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2))
    finally:
        await store.close()
    return 0


async def _run_delete_crawl(args: argparse.Namespace) -> int:
    dsn = _build_dsn(args)
    store = _store_from_args(args)
    await store.initialize()
    db_name = database_name_from_dsn(dsn)
    try:
        counts = await store.table_row_counts()
        queued, pending, done = await store.frontier_stats()
        print(f"Database: {db_name}")
        print(f"Mode: {args.mode}")
        for table in ("pages", "urls", "frontier", "content", "page_analytics_hits"):
            if table in counts:
                print(f"  {table}: {counts[table]:,}")
        print(f"  frontier: {done:,} done, {pending:,} pending, {queued:,} queued")
        if args.dry_run:
            print("Dry run — no changes made.")
            return 0
        if getattr(args, "confirm", None) != db_name:
            print(f"Re-run with --confirm {db_name} to proceed.", file=sys.stderr)
            return 2
        if args.mode == "drop-database":
            await store.drop_crawl_database(
                maintenance_dsn=args.maintenance_dsn or None,
            )
            print(f"Dropped database {db_name}")
        else:
            await store.truncate_crawl_tables()
            print(f"Truncated crawler_cli tables in {db_name}")
    finally:
        if store.pool is not None:
            await store.close()
    return 0


async def _run_compact_crawl(args: argparse.Namespace) -> int:
    dsn = _build_dsn(args)
    store = _store_from_args(args)
    await store.initialize()
    try:
        stats = await store.html_storage_stats()
        print(json.dumps(stats, indent=2))
        missing = stats["pages_with_html_missing_hash"]
        if args.require_hashes and missing > 0 and not args.backfill_hashes:
            print(
                f"Refusing: {missing} pages have HTML but no content_hash_sha256. "
                "Re-crawl with --content-hashing or pass --backfill-hashes.",
                file=sys.stderr,
            )
            return 2
        if (code := _require_confirm(args, dsn)) is not None:
            return code
        if args.backfill_hashes:
            backfill = await store.backfill_content_hashes(
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
            print(f"Hash backfill: {json.dumps(backfill)}")
            stats = await store.html_storage_stats()
            missing = stats["pages_with_html_missing_hash"]
            if args.require_hashes and missing > 0:
                print(f"Still missing hashes on {missing} pages.", file=sys.stderr)
                return 2
        result = await store.purge_stored_html(
            drop_headers=args.drop_headers,
            vacuum=args.vacuum,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2))
        if args.dry_run:
            print("Dry run — HTML not purged.")
    finally:
        await store.close()
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crawler-cli",
        description="Async SEO crawler with PostgreSQL persistence",
    )
    subparsers = parser.add_subparsers(dest="command")

    crawl_parser = subparsers.add_parser("crawl", help="Run a crawl")
    _add_crawl_args(crawl_parser)

    emb_parser = subparsers.add_parser("generate-embeddings", help="Generate OpenAI embeddings for crawled pages")
    emb_parser.add_argument("--api-key", help="OpenAI API key (or set OPENAI_API_KEY)")
    emb_parser.add_argument("--model", default="text-embedding-3-small", help="Embedding model")
    emb_parser.add_argument("--batch-size", type=int, default=10, help="Pages per API batch")
    emb_parser.add_argument("--delay", type=float, default=1.0, help="Delay between batches (seconds)")
    emb_parser.add_argument("--force", action="store_true", help="Regenerate existing embeddings")
    emb_parser.add_argument("--urls", nargs="*", help="Optional URL filter list")
    _add_postgres_args(emb_parser)

    cmp_parser = subparsers.add_parser("compare", help="Compare two saved crawl JSON files")
    cmp_parser.add_argument("baseline_json", help="Baseline crawl JSON path")
    cmp_parser.add_argument("candidate_json", help="Candidate crawl JSON path")
    cmp_parser.add_argument("--baseline-label", default="baseline")
    cmp_parser.add_argument("--candidate-label", default="candidate")
    cmp_parser.add_argument("--compare-links", action="store_true")
    cmp_parser.add_argument("--output", help="Write comparison rows JSON to this path")
    cmp_parser.add_argument("--persist", action="store_true", help="Persist comparison to PostgreSQL")
    _add_postgres_args(cmp_parser)

    compact_html_parser = subparsers.add_parser(
        "compact-html",
        help="Gzip-compress legacy uncompressed HTML in pages.html_compressed",
    )
    compact_html_parser.add_argument("--batch-size", type=int, default=500)
    _add_confirm_args(compact_html_parser)
    _add_postgres_args(compact_html_parser)

    delete_parser = subparsers.add_parser(
        "delete-crawl",
        help="Truncate all crawler_cli tables or drop the crawl database",
    )
    delete_parser.add_argument(
        "--mode",
        choices=("truncate", "drop-database"),
        default="truncate",
        help="truncate: empty tables in place; drop-database: DROP DATABASE",
    )
    delete_parser.add_argument(
        "--maintenance-dsn",
        help="DSN for postgres DB used when --mode drop-database (default: same host, db postgres)",
    )
    _add_confirm_args(delete_parser)
    _add_postgres_args(delete_parser)

    compact_parser = subparsers.add_parser(
        "compact-crawl",
        help="Drop stored HTML while keeping audit metadata and content hashes",
    )
    compact_parser.add_argument("--batch-size", type=int, default=500)
    compact_parser.add_argument(
        "--require-hashes",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Refuse to purge HTML unless content_hash_sha256 exists (default: on)",
    )
    compact_parser.add_argument(
        "--backfill-hashes",
        action="store_true",
        help="Compute missing hashes from stored HTML before purging",
    )
    compact_parser.add_argument(
        "--drop-headers",
        action="store_true",
        help="Also clear pages.headers_json",
    )
    compact_parser.add_argument(
        "--vacuum",
        action="store_true",
        help="Run VACUUM ANALYZE pages after purge (can be slow)",
    )
    _add_confirm_args(compact_parser)
    _add_postgres_args(compact_parser)

    return parser


def _normalize_argv(argv: list[str]) -> list[str]:
    if not argv:
        return ["crawl"]
    if argv[0] in {
        "crawl",
        "generate-embeddings",
        "compare",
        "compact-html",
        "delete-crawl",
        "compact-crawl",
    }:
        return argv
    if "://" in argv[0]:
        return ["crawl", *argv]
    return argv


async def _dispatch(args: argparse.Namespace) -> int:
    command = args.command or "crawl"
    if command == "crawl":
        return await _run_crawl(args)
    if command == "generate-embeddings":
        return await _run_embeddings(args)
    if command == "compare":
        return await _run_compare(args)
    if command == "compact-html":
        return await _run_compact_html(args)
    if command == "delete-crawl":
        return await _run_delete_crawl(args)
    if command == "compact-crawl":
        return await _run_compact_crawl(args)
    print(f"Unknown command: {command}", file=sys.stderr)
    return 2


def main() -> None:
    argv = _normalize_argv(sys.argv[1:])
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command in {None, "crawl"} and not getattr(args, "command", None):
        args.command = "crawl"
    try:
        sys.exit(asyncio.run(_dispatch(args)))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
