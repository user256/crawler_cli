from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from .auth import AuthConfig
from .validators import (
    require_non_negative_float,
    require_non_negative_int,
    require_percentage,
    require_positive_float,
    require_positive_int,
)

if TYPE_CHECKING:
    from .portal_policy import PortalConnectionPolicy


BackendName = Literal["aiohttp", "curl_cffi", "playwright"]

# Circuit-breaker defaults, shared between CrawlConfig and the CLI's env-var
# fallback resolution in __main__._build_config. Threshold was raised from 3 to
# 15 (ticket 039 notes) so healthy-but-slow sites don't trip the breaker and
# silently discard work.
CB_ENABLED_DEFAULT = True
CB_THRESHOLD_DEFAULT = 15
CB_RECOVERY_SECONDS_DEFAULT = 30.0

# 25 MB: large enough to hold real-world Magento/WooCommerce sitemaps
# (often >5 MB) so they parse intact, while still capping runaway downloads.
# Overridable per run via the --max-response-bytes CLI flag.
MAX_RESPONSE_BYTES_DEFAULT = 25_000_000
DEFAULT_OPEN_CRAWL_LIMIT = 200


def _env_bool(name: str) -> bool | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _env_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except ValueError:
        return None


@dataclass(slots=True)
class CrawlConfig:
    backend: BackendName = "aiohttp"
    user_agent: str = "crawler_cli/0.1"
    ua_map: dict[str, str] = field(default_factory=dict)
    """Per-domain user agents (ticket 080). Keys are bare registrable domains;
    a host matches its own domain and any subdomain (``www.casino.org`` matches
    ``casino.org``). ``user_agent`` is the fallback. Threaded through every
    backend as a per-request User-Agent override."""
    refresh_days: int = 0
    """Staleness window in days (ticket 080). When > 0, URLs already fetched
    successfully (HTTP 200) within this window are skipped at enqueue time so a
    periodic re-run only refetches what has aged out. 0 refetches everything."""
    timeout_seconds: float = 30.0
    max_concurrency: int = 10
    max_requests_per_context: int = 50
    rate_limit_per_second: float = 5.0
    follow_redirects: bool = True
    verify_ssl: bool = True
    max_response_bytes: int = MAX_RESPONSE_BYTES_DEFAULT
    playwright_network_idle_timeout_seconds: float = 5.0
    playwright_wait_for_selector: str = ""
    """If set, the Playwright backend waits for this CSS selector to appear
    before snapshotting the DOM (ticket 031). Times out gracefully."""
    playwright_wait_for_selector_timeout_seconds: float = 10.0
    playwright_cdp_endpoint: str = ""
    playwright_browser_channel: str = ""
    playwright_executable_path: str = ""
    playwright_user_data_dir: str = ""
    playwright_profile_directory: str = ""
    playwright_headless: bool = True
    collect_web_vitals: bool = False
    """Capture lab Core Web Vitals (LCP/CLS/INP) via a PerformanceObserver shim
    on the Playwright backend (ticket 046). No effect on HTTP backends."""
    memory_high_watermark_percent: float = 85.0
    memory_recovery_watermark_percent: float = 70.0
    respect_robots_txt: bool = True
    robots_cache_ttl_seconds: float = 3600.0
    honor_robots_crawl_delay: bool = True
    default_open_crawl_limit: int = DEFAULT_OPEN_CRAWL_LIMIT
    same_host_only: bool = True
    enable_content_hashing: bool = False
    compress_html: bool = True
    store_html: bool = True
    circuit_breaker_enabled: bool = CB_ENABLED_DEFAULT
    circuit_breaker_failure_threshold: int = CB_THRESHOLD_DEFAULT
    circuit_breaker_recovery_seconds: float = CB_RECOVERY_SECONDS_DEFAULT
    seed_from_archive: bool = False
    archive_timeout_seconds: float = 10.0
    archive_max_urls: int = 250
    frontier_max_retries: int = 3
    frontier_retry_base_delay_seconds: float = 2.0
    request_headers: dict[str, str] = field(default_factory=dict)
    proxy: str = ""
    """Proxy URL routed through every backend, e.g. ``http://host:8080`` or
    ``socks5://host:1080``. Credentials may be embedded (``http://user:pass@host``)
    or supplied separately via ``proxy_auth`` (ticket 027)."""
    proxy_auth: str = ""
    """Optional ``user:password`` for the proxy when not embedded in ``proxy``."""
    proxies: list[str] = field(default_factory=list)
    """Pool of proxy URLs to rotate across in ``list`` mode (ticket 045). When
    non-empty this takes precedence over the single ``proxy`` for the HTTP
    backends. Each entry may carry embedded credentials; ``proxy_auth`` is not
    applied to pool entries."""
    proxy_mode: str = "list"
    """``list`` (client-side pool of distinct proxies, ticket 045) or
    ``gateway`` (a single residential rotating-gateway endpoint whose exit IP
    rotates server-side per request, ticket 072). In ``gateway`` mode the single
    ``proxy`` endpoint is used, never evicted, and retried on failure."""
    proxy_rotation: str = "round-robin"
    """list mode only: ``round-robin`` (per request) or ``per-host`` (sticky)."""
    proxy_max_failures: int = 3
    """list mode only: consecutive failures before a pool proxy is put on cooldown."""
    proxy_cooldown_seconds: float = 60.0
    """list mode only: how long an evicted pool proxy stays out of rotation."""
    proxy_gateway_max_retries: int = 2
    """gateway mode: extra retries through the gateway on a failed fetch (each
    retry gets a fresh server-side exit IP)."""
    detect_challenges: bool = True
    """Detect bot-challenge interstitials (Cloudflare/Datadome/...) and treat
    them as blocked rather than content (ticket 074)."""
    challenge_escalate_to_browser: bool = True
    """On a challenge from an HTTP backend, escalate the fetch to the
    Playwright/Obscura browser backend through a fresh IP (ticket 074)."""
    portal_connection_policy: PortalConnectionPolicy | None = None
    """Optional Portal-owned, per-connection URL policy.  It is supported only
    by the aiohttp backend and covers initial HTTP requests, redirects and
    sitemap fetches; browser navigation and live comparison remain unsupported."""
    challenge_max_escalations: int = 1
    """Max browser escalations per URL before recording it as blocked."""
    cookies: dict[str, str] = field(default_factory=dict)
    """Session cookies injected as a ``Cookie`` header on every request (ticket 028).
    Used as a fallback when ``scoped_cookies`` is empty."""
    scoped_cookies: list = field(default_factory=list)
    """Cookies (``cookies.Cookie``) with domain/path attributes retained; when
    non-empty the backends select per-request only the cookies matching the
    target URL (ticket 048). Typed as ``list`` to avoid a config→cookies import
    cycle."""
    extraction_rules: list = field(default_factory=list)
    """Custom data extraction rules (``ExtractionRule``) evaluated per HTML page;
    results land in ``CrawlResult.custom_data`` and the ``custom_data`` JSONB
    column (ticket 026). Typed as ``list`` to avoid a config→extract import cycle."""
    cms_detection: bool = False
    analytics_detection: bool = False
    skip_amp_variants: bool = False
    """When True, AMP-shaped discovered URLs (a ``/amp`` path tail or an
    ``amp=1`` query param) are not enqueued at discovery time, so no crawl
    budget is spent on them (ticket 103).  Default OFF: crawl-and-classify
    remains the default so AMP canonical-hygiene reporting keeps working."""
    analytics_expected_ids: list[str] = field(default_factory=list)
    discover_sitemaps: bool = True
    sitemap_max_urls: int = 50_000
    sitemap_max_depth: int = 3
    skip_sitemaps: bool = False
    allowed_hosts: list[str] = field(default_factory=list)
    """Additional hosts to crawl beyond the seed host(s).
    When empty and same_host_only=True, only the seed host is crawled.
    When populated, these hosts are also allowed (in addition to seeds),
    including cross-host robots.txt ``Sitemap:`` targets and their page locs.
    """
    path_restriction: str = ""
    """If set, only URLs whose path contains this substring are fetched."""
    path_exclude: list[str] = field(default_factory=list)
    """Path prefixes to skip (e.g. ``/news/``). Matched against urlparse path."""
    auth: AuthConfig | None = None
    csv_urls: list[str] = field(default_factory=list)
    csv_seed_mode: bool = False
    obscura_enabled: bool = False
    obscura_binary: str = "obscura"
    obscura_host: str = "127.0.0.1"
    obscura_port: int = 9222
    obscura_proxy: str = ""
    obscura_workers: int = 1
    obscura_managed: bool = True
    obscura_stealth: bool | None = None
    obscura_fetch_subprocess: bool = False
    """Use Obscura's one-shot ``obscura fetch`` subprocess per request instead of
    a persistent CDP browser connection. Each fetch shells out to the binary,
    which renders the page and returns HTML. Slower per page (process spawn) but
    avoids the persistent-CDP session (connect_over_cdp/goto) hanging seen in
    some sandboxes. Implies a browser/JS render; honours obscura_stealth and
    obscura_proxy. Selected via --obscura-fetch on the CLI."""
    curl_impersonate: str = ""
    """curl_cffi impersonation target, e.g. ``chrome``, ``safari``, ``firefox``.
    Empty string or ``none`` disables impersonation (ticket 053)."""
    per_host_concurrency: int = 4
    """Maximum simultaneous requests to any single host (0 = unlimited).
    Prevents the full worker pool bursting against one origin (ticket-063)."""
    keep_html_in_results: bool = False
    """Retain raw_html/extracted/discovered_links on results after persist
    during open crawls.  Off by default so long crawls stay memory-bounded
    (ticket-059); library callers that read job.results directly can opt in."""

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Raise :class:`ValueError` when numeric configuration is invalid.

        Same rules as the CLI argparse types (ticket 093): reject negatives,
        NaN/infinity, and cross-field contradictions before the engine opens
        sockets or creates ``asyncio.Semaphore`` values.
        """
        require_positive_int(self.max_concurrency, field="max_concurrency")
        require_non_negative_int(self.max_requests_per_context, field="max_requests_per_context")
        require_non_negative_int(self.refresh_days, field="refresh_days")
        require_non_negative_int(self.default_open_crawl_limit, field="default_open_crawl_limit")
        require_non_negative_int(self.per_host_concurrency, field="per_host_concurrency")
        require_positive_int(self.max_response_bytes, field="max_response_bytes")
        require_positive_float(self.timeout_seconds, field="timeout_seconds")
        require_non_negative_float(
            self.playwright_network_idle_timeout_seconds,
            field="playwright_network_idle_timeout_seconds",
        )
        require_positive_float(
            self.playwright_wait_for_selector_timeout_seconds,
            field="playwright_wait_for_selector_timeout_seconds",
        )
        require_non_negative_float(self.rate_limit_per_second, field="rate_limit_per_second")
        require_percentage(self.memory_high_watermark_percent, field="memory_high_watermark_percent")
        require_percentage(
            self.memory_recovery_watermark_percent,
            field="memory_recovery_watermark_percent",
        )
        if self.memory_recovery_watermark_percent >= self.memory_high_watermark_percent:
            raise ValueError(
                "memory_recovery_watermark_percent must be below "
                f"memory_high_watermark_percent "
                f"({self.memory_recovery_watermark_percent} >= "
                f"{self.memory_high_watermark_percent})"
            )
        require_non_negative_float(self.robots_cache_ttl_seconds, field="robots_cache_ttl_seconds")
        require_positive_int(
            self.circuit_breaker_failure_threshold,
            field="circuit_breaker_failure_threshold",
        )
        require_positive_float(
            self.circuit_breaker_recovery_seconds,
            field="circuit_breaker_recovery_seconds",
        )
        require_positive_float(self.archive_timeout_seconds, field="archive_timeout_seconds")
        require_positive_int(self.archive_max_urls, field="archive_max_urls")
        require_non_negative_int(self.frontier_max_retries, field="frontier_max_retries")
        require_non_negative_float(
            self.frontier_retry_base_delay_seconds,
            field="frontier_retry_base_delay_seconds",
        )
        require_non_negative_int(self.proxy_max_failures, field="proxy_max_failures")
        require_non_negative_float(self.proxy_cooldown_seconds, field="proxy_cooldown_seconds")
        require_non_negative_int(self.proxy_gateway_max_retries, field="proxy_gateway_max_retries")
        require_non_negative_int(self.challenge_max_escalations, field="challenge_max_escalations")
        require_positive_int(self.sitemap_max_urls, field="sitemap_max_urls")
        require_positive_int(self.sitemap_max_depth, field="sitemap_max_depth")
        require_positive_int(self.obscura_workers, field="obscura_workers")
        require_positive_int(self.obscura_port, field="obscura_port")
        if self.obscura_port > 65535:
            raise ValueError(f"obscura_port must be <= 65535, got {self.obscura_port}")
        if self.portal_connection_policy is not None:
            if self.backend != "aiohttp":
                raise ValueError("portal_connection_policy requires the aiohttp backend")
            if self.proxy or self.proxies:
                raise ValueError("portal_connection_policy cannot be combined with a proxy")
            if self.challenge_escalate_to_browser:
                raise ValueError(
                    "portal_connection_policy requires challenge_escalate_to_browser=False "
                    "because browser navigation is not guarded"
                )

    @staticmethod
    def _url_path(url: str) -> str:
        from urllib.parse import urlparse

        return urlparse(url).path or "/"

    def is_path_excluded(self, url: str) -> bool:
        path_val = self._url_path(url)
        for prefix in self.path_exclude:
            normalized = prefix if prefix.startswith("/") else f"/{prefix}"
            if path_val.startswith(normalized):
                return True
        return False

    def is_path_restricted_out(self, url: str) -> bool:
        if not self.path_restriction:
            return False
        return self.path_restriction not in self._url_path(url)

    def should_crawl_url(self, url: str) -> bool:
        """Return False when the URL is discovered but must not be fetched."""
        if self.is_path_excluded(url):
            return False
        if self.is_path_restricted_out(url):
            return False
        return True

    def user_agent_for(self, url: str) -> str:
        """Resolve the User-Agent for *url* (ticket 080). A host matches a
        ``ua_map`` domain if it equals it or is a subdomain of it; otherwise the
        default ``user_agent`` is used (intent_overlap.py make_ua_resolver:274)."""
        if not self.ua_map:
            return self.user_agent
        from urllib.parse import urlparse

        # hostname (not netloc) so an explicit port never defeats the match.
        host = (urlparse(url).hostname or "").lower()
        for domain, ua in self.ua_map.items():
            if host == domain or host.endswith("." + domain):
                return ua
        return self.user_agent

    def path_skip_detail(self, url: str) -> str:
        if self.is_path_excluded(url):
            return "path_exclude"
        if self.is_path_restricted_out(url):
            return "path_restriction"
        return ""

    def is_host_allowed(self, url: str, seeds: list[str]) -> bool:
        """Check if a URL's host is allowed given the crawl constraints."""
        from urllib.parse import urlparse

        host = urlparse(url).netloc.lower()
        seed_hosts = {urlparse(s).netloc.lower() for s in seeds}
        allowed = seed_hosts | {h.lower() for h in self.allowed_hosts}
        return host in allowed

    @property
    def min_interval_seconds(self) -> float:
        if self.rate_limit_per_second <= 0:
            return 0.0
        return 1.0 / self.rate_limit_per_second


def parse_ua_map(specs: list[str]) -> dict[str, str]:
    """Parse ``--ua DOMAIN=UA`` specs into a domain->user-agent map (ticket 080,
    intent_overlap.py parse_ua_map:286). Raises ValueError on a malformed spec."""
    ua_map: dict[str, str] = {}
    for spec in specs:
        domain, sep, ua = spec.partition("=")
        if not sep or not domain.strip() or not ua.strip():
            raise ValueError(f'--ua expects DOMAIN="User Agent", got {spec!r}')
        ua_map[domain.strip().lower()] = ua.strip()
    return ua_map
