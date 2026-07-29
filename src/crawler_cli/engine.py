from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .amp import is_amp_url_shape
from .archive import discover_historical_urls
from .backends import ObscuraFetchBackend, PlaywrightBackend, RateLimiter, build_backend
from .challenge import detect_challenge
from .circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitState
from .config import CrawlConfig
from .custom_extract import CustomExtractor
from .detection import CMSDetector, AnalyticsDetector
from .extract import extract_links, extract_page_data, parse_html
from .hashing import sha256_hash, simhash64
from .models import BrowserRuntime, CrawlJobResult, CrawlResult, DiscoveredLink, ExtractedContent
from .persistence import AsyncpgStore, MemoryStore
from .portal_policy import ConnectionPurpose
from .robots import RobotsPolicyCache
from .serialization import serialize_crawl_job, serialize_crawl_result, serialize_job_summary_metadata
from .sitemap import SitemapParser, discover_sitemap_paths

logger = logging.getLogger(__name__)

# Pages larger than this are parsed via asyncio.to_thread so the event loop
# stays responsive (tickets 060/069). ~256 KB of HTML.
_PARSE_OFFLOAD_CHARS = 262_144


def _linux_memory_usage_percent() -> float | None:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return None

    values: dict[str, int] = {}
    try:
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            parts = line.split(":", 1)
            if len(parts) != 2:
                continue
            key = parts[0].strip()
            raw_value = parts[1].strip().split()[0]
            if raw_value.isdigit():
                values[key] = int(raw_value)
    except OSError:
        return None

    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return None
    used = max(0, total - available)
    return (used / total) * 100.0


def _archive_seed_target(seed: str) -> str | None:
    """Normalise a seed URL to the host used for archive.org expansion."""
    parsed = urlparse(seed)
    target = (parsed.netloc or seed).lower().strip()
    return target or None


def _new_crawl_run_id() -> str:
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"crawl-{timestamp}-{uuid.uuid4().hex[:8]}"


def _crawl_run_config_snapshot(config: CrawlConfig, seeds: list[str]) -> dict[str, Any]:
    """Return the material run-compatibility inputs for resume validation.

    Runtime knobs such as concurrency, retry backoff, and max-pages can change
    safely across resumes. Seed and scope choices cannot: changing them would
    make a resumed frontier represent a different crawl.
    """
    return {
        "seed_urls": list(dict.fromkeys(seeds)),
        "same_host_only": config.same_host_only,
        "allowed_hosts": sorted({host.lower() for host in config.allowed_hosts}),
        "path_restriction": config.path_restriction,
        "path_exclude": sorted(config.path_exclude),
        "respect_robots_txt": config.respect_robots_txt,
        "discover_sitemaps": config.discover_sitemaps,
        "skip_sitemaps": config.skip_sitemaps,
        "seed_from_archive": config.seed_from_archive,
        "csv_seed_mode": config.csv_seed_mode,
        "csv_urls": list(dict.fromkeys(config.csv_urls)),
        # A guarded job must not be resumed by an unguarded worker.
        "portal_connection_policy": config.portal_connection_policy is not None,
    }


def _crawl_run_config_hash(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CrawlRunSelectionError(RuntimeError):
    """Invalid run selection or resume state for crawl_open()."""


class CrawlEngine:
    def __init__(self, config: CrawlConfig, store: AsyncpgStore | MemoryStore | None = None) -> None:
        self.config = config
        self.backend = build_backend(config)
        self.store = store
        self._semaphore = asyncio.Semaphore(config.max_concurrency)
        self._rate_limiter = RateLimiter(config.min_interval_seconds)
        self._robots = RobotsPolicyCache(config)
        self._host_delays: dict[str, asyncio.Lock] = {}
        self._host_last_fetch: dict[str, float] = {}
        self._host_semaphores: dict[str, asyncio.Semaphore] = {}
        self._circuit_breakers = CircuitBreakerRegistry(
            failure_threshold=config.circuit_breaker_failure_threshold,
            recovery_timeout_seconds=config.circuit_breaker_recovery_seconds,
        )
        self._cms_detector = CMSDetector() if config.cms_detection else None
        self._analytics_detector = AnalyticsDetector() if config.analytics_detection else None
        self._custom_extractor = CustomExtractor(config.extraction_rules) if config.extraction_rules else None
        self._effective_worker_limit = max(1, config.max_concurrency)
        self._stop_requested: bool = False
        # Count of URLs skipped at enqueue time by --refresh-days (ticket 080).
        self._refresh_skipped: int = 0
        # Lazily-built browser backend used to escalate challenged HTTP fetches
        # (ticket 074). Only created when an escalation actually happens.
        self._challenge_backend: PlaywrightBackend | None = None
        if 0 < config.per_host_concurrency < config.max_concurrency:
            logger.info(
                "Per-host cap %d is below max workers %d — single-host crawls are limited to "
                "%d concurrent fetches (adjust with --per-host-concurrency)",
                config.per_host_concurrency,
                config.max_concurrency,
                config.per_host_concurrency,
            )

    def request_stop(self) -> None:
        """Signal the crawl loop to drain in-flight work and exit cleanly."""
        self._stop_requested = True

    def _is_browser_backend(self, backend: object) -> bool:
        # Both render JS in a real browser, so a bot-challenge seen through
        # either is already "as good as it gets" — don't escalate further.
        return isinstance(backend, (PlaywrightBackend, ObscuraFetchBackend))

    async def _get_challenge_backend(self) -> PlaywrightBackend:
        """Lazily build a Playwright/Obscura backend for challenge escalation."""
        if self._challenge_backend is None:
            # Force a browser backend regardless of the configured one. Honour
            # Obscura if the operator configured it; otherwise plain Playwright.
            import dataclasses

            browser_config = dataclasses.replace(self.config, backend="playwright")
            self._challenge_backend = PlaywrightBackend(browser_config)
        return self._challenge_backend

    async def _handle_challenge(self, url: str, response):
        """Detect a bot-challenge interstitial and, if configured, escalate the
        fetch to the browser backend through a fresh IP (ticket 074).

        Returns (response, challenge_kind). When escalation succeeds the returned
        response is the browser's; when it still fails (or escalation is off /
        the active backend is already a browser) the original response is
        returned with the detected challenge kind recorded.
        """
        kind = detect_challenge(response.status, response.headers, response.text)
        if kind is None:
            return response, None

        # Already a browser backend, or escalation disabled → just flag it.
        if (
            self.config.portal_connection_policy is not None
            or self._is_browser_backend(self.backend)
            or not self.config.challenge_escalate_to_browser
        ):
            logger.warning("Bot challenge (%s) on %s — recorded as blocked", kind, url)
            return response, kind

        logger.info("Bot challenge (%s) on %s — escalating to browser", kind, url)
        backend = await self._get_challenge_backend()
        for _ in range(max(1, self.config.challenge_max_escalations)):
            try:
                escalated = await backend.fetch_resilient(url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Challenge escalation fetch failed for %s: %s", url, type(exc).__name__)
                break
            esc_kind = detect_challenge(escalated.status, escalated.headers, escalated.text)
            if esc_kind is None and escalated.status and escalated.status < 400:
                logger.info("Challenge cleared for %s via browser escalation", url)
                return escalated, None
            response = escalated
            kind = esc_kind or kind
        logger.warning("Bot challenge (%s) persisted on %s after escalation — blocked", kind, url)
        return response, kind

    def _record_breaker_failure(self, circuit: CircuitBreaker, host: str, trigger: str) -> None:
        """Record a failure and log the trigger if it opens the breaker."""
        was_open = circuit.state == CircuitState.OPEN
        circuit.record_failure()
        if not was_open and circuit.state == CircuitState.OPEN:
            logger.warning(
                "Circuit breaker OPEN for %s after %d failures (last trigger: %s)",
                host,
                circuit.failure_count,
                trigger,
            )

    def _parse_and_extract(
        self, html: str, url: str, headers: dict[str, str]
    ) -> tuple[ExtractedContent, list[DiscoveredLink]]:
        """Parse once and run both extraction passes on the shared soup.

        Synchronous on purpose: called inline for small pages and via
        asyncio.to_thread for large ones (tickets 060/069)."""
        soup = parse_html(html)
        extracted = extract_page_data(html, url, headers, soup=soup)
        discovered_links = extract_links(
            html,
            url,
            same_host_only=self.config.same_host_only,
            allowed_hosts=set(self.config.allowed_hosts) if self.config.allowed_hosts else None,
            soup=soup,
        )
        return extracted, discovered_links

    def _host_semaphore(self, host: str) -> asyncio.Semaphore | None:
        """Return a per-host concurrency semaphore, or None when unlimited."""
        limit = self.config.per_host_concurrency
        if limit <= 0:
            return None
        if host not in self._host_semaphores:
            self._host_semaphores[host] = asyncio.Semaphore(limit)
        return self._host_semaphores[host]

    def _skip_result(self, url: str, reason: str, *, allowed_by_robots: bool | None = None) -> CrawlResult:
        return CrawlResult(
            requested_url=url,
            final_url=url,
            status=0,
            headers={},
            content_type=None,
            fetch_backend=self.config.backend,
            extracted=None,
            raw_html=None,
            allowed_by_robots=(
                allowed_by_robots
                if allowed_by_robots is not None
                else (True if self.config.respect_robots_txt else None)
            ),
            skip_reason=reason,
        )

    async def crawl(self, url: str) -> CrawlResult:
        async with self._semaphore:
            try:
                if not self.config.should_crawl_url(url):
                    return self._skip_result(url, f"path_out_of_scope:{self.config.path_skip_detail(url)}")
                if self.config.respect_robots_txt:
                    allowed = await self._robots.is_allowed(url)
                    if not allowed:
                        return self._skip_result(url, "robots_txt_disallow", allowed_by_robots=False)
                    if self.config.honor_robots_crawl_delay:
                        await self._wait_for_host_delay(url)
                await self._rate_limiter.wait()
                host = urlparse(url).netloc.lower()
                if self.config.circuit_breaker_enabled:
                    circuit = self._circuit_breakers.for_host(host)
                    if not circuit.should_allow():
                        return self._skip_result(url, "circuit_breaker_open")
                # Per-host concurrency cap: acquired after skip-checks so
                # rejected requests don't hold slots (ticket-063).
                _host_sem = self._host_semaphore(host)
                if _host_sem is not None:
                    await _host_sem.acquire()
                try:
                    # Prefer the gateway-retry wrapper (ticket 072); fall back to
                    # plain fetch for backends that don't implement it (test fakes,
                    # external backends).
                    response = await self._fetch_for_purpose(url, "initial")
                finally:
                    if _host_sem is not None:
                        _host_sem.release()

                # Bot-challenge detection + escalate-to-browser (ticket 074).
                # Unresolved challenges hard-stop before extraction/persistence
                # of interstitial HTML as page content (ticket 089).
                challenge_kind = None
                if self.config.detect_challenges:
                    response, challenge_kind = await self._handle_challenge(url, response)
                # Case-insensitive header lookup (Playwright returns lowercase keys)
                headers_lower = {k.lower(): v for k, v in response.headers.items()}
                content_type = headers_lower.get("content-type")
                extracted = None
                raw_html = None
                content_hash_sha256 = None
                content_hash_simhash = None
                discovered_links: list[DiscoveredLink] = []
                detected_cms = None
                detected_analytics = None
                custom_data = None
                skip_reason: str | None = None
                if challenge_kind is not None:
                    # Blocked: keep fetch metadata + vendor, never treat the
                    # interstitial as extractable/crawled content.
                    skip_reason = "bot_challenge"
                elif content_type and "html" in content_type.lower():
                    raw_html = response.text
                    # Large documents are parsed in a worker thread so a
                    # multi-MB page can't stall every in-flight fetch on the
                    # event loop (tickets 060/069).
                    if len(response.text) > _PARSE_OFFLOAD_CHARS:
                        extracted, discovered_links = await asyncio.to_thread(
                            self._parse_and_extract, response.text, response.url, response.headers
                        )
                    else:
                        extracted, discovered_links = self._parse_and_extract(
                            response.text, response.url, response.headers
                        )
                    if self.config.enable_content_hashing:
                        content_hash_sha256 = sha256_hash(response.text)
                        content_hash_simhash = simhash64(response.text)

                    # Perform CMS detection if enabled and this is HTML content
                    if self._cms_detector is not None:
                        detected_cms = self._cms_detector.detect(response)

                    # Perform analytics detection if enabled and this is HTML content
                    if self._analytics_detector is not None:
                        detected_analytics = self._analytics_detector.detect(response)

                    # Evaluate custom extraction rules if configured
                    if self._custom_extractor is not None:
                        custom_data = self._custom_extractor.extract(response.text)

                browser_runtime = self._build_browser_runtime()
                result = CrawlResult(
                    requested_url=response.requested_url,
                    final_url=response.url,
                    status=response.status,
                    headers=response.headers,
                    content_type=content_type,
                    fetch_backend=self.config.backend,
                    extracted=extracted,
                    raw_html=raw_html,
                    content_hash_sha256=content_hash_sha256,
                    content_hash_simhash=content_hash_simhash,
                    discovered_links=discovered_links,
                    allowed_by_robots=True if self.config.respect_robots_txt else None,
                    skip_reason=skip_reason,
                    challenge=challenge_kind,
                    detected_cms=detected_cms,
                    detected_analytics=detected_analytics,
                    browser_runtime=browser_runtime,
                    ttfb_seconds=response.ttfb_seconds,
                    total_duration_seconds=response.elapsed_seconds,
                    custom_data=custom_data,
                    lcp_ms=response.lcp_ms,
                    cls=response.cls,
                    inp_ms=response.inp_ms,
                    redirect_chain=response.redirect_chain,
                )
                if self.config.circuit_breaker_enabled:
                    circuit = self._circuit_breakers.for_host(host)
                    if response.status >= 500 or response.status == 429:
                        self._record_breaker_failure(circuit, host, f"http_{response.status}")
                    else:
                        circuit.record_success()
            except Exception as exc:
                host = urlparse(url).netloc.lower()
                logger.warning("fetch_error for %s: %s: %s", url, type(exc).__name__, exc)
                if self.config.circuit_breaker_enabled:
                    circuit = self._circuit_breakers.for_host(host)
                    self._record_breaker_failure(circuit, host, f"fetch_error:{type(exc).__name__}")
                return self._skip_result(url, f"fetch_error:{type(exc).__name__}")
            # Persist OUTSIDE the fetch try-block: a database error must never
            # masquerade as a fetch error or discard a successfully-fetched page.
            if self.store is not None:
                await self._persist_with_retry(result)
            return result

    async def _persist_with_retry(self, result: CrawlResult, *, max_attempts: int = 5) -> None:
        """Persist a fetched page, retrying on transient write contention.

        Concurrent persists can hit PostgreSQL deadlocks / serialization
        failures on shared lookup-table upserts. We back off and retry; on final
        failure we record ``persist_error`` on the result rather than losing the
        page (its fetched data is still returned and saved)."""
        import asyncpg

        assert self.store is not None
        for attempt in range(max_attempts):
            try:
                await self.store.persist(result)
                return
            except (asyncpg.DeadlockDetectedError, asyncpg.SerializationError) as exc:
                if attempt + 1 >= max_attempts:
                    result.persist_error = type(exc).__name__
                    logger.warning(
                        "Persist failed for %s after %d attempts: %s — page data retained",
                        result.final_url,
                        max_attempts,
                        result.persist_error,
                        extra={
                            "event": "persist_error",
                            "url": result.final_url,
                            "persist_error": result.persist_error,
                            "attempts": max_attempts,
                        },
                    )
                    return
                await asyncio.sleep(0.05 * (2**attempt))
            except Exception as exc:  # noqa: BLE001 - persistence must not lose the page
                result.persist_error = type(exc).__name__
                logger.warning(
                    "Persist failed for %s: %s — page data retained in results",
                    result.final_url,
                    result.persist_error,
                    extra={
                        "event": "persist_error",
                        "url": result.final_url,
                        "persist_error": result.persist_error,
                    },
                )
                return

    async def crawl_many(self, urls: Iterable[str], *, save_to: str | None = None) -> list[CrawlResult]:
        """Crawl *urls* with a continuous worker pool (ticket-061).

        Results are returned in input order regardless of completion order.
        The worker limit shrinks under memory pressure via _current_worker_limit().
        """
        url_list = list(urls)
        if not url_list:
            return []
        # Slot results by original index to preserve input order.
        ordered: list[CrawlResult | None] = [None] * len(url_list)
        in_flight: dict[asyncio.Task, int] = {}  # task → url_list index
        pending_indices = list(range(len(url_list)))

        while pending_indices or in_flight:
            # Honour request_stop(): drain in-flight, schedule nothing new
            # (ticket-069, parity with crawl_open's ticket-064 behaviour).
            if not self._stop_requested:
                fill_n = max(0, self._current_worker_limit() - len(in_flight))
                while fill_n > 0 and pending_indices:
                    idx = pending_indices.pop(0)
                    task = asyncio.create_task(self.crawl(url_list[idx]))
                    in_flight[task] = idx
                    fill_n -= 1

            if not in_flight:
                break

            done, _ = await asyncio.wait(set(in_flight.keys()), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                idx = in_flight.pop(task)
                ordered[idx] = task.result()

        results = [r for r in ordered if r is not None]
        if save_to:
            await self._save_results(
                CrawlJobResult(mode="list", seed_urls=url_list, results=results, interrupted=self._stop_requested),
                save_to,
            )
        return results

    async def _enqueue_frontier(
        self,
        frontier_data: list,
        *,
        source: str | None = None,
        source_detail: str | None = None,
    ) -> int:
        """Enqueue frontier rows, applying the --refresh-days staleness filter
        (ticket 080). URLs already fetched successfully within the window are
        dropped and counted, so a periodic re-run only refetches what aged out.
        """
        if self.config.refresh_days > 0 and frontier_data and self.store is not None:
            import time as _time

            cutoff = int(_time.time()) - self.config.refresh_days * 86400
            fresh = await self.store.urls_fetched_since([item[0] for item in frontier_data], cutoff)
            if fresh:
                before = len(frontier_data)
                frontier_data = [item for item in frontier_data if item[0] not in fresh]
                self._refresh_skipped += before - len(frontier_data)
        if not frontier_data or self.store is None:
            return 0
        return await self.store.enqueue_frontier(frontier_data, source=source, source_detail=source_detail)

    async def crawl_list(self, urls: Iterable[str], *, save_to: str | None = None) -> CrawlJobResult:
        seed_urls = list(urls)
        self._log_browser_runtime()
        results = await self.crawl_many(seed_urls, save_to=None)
        job = CrawlJobResult(
            mode="list",
            seed_urls=seed_urls,
            results=results,
            saved_to=save_to,
            interrupted=self._stop_requested,
        )
        if job.persist_error_count:
            logger.warning(
                "Crawl persistence incomplete: %d failure(s), durability=%s, urls=%s",
                job.persist_error_count,
                job.durability,
                job.persist_failed_urls[:20],
                extra={
                    "event": "persist_summary",
                    "persist_error_count": job.persist_error_count,
                    "persist_failed_urls": job.persist_failed_urls,
                    "durability": job.durability,
                },
            )
        if save_to:
            await self._save_results(job, save_to)
        return job

    def _sitemap_url_reject_reason(
        self,
        url: str,
        seeds: list[str],
        *,
        check_path: bool = True,
    ) -> str | None:
        """Return a provenance detail when *url* must not be fetched/enqueued.

        Rejects unsupported schemes, malformed URLs, credential-bearing URLs,
        host-scope violations, and (when *check_path*) path exclusions
        (ticket 087).
        """
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            if parsed.scheme and parsed.scheme not in {"http", "https"}:
                return "unsupported_scheme"
            return "malformed_url"
        if parsed.username is not None or parsed.password is not None:
            return "credential_url"
        if self.config.same_host_only and not self.config.is_host_allowed(url, seeds):
            return "host_out_of_scope"
        if check_path and not self.config.should_crawl_url(url):
            return self.config.path_skip_detail(url) or "path_out_of_scope"
        return None

    async def _bounded_fetch_response(self, url: str):
        """Fetch *url* under the same politeness controls as page crawls.

        Honours global concurrency, crawl-delay, rate limiting, per-host
        concurrency, circuit breaking, resilient/proxy retries, response
        caps (via the backend), and challenge handling (ticket 087).
        Returns None when the fetch is skipped or fails.
        """
        from .models import FetchResponse

        async with self._semaphore:
            try:
                if self.config.respect_robots_txt and self.config.honor_robots_crawl_delay:
                    await self._wait_for_host_delay(url)
                await self._rate_limiter.wait()
                host = urlparse(url).netloc.lower()
                if self.config.circuit_breaker_enabled:
                    circuit = self._circuit_breakers.for_host(host)
                    if not circuit.should_allow():
                        logger.info("Skipping sitemap fetch for %s: circuit_breaker_open", url)
                        return None
                host_sem = self._host_semaphore(host)
                if host_sem is not None:
                    await host_sem.acquire()
                try:
                    response = await self._fetch_for_purpose(url, "sitemap")
                finally:
                    if host_sem is not None:
                        host_sem.release()

                challenge_kind = None
                if self.config.detect_challenges:
                    response, challenge_kind = await self._handle_challenge(url, response)
                if challenge_kind is not None:
                    logger.warning(
                        "Skipping sitemap fetch for %s: bot challenge (%s)",
                        url,
                        challenge_kind,
                    )
                    if self.config.circuit_breaker_enabled:
                        circuit = self._circuit_breakers.for_host(host)
                        self._record_breaker_failure(circuit, host, f"challenge:{challenge_kind}")
                    return None

                if self.config.circuit_breaker_enabled:
                    circuit = self._circuit_breakers.for_host(host)
                    if response.status >= 500 or response.status == 429:
                        self._record_breaker_failure(circuit, host, f"http_{response.status}")
                    else:
                        circuit.record_success()
                return response if isinstance(response, FetchResponse) else None
            except Exception as exc:
                host = urlparse(url).netloc.lower()
                logger.warning("sitemap fetch_error for %s: %s: %s", url, type(exc).__name__, exc)
                if self.config.circuit_breaker_enabled:
                    circuit = self._circuit_breakers.for_host(host)
                    self._record_breaker_failure(circuit, host, f"fetch_error:{type(exc).__name__}")
                return None

    async def _fetch_for_purpose(self, url: str, purpose: ConnectionPurpose):
        """Route guarded call sites through the Portal-aware backend API."""
        if self.config.portal_connection_policy is not None:
            fetch_for_purpose = getattr(self.backend, "fetch_for_purpose", None)
            if fetch_for_purpose is None:
                raise RuntimeError("Portal connection policy requires a policy-aware backend")
            return await fetch_for_purpose(url, purpose)
        fetch_resilient = getattr(self.backend, "fetch_resilient", None)
        if fetch_resilient is not None:
            return await fetch_resilient(url)
        return await self.backend.fetch(url)

    async def _remaining_frontier_budget(self, limit: int) -> int | None:
        """Return remaining run-global frontier slots, or None when unlimited."""
        if limit <= 0 or self.store is None:
            return None
        queued_count, pending_count, done_count = await self.store.frontier_stats()
        return max(0, limit - (queued_count + pending_count + done_count))

    async def _record_sitemap_rejects(self, rejects: list[tuple[str, str]]) -> None:
        """Record rejected sitemap URLs as provenance without consuming frontier budget."""
        if not rejects or self.store is None:
            return
        # Preserve first-seen detail per URL.
        by_url: dict[str, str] = {}
        for url, detail in rejects:
            by_url.setdefault(url, detail)
        await self.store.record_sources_bulk(list(by_url.items()), source="sitemap")

    async def _discover_and_enqueue_sitemaps(
        self,
        seeds: list[str],
        limit: int,
    ) -> list[tuple[str, int, str | None, float]]:
        """Fetch robots.txt + well-known sitemaps, parse them, enqueue URLs.

        Applies the same host-scope, URL-safety, frontier-budget, and
        politeness controls as ordinary link discovery (ticket 087).
        """
        sitemap_urls: list[tuple[str, str]] = []
        parser = SitemapParser()
        rejects: list[tuple[str, str]] = []
        for seed in seeds:
            # 1. robots.txt sitemap directives
            robots_sitemaps = await self._robots.sitemaps(seed)
            for sm in robots_sitemaps:
                sitemap_urls.append((sm, "robots_sitemap"))
            # 2. well-known paths
            for candidate in discover_sitemap_paths(seed):
                sitemap_urls.append((candidate, "sitemap"))

        # Deduplicate while preserving order; drop out-of-scope sitemap docs
        # before any fetch (ticket 087).
        seen: set[str] = set()
        unique_sitemaps: list[tuple[str, str]] = []
        for sm_url, source_kind in sitemap_urls:
            if sm_url in seen:
                continue
            seen.add(sm_url)
            reason = self._sitemap_url_reject_reason(sm_url, seeds, check_path=False)
            if reason is not None:
                rejects.append((sm_url, reason))
                continue
            unique_sitemaps.append((sm_url, source_kind))

        all_page_urls: list[tuple[str, str]] = []  # (url, detail=sitemap_url)
        # Count page locs once across all sitemap documents before applying the
        # frontier budget. A sitemap index can repeat a shard and individual
        # urlsets commonly repeat locs; letting those duplicates into
        # ``all_page_urls`` would spend slots that the frontier later rejects.
        seen_page_urls: set[str] = set()
        hreflang_data: list[tuple[str, list]] = []  # (page_url, hreflang_links)
        page_budget = await self._remaining_frontier_budget(limit)

        # BFS over sitemap indexes — fetch each level's shards concurrently
        # rather than one at a time to speed up large sitemap hierarchies
        # (ticket-065). Fetches go through the bounded request path (ticket 087).
        current_level = [(sm_url, source_kind, 0) for sm_url, source_kind in unique_sitemaps]
        fetched: set[str] = set()
        while current_level:
            if page_budget is not None and len(all_page_urls) >= page_budget:
                break
            # Filter out already-fetched or too-deep items.
            to_fetch_now = [
                (sm_url, source_kind, depth)
                for sm_url, source_kind, depth in current_level
                if sm_url not in fetched and depth <= self.config.sitemap_max_depth
            ]
            for sm_url, _, _ in to_fetch_now:
                fetched.add(sm_url)
            if not to_fetch_now:
                break

            # Fetch all shards at this BFS level concurrently.
            fetch_limit = max(1, self._current_worker_limit())
            next_level: list[tuple[str, str, int]] = []

            from .models import FetchResponse as _FetchResponse

            async def _fetch_one(
                sm_url: str, source_kind: str, depth: int
            ) -> tuple[str, str, int, _FetchResponse | None]:
                response = await self._bounded_fetch_response(sm_url)
                return (sm_url, source_kind, depth, response)

            # Process in bounded batches to respect worker limit.
            for i in range(0, len(to_fetch_now), fetch_limit):
                if page_budget is not None and len(all_page_urls) >= page_budget:
                    break
                batch = to_fetch_now[i : i + fetch_limit]
                batch_results = await asyncio.gather(*[_fetch_one(sm_url, sk, depth) for sm_url, sk, depth in batch])
                for sm_url, source_kind, depth, response in batch_results:
                    if response is None or response.status != 200:
                        continue
                    try:
                        doc = parser.parse(sm_url, response.body, response.headers.get("Content-Type"))
                    except Exception as exc:
                        # A single malformed/truncated sitemap must not abort the
                        # whole crawl; skip it and continue with the others.
                        logger.warning("Skipping unparseable sitemap %s: %s", sm_url, exc)
                        continue
                    if doc.kind == "sitemap_index":
                        for child in doc.children:
                            if child in fetched:
                                continue
                            reason = self._sitemap_url_reject_reason(child, seeds, check_path=False)
                            if reason is not None:
                                rejects.append((child, reason))
                                continue
                            next_level.append((child, source_kind, depth + 1))
                    else:
                        for su in doc.urls[: self.config.sitemap_max_urls]:
                            reason = self._sitemap_url_reject_reason(su.loc, seeds, check_path=True)
                            if reason is not None:
                                rejects.append((su.loc, reason))
                                continue
                            if su.loc in seen_page_urls:
                                continue
                            seen_page_urls.add(su.loc)
                            if page_budget is not None and len(all_page_urls) >= page_budget:
                                break
                            all_page_urls.append((su.loc, sm_url))
                            if su.hreflang_links:
                                kept_hreflang = []
                                for hl in su.hreflang_links:
                                    hl_reason = self._sitemap_url_reject_reason(hl.href, seeds, check_path=True)
                                    if hl_reason is not None:
                                        rejects.append((hl.href, hl_reason))
                                        continue
                                    kept_hreflang.append(hl)
                                if kept_hreflang:
                                    hreflang_data.append((su.loc, kept_hreflang))

            current_level = next_level

        await self._record_sitemap_rejects(rejects)

        # Enqueue under the active run's remaining frontier budget (ticket 087).
        frontier_data: list[tuple[str, int, str | None, float]] = [
            (url, 0, None, self._priority_score(url, 0)) for url, _sm_url in all_page_urls
        ]
        remaining = await self._remaining_frontier_budget(limit)
        if remaining is not None:
            frontier_data = frontier_data[:remaining]
        enqueued_urls = {item[0] for item in frontier_data}

        if frontier_data:
            await self._enqueue_frontier(
                frontier_data,
                source="sitemap",
                source_detail=None,
            )
            in_scope_pairs = [(url, sm_url) for url, sm_url in all_page_urls if url in enqueued_urls]
            if in_scope_pairs:
                await self.store.record_sources_bulk(in_scope_pairs, source="sitemap")

        # Persist hreflang from sitemap in one bulk call (ticket-065).
        if hreflang_data and self.store is not None:
            await self.store.persist_sitemap_hreflang_bulk(hreflang_data)

        return frontier_data

    def _log_browser_runtime(self) -> None:
        runtime = self._build_browser_runtime()
        if runtime is None:
            logger.info("JS backend: none (HTTP backend)")
            return
        logger.info("JS backend: %s", runtime.provider)
        if runtime.cdp_endpoint:
            logger.info("CDP endpoint: %s", runtime.cdp_endpoint)
        if runtime.provider == "obscura":
            stealth = "unknown" if runtime.stealth is None else ("enabled" if runtime.stealth else "disabled")
            logger.info("Stealth: %s", stealth)
            logger.info("Managed process: %s", "yes" if runtime.managed else "no")

    async def _prepare_crawl_run(
        self,
        seeds: list[str],
        *,
        run_id: str | None,
        resume: bool,
        allow_run_config_mismatch: bool,
    ) -> tuple[str, dict[str, Any], str]:
        if self.store is None:
            raise RuntimeError("crawl_open requires a frontier store")
        selected_run_id = run_id or _new_crawl_run_id()
        if resume and not run_id:
            raise RuntimeError("resume requires an explicit crawl run id")

        snapshot = _crawl_run_config_snapshot(self.config, seeds)
        config_hash = _crawl_run_config_hash(snapshot)
        set_active = getattr(self.store, "set_active_crawl_run", None)
        get_run = getattr(self.store, "get_crawl_run", None)
        create_run = getattr(self.store, "create_crawl_run", None)
        update_status = getattr(self.store, "update_crawl_run_status", None)

        existing_run = await get_run(selected_run_id) if get_run is not None else None
        if resume:
            if existing_run is None and get_run is not None:
                raise CrawlRunSelectionError(f"crawl run not found: {selected_run_id}")
            stored_hash = str(existing_run.get("config_hash", "")) if isinstance(existing_run, dict) else ""
            if stored_hash and stored_hash != config_hash and not allow_run_config_mismatch:
                raise CrawlRunSelectionError(
                    "crawl run config mismatch; use --allow-run-config-mismatch only if you intend to "
                    f"resume {selected_run_id} with different seeds/scope/config"
                )
            if stored_hash and stored_hash != config_hash:
                logger.warning("Resuming crawl run %s despite seed/scope/config mismatch", selected_run_id)
            if set_active is not None:
                set_active(selected_run_id)
            if update_status is not None:
                await update_status(selected_run_id, "running")
            logger.info("Resuming crawl run %s", selected_run_id)
            return selected_run_id, snapshot, config_hash

        if existing_run is not None:
            raise CrawlRunSelectionError(
                f"crawl run already exists: {selected_run_id}; choose a new --crawl-run-id or use --resume"
            )
        if create_run is not None:
            try:
                await create_run(
                    selected_run_id,
                    seed_urls=seeds,
                    config_hash=config_hash,
                    config=snapshot,
                    status="running",
                )
            except ValueError as exc:
                raise CrawlRunSelectionError(str(exc)) from exc
        elif set_active is not None:
            set_active(selected_run_id)
        logger.info("Starting crawl run %s", selected_run_id)
        return selected_run_id, snapshot, config_hash

    async def _set_crawl_run_status(self, run_id: str, status: str) -> None:
        if self.store is None:
            return
        update_status = getattr(self.store, "update_crawl_run_status", None)
        if update_status is not None:
            await update_status(run_id, status)

    async def crawl_open(
        self,
        seed_urls: Iterable[str],
        *,
        max_urls: int | None = None,
        save_to: str | None = None,
        run_id: str | None = None,
        resume: bool = False,
        allow_run_config_mismatch: bool = False,
    ) -> CrawlJobResult:
        if self.store is None:
            raise RuntimeError("crawl_open requires a frontier store")
        if self.config.csv_urls and not self.config.csv_seed_mode:
            return await self.crawl_list(self.config.csv_urls, save_to=save_to)
        limit = max_urls if max_urls is not None else self.config.default_open_crawl_limit
        if limit > 0:
            logger.info("Open crawl limit: %d URLs", limit)
        else:
            logger.info("Open crawl limit: unlimited (0)")
        seeds = list(seed_urls)
        if self.config.csv_urls and self.config.csv_seed_mode:
            seeds = list(dict.fromkeys([*self.config.csv_urls, *seeds]))
        if self.config.seed_from_archive:
            archive_candidates: list[str] = []
            archive_targets = list(
                dict.fromkeys(target for seed in seeds if (target := _archive_seed_target(seed)) is not None)
            )
            for archive_target in archive_targets:
                archive_candidates.extend(await discover_historical_urls(archive_target, self.config))
            seeds = list(dict.fromkeys([*seeds, *archive_candidates]))

        def _open_crawl_metadata(job: CrawlJobResult | None = None) -> dict[str, object]:
            payload: dict[str, object] = {
                "seed_urls": seeds,
                "max_urls": limit,
                "same_host_only": self.config.same_host_only,
                "respect_robots_txt": self.config.respect_robots_txt,
                "path_restriction": self.config.path_restriction,
                "path_exclude": self.config.path_exclude,
            }
            if job is not None:
                payload.update(serialize_job_summary_metadata(job, saved_to=save_to))
            return payload

        if not seeds:
            job = CrawlJobResult(mode="open", seed_urls=[], results=[], saved_to=save_to, max_urls=limit, run_id=run_id)
            await self.store.save_metadata("crawl_open", _open_crawl_metadata(job))
            if save_to:
                await self._save_results(job, save_to)
            return job
        crawl_run_id, run_snapshot, run_config_hash = await self._prepare_crawl_run(
            seeds,
            run_id=run_id,
            resume=resume,
            allow_run_config_mismatch=allow_run_config_mismatch,
        )
        results: list[CrawlResult] = []
        # Open the JSONL output file early so results stream out incrementally
        # rather than buffering the whole crawl in RAM (ticket-059).
        _jsonl_fh = None
        if save_to:
            _out_path = Path(save_to)
            _out_path.parent.mkdir(parents=True, exist_ok=True)
            _jsonl_fh = _out_path.open("w", encoding="utf-8")
        self._log_browser_runtime()
        await self.store.save_metadata(
            "crawl_open",
            {
                "run_id": crawl_run_id,
                "resume": resume,
                "seed_urls": seeds,
                "max_urls": limit,
                "same_host_only": self.config.same_host_only,
                "respect_robots_txt": self.config.respect_robots_txt,
                "path_restriction": self.config.path_restriction,
                "path_exclude": self.config.path_exclude,
                "config_hash": run_config_hash,
                "compatibility_config": run_snapshot,
            },
        )
        queued_count, pending_count, done_count = await self.store.frontier_stats()
        logger.info(
            "Crawl run %s frontier before start: %d queued, %d pending, %d done",
            crawl_run_id,
            queued_count,
            pending_count,
            done_count,
        )

        if not resume:
            # Fresh crawl: enqueue seeds (record out-of-scope seeds without fetching)
            seed_enqueue = [
                (url, 0, None, self._priority_score(url, 0)) for url in seeds if self.config.should_crawl_url(url)
            ]
            seed_skip = [url for url in seeds if not self.config.should_crawl_url(url)]
            if seed_skip:
                await self._record_out_of_scope_urls(seed_skip, source="seed", detail="path_out_of_scope")
            if seed_enqueue:
                await self._enqueue_frontier(seed_enqueue, source="seed")
            if self.config.discover_sitemaps and not self.config.skip_sitemaps:
                await self._discover_and_enqueue_sitemaps(seeds, limit)
        else:
            # Resume: reset stale pending items back to queued
            reset_count = await self.store.frontier_reset_all_pending_to_queued()
            if reset_count:
                logger.info("Resumed crawl run %s: reset %d pending URLs to queued", crawl_run_id, reset_count)

        session_crawled = 0
        session_retry_attempts = 0
        frontier_mark_done_failed_urls: list[str] = []
        # in_flight maps task → (url, depth, parent_url, retry_count)
        in_flight: dict[asyncio.Task, tuple[str, int, str | None, int]] = {}

        async def _flush_completed(
            done: set[asyncio.Task],
        ) -> None:
            nonlocal session_crawled
            nonlocal session_retry_attempts
            nonlocal _jsonl_fh
            nonlocal frontier_mark_done_failed_urls
            discovered_to_enqueue: list[tuple[str, int, str | None, float]] = []
            out_of_scope_discovered: list[str] = []
            done_urls: list[str] = []
            # Persist failures stay pending so resume can retry the write
            # (ticket 092). Do not mark them done.
            persist_failed_urls: list[str] = []

            for task in done:
                item = in_flight.pop(task)
                url, depth, _parent_url, retry_count = item
                result: CrawlResult = task.result()

                transient_error = result.status in {429, 500, 502, 503, 504} or (
                    result.skip_reason is not None and "Timeout" in result.skip_reason
                )
                if transient_error and retry_count < self.config.frontier_max_retries:
                    # Don't count this attempt in results or budget — it will
                    # be retried and the final outcome will be counted then
                    # (ticket-062).
                    session_retry_attempts += 1
                    delay = self.config.frontier_retry_base_delay_seconds * (2**retry_count)
                    await self.store.frontier_mark_retry(url, retry_count + 1, delay)
                    continue

                results.append(result)
                session_crawled += 1
                if result.persist_error is not None:
                    persist_failed_urls.append(url)
                else:
                    done_urls.append(url)
                # Stream every appended result — including skips — so the
                # JSONL file is a complete record and its summary counts
                # reconcile with its lines (ticket-068).  Retried attempts
                # never reach this point and stay out of the file.
                if _jsonl_fh is not None:
                    _jsonl_fh.write(json.dumps(serialize_crawl_result(result), ensure_ascii=False) + "\n")
                if result.skip_reason is not None:
                    continue
                for link in result.discovered_links:
                    if self.config.same_host_only and not self.config.is_host_allowed(link.href, seeds):
                        continue
                    if self.config.skip_amp_variants and is_amp_url_shape(link.href):
                        # --skip-amp-variants: don't spend crawl budget fetching
                        # AMP URL shapes (ticket 103).  They're still recorded as
                        # discovered-but-out-of-scope so provenance is preserved.
                        out_of_scope_discovered.append(link.href)
                        continue
                    if self.config.should_crawl_url(link.href):
                        discovered_to_enqueue.append(
                            (link.href, depth + 1, url, self._priority_score(link.href, depth + 1))
                        )
                    else:
                        out_of_scope_discovered.append(link.href)
                if result.extracted is not None:
                    for hl in result.extracted.hreflang_links:
                        href = hl.href
                        if self.config.same_host_only and not self.config.is_host_allowed(href, seeds):
                            continue
                        if self.config.should_crawl_url(href):
                            discovered_to_enqueue.append((href, depth + 1, url, self._priority_score(href, depth + 1)))
                        else:
                            out_of_scope_discovered.append(href)
                # Release bulk fields once links are consumed and the result
                # is already streamed to disk; Postgres has the full content
                # so holding it in RAM serves nothing (ticket-059).  Library
                # callers can opt out via keep_html_in_results (ticket-069).
                if not self.config.keep_html_in_results:
                    result.raw_html = None
                    result.extracted = None
                    result.discovered_links = []

            if out_of_scope_discovered:
                await self._record_out_of_scope_urls(
                    list(dict.fromkeys(out_of_scope_discovered)),
                    source="link",
                    detail="path_out_of_scope",
                )
            if discovered_to_enqueue:
                # Enqueuing discovered links must never crash the crawl. Under heavy
                # concurrency the urls/frontier upserts can still exhaust the
                # deadlock retries; if so, log and continue — these links will be
                # rediscovered when sibling pages are crawled (the page itself is
                # already persisted and marked done below).
                try:
                    if limit <= 0:
                        await self._enqueue_frontier(discovered_to_enqueue, source="link")
                    else:
                        queued_count, pending_count, done_count = await self.store.frontier_stats()
                        remaining_frontier_budget = max(0, limit - (queued_count + pending_count + done_count))
                        if remaining_frontier_budget > 0:
                            await self._enqueue_frontier(
                                discovered_to_enqueue[:remaining_frontier_budget], source="link"
                            )
                except Exception as exc:  # noqa: BLE001 - link enqueue is best-effort
                    logger.warning(
                        "Failed to enqueue %d discovered links (%s) — they will be rediscovered from sibling pages",
                        len(discovered_to_enqueue),
                        type(exc).__name__,
                    )
            if persist_failed_urls:
                logger.warning(
                    "Leaving %d URL(s) pending after persist failure for resume: %s",
                    len(persist_failed_urls),
                    persist_failed_urls[:10],
                    extra={
                        "event": "persist_frontier_pending",
                        "count": len(persist_failed_urls),
                        "urls": persist_failed_urls,
                    },
                )
            if done_urls:
                # A successful persist followed by mark-done failure must stay
                # resumable (pending → queued on --resume), not silently lost
                # (ticket 092).
                try:
                    await self.store.frontier_mark_done(done_urls)
                except Exception as exc:  # noqa: BLE001 - keep frontier resumable
                    frontier_mark_done_failed_urls.extend(done_urls)
                    logger.warning(
                        "frontier_mark_done failed for %d URL(s) after persist (%s) — leaving pending for resume",
                        len(done_urls),
                        type(exc).__name__,
                        extra={
                            "event": "frontier_mark_done_error",
                            "count": len(done_urls),
                            "urls": done_urls,
                            "error": type(exc).__name__,
                        },
                    )

        interrupted = False
        try:
            while True:
                # Stop flag set externally (e.g. SIGINT handler in __main__):
                # drain in-flight work but don't pick up new URLs (ticket-064).
                if self._stop_requested:
                    interrupted = True
                    if not in_flight:
                        break
                    done, _ = await asyncio.wait(set(in_flight.keys()), return_when=asyncio.FIRST_COMPLETED)
                    await _flush_completed(done)
                    continue

                # How many more slots can we fill?
                worker_limit = self._current_worker_limit()
                if limit > 0:
                    remaining = limit - session_crawled - len(in_flight)
                    if remaining <= 0 and not in_flight:
                        break
                    fill_n = max(0, min(worker_limit - len(in_flight), remaining if remaining > 0 else 0))
                else:
                    fill_n = max(0, worker_limit - len(in_flight))

                if fill_n > 0:
                    frontier_batch = await self.store.frontier_next_batch(fill_n)
                    path_skipped: list[str] = []
                    for item in frontier_batch:
                        url = item[0]
                        if self.config.should_crawl_url(url):
                            task = asyncio.create_task(self.crawl(url))
                            in_flight[task] = item
                        else:
                            path_skipped.append(url)
                    if path_skipped:
                        await self._record_out_of_scope_urls(path_skipped, source="link", detail="path_out_of_scope")

                if not in_flight:
                    # Nothing queued and nothing running — crawl is complete.
                    break

                # Wait for at least one task to finish before refilling.
                done, _ = await asyncio.wait(set(in_flight.keys()), return_when=asyncio.FIRST_COMPLETED)
                await _flush_completed(done)

            # limit == 0 means "unlimited"; results[:0] would wrongly drop everything.
            job = CrawlJobResult(
                mode="open",
                seed_urls=seeds,
                results=results if limit <= 0 else results[:limit],
                saved_to=save_to,
                max_urls=limit,
                run_id=crawl_run_id,
                retry_attempts=session_retry_attempts,
                interrupted=interrupted,
                refresh_skipped_count=self._refresh_skipped,
                frontier_mark_done_failed_urls=frontier_mark_done_failed_urls,
            )
            if interrupted:
                logger.warning("Crawl interrupted: %d URLs crawled before stop", session_crawled)
            if job.persist_error_count:
                logger.warning(
                    "Crawl persistence incomplete: %d failure(s), durability=%s, urls=%s",
                    job.persist_error_count,
                    job.durability,
                    job.persist_failed_urls[:20],
                    extra={
                        "event": "persist_summary",
                        "persist_error_count": job.persist_error_count,
                        "persist_failed_urls": job.persist_failed_urls,
                        "durability": job.durability,
                    },
                )
            if job.frontier_mark_done_error_count:
                logger.warning(
                    "Crawl frontier bookkeeping incomplete: %d URL(s) pending for --resume: %s",
                    job.frontier_mark_done_error_count,
                    job.frontier_mark_done_failed_urls[:20],
                    extra={
                        "event": "frontier_mark_done_summary",
                        "frontier_mark_done_error_count": job.frontier_mark_done_error_count,
                        "frontier_mark_done_failed_urls": job.frontier_mark_done_failed_urls,
                    },
                )
            crawl_run_status = (
                "interrupted"
                if interrupted
                else "complete_with_errors"
                if job.persist_error_count or job.frontier_mark_done_error_count
                else "complete"
            )
            job.crawl_run_status = crawl_run_status
            await self._set_crawl_run_status(crawl_run_id, crawl_run_status)
            if _jsonl_fh is not None:
                # Append a summary record as the last line so tooling can
                # detect a complete crawl and read aggregate counts without
                # re-scanning all result lines (ticket-059 / ticket-092).
                summary = {
                    "__type": "summary",
                    "mode": job.mode,
                    "run_id": job.run_id,
                    "seed_urls": job.seed_urls,
                    "max_urls": job.max_urls,
                    **serialize_job_summary_metadata(job, saved_to=save_to),
                }
                _jsonl_fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
                _jsonl_fh.close()
                _jsonl_fh = None
            await self.store.save_metadata(
                "crawl_open",
                {
                    **_open_crawl_metadata(job),
                    "run_id": crawl_run_id,
                    "resume": resume,
                    "config_hash": run_config_hash,
                    "compatibility_config": run_snapshot,
                },
            )
            return job
        except Exception:
            await self._set_crawl_run_status(crawl_run_id, "failed")
            raise
        finally:
            if _jsonl_fh is not None:
                _jsonl_fh.close()
            await self.close()

    async def close(self) -> None:
        # Tear down the lazily-built challenge-escalation backend too (ticket 074).
        if self._challenge_backend is not None:
            with contextlib.suppress(Exception):
                await self._challenge_backend.close()
            self._challenge_backend = None
        close = getattr(self.backend, "close", None)
        if close is None:
            return
        await close()

    async def __aenter__(self) -> CrawlEngine:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def _wait_for_host_delay(self, url: str) -> None:
        host = urlparse(url).netloc.lower()
        delay = await self._robots.get_crawl_delay(url)
        if not delay or delay <= 0:
            return
        lock = self._host_delays.setdefault(host, asyncio.Lock())
        async with lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            last_fetch = self._host_last_fetch.get(host, 0.0)
            sleep_for = delay - (now - last_fetch)
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
                now = loop.time()
            self._host_last_fetch[host] = now

    def _same_host(self, a: str, b: str) -> bool:
        return urlparse(a).netloc.lower() == urlparse(b).netloc.lower()

    def _is_host_allowed(self, url: str, seeds: list[str]) -> bool:
        """Check if URL's host is allowed for crawling."""
        return self.config.is_host_allowed(url, seeds)

    async def _record_out_of_scope_urls(
        self,
        urls: list[str],
        *,
        source: str,
        detail: str,
    ) -> None:
        if not urls or self.store is None:
            return
        unique_urls = list(dict.fromkeys(urls))
        pairs = [(url, self.config.path_skip_detail(url) or detail) for url in unique_urls]
        await self.store.record_sources_bulk(pairs, source=source)
        await self.store.frontier_mark_done(unique_urls)

    async def _save_results(self, job: CrawlJobResult, save_to: str) -> None:
        payload = serialize_crawl_job(job, saved_to=save_to)
        path = Path(save_to)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _sample_memory_usage_percent(self) -> float | None:
        return _linux_memory_usage_percent()

    def _current_worker_limit(self) -> int:
        threshold = self.config.memory_high_watermark_percent
        if threshold <= 0:
            return max(1, self.config.max_concurrency)

        usage_percent = self._sample_memory_usage_percent()
        if usage_percent is None:
            return self._effective_worker_limit

        recovery = min(threshold, self.config.memory_recovery_watermark_percent)
        if usage_percent >= threshold and self._effective_worker_limit > 1:
            self._effective_worker_limit -= 1
        elif usage_percent <= recovery and self._effective_worker_limit < self.config.max_concurrency:
            self._effective_worker_limit += 1
        return self._effective_worker_limit

    def _build_browser_runtime(self) -> BrowserRuntime | None:
        if self.config.backend != "playwright":
            return None
        if self.config.obscura_enabled:
            effective_stealth = self.config.obscura_stealth
            if effective_stealth is None and self.config.obscura_managed and not self.config.analytics_detection:
                effective_stealth = True
            return BrowserRuntime(
                provider="obscura",
                cdp_endpoint=f"http://{self.config.obscura_host}:{self.config.obscura_port}",
                managed=self.config.obscura_managed,
                stealth=effective_stealth,
            )
        if self.config.playwright_cdp_endpoint:
            return BrowserRuntime(
                provider="cdp",
                cdp_endpoint=self.config.playwright_cdp_endpoint,
                managed=None,
                stealth=None,
                persistent=None,
                channel=None,
                executable_path=None,
                user_data_dir=None,
                profile_directory=None,
                headless=None,
            )
        return BrowserRuntime(
            provider="chromium",
            cdp_endpoint=None,
            managed=None,
            stealth=None,
            persistent=bool(self.config.playwright_user_data_dir),
            channel=self.config.playwright_browser_channel or None,
            executable_path=self.config.playwright_executable_path or None,
            user_data_dir=self.config.playwright_user_data_dir or None,
            profile_directory=self.config.playwright_profile_directory or None,
            headless=self.config.playwright_headless,
        )

    def _result_to_dict(self, result: CrawlResult) -> dict[str, object]:
        return serialize_crawl_result(result)

    def _priority_score(self, url: str, depth: int) -> float:
        parsed = urlparse(url)
        path_segments = [segment for segment in parsed.path.split("/") if segment]
        score = 100.0
        score -= depth * 5.0
        score -= len(path_segments) * 2.0
        if parsed.query:
            score -= 10.0
        if parsed.path.endswith((".jpg", ".png", ".pdf", ".zip")):
            score -= 20.0
        return score
