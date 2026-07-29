from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Required, TypedDict, cast
from urllib.parse import quote as _urlquote

if TYPE_CHECKING:
    from .models import CrawlJobResult, CrawlResult

from .archive import audit_archive_urls
from .auth import AuthConfig, AuthType
from .compare_urls import build_pair_rows, load_url_pairs, rows_failing
from .comparison import DEFAULT_SIMHASH_THRESHOLD, compare_deep, comparison_rows
from .config import (
    CB_ENABLED_DEFAULT,
    CB_RECOVERY_SECONDS_DEFAULT,
    CB_THRESHOLD_DEFAULT,
    DEFAULT_OPEN_CRAWL_LIMIT,
    MAX_RESPONSE_BYTES_DEFAULT,
    BackendName,
    CrawlConfig,
    _env_bool,
    _env_float,
    _env_int,
)
from .cookies import (
    load_cookies_file,
    load_scoped_cookies_file,
    parse_cookie_pairs,
    scoped_cookies_from_pairs,
)
from .csv_urls import load_urls_from_csv
from .embeddings import generate_embeddings_for_store
from .engine import CrawlEngine, CrawlRunSelectionError
from .exit_codes import EXIT_FINDINGS, EXIT_VALIDATION, resolve_crawl_exit_code
from .intent_signature import DEFAULT_THIN_SIGNATURE_WORDS
from .persistence import AsyncpgStore, MemoryStore, database_name_from_dsn
from .remap import Remap
from .reports import CrawlReports
from .validators import (
    non_negative_float,
    non_negative_int,
    percentage,
    positive_float,
    positive_int,
    probability,
    require_non_negative_int,
    require_positive_float,
    require_positive_int,
    require_probability,
)

logger = logging.getLogger(__name__)

COMPARE_SCHEMA_VERSION = "crawler-cli/compare/1"
"""Schema identifier for ``compare --output`` JSON and its stdout summary (ticket 3344)."""

COMPARE_URLS_SCHEMA_VERSION = "crawler-cli/compare-urls/1"
"""Schema identifier for ``compare-urls --output`` JSON/CSV and its stdout summary (ticket 3344)."""


def _env_or_default(prefix: str, key: str, default: str | None = None) -> str | None:
    for p in (prefix, "CRAWLER_CLI", "PostgreSQLCrawler"):
        val = os.environ.get(f"{p}_{key}")
        if val:
            return val
    return default


def _build_dsn(args: argparse.Namespace) -> str:
    if getattr(args, "postgres_dsn", None):
        return args.postgres_dsn
    for prefix in ("CRAWLER_CLI", "PostgreSQLCrawler"):
        dsn = os.environ.get(f"{prefix}_POSTGRES_DSN")
        if dsn:
            return dsn
    host = args.postgres_host or _env_or_default("CRAWLER_CLI", "POSTGRES_HOST", "localhost")
    port = args.postgres_port or _env_or_default("CRAWLER_CLI", "POSTGRES_PORT", "5432")
    user = args.postgres_user or _env_or_default("CRAWLER_CLI", "POSTGRES_USER", "crawler")
    password = args.postgres_password or _env_or_default("CRAWLER_CLI", "POSTGRES_PASSWORD", "")
    dbname = args.postgres_db or _env_or_default("CRAWLER_CLI", "POSTGRES_DB", "crawler")
    # Percent-encode credentials so special chars (@, :, /, #) don't break the DSN.
    safe_user = _urlquote(user, safe="")
    safe_password = _urlquote(password, safe="")
    return f"postgresql://{safe_user}:{safe_password}@{host}:{port}/{dbname}"


_STORE_ENV_PREFIXES = ("CRAWLER_CLI", "PostgreSQLCrawler")


def store_dsn_env_vars(side: str) -> tuple[str, ...]:
    """Well-known env vars holding the store DSN for one compare side (ticket 122).

    Mirrors the prefixes :func:`_build_dsn` already accepts, e.g.
    ``CRAWLER_CLI_BASELINE_POSTGRES_DSN`` / ``PostgreSQLCrawler_BASELINE_POSTGRES_DSN``.
    """
    return tuple(f"{prefix}_{side.upper()}_POSTGRES_DSN" for prefix in _STORE_ENV_PREFIXES)


def _resolve_store_dsn(args: argparse.Namespace, side: str) -> str | None:
    """Resolve the PostgreSQL DSN for one compare side (ticket 122).

    Precedence: ``--<side>-store DSN`` > ``--<side>-store-env VAR`` > the
    well-known :func:`store_dsn_env_vars` variables. Sourcing the DSN from the
    environment keeps credentials out of shell history and the process list;
    the inline flag stays available as an override for local one-offs.

    Returns ``None`` when no DSN is configured for this side (the side then
    falls back to a JSON artifact).
    """
    inline = getattr(args, f"{side}_store", None)
    if inline:
        return str(inline)
    env_var = getattr(args, f"{side}_store_env", None)
    if env_var:
        value = os.environ.get(env_var)
        if not value:
            raise ValueError(f"Environment variable {env_var!r} for --{side}-store-env is not set or is empty")
        return value
    for name in store_dsn_env_vars(side):
        value = os.environ.get(name)
        if value:
            return value
    return None


def _resolve_secret_sources(*, value: str, env_var: str, file_path: str, label: str) -> str:
    sources = [bool(value), bool(env_var), bool(file_path)]
    if sum(sources) > 1:
        raise ValueError(f"Provide only one of --{label}, --{label}-env, or --{label}-file")
    if env_var:
        secret = os.environ.get(env_var)
        if not secret:
            raise ValueError(f"Environment variable {env_var!r} for --{label}-env is not set or is empty")
        return secret
    if file_path:
        path = Path(file_path)
        try:
            return path.read_text(encoding="utf-8").rstrip("\r\n")
        except OSError as exc:
            raise ValueError(f"Unable to read --{label}-file {file_path!r}: {exc}") from exc
    return value


def _password_source_flag(args: argparse.Namespace) -> str | None:
    """Return the CLI flag name for the supplied auth-password source, if any."""
    if getattr(args, "auth_password", "") or "":
        return "--auth-password"
    if getattr(args, "auth_password_env", "") or "":
        return "--auth-password-env"
    if getattr(args, "auth_password_file", "") or "":
        return "--auth-password-file"
    return None


def _build_auth(args: argparse.Namespace) -> AuthConfig | None:
    auth_type = getattr(args, "auth_type", "") or ""
    username = getattr(args, "auth_username", "") or ""
    # Bearer tokens accept the same secret sources as basic-auth passwords so
    # automation can keep tokens out of process argv (ticket 3344).
    token = _resolve_secret_sources(
        value=getattr(args, "auth_token", "") or "",
        env_var=getattr(args, "auth_token_env", "") or "",
        file_path=getattr(args, "auth_token_file", "") or "",
        label="auth-token",
    )
    password_flag = _password_source_flag(args)
    password = _resolve_secret_sources(
        value=getattr(args, "auth_password", "") or "",
        env_var=getattr(args, "auth_password_env", "") or "",
        file_path=getattr(args, "auth_password_file", "") or "",
        label="auth-password",
    )
    if not password:
        password = token
    if not auth_type and not username and not token:
        if password_flag is not None:
            raise ValueError(f"{password_flag} requires --auth-username or --auth-type basic")
        return None
    if not auth_type:
        auth_type = "basic" if username else "bearer"
    return AuthConfig(
        # argparse --auth-type choices constrain this to the AuthType literal set.
        auth_type=cast("AuthType", auth_type),
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


def _postgres_config_supplied(args: argparse.Namespace) -> bool:
    if getattr(args, "postgres_dsn", None):
        return True
    arg_names = (
        "postgres_host",
        "postgres_port",
        "postgres_user",
        "postgres_password",
        "postgres_db",
    )
    if any(getattr(args, name, None) for name in arg_names):
        return True
    for prefix in ("CRAWLER_CLI", "PostgreSQLCrawler"):
        if os.environ.get(f"{prefix}_POSTGRES_DSN"):
            return True
        for key in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
            if f"{prefix}_{key}" in os.environ:
                return True
    return False


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
            f"Refusing to modify database {db_name!r} without --confirm {db_name}",
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

    if has_obscura and any(
        (
            getattr(args, "playwright_cdp_endpoint", None),
            getattr(args, "playwright_cdp_host", None),
            getattr(args, "playwright_cdp_port", None),
            getattr(args, "playwright_channel", None),
            getattr(args, "playwright_executable_path", None),
            getattr(args, "playwright_user_data_dir", None),
            getattr(args, "playwright_profile_directory", None),
        )
    ):
        print("Error: --obscura cannot be combined with Playwright CDP/profile launch flags", file=sys.stderr)
        sys.exit(2)


def _validate_playwright_args(args: argparse.Namespace) -> None:
    channel = getattr(args, "playwright_channel", None)
    executable_path = getattr(args, "playwright_executable_path", None)
    user_data_dir = getattr(args, "playwright_user_data_dir", None)
    profile_directory = getattr(args, "playwright_profile_directory", None)
    cdp_endpoint = getattr(args, "playwright_cdp_endpoint", None)
    cdp_host = getattr(args, "playwright_cdp_host", None)
    cdp_port = getattr(args, "playwright_cdp_port", None)

    if channel and executable_path:
        print(
            "Error: --playwright-channel and --playwright-executable-path are mutually exclusive",
            file=sys.stderr,
        )
        sys.exit(2)

    if profile_directory and not user_data_dir:
        print(
            "Error: --playwright-profile-directory requires --playwright-user-data-dir",
            file=sys.stderr,
        )
        sys.exit(2)

    if cdp_host and cdp_port is None:
        print(
            "Error: --playwright-cdp-host requires --playwright-cdp-port",
            file=sys.stderr,
        )
        sys.exit(2)

    if cdp_endpoint and any((cdp_host, cdp_port)):
        print(
            "Error: --playwright-cdp-endpoint cannot be combined with --playwright-cdp-host/--playwright-cdp-port",
            file=sys.stderr,
        )
        sys.exit(2)

    if (cdp_endpoint or cdp_port is not None) and any((channel, executable_path, user_data_dir, profile_directory)):
        print(
            "Error: --playwright-cdp-endpoint cannot be combined with local Playwright launch/profile flags",
            file=sys.stderr,
        )
        sys.exit(2)


def _resolve_playwright_cdp_endpoint(args: argparse.Namespace) -> str:
    endpoint = getattr(args, "playwright_cdp_endpoint", "") or ""
    if endpoint:
        return endpoint
    cdp_port = getattr(args, "playwright_cdp_port", None)
    if cdp_port is None:
        return ""
    cdp_host = getattr(args, "playwright_cdp_host", None) or "127.0.0.1"
    return f"http://{cdp_host}:{cdp_port}"


def _resolve_obscura_stealth(args: argparse.Namespace) -> bool | None:
    """Resolve explicit stealth flags into tri-state."""
    if getattr(args, "obscura_stealth", False):
        return True
    if getattr(args, "no_obscura_stealth", False):
        return False
    return None


def _resolve_circuit_breaker(args: argparse.Namespace) -> tuple[bool, int, float]:
    """Resolve circuit-breaker settings with CLI > env var > default precedence.

    CLI flags use ``default=None`` (numeric) / a dedicated ``--no-circuit-breaker``
    store_true so we can tell "not passed" from an explicit value.
    """
    # enabled: --no-circuit-breaker forces off; otherwise env then default.
    if getattr(args, "no_circuit_breaker", False):
        enabled = False
    else:
        env_enabled = _env_bool("CRAWLER_CLI_CB_ENABLED")
        enabled = env_enabled if env_enabled is not None else CB_ENABLED_DEFAULT

    cli_threshold = getattr(args, "circuit_breaker_threshold", None)
    if cli_threshold is not None:
        threshold = cli_threshold
    else:
        env_threshold = _env_int("CRAWLER_CLI_CB_THRESHOLD")
        threshold = env_threshold if env_threshold is not None else CB_THRESHOLD_DEFAULT
    threshold = require_positive_int(threshold, field="circuit breaker threshold")

    cli_recovery = getattr(args, "circuit_breaker_recovery_seconds", None)
    if cli_recovery is not None:
        recovery = cli_recovery
    else:
        env_recovery = _env_float("CRAWLER_CLI_CB_RECOVERY_SECONDS")
        recovery = env_recovery if env_recovery is not None else CB_RECOVERY_SECONDS_DEFAULT
    recovery = require_positive_float(recovery, field="circuit breaker recovery seconds")

    return enabled, threshold, recovery


def _resolve_concurrency(args: argparse.Namespace) -> int:
    """Resolve ``--max-workers`` / ``--concurrency`` aliases (ticket 093).

    Both flags are equivalent; disagreeing explicit values are rejected rather
    than silently preferring one.
    """
    max_workers = getattr(args, "max_workers", None)
    concurrency = getattr(args, "concurrency", None)
    if max_workers is not None and concurrency is not None and max_workers != concurrency:
        raise ValueError(
            f"--max-workers ({max_workers}) and --concurrency ({concurrency}) disagree; "
            "pass only one alias, or the same value for both"
        )
    if max_workers is not None:
        return max_workers
    if concurrency is not None:
        return concurrency
    return 15


def _validate_memory_watermarks(args: argparse.Namespace) -> None:
    high = getattr(args, "memory_high_watermark", None)
    recovery = getattr(args, "memory_recovery_watermark", None)
    if high is None or recovery is None:
        return
    if recovery >= high:
        raise ValueError(f"--memory-recovery-watermark ({recovery}) must be below --memory-high-watermark ({high})")


def _validate_intent_overlap_numeric_args(args: argparse.Namespace) -> None:
    """Reject invalid overlap/ANN numerics before store init or output mkdir."""
    threshold = require_probability(args.threshold, field="--threshold")
    dup_threshold = require_probability(args.dup_threshold, field="--dup-threshold")
    if dup_threshold < threshold:
        raise ValueError(f"--dup-threshold ({dup_threshold}) must be >= --threshold ({threshold})")
    require_positive_int(args.ann_min_pages, field="--ann-min-pages")
    require_positive_int(args.ann_k, field="--ann-k")
    require_non_negative_int(args.thin_signature_words, field="--thin-signature-words")


def _build_config(args: argparse.Namespace) -> CrawlConfig:
    _validate_obscura_args(args)
    _validate_playwright_args(args)
    _validate_memory_watermarks(args)
    playwright_cdp_endpoint = _resolve_playwright_cdp_endpoint(args)
    wants_playwright = bool(
        args.js
        or playwright_cdp_endpoint
        or getattr(args, "playwright_channel", None)
        or getattr(args, "playwright_executable_path", None)
        or getattr(args, "playwright_user_data_dir", None)
    )
    backend: str = "playwright" if wants_playwright else (args.http_backend or "aiohttp")
    headers: dict[str, str] = {}
    if args.custom_ua:
        headers["User-Agent"] = args.custom_ua

    allowed_hosts = [h.strip() for h in args.allowed_hosts.split(",") if h.strip()] if args.allowed_hosts else []
    path_exclude = (
        [p.strip() for p in args.path_exclude.split(",") if p.strip()] if getattr(args, "path_exclude", None) else []
    )
    csv_urls: list[str] = []
    if getattr(args, "csv_file", None):
        csv_urls = load_urls_from_csv(args.csv_file, column=args.csv_column)

    obscura_enabled = getattr(args, "obscura", False)
    obscura_stealth = _resolve_obscura_stealth(args)

    # Resolve the obscura binary: an explicit --obscura-binary wins, otherwise
    # auto-discover (install dir from `install-obscura`, OBSCURA_BINARY env,
    # PATH, sibling checkout). Falls back to the bare name so the spawn still
    # produces a clear "not found" error if nothing is installed.
    obscura_binary = getattr(args, "obscura_binary", None)
    if obscura_enabled:
        from .obscura_install import find_obscura_binary

        obscura_binary = find_obscura_binary(obscura_binary) or (obscura_binary or "obscura")
    else:
        obscura_binary = obscura_binary or "obscura"

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

    # Core Web Vitals need an in-page PerformanceObserver, so they're only
    # measurable on the Playwright backend (ticket 046). Warn rather than fail:
    # the columns simply stay null on HTTP backends.
    if getattr(args, "collect_web_vitals", False) and backend != "playwright":
        logger.warning(
            "--web-vitals requires the JS backend (--js or --obscura); "
            "Core Web Vitals will not be collected on the %s backend.",
            backend,
        )

    cb_enabled, cb_threshold, cb_recovery = _resolve_circuit_breaker(args)

    extraction_rules: list = []
    if getattr(args, "extraction_rules", None):
        from .custom_extract import load_extraction_rules

        extraction_rules = load_extraction_rules(args.extraction_rules)

    # Cookies: a cookies-file carries domain/path attributes, so it produces
    # scoped cookies that are matched per-request (ticket 048). CLI --cookie
    # pairs have no domain and are kept as all-host cookies so the original
    # single-host login-wall behaviour (ticket 028) is preserved. Passing
    # --no-cookie-scoping forces the legacy flat all-hosts map even for files.
    cookies: dict[str, str] = {}
    scoped_cookies: list = []
    use_scoping = not getattr(args, "no_cookie_scoping", False)
    if getattr(args, "cookies_file", None):
        if use_scoping:
            scoped_cookies.extend(load_scoped_cookies_file(args.cookies_file))
        else:
            cookies.update(load_cookies_file(args.cookies_file))
    if getattr(args, "cookies", None):
        if use_scoping:
            scoped_cookies.extend(scoped_cookies_from_pairs(args.cookies))
        else:
            # CLI --cookie pairs override file values on name collision.
            cookies.update(parse_cookie_pairs(args.cookies))

    # Proxy pool (ticket 045): one URL per line, blanks and #comments skipped.
    proxies: list[str] = []
    if getattr(args, "proxy_file", None):
        for line in Path(args.proxy_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                proxies.append(line)

    # Resolve proxy mode (ticket 072): explicit flag wins; otherwise default to
    # gateway when only a single --proxy is given (no list), else list.
    _proxy_mode = getattr(args, "proxy_mode", None)
    if _proxy_mode is None:
        _proxy_mode = "gateway" if (getattr(args, "proxy", "") and not proxies) else "list"

    # --max-workers and --concurrency are aliases; disagreeing values are rejected.
    _concurrency = _resolve_concurrency(args)

    curl_impersonate = getattr(args, "curl_impersonate", "") or ""
    # When impersonating, the curl_cffi profile supplies the UA; only override
    # it if the operator explicitly passed --custom-ua.
    if curl_impersonate and curl_impersonate != "none" and not args.custom_ua:
        _user_agent = ""
    else:
        _user_agent = args.custom_ua or "crawler_cli/0.1"

    user_data_dir = getattr(args, "playwright_user_data_dir", "") or ""
    if user_data_dir:
        user_data_dir = str(Path(user_data_dir).expanduser())
    executable_path = getattr(args, "playwright_executable_path", "") or ""
    if executable_path:
        executable_path = str(Path(executable_path).expanduser())
    using_real_profile = bool(user_data_dir)
    headed = getattr(args, "headed", False)
    playwright_headless = False if using_real_profile and not headed else not headed

    from .config import parse_ua_map
    from .portal_policy import load_connection_policy

    ua_map = parse_ua_map(getattr(args, "ua", None) or [])
    policy_spec = getattr(args, "portal_url_policy", "") or ""
    portal_connection_policy = load_connection_policy(policy_spec) if policy_spec else None

    return CrawlConfig(
        # backend is built from the --http-backend choices plus the "playwright"
        # literal, so it is always a valid BackendName.
        backend=cast("BackendName", backend),
        user_agent=_user_agent,
        ua_map=ua_map,
        refresh_days=getattr(args, "refresh_days", 0) or 0,
        max_concurrency=_concurrency,
        max_requests_per_context=args.max_requests_per_context,
        default_open_crawl_limit=args.max_pages,
        max_response_bytes=getattr(args, "max_response_bytes", MAX_RESPONSE_BYTES_DEFAULT),
        timeout_seconds=args.timeout,
        playwright_network_idle_timeout_seconds=(
            args.wait_for_network_idle
            if getattr(args, "wait_for_network_idle", None) is not None
            else args.playwright_network_idle_timeout
        ),
        playwright_wait_for_selector=getattr(args, "wait_for_selector", "") or "",
        playwright_wait_for_selector_timeout_seconds=getattr(args, "wait_for_selector_timeout", 10.0),
        playwright_cdp_endpoint=playwright_cdp_endpoint,
        playwright_browser_channel=getattr(args, "playwright_channel", "") or "",
        playwright_executable_path=executable_path,
        playwright_user_data_dir=user_data_dir,
        playwright_profile_directory=getattr(args, "playwright_profile_directory", "") or "",
        playwright_headless=playwright_headless,
        collect_web_vitals=getattr(args, "collect_web_vitals", False),
        memory_high_watermark_percent=args.memory_high_watermark,
        memory_recovery_watermark_percent=args.memory_recovery_watermark,
        respect_robots_txt=not args.ignore_robots,
        same_host_only=not args.offsite,
        seed_from_archive=args.archive_org_check,
        request_headers=headers,
        cookies=cookies,
        scoped_cookies=scoped_cookies,
        proxy=getattr(args, "proxy", "") or "",
        proxy_auth=getattr(args, "proxy_auth", "") or "",
        proxies=proxies,
        proxy_mode=_proxy_mode,
        proxy_rotation=getattr(args, "proxy_rotation", "round-robin"),
        proxy_max_failures=getattr(args, "proxy_max_failures", 3),
        proxy_cooldown_seconds=getattr(args, "proxy_cooldown_seconds", 60.0),
        proxy_gateway_max_retries=getattr(args, "proxy_gateway_max_retries", 2),
        detect_challenges=not getattr(args, "no_challenge_detection", False),
        # The policy covers HTTP only; never let its guarded crawl silently
        # escape into an unguarded browser challenge escalation.
        challenge_escalate_to_browser=(
            False if portal_connection_policy is not None else not getattr(args, "no_challenge_escalation", False)
        ),
        portal_connection_policy=portal_connection_policy,
        extraction_rules=extraction_rules,
        discover_sitemaps=not args.skip_sitemaps,
        allowed_hosts=allowed_hosts,
        path_restriction=getattr(args, "path_restriction", "") or "",
        path_exclude=path_exclude,
        auth=_build_auth(args),
        csv_urls=csv_urls,
        csv_seed_mode=bool(getattr(args, "csv_seed", False)),
        cms_detection=getattr(args, "cms_detection", False),
        analytics_detection=getattr(args, "analytics_detection", False),
        skip_amp_variants=getattr(args, "skip_amp_variants", False),
        analytics_expected_ids=getattr(args, "analytics_expected_id", []) or [],
        circuit_breaker_enabled=cb_enabled,
        circuit_breaker_failure_threshold=cb_threshold,
        circuit_breaker_recovery_seconds=cb_recovery,
        enable_content_hashing=getattr(args, "content_hashing", False),
        compress_html=not getattr(args, "no_html_compression", False),
        store_html=not getattr(args, "no_store_html", False),
        obscura_enabled=obscura_enabled,
        obscura_binary=obscura_binary,
        obscura_host=getattr(args, "obscura_host", "127.0.0.1"),
        obscura_port=getattr(args, "obscura_port", 9222),
        obscura_proxy=getattr(args, "obscura_proxy", ""),
        obscura_workers=getattr(args, "obscura_workers", 1),
        obscura_managed=not getattr(args, "obscura_unmanaged", False),
        obscura_stealth=obscura_stealth,
        obscura_fetch_subprocess=getattr(args, "obscura_fetch", False),
        curl_impersonate=curl_impersonate,
        per_host_concurrency=getattr(args, "per_host_concurrency", 4),
    )


def _add_postgres_args(parser: argparse.ArgumentParser) -> None:
    pg = parser.add_argument_group("PostgreSQL connection")
    pg.add_argument("--postgres-dsn", help="Full PostgreSQL DSN string")
    pg.add_argument("--postgres-host", help="PostgreSQL host")
    pg.add_argument("--postgres-port", help="PostgreSQL port")
    pg.add_argument("--postgres-user", help="PostgreSQL user")
    pg.add_argument("--postgres-password", help="PostgreSQL password")
    pg.add_argument("--postgres-db", help="PostgreSQL database name")


def _add_reporting_run_selector(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--crawl-run-id",
        help="Crawl run whose immutable snapshots to read. Required when the database contains multiple runs.",
    )


def _add_crawl_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("url", nargs="?", help="Seed URL to crawl")
    parser.add_argument(
        "--seed-url",
        dest="seed_urls",
        action="append",
        default=[],
        help="Additional seed URL. Repeat to crawl multiple hosts in one run.",
    )
    run_group = parser.add_argument_group("Crawl run/resume")
    run_group.add_argument(
        "--resume",
        metavar="RUN_ID",
        help="Resume the selected crawl run id; pending rows from other runs are never claimed.",
    )
    run_group.add_argument(
        "--crawl-run-id",
        help="Run id to assign to a new open crawl. Defaults to a generated crawl-YYYYMMDDTHHMMSSZ-xxxxxxxx id.",
    )
    run_group.add_argument(
        "--allow-run-config-mismatch",
        action="store_true",
        help="Allow --resume when the saved seed/scope/config fingerprint differs from this invocation.",
    )
    parser.add_argument(
        "--intent-signatures",
        action="store_true",
        help="After the crawl, compute intent signatures over crawled HTML (ticket 076).",
    )
    parser.add_argument(
        "--refresh-days",
        type=non_negative_int,
        default=0,
        help="Skip URLs already fetched successfully within N days (0 = refetch all).",
    )
    parser.add_argument(
        "--ua",
        action="append",
        default=[],
        metavar="DOMAIN=UA",
        help='Per-domain User-Agent, e.g. --ua "casino.org=Screaming Frog/1.0" '
        "(repeatable; matches subdomains). Falls back to --custom-ua/--user-agent.",
    )
    parser.add_argument(
        "--max-workers",
        type=positive_int,
        default=None,
        help="Max concurrent workers (default 15). Alias: --concurrency.",
    )
    parser.add_argument(
        "--concurrency",
        type=positive_int,
        default=None,
        help="Alias for --max-workers.",
    )
    parser.add_argument(
        "--per-host-concurrency",
        type=non_negative_int,
        default=4,
        help="Max simultaneous requests to any single host (0 = unlimited, default 4).",
    )
    parser.add_argument(
        "--max-pages",
        type=non_negative_int,
        default=DEFAULT_OPEN_CRAWL_LIMIT,
        help=(
            "Max URLs to crawl during open crawls "
            f"(default {DEFAULT_OPEN_CRAWL_LIMIT}; 0 = unlimited and can expand aggressively via links/sitemaps)."
        ),
    )
    parser.add_argument(
        "--max-response-bytes",
        type=positive_int,
        default=MAX_RESPONSE_BYTES_DEFAULT,
        help=(
            "Max bytes read per response before truncation (default "
            f"{MAX_RESPONSE_BYTES_DEFAULT}). Raise it for sites with very "
            "large sitemaps so they parse intact; lower it to cap downloads."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=30.0,
        help="Per-request timeout in seconds",
    )
    parser.add_argument("--js", action="store_true", help="Use Playwright (JS-enabled) backend")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Launch the Playwright browser headed instead of headless",
    )
    parser.add_argument(
        "--max-requests-per-context",
        type=non_negative_int,
        default=50,
        help="Recycle Playwright browser contexts after this many page loads (0 disables recycling)",
    )
    parser.add_argument(
        "--playwright-network-idle-timeout",
        type=non_negative_float,
        default=5.0,
        help="Additional Playwright network-idle settle timeout in seconds",
    )
    parser.add_argument(
        "--playwright-cdp-endpoint",
        help="Connect Playwright to an existing CDP browser such as Obscura or a locally launched Chrome/Edge",
    )
    parser.add_argument(
        "--playwright-cdp-host",
        help="CDP host for an already-running Chrome/Edge launched with --remote-debugging-port (default 127.0.0.1)",
    )
    parser.add_argument(
        "--playwright-cdp-port",
        type=positive_int,
        help="CDP port for an already-running Chrome/Edge launched with --remote-debugging-port",
    )
    parser.add_argument(
        "--playwright-channel",
        help="Launch a branded browser channel with Playwright, e.g. chrome or msedge",
    )
    parser.add_argument(
        "--playwright-executable-path",
        help="Launch this Chrome/Edge/Chromium executable with Playwright",
    )
    parser.add_argument(
        "--playwright-user-data-dir",
        help="Launch a persistent Playwright browser against this Chromium user-data directory",
    )
    parser.add_argument(
        "--playwright-profile-directory",
        help="Profile directory inside --playwright-user-data-dir, e.g. Default or 'Profile 1'",
    )
    parser.add_argument(
        "--wait-for-selector",
        help="JS backend only: wait for this CSS selector before snapshotting the DOM "
        "(for SPAs that hydrate content async). Times out gracefully.",
    )
    parser.add_argument(
        "--wait-for-selector-timeout",
        type=positive_float,
        default=10.0,
        help="Timeout in seconds for --wait-for-selector (default 10)",
    )
    parser.add_argument(
        "--wait-for-network-idle",
        type=non_negative_float,
        metavar="SECONDS",
        help="JS backend only: override the network-idle settle timeout in seconds "
        "(alias for --playwright-network-idle-timeout; 0 disables the idle wait)",
    )
    parser.add_argument(
        "--web-vitals",
        action="store_true",
        dest="collect_web_vitals",
        help="JS backend only: capture lab Core Web Vitals (LCP/CLS/INP) per page "
        "via a PerformanceObserver shim (ticket 046). No effect on HTTP backends.",
    )
    parser.add_argument(
        "--no-challenge-detection",
        action="store_true",
        help="Disable bot-challenge (Cloudflare/Datadome/...) detection (ticket 074). "
        "By default challenges are detected and not stored as content.",
    )
    parser.add_argument(
        "--no-challenge-escalation",
        action="store_true",
        help="Detect challenges but do not escalate HTTP fetches to the browser "
        "backend; just record them as blocked (ticket 074).",
    )
    parser.add_argument(
        "--portal-url-policy",
        metavar="MODULE:FACTORY",
        help=(
            "Load this local Portal-owned async connection-policy factory. It pins every initial, "
            "redirect and sitemap HTTP connection; browser navigation, browser subresources and "
            "live comparisons are unsupported, and challenge browser escalation is disabled."
        ),
    )
    parser.add_argument(
        "--memory-high-watermark",
        type=percentage,
        default=85.0,
        help="Reduce worker concurrency when system memory usage reaches this percent",
    )
    parser.add_argument(
        "--memory-recovery-watermark",
        type=percentage,
        default=70.0,
        help="Restore worker concurrency once system memory usage drops to this percent",
    )
    parser.add_argument("--http-backend", choices=["aiohttp", "curl_cffi"], help="HTTP backend")
    parser.add_argument(
        "--impersonate",
        dest="curl_impersonate",
        default="",
        metavar="TARGET",
        help="curl_cffi only: browser fingerprint to impersonate (e.g. chrome, safari, firefox). "
        "Pass 'none' to disable. When set, the User-Agent is not overridden unless --custom-ua is also given.",
    )
    parser.add_argument("--custom-ua", "--user-agent", dest="custom_ua", help="Custom User-Agent")
    parser.add_argument("--ignore-robots", action="store_true", help="Ignore robots.txt")
    parser.add_argument("--offsite", action="store_true", help="Follow off-site links")
    parser.add_argument(
        "--allowed-hosts",
        default="",
        help="Comma-separated additional hosts, including CDN Sitemap: hosts",
    )
    parser.add_argument("--path-restriction", help="Restrict crawl to paths containing this string")
    parser.add_argument(
        "--path-exclude",
        help="Comma-separated path prefixes to exclude (e.g. /news/,/admin/)",
    )
    cb = parser.add_argument_group("Circuit breaker (per-host)")
    cb.add_argument(
        "--circuit-breaker-threshold",
        type=positive_int,
        default=None,
        help=(
            "Consecutive per-host failures before the breaker opens "
            f"(default {CB_THRESHOLD_DEFAULT}; env CRAWLER_CLI_CB_THRESHOLD)"
        ),
    )
    cb.add_argument(
        "--circuit-breaker-recovery-seconds",
        type=positive_float,
        default=None,
        help=(
            "Seconds an open breaker waits before a half-open retry "
            f"(default {CB_RECOVERY_SECONDS_DEFAULT}; env CRAWLER_CLI_CB_RECOVERY_SECONDS)"
        ),
    )
    cb.add_argument(
        "--no-circuit-breaker",
        action="store_true",
        help="Disable the per-host circuit breaker entirely (env CRAWLER_CLI_CB_ENABLED=0)",
    )
    parser.add_argument("--archive-org-check", action="store_true", help="Seed from archive.org + run audit")
    parser.add_argument("--skip-sitemaps", action="store_true", help="Skip sitemap discovery")
    parser.add_argument(
        "--extraction-rules",
        help="Path to a JSON file of custom extraction rules (CSS/XPath/regex). "
        "Results are stored in the content.custom_data JSONB column.",
    )
    parser.add_argument(
        "--skip-amp-variants",
        action="store_true",
        help="Do not enqueue AMP-shaped URLs (a /amp path tail or amp=1 query param) at "
        "discovery time, saving crawl budget (ticket 103). Default OFF: crawl-and-classify "
        "so AMP canonical-hygiene reporting keeps working.",
    )
    parser.add_argument("--cms-detection", action="store_true", help="Enable CMS platform detection")
    parser.add_argument(
        "--analytics-detection", action="store_true", help="Enable analytics / tag manager / pixel detection"
    )
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
    obscura.add_argument("--obscura-port", type=positive_int, default=argparse.SUPPRESS, help="Obscura port")
    obscura.add_argument("--obscura-proxy", default=argparse.SUPPRESS, help="Proxy URL for Obscura")
    obscura.add_argument("--obscura-workers", type=positive_int, default=argparse.SUPPRESS, help="Obscura worker count")
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
    obscura.add_argument(
        "--obscura-fetch",
        action="store_true",
        default=argparse.SUPPRESS,
        help=(
            "Fetch via the one-shot 'obscura fetch' subprocess per request "
            "instead of a persistent CDP browser connection. More robust where "
            "connect_over_cdp/goto can hang; no obscura serve / port needed."
        ),
    )
    parser.add_argument("--output-dir", type=Path, help="Directory for CSV/JSON output")
    parser.add_argument("--save-to", help="Path to save crawl JSON results")
    parser.add_argument(
        "--allow-persist-failures",
        action="store_true",
        help=(
            "Best-effort durability: exit 0 even when some pages failed to persist "
            "(ticket 092). Default is non-zero so automation notices incomplete DB writes."
        ),
    )
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
    proxy = parser.add_argument_group("Proxy")
    proxy.add_argument(
        "--proxy",
        help="Proxy URL routed through all backends (e.g. http://host:8080, "
        "socks5://host:1080). Credentials may be embedded or passed via --proxy-auth.",
    )
    proxy.add_argument(
        "--proxy-auth",
        metavar="USER:PASSWORD",
        help="Proxy credentials when not embedded in --proxy.",
    )
    proxy.add_argument(
        "--proxy-file",
        help="File with one proxy URL per line; rotated across requests in list "
        "mode (ticket 045). Takes precedence over --proxy.",
    )
    proxy.add_argument(
        "--proxy-mode",
        choices=["list", "gateway"],
        default=None,
        help="'gateway' = a single residential rotating-gateway endpoint (set "
        "via --proxy) whose IP rotates server-side per request; never evicted, "
        "retried on failure (ticket 072). 'list' = client-side pool from "
        "--proxy-file/--proxy (ticket 045). Default: gateway when only --proxy "
        "is set, else list.",
    )
    proxy.add_argument(
        "--proxy-gateway-max-retries",
        type=non_negative_int,
        default=2,
        help="gateway mode: extra retries through the gateway on a failed fetch "
        "(each retry gets a fresh exit IP). Default 2.",
    )
    proxy.add_argument(
        "--proxy-rotation",
        choices=["round-robin", "per-host"],
        default="round-robin",
        help="list mode: rotation strategy: round-robin (per request) or "
        "per-host (sticky per target host). Default round-robin.",
    )
    proxy.add_argument(
        "--proxy-max-failures",
        type=non_negative_int,
        default=3,
        help="Consecutive failures before a pool proxy is put on cooldown (default 3).",
    )
    proxy.add_argument(
        "--proxy-cooldown",
        type=non_negative_float,
        default=60.0,
        dest="proxy_cooldown_seconds",
        help="Seconds an evicted pool proxy stays out of rotation (default 60).",
    )
    cookies = parser.add_argument_group("Session cookies")
    cookies.add_argument(
        "--cookie",
        action="append",
        default=[],
        dest="cookies",
        metavar="NAME=VALUE",
        help="Session cookie to inject on every request. Repeatable; a single value may also contain ';'-joined pairs.",
    )
    cookies.add_argument(
        "--cookies-file",
        help="Load cookies from a JSON (dev-tools / storageState) or Netscape "
        "cookies.txt file. Domain/path attributes are honoured per-request "
        "(see --no-cookie-scoping).",
    )
    cookies.add_argument(
        "--no-cookie-scoping",
        action="store_true",
        help="Send all cookies to every host as one flat Cookie header, "
        "ignoring their domain/path attributes (legacy ticket-028 behaviour).",
    )
    auth = parser.add_argument_group("HTTP authentication")
    auth.add_argument("--auth-type", choices=["basic", "bearer"], help="Authentication type")
    auth.add_argument("--auth-username", help="Username for basic auth")
    auth.add_argument("--auth-password", help="Password for basic auth")
    auth.add_argument("--auth-password-env", help="Read the basic auth password from this environment variable")
    auth.add_argument("--auth-password-file", help="Read the basic auth password from this file")
    auth.add_argument("--auth-token", help="Bearer token or password fallback")
    auth.add_argument("--auth-token-env", help="Read the bearer token from this environment variable")
    auth.add_argument("--auth-token-file", help="Read the bearer token from this file")
    _add_postgres_args(parser)


async def _run_crawl(args: argparse.Namespace) -> int:
    seeds = _collect_seed_urls(args)
    if not seeds and not args.csv_file:
        print("Error: provide a seed URL, one or more --seed-url values, or --csv-file", file=sys.stderr)
        return EXIT_VALIDATION
    if args.csv_file and not seeds and not args.csv_seed:
        args.url = load_urls_from_csv(args.csv_file, column=args.csv_column)[0]
        seeds = _collect_seed_urls(args)
    if args.resume and args.crawl_run_id:
        print("Error: use --resume RUN_ID or --crawl-run-id for a new run, not both", file=sys.stderr)
        return EXIT_VALIDATION

    try:
        config = _build_config(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_VALIDATION
    config.default_open_crawl_limit = args.max_pages

    if config.circuit_breaker_enabled:
        logger.info(
            "Circuit breaker: enabled (threshold=%d, recovery=%.1fs)",
            config.circuit_breaker_failure_threshold,
            config.circuit_breaker_recovery_seconds,
        )
    else:
        logger.info("Circuit breaker: disabled")

    if args.archive_org_check and not _postgres_config_supplied(args):
        print("Error: --archive-org-check requires PostgreSQL configuration", file=sys.stderr)
        return EXIT_VALIDATION

    if _postgres_config_supplied(args):
        store: AsyncpgStore | MemoryStore | None = _store_from_args(args)
        await store.initialize()
    else:
        store = MemoryStore()
    engine = CrawlEngine(config, store=store)

    # Install SIGINT/SIGTERM handlers: first signal requests a clean drain,
    # second signal cancels hard (ticket-064).  Handlers are removed on exit.
    import signal as _signal

    _sig_count = 0

    def _stop_handler(signum: int, _frame: object) -> None:
        nonlocal _sig_count
        _sig_count += 1
        if _sig_count == 1:
            logger.warning("Interrupt received — draining in-flight work, press again to force quit")
            engine.request_stop()
        else:
            raise KeyboardInterrupt

    _orig_sigint = _signal.signal(_signal.SIGINT, _stop_handler)
    _orig_sigterm = _signal.signal(_signal.SIGTERM, _stop_handler)

    _exit_code = 0
    try:
        if config.csv_urls and not config.csv_seed_mode:
            job = await engine.crawl_list(config.csv_urls, save_to=args.save_to)
        else:
            try:
                job = await engine.crawl_open(
                    seeds,
                    save_to=args.save_to,
                    run_id=args.resume or args.crawl_run_id,
                    resume=bool(args.resume),
                    allow_run_config_mismatch=args.allow_run_config_mismatch,
                )
            except CrawlRunSelectionError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return EXIT_VALIDATION
        _exit_code = resolve_crawl_exit_code(
            job,
            allow_persist_failures=bool(getattr(args, "allow_persist_failures", False)),
        )
        persist_errors = job.persist_error_count
        label = "Crawl interrupted" if job.interrupted else "Crawl complete"
        durability_label = {
            "durable": "durable",
            "partially_durable": "partially durable",
            "saved_output_only": "saved-output-only",
        }[job.durability]
        summary = (
            f"{label}: {job.crawled_count} crawled, {job.blocked_count} blocked by robots, "
            f"durability={durability_label}"
        )
        if job.refresh_skipped_count:
            summary += f", {job.refresh_skipped_count} skipped (fresh within --refresh-days)"
        if job.retry_attempts:
            summary += f", {job.retry_attempts} transient retries"
        if job.challenge_blocked_count:
            summary += f", {job.challenge_blocked_count} blocked by bot-challenge"
        if persist_errors:
            summary += f", {persist_errors} persist failures"
            if job.persist_failed_urls:
                preview = ", ".join(job.persist_failed_urls[:5])
                if persist_errors > 5:
                    preview += ", ..."
                summary += f" [{preview}]"
            if args.save_to:
                summary += f" (results in {args.save_to})"
            elif job.durability == "saved_output_only":
                summary += " (in-memory results only)"
        if job.frontier_mark_done_error_count:
            summary += f", {job.frontier_mark_done_error_count} frontier mark-done failures pending for --resume"
        if job.run_id:
            summary += f" (run {job.run_id})"
        print(summary)

        if getattr(args, "intent_signatures", False):
            if isinstance(store, AsyncpgStore):
                from .intent_signature import backfill_intent_signatures

                sig_result = await backfill_intent_signatures(store)
                print(
                    f"Intent signatures: processed={sig_result.processed} "
                    f"updated={sig_result.updated} unchanged={sig_result.unchanged}"
                )
            else:
                print(
                    "Note: --intent-signatures needs PostgreSQL; skipped for in-memory crawl.",
                    file=sys.stderr,
                )

        if args.archive_org_check and seeds:
            seen_domains: set[str] = set()
            for seed in seeds:
                domain = seed.split("://", 1)[-1].split("/")[0].lower()
                if not domain or domain in seen_domains:
                    continue
                seen_domains.add(domain)
                audit = await audit_archive_urls(domain, store, config, output_dir=args.output_dir)
                print(f"Archive audit [{domain}]: {audit.archive_url_count} historical URLs")
                logger.info("  Missing: %d", len(audit.missing_urls))
                logger.info("  Legacy issues: %d", len(audit.legacy_issues))
                if args.output_dir:
                    logger.info("  CSVs written to %s", args.output_dir)
    finally:
        _signal.signal(_signal.SIGINT, _orig_sigint)
        _signal.signal(_signal.SIGTERM, _orig_sigterm)
        await engine.close()
        await store.close()
    return _exit_code


async def _run_embeddings(args: argparse.Namespace) -> int:
    if args.provider == "sentence-transformers":
        return await _run_local_embeddings(args)

    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Error: set --api-key or OPENAI_API_KEY", file=sys.stderr)
        return 2

    model = args.model or "text-embedding-3-small"
    batch_size = args.batch_size or 10
    store = _store_from_args(args)
    await store.initialize()

    try:
        run_id = await store.resolve_reporting_run_id(args.crawl_run_id)
        urls = None
        if args.urls:
            urls = args.urls
        result = await generate_embeddings_for_store(
            store,
            api_key=api_key,
            model=model,
            batch_size=batch_size,
            delay_seconds=args.delay,
            skip_existing=not args.force,
            urls=urls,
            run_id=run_id,
        )
        print(f"Embeddings complete: processed={result.processed} skipped={result.skipped} failed={result.failed}")
        if result.errors:
            print("Errors:")
            for error in result.errors[:10]:
                print(f"  - {error}")
    finally:
        await store.close()
    return 0


async def _run_local_embeddings(args: argparse.Namespace) -> int:
    from .embeddings import (
        DEFAULT_LOCAL_MODEL,
        generate_signature_embeddings_for_store,
    )

    model = args.model or DEFAULT_LOCAL_MODEL
    source = args.source or "signature"
    batch_size = args.batch_size or 64

    store = _store_from_args(args)
    await store.initialize()
    try:
        run_id = await store.resolve_reporting_run_id(args.crawl_run_id)
        result = await generate_signature_embeddings_for_store(
            store,
            model=model,
            revision=args.model_revision,
            batch_size=batch_size,
            force=args.force,
            urls=args.urls or None,
            source=source,
            run_id=run_id,
        )
    finally:
        await store.close()

    print(
        f"Embeddings complete (sentence-transformers, model={model}, source={source}): "
        f"processed={result.processed} skipped={result.skipped} failed={result.failed}"
    )
    if result.errors:
        print("Errors:")
        for error in result.errors[:10]:
            print(f"  - {error}")
    return 1 if result.failed else 0


async def _run_backfill_signatures(args: argparse.Namespace) -> int:
    from .intent_signature import backfill_intent_signatures

    store = _store_from_args(args)
    await store.initialize()
    try:
        run_id = await store.resolve_reporting_run_id(args.crawl_run_id)
        result = await backfill_intent_signatures(
            store,
            urls=args.urls or None,
            boilerplate_share=args.boilerplate_share,
            min_words=args.min_words,
            dry_run=args.dry_run,
            run_id=run_id,
        )
    finally:
        await store.close()

    suffix = " (dry-run)" if args.dry_run else ""
    print(
        f"Intent signatures{suffix}: processed={result.processed} "
        f"updated={result.updated} unchanged={result.unchanged} "
        f"low_confidence={result.low_confidence} no_text={result.no_text}"
    )
    if result.by_method:
        methods = ", ".join(f"{k}={v}" for k, v in sorted(result.by_method.items()))
        print(f"  extraction: {methods}")
    return 0


async def _run_hreflang_groups(args: argparse.Namespace) -> int:
    from .hreflang_groups import build_and_store_identity

    store = _store_from_args(args)
    await store.initialize()
    try:
        run_id = await store.resolve_reporting_run_id(args.crawl_run_id)
        result = await build_and_store_identity(store, run_id=run_id)
    finally:
        await store.close()

    print(
        f"Hreflang identity: {result.groups} groups covering {result.grouped_urls} "
        f"of {result.pages} pages; {result.variants} URL variants folded into "
        f"{result.representatives} representatives; "
        f"{result.reciprocity_issues} reciprocity issues."
    )
    return 0


async def _run_intent_overlap(args: argparse.Namespace) -> int:
    from .embeddings import MixedModelError
    from .intent_overlap import run_intent_overlap

    try:
        _validate_intent_overlap_numeric_args(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_VALIDATION
    html_report = bool(getattr(args, "html_report", False))
    json_report = bool(getattr(args, "json_report", False) or html_report)

    run_args = {
        "threshold": args.threshold,
        "dup_threshold": args.dup_threshold,
        "hreflang_mode": args.hreflang_mode,
        "primary_lang": args.primary_lang,
        "lang_split": not args.no_lang_split,
        "linkage": args.linkage,
        "out": args.out,
        "fail_on": args.fail_on,
        "ann": args.ann,
        "ann_min_pages": args.ann_min_pages,
        "ann_k": args.ann_k,
        "thin_signature_words": args.thin_signature_words,
        "time_sequenced_section": args.time_sequenced_section,
        "json_report": json_report,
        "html_report": html_report,
        "json_min_similarity": args.json_min_similarity,
        "projection_seed": args.projection_seed,
    }

    store = _store_from_args(args)
    await store.initialize()
    try:
        run_id = await store.resolve_reporting_run_id(args.crawl_run_id)
        run = await run_intent_overlap(
            store,
            out_dir=args.out,
            threshold=args.threshold,
            dup_threshold=args.dup_threshold,
            hreflang_mode=args.hreflang_mode,
            primary_lang=args.primary_lang,
            lang_split=not args.no_lang_split,
            linkage=args.linkage,
            fail_on=args.fail_on,
            use_ann=args.ann,
            ann_min_pages=args.ann_min_pages,
            ann_k=args.ann_k,
            thin_signature_words=args.thin_signature_words,
            time_sequenced_sections=args.time_sequenced_section or (),
            run_args=run_args,
            json_report=json_report,
            json_min_similarity=args.json_min_similarity,
            projection_seed=args.projection_seed,
            crawl_run_id=run_id,
        )
    except MixedModelError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        # e.g. hnswlib missing for --ann, or numpy missing for analysis.
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    finally:
        await store.close()

    if html_report:
        from pathlib import Path

        from .report_html import write_report_html

        json_path = Path(args.out) / "report_data.json"
        html_path = Path(args.out) / "report.html"
        try:
            write_report_html(json_path, html_path)
            run.written.append(str(html_path))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"Error writing HTML report: {exc}", file=sys.stderr)
            return 2

    s = run.result.summary
    tp = s.get("threshold_percentile")
    tnote = f" (threshold {args.threshold} ~ p{tp:.0f} of NN similarity)" if tp is not None else ""
    relation_counts = s.get("relation_counts") or {}
    pc_pairs = relation_counts.get("parent-child", 0)
    pc_note = f" ({pc_pairs} parent-child)" if pc_pairs else ""
    ts_note = (
        f", {s.get('time_sequenced_pairs', 0)} time-sequenced pairs excluded from duplicate gating"
        if args.time_sequenced_section
        else ""
    )
    print(
        f"intent-overlap: {s.get('embedded', 0)} embedded pages, "
        f"{s.get('overlap_pairs', 0)} pairs{pc_note}, {s.get('clusters', 0)} clusters, "
        f"{s.get('duplicate_pages', 0)} duplicate pages "
        f"({s.get('suppressed_pairs', 0)} intra-hreflang pairs suppressed){ts_note}{tnote}"
    )
    param_pages = s.get("parameterised_pages", 0)
    if param_pages:
        print(
            f"parameterised URLs: {param_pages} pages "
            f"({s.get('parameterised_duplicates', 0)} folded as duplicates of their base, "
            f"{s.get('missing_canonical', 0)} missing a canonical)"
        )
    amp_variants = s.get("amp_variants", 0)
    if amp_variants:
        print(
            f"amp variants: {amp_variants} classified "
            f"({s.get('amp_missing_canonical', 0)} missing a canonical — see amp_issues.csv)"
        )
    print(
        f"  thin content: {s.get('thin_content_pages', 0)} pages downgraded from duplicate risk "
        f"({s.get('thin_pages', 0)} pages below --thin-signature-words "
        f"{s.get('thin_signature_words', args.thin_signature_words)}, "
        f"{s.get('thin_pairs', 0)} thin-vs-thin pairs excluded from --fail-on duplicate)"
    )
    print(f"Reports written to {args.out}/ ({len(run.written)} files)")
    if run.exit_code:
        print(
            f"--fail-on {args.fail_on}: findings present (exit {run.exit_code})",
            file=sys.stderr,
        )
    return run.exit_code


def _run_render_report(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .report_html import write_report_html

    try:
        out = write_report_html(args.data, args.output)
    except FileNotFoundError:
        print(f"Error: report data not found: {args.data}", file=sys.stderr)
        return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error rendering report: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote {out} ({Path(out).stat().st_size} bytes)")
    return 0


# --- Saved-crawl JSON schema (ticket 083) -----------------------------------
# TypedDicts describing exactly what serialization.py writes, so mypy checks the
# field types the _load_* deserializers pull back out — replacing the per-field
# arg-type suppressions that widened the payloads to ``Any``.
# Every key is optional at the JSON level (older artifacts omit newer keys, hence
# the tolerant ``.get(..., default)`` reads below); the three the loader
# dereferences unconditionally are ``Required`` so a row missing them is a type
# error rather than a silent ``None``.


class _SavedHreflangLink(TypedDict, total=False):
    hreflang: str
    href: str
    source: Literal["http_header", "html_head", "sitemap"]


class _SavedExtracted(TypedDict, total=False):
    title: str | None
    meta_description: str | None
    meta_robots: list[str]
    x_robots_tag: list[str]
    canonical: str | None
    x_canonical: str | None
    hreflang_links: list[_SavedHreflangLink]
    html_lang: str | None
    headings: dict[str, list[str]]
    text: str
    word_count: int
    metadata: dict[str, Any]
    schema_data: list[dict[str, Any]]


class _SavedBrowserRuntime(TypedDict, total=False):
    provider: Literal["chromium", "cdp", "obscura"]
    cdp_endpoint: str | None
    managed: bool | None
    stealth: bool | None
    persistent: bool | None
    channel: str | None
    executable_path: str | None
    user_data_dir: str | None
    profile_directory: str | None
    headless: bool | None


class _SavedDiscoveredLink(TypedDict, total=False):
    href: str
    anchor_text: str | None
    xpath: str
    is_image: bool
    fragment: str | None
    url_parameters: str | None
    original_href: str | None


class _SavedResult(TypedDict, total=False):
    requested_url: Required[str]
    final_url: Required[str]
    status: Required[int]
    headers: dict[str, str]
    content_type: str | None
    fetch_backend: str
    extracted: _SavedExtracted | None
    raw_html: str | None
    content_hash_sha256: str | None
    content_hash_simhash: int | None
    discovered_links: list[_SavedDiscoveredLink]
    allowed_by_robots: bool | None
    skip_reason: str | None
    persist_error: str | None
    challenge: str | None
    browser_runtime: _SavedBrowserRuntime | None
    ttfb_seconds: float | None
    total_duration_seconds: float | None
    custom_data: dict[str, Any] | None
    lcp_ms: float | None
    cls: float | None
    inp_ms: float | None
    redirect_chain: list[dict[str, Any]]


class _SavedJob(TypedDict, total=False):
    mode: Literal["list", "open"]
    seed_urls: list[str]
    saved_to: str | None
    max_urls: int | None
    retry_attempts: int
    interrupted: bool
    run_id: str | None
    frontier_mark_done_failed_urls: list[str]
    crawl_run_status: str | None
    results: list[_SavedResult]


_REPORT_NAMES = (
    "orphans",
    "indexability",
    "redirect-chains",
    "hub-pages",
    "slowest",
    "cwv",
    "analytics-inventory",
    "missing-analytics",
    "missing-expected-id",
)


async def _fetch_report(reports: CrawlReports, name: str, args: argparse.Namespace) -> list[dict[str, object]]:
    if name == "orphans":
        return await reports.orphan_pages()
    if name == "indexability":
        return await reports.indexability_reasons()
    if name == "redirect-chains":
        return await reports.redirect_chains()
    if name == "hub-pages":
        return await reports.site_hub_pages(min_outlinks=args.min_outlinks)
    if name == "slowest":
        return await reports.slowest_pages(limit=args.limit)
    if name == "cwv":
        return await reports.worst_cwv_pages(limit=args.limit)
    if name == "analytics-inventory":
        return await reports.analytics_inventory()
    if name == "missing-analytics":
        return await reports.pages_missing_analytics(vendor=args.vendor)
    if name == "missing-expected-id":
        return await reports.pages_missing_expected_id(args.expected_id)
    raise ValueError(f"unknown report: {name}")


def _report_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _render_report_table(name: str, rows: list[dict[str, object]]) -> str:
    lines = [f"# {name} ({len(rows)} rows)"]
    if not rows:
        lines.append("(no rows)")
        return "\n".join(lines)
    columns = list(rows[0].keys())
    widths = {col: max(len(col), *(len(_report_cell(row.get(col))) for row in rows)) for col in columns}
    lines.append("  ".join(col.ljust(widths[col]) for col in columns).rstrip())
    for row in rows:
        lines.append("  ".join(_report_cell(row.get(col)).ljust(widths[col]) for col in columns).rstrip())
    return "\n".join(lines)


def _emit_report_results(results: dict[str, list[dict[str, object]]], args: argparse.Namespace) -> None:
    if args.format == "json":
        text = json.dumps(results, indent=2, sort_keys=True, default=str)
        if args.out:
            Path(args.out).write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
        return
    if args.format == "csv":
        import csv as _csv

        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, rows in results.items():
            path = out_dir / f"{name.replace('-', '_')}.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                if rows:
                    writer = _csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                    writer.writeheader()
                    writer.writerows(rows)
            print(f"{name}: {len(rows)} rows -> {path}")
        return
    text = "\n\n".join(_render_report_table(name, rows) for name, rows in results.items())
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


async def _run_report(args: argparse.Namespace) -> int:
    requested = list(dict.fromkeys(args.reports))
    unknown = [name for name in requested if name not in _REPORT_NAMES]
    if unknown:
        print(
            f"Error: unknown report(s): {', '.join(unknown)}. Valid reports: {', '.join(_REPORT_NAMES)}",
            file=sys.stderr,
        )
        return EXIT_VALIDATION
    if not requested:
        # missing-expected-id needs an identifier, so it only joins the default
        # set when --expected-id makes it answerable.
        requested = [name for name in _REPORT_NAMES if name != "missing-expected-id" or args.expected_id]
    if "missing-expected-id" in requested and not args.expected_id:
        print("Error: report 'missing-expected-id' requires --expected-id", file=sys.stderr)
        return EXIT_VALIDATION
    if args.format == "csv" and not args.out:
        print("Error: --format csv requires --out DIRECTORY", file=sys.stderr)
        return EXIT_VALIDATION

    import asyncpg

    store = _store_from_args(args)
    reports = CrawlReports(store, run_id=args.crawl_run_id)
    try:
        results: dict[str, list[dict[str, object]]] = {}
        for name in requested:
            results[name] = await _fetch_report(reports, name, args)
    except asyncpg.exceptions.UndefinedTableError as exc:
        print(
            f"Error: {exc}. This database has no run-aware snapshot schema — it either "
            "predates snapshots (re-crawl with a current version) or is not a crawler_cli database.",
            file=sys.stderr,
        )
        return EXIT_VALIDATION
    finally:
        await store.close()
    _emit_report_results(results, args)
    return 0


def _load_saved_crawl(path: Path) -> "CrawlJobResult":
    from .models import (
        BrowserRuntime,
        CrawlJobResult,
        CrawlResult,
        DiscoveredLink,
        ExtractedContent,
        HreflangLink,
        RobotsDirectives,
    )

    def _load_browser_runtime(payload: _SavedBrowserRuntime | None) -> BrowserRuntime | None:
        if not payload:
            return None
        return BrowserRuntime(
            provider=payload.get("provider", "chromium"),
            cdp_endpoint=payload.get("cdp_endpoint"),
            managed=payload.get("managed"),
            stealth=payload.get("stealth"),
            persistent=payload.get("persistent"),
            channel=payload.get("channel"),
            executable_path=payload.get("executable_path"),
            user_data_dir=payload.get("user_data_dir"),
            profile_directory=payload.get("profile_directory"),
            headless=payload.get("headless"),
        )

    def _load_extracted(payload: _SavedExtracted | None) -> ExtractedContent | None:
        if not payload:
            return None
        hreflang_links = [
            HreflangLink(
                hreflang=str(link.get("hreflang", "")),
                href=str(link.get("href", "")),
                source=link.get("source", "html_head"),
            )
            for link in payload.get("hreflang_links", []) or []
            if isinstance(link, dict)
        ]
        return ExtractedContent(
            title=payload.get("title"),
            meta_description=payload.get("meta_description"),
            meta_robots=RobotsDirectives(raw=list(payload.get("meta_robots", []) or [])),
            x_robots_tag=RobotsDirectives(raw=list(payload.get("x_robots_tag", []) or [])),
            canonical=payload.get("canonical"),
            x_canonical=payload.get("x_canonical"),
            hreflang_links=hreflang_links,
            html_lang=payload.get("html_lang"),
            headings=dict(payload.get("headings", {}) or {}),
            text=str(payload.get("text", "")),
            word_count=int(payload.get("word_count", 0) or 0),
            metadata=dict(payload.get("metadata", {}) or {}),
            schema_data=list(payload.get("schema_data", []) or []),
        )

    def _load_discovered_links(payload: list[_SavedDiscoveredLink] | None) -> list[DiscoveredLink]:
        links: list[DiscoveredLink] = []
        for item in payload or []:
            if not isinstance(item, dict):
                continue
            links.append(
                DiscoveredLink(
                    href=str(item.get("href", "")),
                    anchor_text=item.get("anchor_text"),
                    xpath=str(item.get("xpath", "")),
                    is_image=bool(item.get("is_image", False)),
                    fragment=item.get("fragment"),
                    url_parameters=item.get("url_parameters"),
                    original_href=item.get("original_href"),
                )
            )
        return links

    def _load_result(item: _SavedResult) -> CrawlResult:
        return CrawlResult(
            requested_url=str(item["requested_url"]),
            final_url=str(item["final_url"]),
            status=int(item["status"]),
            headers=dict(item.get("headers", {}) or {}),
            content_type=item.get("content_type"),
            fetch_backend=str(item.get("fetch_backend", "aiohttp")),
            extracted=_load_extracted(item.get("extracted")),
            raw_html=item.get("raw_html"),
            content_hash_sha256=item.get("content_hash_sha256"),
            content_hash_simhash=item.get("content_hash_simhash"),
            discovered_links=_load_discovered_links(item.get("discovered_links")),
            allowed_by_robots=item.get("allowed_by_robots"),
            skip_reason=item.get("skip_reason"),
            persist_error=item.get("persist_error"),
            challenge=item.get("challenge"),
            browser_runtime=_load_browser_runtime(item.get("browser_runtime")),
            ttfb_seconds=item.get("ttfb_seconds"),
            total_duration_seconds=item.get("total_duration_seconds"),
            custom_data=item.get("custom_data"),
            lcp_ms=item.get("lcp_ms"),
            cls=item.get("cls"),
            inp_ms=item.get("inp_ms"),
            redirect_chain=list(item.get("redirect_chain", []) or []),
        )

    raw_text = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        lines = [json.loads(line) for line in raw_text.splitlines() if line.strip()]
        # json.loads returns Any; cast the summary line to the saved-job schema so
        # the CrawlJobResult fields below are type-checked. Result lines stay Any,
        # which _load_result accepts as a _SavedResult.
        summary = cast("_SavedJob", next((line for line in lines if line.get("__type") == "summary"), {}))
        results = [_load_result(line) for line in lines if line.get("__type") != "summary"]
        return CrawlJobResult(
            mode=summary.get("mode", "open"),
            seed_urls=list(summary.get("seed_urls", []) or []),
            results=results,
            saved_to=summary.get("saved_to"),
            max_urls=summary.get("max_urls"),
            run_id=summary.get("run_id"),
            retry_attempts=int(summary.get("retry_attempts", 0) or 0),
            interrupted=bool(summary.get("interrupted", False)),
            frontier_mark_done_failed_urls=list(summary.get("frontier_mark_done_failed_urls", []) or []),
            crawl_run_status=summary.get("crawl_run_status"),
        )

    if isinstance(payload, dict) and "results" in payload:
        job = cast("_SavedJob", payload)
        return CrawlJobResult(
            mode=job.get("mode", "list"),
            seed_urls=list(job.get("seed_urls", []) or []),
            results=[_load_result(item) for item in job.get("results", []) or [] if isinstance(item, dict)],
            saved_to=job.get("saved_to"),
            max_urls=job.get("max_urls"),
            run_id=job.get("run_id"),
            retry_attempts=int(job.get("retry_attempts", 0) or 0),
            interrupted=bool(job.get("interrupted", False)),
            frontier_mark_done_failed_urls=list(job.get("frontier_mark_done_failed_urls", []) or []),
            crawl_run_status=job.get("crawl_run_status"),
        )

    raise ValueError(f"Unsupported crawl artifact format: {path}")


def _load_artifact(path: str, label: str) -> "CrawlJobResult":
    """Load a crawl artifact, reporting a missing/unreadable file as a clean
    error instead of an uncaught traceback (ticket 123)."""
    try:
        return _load_saved_crawl(Path(path))
    except OSError as exc:
        raise ValueError(f"cannot read {label} artifact {path!r}: {exc}") from exc


async def _load_compare_side(
    *,
    json_path: str | None,
    store_dsn: str | None,
    run_id: str | None,
    side: str,
    include_html: bool = False,
) -> "list[CrawlResult] | CrawlJobResult":
    """Resolve one side of a ``compare`` from either a JSON artifact or a stored
    PostgreSQL crawl run (ticket 122).

    Passing both is rejected rather than silently preferring one (ticket 123).
    ``include_html`` is forwarded to the store loader so an active ``--replace``
    can re-hash real HTML instead of falling back to un-remapped stored hashes.
    """
    if store_dsn and json_path:
        raise ValueError(
            f"provide either a {side} JSON path or --{side}-store, not both (got {json_path!r} and a {side} store DSN)"
        )
    if store_dsn:
        store = AsyncpgStore(store_dsn)
        await store.initialize()
        try:
            resolved = await store.resolve_reporting_run_id(run_id)
            return await store.fetch_pages_for_comparison(run_id=resolved, include_html=include_html)
        finally:
            await store.close()
    if not json_path:
        raise ValueError(f"provide a {side} JSON path or --{side}-store DSN")
    return _load_artifact(json_path, side)


async def _run_compare(args: argparse.Namespace) -> int:
    # New ticket-122 flags are read via getattr so programmatic callers that
    # build a minimal Namespace keep working (existing behaviour unchanged).
    try:
        remap = Remap.from_specs(getattr(args, "replace", None))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_VALIDATION
    try:
        baseline_job = await _load_compare_side(
            json_path=args.baseline_json,
            store_dsn=_resolve_store_dsn(args, "baseline"),
            run_id=getattr(args, "baseline_run", None),
            side="baseline",
            include_html=bool(remap),
        )
        candidate_job = await _load_compare_side(
            json_path=args.candidate_json,
            store_dsn=_resolve_store_dsn(args, "candidate"),
            run_id=getattr(args, "candidate_run", None),
            side="candidate",
            include_html=bool(remap),
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_VALIDATION

    diff = compare_deep(
        baseline_job,
        candidate_job,
        compare_links=args.compare_links,
        remap=remap if remap else None,
        simhash_threshold=getattr(args, "simhash_threshold", DEFAULT_SIMHASH_THRESHOLD),
    )

    if diff.remap_fallback_paths:
        # A silently-ineffective --replace looks exactly like a clean diff, so
        # say so loudly rather than let host noise read as real change (t123).
        count = len(diff.remap_fallback_paths)
        print(
            f"Warning: --replace could not be applied to {count} page(s) — no stored HTML to re-hash, "
            "so their content verdicts use un-remapped hashes and may report host-derived noise. "
            "Re-crawl with --content-hashing (and without --no-store-html), or compare JSON artifacts.",
            file=sys.stderr,
        )
        for path in diff.remap_fallback_paths[:10]:
            print(f"  - {path}", file=sys.stderr)
        if count > 10:
            print(f"  … and {count - 10} more", file=sys.stderr)

    if args.output:
        payload = {"schema_version": COMPARE_SCHEMA_VERSION, "rows": comparison_rows(diff)}
        Path(args.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
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
        verdict_counts: dict[str, int] = {}
        for verdict in diff.content_verdicts.values():
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        print(
            json.dumps(
                {
                    "schema_version": COMPARE_SCHEMA_VERSION,
                    "missing_urls": diff.missing_urls,
                    "new_urls": diff.new_urls,
                    "title_changes": len(diff.title_changes),
                    "url_moves": len(diff.url_moves),
                    "schema_changes": len(diff.schema_changes),
                    "link_changes": len(diff.link_changes),
                    "content_verdicts": verdict_counts,
                },
                indent=2,
            )
        )
    return 0


async def _resolve_compare_urls_side(
    urls: list[str],
    *,
    side: str,
    artifact: str | None,
    store_dsn: str | None,
    run_id: str | None,
    fetch_missing: bool,
    match_final_url: bool = True,
    include_html: bool = False,
    args: argparse.Namespace,
) -> dict[str, "CrawlResult"]:
    """Resolve page data for one side of ``compare-urls`` in precedence order:
    saved JSON artifact → PostgreSQL store → live fetch (ticket 122).

    A single batched ``crawl_list`` runs for whatever remains unresolved when
    ``--fetch-missing`` is set — never one fetch per row.

    ``match_final_url=False`` (the source side) matches results by
    ``requested_url`` only: a result that merely *redirected to* a source URL
    must not stand in for a crawl of that URL, or its redirect verdict would be
    attributed to the wrong pair. The target side keeps ``final_url`` as a
    fallback, where content — not redirect behaviour — is what's compared.
    """
    wanted = list(dict.fromkeys(urls))
    wanted_set = set(wanted)
    resolved: dict[str, CrawlResult] = {}

    def _index(results: "list[CrawlResult]") -> None:
        for result in results:
            key = result.requested_url
            if key in wanted_set and key not in resolved:
                resolved[key] = result
        if not match_final_url:
            return
        for result in results:
            key = result.final_url
            if key in wanted_set and key not in resolved:
                resolved[key] = result

    if artifact:
        _index(_load_artifact(artifact, side).results)
    remaining = [url for url in wanted if url not in resolved]
    if remaining and store_dsn:
        store = AsyncpgStore(store_dsn)
        await store.initialize()
        try:
            resolved_run = await store.resolve_reporting_run_id(run_id)
            _index(
                await store.fetch_pages_for_comparison(urls=remaining, run_id=resolved_run, include_html=include_html)
            )
        finally:
            await store.close()
    remaining = [url for url in wanted if url not in resolved]
    if remaining and fetch_missing:
        # One batched crawl through the real engine — robots, throttle, backend
        # selection all apply; redirects are followed (config default) so the
        # source chain is observed rather than toggled in place (ticket 122).
        config = CrawlConfig(
            backend=args.backend,
            enable_content_hashing=True,
            same_host_only=False,
            respect_robots_txt=not args.ignore_robots,
        )
        engine = CrawlEngine(config, store=MemoryStore())
        try:
            job = await engine.crawl_list(remaining)
        finally:
            await engine.close()
        _index(job.results)
    return resolved


def _compare_urls_to_session_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Map ``compare-urls`` rows onto the comparison-session row shape so they
    can persist through the existing ``crawl_comparison_urls`` table (ticket 122;
    dedicated redirect columns are a deferred follow-up)."""
    session_rows: list[dict[str, object]] = []
    for row in rows:
        deltas = cast("dict[str, dict[str, object]]", row.get("field_deltas", {}))
        chain = cast("list[dict[str, object]]", row.get("redirect_chain", []))
        chain_text = " -> ".join(str(hop.get("url")) for hop in chain)
        verdict = str(row.get("redirect_verdict"))
        session_rows.append(
            {
                "path": row.get("source_url"),
                "baseline_url": row.get("source_final_url") or row.get("source_url"),
                "candidate_url": row.get("target_url"),
                "exists_on_baseline": row.get("source_status") is not None,
                "exists_on_candidate": row.get("target_status") is not None,
                "baseline_title": deltas.get("title", {}).get("source"),
                "candidate_title": deltas.get("title", {}).get("target"),
                "baseline_h1": deltas.get("h1", {}).get("source"),
                "candidate_h1": deltas.get("h1", {}).get("target"),
                "baseline_meta_description": deltas.get("meta_description", {}).get("source"),
                "candidate_meta_description": deltas.get("meta_description", {}).get("target"),
                "baseline_word_count": deltas.get("word_count", {}).get("source"),
                "candidate_word_count": deltas.get("word_count", {}).get("target"),
                "is_moved_content": bool(chain),
                "redirect_chain": f"{verdict}: {chain_text}" if chain_text else verdict,
                "content_verdict": row.get("content_verdict"),
                "simhash_distance": row.get("simhash_distance"),
            }
        )
    return session_rows


async def _run_compare_urls(args: argparse.Namespace) -> int:
    try:
        remap = Remap.from_specs(args.replace)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_VALIDATION
    try:
        parsed = load_url_pairs(
            args.pairs,
            source_column=args.source_column,
            target_column=args.target_column,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_VALIDATION

    if not parsed.pairs:
        print("Error: no usable source/target pairs in mapping CSV", file=sys.stderr)
        return EXIT_VALIDATION
    if parsed.skipped:
        print(f"Skipped {parsed.skipped} pair(s):", file=sys.stderr)
        for reason in parsed.skipped_reasons:
            print(f"  - {reason}", file=sys.stderr)

    try:
        source_dsn = _resolve_store_dsn(args, "source")
        target_dsn = _resolve_store_dsn(args, "target")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_VALIDATION

    try:
        source_by_url = await _resolve_compare_urls_side(
            [pair.source_url for pair in parsed.pairs],
            side="source",
            artifact=args.source_artifact,
            store_dsn=source_dsn,
            run_id=args.source_run,
            fetch_missing=args.fetch_missing,
            match_final_url=False,
            include_html=bool(remap),
            args=args,
        )
        target_by_url = await _resolve_compare_urls_side(
            [pair.target_url for pair in parsed.pairs],
            side="target",
            artifact=args.target_artifact,
            store_dsn=target_dsn,
            run_id=args.target_run,
            fetch_missing=args.fetch_missing,
            include_html=bool(remap),
            args=args,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_VALIDATION

    rows = build_pair_rows(
        parsed.pairs,
        lambda url: source_by_url.get(url),
        lambda url: target_by_url.get(url),
        remap=remap if remap else None,
        simhash_threshold=args.simhash_threshold,
    )

    if args.output:
        _write_compare_urls_output(rows, args.output)
        print(f"Wrote {len(rows)} compare-urls rows to {args.output}")

    if args.persist:
        store = _store_from_args(args)
        await store.initialize()
        try:
            session_id = await store.persist_comparison_session(
                baseline_label=args.source_label,
                candidate_label=args.target_label,
                rows=_compare_urls_to_session_rows(rows),
            )
            print(f"Persisted compare-urls session {session_id}")
        finally:
            await store.close()

    verdict_counts: dict[str, int] = {}
    for row in rows:
        key = str(row["redirect_verdict"])
        verdict_counts[key] = verdict_counts.get(key, 0) + 1
    print(
        json.dumps(
            {
                "schema_version": COMPARE_URLS_SCHEMA_VERSION,
                "pairs": len(rows),
                "redirect_verdicts": verdict_counts,
            },
            indent=2,
        )
    )

    if args.fail_on:
        failures = rows_failing(rows, args.fail_on)
        if failures:
            # Findings, not a usage error: the run completed and the data
            # failed the gate — distinct from EXIT_VALIDATION so CI callers can
            # tell "bad invocation" from "bad mapping" (ticket 3344).
            print(
                f"FAIL: {len(failures)} pair(s) tripped --fail-on {args.fail_on}",
                file=sys.stderr,
            )
            return EXIT_FINDINGS
    return 0


COMPARE_URLS_CSV_COLUMNS = [
    "source_url",
    "target_url",
    "source_status",
    "target_status",
    "source_final_url",
    "redirect_verdict",
    "redirect_hops",
    "redirect_chain",
    "sha256_equal",
    "simhash_distance",
    "content_verdict",
    "note",
]
"""Frozen CSV column order for ``compare-urls --output *.csv`` (ticket 3344).

Appending columns is allowed within ``compare-urls/1``; renaming, removing or
reordering existing columns requires a schema-version bump."""


def _format_redirect_chain(chain: list[dict[str, object]]) -> str:
    """Render hops for the CSV report as ``url (301) -> url (302)`` (ticket 123).

    Ticket 122 required the report to carry the hops; the first CSV writer
    dropped them and appended ``(N hop)`` into ``source_final_url``, which
    corrupted that column for anything consuming the URL."""
    return " -> ".join(f"{hop.get('url')} ({hop.get('status')})" for hop in chain)


def _write_compare_urls_output(rows: list[dict[str, object]], output: str) -> None:
    path = Path(output)
    if path.suffix.lower() == ".csv":
        import csv as _csv

        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = _csv.DictWriter(handle, fieldnames=COMPARE_URLS_CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                chain = cast("list[dict[str, object]]", row.get("redirect_chain", []))
                flat = {key: row.get(key) for key in COMPARE_URLS_CSV_COLUMNS}
                # URLs stay clean; hop count and the chain get their own columns.
                flat["redirect_hops"] = len(chain)
                flat["redirect_chain"] = _format_redirect_chain(chain)
                writer.writerow(flat)
    else:
        payload = {"schema_version": COMPARE_URLS_SCHEMA_VERSION, "rows": rows}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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
        queued, pending, done = await store.frontier_stats_all_runs()
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
        run_id = await store.resolve_reporting_run_id(args.crawl_run_id)
        stats = await store.run_snapshot_html_stats(run_id=run_id)
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
            print("Snapshot hashes are immutable; re-crawl the selected run to add missing hashes.", file=sys.stderr)
            return 2
        result = await store.purge_run_snapshot_html(
            run_id=run_id, drop_headers=args.drop_headers, dry_run=args.dry_run
        )
        print(json.dumps(result, indent=2))
        if args.dry_run:
            print("Dry run — HTML not purged.")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    finally:
        await store.close()
    return 0


async def _run_generate_sitemap(args: argparse.Namespace) -> int:
    from .sitemap_generate import fetch_indexable_urls, write_sitemap

    store = _store_from_args(args)
    await store.initialize()
    try:
        run_id = await store.resolve_reporting_run_id(args.crawl_run_id)
        urls = await fetch_indexable_urls(store, run_id=run_id)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    finally:
        await store.close()

    if not urls:
        print("No indexable, canonical, 200-OK URLs found — nothing to write.", file=sys.stderr)
        return 1

    written = write_sitemap(
        urls,
        args.output,
        base_url=getattr(args, "base_url", None),
        max_urls_per_file=args.max_urls_per_file,
    )
    print(f"Wrote {len(urls)} URLs to {len(written)} file(s):")
    for path in written:
        print(f"  {path}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crawler-cli",
        description="Async SEO crawler with PostgreSQL persistence",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging (shows frontier/robots/breaker detail)",
    )
    verbosity.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress INFO logs; only show warnings, errors, and final summary",
    )
    subparsers = parser.add_subparsers(dest="command")

    crawl_parser = subparsers.add_parser("crawl", help="Run a crawl")
    _add_crawl_args(crawl_parser)

    emb_parser = subparsers.add_parser(
        "generate-embeddings",
        help="Generate embeddings for crawled pages (OpenAI or local sentence-transformers)",
    )
    emb_parser.add_argument(
        "--provider",
        choices=("openai", "sentence-transformers"),
        default="openai",
        help="Embedding provider (default: openai; sentence-transformers is local, no API key)",
    )
    emb_parser.add_argument("--api-key", help="OpenAI API key (or set OPENAI_API_KEY)")
    emb_parser.add_argument(
        "--model",
        default=None,
        help="Embedding model (default: text-embedding-3-small for openai, "
        "paraphrase-multilingual-MiniLM-L12-v2 for sentence-transformers)",
    )
    emb_parser.add_argument(
        "--model-revision",
        default=None,
        help="HuggingFace model revision to pin (sentence-transformers only)",
    )
    emb_parser.add_argument(
        "--source",
        choices=("signature", "page-text"),
        default=None,
        help="Embed intent signatures or cleaned page text "
        "(default: signature for sentence-transformers, page-text for openai)",
    )
    emb_parser.add_argument(
        "--batch-size", type=positive_int, default=None, help="Batch size (default 10 openai, 64 local)"
    )
    emb_parser.add_argument(
        "--delay", type=non_negative_float, default=1.0, help="Delay between batches (seconds, openai)"
    )
    emb_parser.add_argument("--force", action="store_true", help="Regenerate existing embeddings")
    emb_parser.add_argument("--urls", nargs="*", help="Optional URL filter list")
    _add_postgres_args(emb_parser)
    _add_reporting_run_selector(emb_parser)

    sig_parser = subparsers.add_parser(
        "backfill-signatures",
        help="Compute intent signatures (trafilatura main text + unified hash) over stored HTML",
    )
    sig_parser.add_argument("--urls", nargs="*", help="Optional URL filter list")
    sig_parser.add_argument(
        "--boilerplate-share",
        type=probability,
        default=0.30,
        help="Min title share for per-site boilerplate stripping (default 0.30)",
    )
    sig_parser.add_argument(
        "--min-words",
        type=non_negative_int,
        default=50,
        help="Pages below this word count get signal_confidence=low (default 50)",
    )
    sig_parser.add_argument("--dry-run", action="store_true", help="Report counts without writing")
    _add_postgres_args(sig_parser)
    _add_reporting_run_selector(sig_parser)

    hreflang_parser = subparsers.add_parser(
        "hreflang-groups",
        help="Build hreflang alternate groups + resolve URL variants from crawler-captured edges",
    )
    _add_postgres_args(hreflang_parser)
    _add_reporting_run_selector(hreflang_parser)

    io_parser = subparsers.add_parser(
        "intent-overlap",
        help="Analyse intent overlap / de-canonicalisation risk over a crawled + embedded site",
    )
    io_parser.add_argument("--threshold", type=probability, default=0.85, help="Overlap threshold (default 0.85)")
    io_parser.add_argument(
        "--dup-threshold",
        type=probability,
        default=0.92,
        help="Duplicate / decanonicalisation threshold (default 0.92)",
    )
    io_parser.add_argument(
        "--hreflang-mode",
        choices=("suppress", "primary-only", "off"),
        default="suppress",
        help="suppress: skip intra-group pairs (default); primary-only: one page per group; off",
    )
    io_parser.add_argument("--primary-lang", default="en", help="Preferred language for primary-only mode")
    io_parser.add_argument("--no-lang-split", action="store_true", help="Compare across languages too")
    io_parser.add_argument(
        "--linkage", choices=("single", "complete"), default="single", help="Clustering linkage (default single)"
    )
    io_parser.add_argument("--out", default="./out", help="Output directory for CSV reports")
    io_parser.add_argument(
        "--thin-signature-words",
        type=non_negative_int,
        default=DEFAULT_THIN_SIGNATURE_WORDS,
        help=(
            "Pages whose signature text (title+h1+meta+extracted body) has fewer than this "
            f"many words are 'thin' (default {DEFAULT_THIN_SIGNATURE_WORDS}); a duplicate-risk page "
            "whose only high-similarity pairings are thin-vs-thin is relabelled 'thin content' "
            "instead of decanonicalisation risk. Calibrate per-site: compare pages.csv word_count "
            "(raw) against signature_words (distinguishing content)"
        ),
    )
    io_parser.add_argument(
        "--fail-on",
        choices=("duplicate", "overlap"),
        default=None,
        help="Exit non-zero when duplicate/overlap pairs exist (CI gating)",
    )
    io_parser.add_argument(
        "--ann",
        action="store_true",
        help="Use hnswlib ANN pair search above --ann-min-pages (needs the [ann] extra)",
    )
    io_parser.add_argument("--ann-min-pages", type=positive_int, default=10000, help="Page count before ANN activates")
    io_parser.add_argument("--ann-k", type=positive_int, default=128, help="hnswlib k neighbours")
    io_parser.add_argument(
        "--time-sequenced-section",
        action="append",
        dest="time_sequenced_section",
        metavar="PATH_PREFIX",
        default=None,
        help=(
            "Repeatable path prefix (e.g. /news) for a recurring-topic archive "
            "where near-duplicate pairs are usually editorially correct (QDF), "
            "not decanonicalisation candidates: intra-section pairs get a "
            "softer 'topical overlap (time-sequenced)' label and are excluded "
            "from --fail-on duplicate by default. Explicit opt-in only."
        ),
    )
    io_parser.add_argument(
        "--json-report",
        action="store_true",
        help=(
            "Also write report_data.json (pages/pairs/clusters + 2D projection "
            "coords) for interactive viewers (ticket 106). Default off."
        ),
    )
    io_parser.add_argument(
        "--json-min-similarity",
        type=float,
        default=None,
        help=(
            "When embedded page count >= 50000, omit pairs below this similarity "
            "from report_data.json (default: --threshold). Linear pages/clusters "
            "are always included."
        ),
    )
    io_parser.add_argument(
        "--projection-seed",
        type=int,
        default=42,
        help="Deterministic seed for UMAP/PCA 2D projection in report_data.json (default 42)",
    )
    io_parser.add_argument(
        "--html-report",
        action="store_true",
        help=(
            "Write report.html as well as report_data.json (implies --json-report). "
            "Self-contained offline cluster map + tables (ticket 107)."
        ),
    )
    _add_postgres_args(io_parser)
    _add_reporting_run_selector(io_parser)

    render_parser = subparsers.add_parser(
        "render-report",
        help="Render report_data.json as a self-contained offline HTML cluster report",
    )
    render_parser.add_argument(
        "--data",
        required=True,
        help="Path to report_data.json from intent-overlap --json-report",
    )
    render_parser.add_argument(
        "-o",
        "--output",
        default="report.html",
        help="Output HTML path (default: report.html)",
    )

    report_parser = subparsers.add_parser(
        "report",
        help="Print SEO audit reports (orphans, redirect chains, CWV, analytics coverage) from a stored crawl",
    )
    report_parser.add_argument(
        "reports",
        nargs="*",
        metavar="REPORT",
        help=(f"Reports to run (default: all that need no extra flags). Valid: {', '.join(_REPORT_NAMES)}"),
    )
    report_parser.add_argument(
        "--format",
        choices=("table", "json", "csv"),
        default="table",
        help="table: aligned text; json: one object keyed by report; csv: one file per report (default: table)",
    )
    report_parser.add_argument(
        "--out",
        help="Output path: a file for table/json (default stdout), a directory for csv (required)",
    )
    report_parser.add_argument(
        "--limit",
        type=non_negative_int,
        default=50,
        help="Row cap for the slowest and cwv reports (default 50)",
    )
    report_parser.add_argument(
        "--min-outlinks",
        type=non_negative_int,
        default=5,
        help="Minimum outlinks for the hub-pages report (default 5)",
    )
    report_parser.add_argument(
        "--vendor",
        help="Restrict missing-analytics to pages lacking this vendor (e.g. 'ga4')",
    )
    report_parser.add_argument(
        "--expected-id",
        help="Analytics identifier the missing-expected-id report checks for (e.g. 'G-XXXX')",
    )
    _add_postgres_args(report_parser)
    _add_reporting_run_selector(report_parser)

    cmp_parser = subparsers.add_parser(
        "compare",
        help="Compare two crawls (saved JSON artifacts or stored runs), with optional host remapping",
    )
    cmp_parser.add_argument(
        "baseline_json", nargs="?", help="Baseline crawl JSON path (omit when using --baseline-store)"
    )
    cmp_parser.add_argument(
        "candidate_json", nargs="?", help="Candidate crawl JSON path (omit when using --candidate-store)"
    )
    cmp_parser.add_argument("--baseline-label", default="baseline")
    cmp_parser.add_argument("--candidate-label", default="candidate")
    cmp_parser.add_argument("--compare-links", action="store_true")
    cmp_parser.add_argument(
        "--baseline-store",
        metavar="DSN",
        help=(
            "Load the baseline side from a PostgreSQL crawl (DSN) instead of a JSON artifact. "
            f"Prefer the environment: {store_dsn_env_vars('baseline')[0]} or --baseline-store-env"
        ),
    )
    cmp_parser.add_argument(
        "--baseline-store-env",
        metavar="VAR",
        help="Name of an environment variable holding the baseline store DSN",
    )
    cmp_parser.add_argument(
        "--candidate-store",
        metavar="DSN",
        help=(
            "Load the candidate side from a PostgreSQL crawl (DSN) instead of a JSON artifact. "
            f"Prefer the environment: {store_dsn_env_vars('candidate')[0]} or --candidate-store-env"
        ),
    )
    cmp_parser.add_argument(
        "--candidate-store-env",
        metavar="VAR",
        help="Name of an environment variable holding the candidate store DSN",
    )
    cmp_parser.add_argument("--baseline-run", metavar="RUN_ID", help="Crawl run id for --baseline-store")
    cmp_parser.add_argument("--candidate-run", metavar="RUN_ID", help="Crawl run id for --candidate-store")
    cmp_parser.add_argument(
        "--replace",
        action="append",
        default=[],
        metavar="FROM=TO",
        help="Literal FROM=TO replacement applied to text/URLs before diffing (repeatable, ordered)",
    )
    cmp_parser.add_argument(
        "--simhash-threshold",
        type=non_negative_int,
        default=DEFAULT_SIMHASH_THRESHOLD,
        help=f"Hamming distance at/under which a page is 'near' rather than 'changed' (default {DEFAULT_SIMHASH_THRESHOLD})",
    )
    cmp_parser.add_argument("--output", help="Write comparison rows JSON to this path")
    cmp_parser.add_argument("--persist", action="store_true", help="Persist comparison to PostgreSQL")
    _add_postgres_args(cmp_parser)

    urls_parser = subparsers.add_parser(
        "compare-urls",
        help="Compare mapped source->target URL pairs from a CSV and validate redirects",
    )
    urls_parser.add_argument("--pairs", required=True, metavar="CSV", help="Mapping CSV with source/target columns")
    urls_parser.add_argument(
        "--source-column", default="source_url", help="CSV source URL column (default: source_url)"
    )
    urls_parser.add_argument(
        "--target-column", default="target_url", help="CSV target URL column (default: target_url)"
    )
    urls_parser.add_argument("--source-artifact", metavar="JSON", help="Source-side crawl JSON to resolve pages from")
    urls_parser.add_argument("--target-artifact", metavar="JSON", help="Target-side crawl JSON to resolve pages from")
    urls_parser.add_argument(
        "--source-store",
        metavar="DSN",
        help=(
            "Source-side PostgreSQL crawl (DSN). Prefer the environment: "
            f"{store_dsn_env_vars('source')[0]} or --source-store-env"
        ),
    )
    urls_parser.add_argument(
        "--source-store-env",
        metavar="VAR",
        help="Name of an environment variable holding the source store DSN",
    )
    urls_parser.add_argument(
        "--target-store",
        metavar="DSN",
        help=(
            "Target-side PostgreSQL crawl (DSN). Prefer the environment: "
            f"{store_dsn_env_vars('target')[0]} or --target-store-env"
        ),
    )
    urls_parser.add_argument(
        "--target-store-env",
        metavar="VAR",
        help="Name of an environment variable holding the target store DSN",
    )
    urls_parser.add_argument("--source-run", metavar="RUN_ID", help="Crawl run id for --source-store")
    urls_parser.add_argument("--target-run", metavar="RUN_ID", help="Crawl run id for --target-store")
    urls_parser.add_argument(
        "--fetch-missing",
        action="store_true",
        help="Live-fetch any pair URL not found in an artifact/store (one batched crawl per side)",
    )
    urls_parser.add_argument(
        "--backend",
        choices=["aiohttp", "curl_cffi", "playwright"],
        default="aiohttp",
        help="Backend for --fetch-missing live fetches (default: aiohttp)",
    )
    urls_parser.add_argument("--ignore-robots", action="store_true", help="Ignore robots.txt on live fetches")
    urls_parser.add_argument(
        "--replace",
        action="append",
        default=[],
        metavar="FROM=TO",
        help="Literal FROM=TO replacement applied before content hashing (repeatable, ordered)",
    )
    urls_parser.add_argument("--simhash-threshold", type=non_negative_int, default=DEFAULT_SIMHASH_THRESHOLD)
    urls_parser.add_argument("--source-label", default="source")
    urls_parser.add_argument("--target-label", default="target")
    urls_parser.add_argument("--output", help="Write rows to this path (.csv for CSV, else JSON)")
    urls_parser.add_argument("--persist", action="store_true", help="Persist rows as a comparison session")
    urls_parser.add_argument(
        "--fail-on",
        choices=["redirect_mismatch", "content_changed", "any"],
        help="Return a non-zero exit code when any pair trips this condition (CI gate)",
    )
    _add_postgres_args(urls_parser)

    compact_html_parser = subparsers.add_parser(
        "compact-html",
        help="Gzip-compress legacy uncompressed HTML in pages.html_compressed",
    )
    compact_html_parser.add_argument("--batch-size", type=positive_int, default=500)
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
    compact_parser.add_argument("--batch-size", type=positive_int, default=500)
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
    _add_reporting_run_selector(compact_parser)

    sitemap_parser = subparsers.add_parser(
        "generate-sitemap",
        help="Generate sitemap.xml from indexable, canonical, 200-OK URLs in a crawl",
    )
    sitemap_parser.add_argument(
        "-o",
        "--output",
        default="sitemap.xml",
        help="Output path for the sitemap (default: sitemap.xml)",
    )
    sitemap_parser.add_argument(
        "--base-url",
        help="Base URL used to build child <loc>s when the sitemap is split into an index",
    )
    sitemap_parser.add_argument(
        "--max-urls-per-file",
        type=positive_int,
        default=50_000,
        help="Split into a sitemap index above this many URLs (default 50000)",
    )
    _add_postgres_args(sitemap_parser)
    _add_reporting_run_selector(sitemap_parser)

    install_parser = subparsers.add_parser(
        "install-obscura",
        help="Download the prebuilt Obscura browser binary for this platform",
    )
    install_parser.add_argument(
        "--obscura-version",
        default=None,
        help="Obscura release tag to install (default: the version pinned in crawler_cli)",
    )
    install_parser.add_argument(
        "--force",
        action="store_true",
        help="Reinstall even if Obscura is already present",
    )

    return parser


_BARE_DOMAIN_RE = None  # compiled lazily


def _looks_like_hostname(token: str) -> bool:
    """Return True if *token* looks like a bare hostname or host:port."""
    import re

    global _BARE_DOMAIN_RE
    if _BARE_DOMAIN_RE is None:
        # matches e.g. example.com, example.com/path, localhost, 192.168.1.1:8080
        _BARE_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z]{2,}|:\d+)")
    return bool(_BARE_DOMAIN_RE.match(token))


def _normalize_argv(argv: list[str]) -> list[str]:
    if not argv:
        return ["crawl"]
    if argv[0] in {
        "crawl",
        "generate-embeddings",
        "backfill-signatures",
        "hreflang-groups",
        "intent-overlap",
        "render-report",
        "report",
        "compare",
        "compare-urls",
        "compact-html",
        "delete-crawl",
        "compact-crawl",
        "generate-sitemap",
        "install-obscura",
    }:
        return argv
    if "://" in argv[0]:
        return ["crawl", *argv]
    if _looks_like_hostname(argv[0]):
        return ["crawl", f"https://{argv[0]}", *argv[1:]]
    return argv


def _run_install_obscura(args: argparse.Namespace) -> int:
    from .obscura_install import DEFAULT_OBSCURA_VERSION, install_obscura

    version = getattr(args, "obscura_version", None) or DEFAULT_OBSCURA_VERSION
    try:
        install_obscura(version, force=getattr(args, "force", False), log=print)
    except Exception as exc:  # noqa: BLE001 - surface a clean CLI error
        print(f"Error installing Obscura: {exc}", file=sys.stderr)
        return 1
    return 0


async def _dispatch(args: argparse.Namespace) -> int:
    command = args.command or "crawl"
    if command == "install-obscura":
        return _run_install_obscura(args)
    if command == "crawl":
        return await _run_crawl(args)
    if command == "generate-embeddings":
        return await _run_embeddings(args)
    if command == "backfill-signatures":
        return await _run_backfill_signatures(args)
    if command == "hreflang-groups":
        return await _run_hreflang_groups(args)
    if command == "intent-overlap":
        return await _run_intent_overlap(args)
    if command == "render-report":
        return _run_render_report(args)
    if command == "report":
        return await _run_report(args)
    if command == "compare":
        return await _run_compare(args)
    if command == "compare-urls":
        return await _run_compare_urls(args)
    if command == "compact-html":
        return await _run_compact_html(args)
    if command == "delete-crawl":
        return await _run_delete_crawl(args)
    if command == "compact-crawl":
        return await _run_compact_crawl(args)
    if command == "generate-sitemap":
        return await _run_generate_sitemap(args)
    print(f"Unknown command: {command}", file=sys.stderr)
    return 2


def main() -> None:
    argv = _normalize_argv(sys.argv[1:])
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command in {None, "crawl"} and not getattr(args, "command", None):
        args.command = "crawl"

    # Configure logging once, here in __main__ only (library code never calls
    # basicConfig so it can be used as a library without noise).
    if getattr(args, "verbose", False):
        level = logging.DEBUG
    elif getattr(args, "quiet", False):
        level = logging.WARNING
    else:
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        sys.exit(asyncio.run(_dispatch(args)))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(EXIT_VALIDATION)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
