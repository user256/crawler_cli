from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


BackendName = Literal["aiohttp", "curl_cffi", "playwright"]


@dataclass(slots=True)
class CrawlConfig:
    backend: BackendName = "aiohttp"
    user_agent: str = "crawler_cli/0.1"
    timeout_seconds: float = 30.0
    max_concurrency: int = 10
    rate_limit_per_second: float = 5.0
    follow_redirects: bool = True
    verify_ssl: bool = True
    max_response_bytes: int = 5_000_000
    respect_robots_txt: bool = True
    robots_cache_ttl_seconds: float = 3600.0
    honor_robots_crawl_delay: bool = True
    default_open_crawl_limit: int = 200
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

    @property
    def min_interval_seconds(self) -> float:
        if self.rate_limit_per_second <= 0:
            return 0.0
        return 1.0 / self.rate_limit_per_second
