from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .auth import AuthConfig


BackendName = Literal["aiohttp", "curl_cffi", "playwright"]


@dataclass(slots=True)
class CrawlConfig:
    backend: BackendName = "aiohttp"
    user_agent: str = "crawler_cli/0.1"
    timeout_seconds: float = 30.0
    max_concurrency: int = 10
    max_requests_per_context: int = 50
    rate_limit_per_second: float = 5.0
    follow_redirects: bool = True
    verify_ssl: bool = True
    max_response_bytes: int = 5_000_000
    playwright_network_idle_timeout_seconds: float = 5.0
    memory_high_watermark_percent: float = 85.0
    memory_recovery_watermark_percent: float = 70.0
    respect_robots_txt: bool = True
    robots_cache_ttl_seconds: float = 3600.0
    honor_robots_crawl_delay: bool = True
    default_open_crawl_limit: int = 0
    max_pages: int = 0
    same_host_only: bool = True
    enable_content_hashing: bool = False
    circuit_breaker_enabled: bool = True
    circuit_breaker_failure_threshold: int = 3
    circuit_breaker_recovery_seconds: float = 30.0
    seed_from_archive: bool = False
    archive_timeout_seconds: float = 10.0
    archive_max_urls: int = 250
    frontier_max_retries: int = 3
    frontier_retry_base_delay_seconds: float = 2.0
    request_headers: dict[str, str] = field(default_factory=dict)
    cms_detection: bool = False
    discover_sitemaps: bool = True
    sitemap_max_urls: int = 50_000
    sitemap_max_depth: int = 3
    skip_sitemaps: bool = False
    allowed_hosts: list[str] = field(default_factory=list)
    """Additional hosts to crawl beyond the seed host(s). 
    When empty and same_host_only=True, only the seed host is crawled.
    When populated, these hosts are also allowed (in addition to seeds).
    """
    path_restriction: str = ""
    """If set, only URLs whose path contains this substring are fetched."""
    path_exclude: list[str] = field(default_factory=list)
    """Path prefixes to skip (e.g. ``/news/``). Matched against urlparse path."""
    auth: AuthConfig | None = None
    csv_urls: list[str] = field(default_factory=list)
    csv_seed_mode: bool = False

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
