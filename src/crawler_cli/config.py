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
    from .authorisation import ScopePredicate, ScopePurpose
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
# Run-wide network budgets are opt-in.  A zero value is deliberately distinct
# from --max-pages: the latter limits frontier URLs, whereas these limits guard
# every budget-aware request attempt and all response bodies it reads.
MAX_REQUESTS_DEFAULT = 0
MAX_BYTES_DEFAULT = 0

# Static JavaScript URL discovery is deliberately bounded independently from
# ordinary page fetches.  The byte default mirrors Googlebot's documented
# per-resource fetch limit, but this crawler treats it as a scan cap rather
# than claiming exact Googlebot parity.
MAX_JAVASCRIPT_BYTES_DEFAULT = 2_000_000
MAX_JAVASCRIPT_FILES_PER_PAGE_DEFAULT = 20
MAX_JAVASCRIPT_CANDIDATES_PER_PAGE_DEFAULT = 500
MAX_CSS_BYTES_DEFAULT = 2_000_000
MAX_CSS_FILES_PER_PAGE_DEFAULT = 20
MAX_CSS_CANDIDATES_PER_PAGE_DEFAULT = 500
MAX_CSS_IMPORT_DEPTH_DEFAULT = 1
MAX_OUTSTANDING_SPECULATIVE_PER_HOST_DEFAULT = 50
MAX_RENDER_DISCOVERY_PAGES_DEFAULT = 20
MAX_RENDER_REQUESTS_PER_PAGE_DEFAULT = 1000
MAX_RENDER_LINKS_PER_PAGE_DEFAULT = 500


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
    max_requests: int = MAX_REQUESTS_DEFAULT
    """Maximum network requests in one run (0 = unlimited)."""
    max_bytes: int = MAX_BYTES_DEFAULT
    """Aggregate response-body bytes for one run (0 = unlimited).

    Enforced only for the Portal-policy aiohttp path. It charges the larger of
    streamed HTTP wire bytes and decoded bytes, rather than reserving the full
    per-response cap before a request is emitted.
    """
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
    discover_javascript_urls: bool = False
    """Inventory static URL-like string literals in inline and linked JS.

    Discovery is evidence-only by default: candidates are serialized and
    persisted but never enter the crawl frontier unless
    ``follow_javascript_urls`` is also enabled.
    """
    follow_javascript_urls: bool = False
    """Enqueue strict, page-like JavaScript URL candidates in open crawls."""
    max_javascript_files_per_page: int = MAX_JAVASCRIPT_FILES_PER_PAGE_DEFAULT
    max_javascript_bytes: int = MAX_JAVASCRIPT_BYTES_DEFAULT
    max_javascript_candidates_per_page: int = MAX_JAVASCRIPT_CANDIDATES_PER_PAGE_DEFAULT
    javascript_relative_base: Literal["document", "document-and-asset"] = "document"
    discover_css_urls: bool = False
    """Inventory URL tokens from inline and bounded linked CSS."""
    discover_style_attributes: bool = False
    """Include style attributes in CSS discovery; implies discover_css_urls."""
    follow_speculative_urls: bool = False
    """Follow strict page-like JS/CSS candidates in open crawls."""
    max_css_files_per_page: int = MAX_CSS_FILES_PER_PAGE_DEFAULT
    max_css_bytes: int = MAX_CSS_BYTES_DEFAULT
    max_css_candidates_per_page: int = MAX_CSS_CANDIDATES_PER_PAGE_DEFAULT
    max_css_import_depth: int = MAX_CSS_IMPORT_DEPTH_DEFAULT
    max_outstanding_speculative_per_host: int = MAX_OUTSTANDING_SPECULATIVE_PER_HOST_DEFAULT
    discover_render_urls: bool = False
    """Capture browser network and hydrated-DOM URL evidence."""
    capture_render_baseline: bool = False
    """Retain the bounded pre-hydration main-document HTML on an in-memory
    result. Used by the render-parity audit; ordinary crawl artifacts do not
    serialize this second document body."""
    follow_rendered_links: bool = False
    """Follow hydrated-only anchor deltas in open crawls."""
    render_discovery_max_raw_links: int = 4
    render_discovery_min_scripts: int = 3
    max_render_discovery_pages: int = MAX_RENDER_DISCOVERY_PAGES_DEFAULT
    max_render_discovery_concurrency: int = 1
    max_render_requests_per_page: int = MAX_RENDER_REQUESTS_PER_PAGE_DEFAULT
    max_render_links_per_page: int = MAX_RENDER_LINKS_PER_PAGE_DEFAULT
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
    scope_predicate: ScopePredicate | None = None
    """The one compiled authorisation-scope predicate for this run (ticket 148).

    ``None`` means no scope manifest is active, which is the ordinary
    technical-SEO crawl: behaviour is exactly as it was before ticket 148. When
    a manifest is active, every URL admission decision in this class consults
    this single predicate, and the engine calls it again at the redirect
    boundary. Nothing else re-derives origin or path scope."""

    def __post_init__(self) -> None:
        if self.follow_javascript_urls:
            self.discover_javascript_urls = True
        if self.discover_style_attributes:
            self.discover_css_urls = True
        if self.follow_speculative_urls:
            self.discover_javascript_urls = True
            self.discover_css_urls = True
        if self.follow_rendered_links:
            self.discover_render_urls = True
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
        require_non_negative_int(self.max_requests, field="max_requests")
        require_non_negative_int(self.max_bytes, field="max_bytes")
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
        require_non_negative_int(
            self.max_javascript_files_per_page,
            field="max_javascript_files_per_page",
        )
        require_positive_int(self.max_javascript_bytes, field="max_javascript_bytes")
        require_positive_int(
            self.max_javascript_candidates_per_page,
            field="max_javascript_candidates_per_page",
        )
        if self.javascript_relative_base not in {"document", "document-and-asset"}:
            raise ValueError(
                "javascript_relative_base must be 'document' or 'document-and-asset', "
                f"got {self.javascript_relative_base!r}"
            )
        require_non_negative_int(self.max_css_files_per_page, field="max_css_files_per_page")
        require_positive_int(self.max_css_bytes, field="max_css_bytes")
        require_positive_int(self.max_css_candidates_per_page, field="max_css_candidates_per_page")
        require_non_negative_int(self.max_css_import_depth, field="max_css_import_depth")
        require_non_negative_int(
            self.max_outstanding_speculative_per_host,
            field="max_outstanding_speculative_per_host",
        )
        require_non_negative_int(
            self.render_discovery_max_raw_links,
            field="render_discovery_max_raw_links",
        )
        require_non_negative_int(self.render_discovery_min_scripts, field="render_discovery_min_scripts")
        require_non_negative_int(self.max_render_discovery_pages, field="max_render_discovery_pages")
        require_positive_int(
            self.max_render_discovery_concurrency,
            field="max_render_discovery_concurrency",
        )
        require_positive_int(self.max_render_requests_per_page, field="max_render_requests_per_page")
        require_positive_int(self.max_render_links_per_page, field="max_render_links_per_page")
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
            if self.discover_render_urls:
                raise ValueError(
                    "portal_connection_policy cannot be combined with render URL discovery; "
                    "browser subrequests are not policy-guarded"
                )
        if self.max_requests or self.max_bytes:
            if self.backend != "aiohttp" or self.portal_connection_policy is None:
                raise ValueError(
                    "max_requests/max_bytes require the Portal-policy aiohttp path; "
                    "other backends cannot truthfully guard every network request"
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

    def scope_denial_reason(
        self,
        url: str,
        *,
        purpose: ScopePurpose = "discovered",
        method: str = "GET",
    ) -> str | None:
        """Return the scope skip reason for *url*, or None when it is in scope.

        This is the only place in the configuration layer that consults the
        compiled authorisation predicate (ticket 148). When no scope manifest is
        active it returns None immediately and ordinary crawling is unaffected.
        """
        if self.scope_predicate is None:
            return None
        return self.scope_predicate.decide(url, purpose=purpose, method=method).skip_reason

    def url_admission_reason(
        self,
        url: str,
        *,
        purpose: ScopePurpose = "discovered",
    ) -> str | None:
        """Return why *url* must not be fetched, or None when it is admissible.

        This is the shared admission decision for every URL class the engine
        handles. Local path flags are evaluated first because they are the
        cheaper and more specific answer, then the authorisation-scope predicate
        is consulted. Both are narrowing-only, so their order does not change
        which URLs are admitted, only which reason is reported.
        """
        if self.is_path_excluded(url):
            return "path_exclude"
        if self.is_path_restricted_out(url):
            return "path_restriction"
        return self.scope_denial_reason(url, purpose=purpose)

    def should_crawl_url(self, url: str) -> bool:
        """Return False when the URL is discovered but must not be fetched."""
        return self.url_admission_reason(url) is None

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
        """Return the provenance detail for a URL that was not admitted.

        The empty string means the URL was admissible, which keeps the existing
        ``path_skip_detail(url) or fallback`` call pattern working unchanged.
        """
        return self.url_admission_reason(url) or ""

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
