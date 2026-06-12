from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlparse

from .archive import discover_historical_urls
from .backends import RateLimiter, build_backend
from .circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitState
from .config import CrawlConfig
from .custom_extract import CustomExtractor
from .detection import CMSDetector, AnalyticsDetector
from .extract import extract_links, extract_page_data, parse_html
from .hashing import sha256_hash, simhash64
from .models import BrowserRuntime, CrawlJobResult, CrawlResult
from .persistence import AsyncpgStore
from .robots import RobotsPolicyCache
from .serialization import serialize_crawl_job, serialize_crawl_result
from .sitemap import SitemapParser, discover_sitemap_paths

logger = logging.getLogger(__name__)


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


class CrawlEngine:
    def __init__(self, config: CrawlConfig, store: AsyncpgStore | None = None) -> None:
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
        self._custom_extractor = (
            CustomExtractor(config.extraction_rules) if config.extraction_rules else None
        )
        self._effective_worker_limit = max(1, config.max_concurrency)
        self._stop_requested: bool = False

    def request_stop(self) -> None:
        """Signal the crawl loop to drain in-flight work and exit cleanly."""
        self._stop_requested = True

    def _record_breaker_failure(self, circuit: CircuitBreaker, host: str, trigger: str) -> None:
        """Record a failure and log the trigger if it opens the breaker."""
        was_open = circuit.state == CircuitState.OPEN
        circuit.record_failure()
        if not was_open and circuit.state == CircuitState.OPEN:
            logger.warning(
                "Circuit breaker OPEN for %s after %d failures (last trigger: %s)",
                host, circuit.failure_count, trigger,
            )

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
                    response = await self.backend.fetch(url)
                finally:
                    if _host_sem is not None:
                        _host_sem.release()
                # Case-insensitive header lookup (Playwright returns lowercase keys)
                headers_lower = {k.lower(): v for k, v in response.headers.items()}
                content_type = headers_lower.get("content-type")
                extracted = None
                raw_html = None
                content_hash_sha256 = None
                content_hash_simhash = None
                discovered_links = []
                detected_cms = None
                detected_analytics = None
                custom_data = None
                if content_type and "html" in content_type.lower():
                    raw_html = response.text
                    # Parse once and share the soup across all extraction
                    # steps to avoid redundant parses (ticket-060).
                    _soup = parse_html(response.text)
                    extracted = extract_page_data(response.text, response.url, response.headers, soup=_soup)
                    if self.config.enable_content_hashing:
                        content_hash_sha256 = sha256_hash(response.text)
                        content_hash_simhash = simhash64(response.text)
                    discovered_links = extract_links(
                        response.text,
                        response.url,
                        same_host_only=self.config.same_host_only,
                        allowed_hosts=set(self.config.allowed_hosts) if self.config.allowed_hosts else None,
                        soup=_soup,
                    )

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
                    detected_cms=detected_cms,
                    detected_analytics=detected_analytics,
                    browser_runtime=browser_runtime,
                    ttfb_seconds=response.ttfb_seconds,
                    total_duration_seconds=response.elapsed_seconds,
                    custom_data=custom_data,
                )
                if self.config.circuit_breaker_enabled:
                    circuit = self._circuit_breakers.for_host(host)
                    if response.status >= 500 or response.status == 429:
                        self._record_breaker_failure(circuit, host, f"http_{response.status}")
                    else:
                        circuit.record_success()
            except Exception as exc:
                host = urlparse(url).netloc.lower()
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
                        result.final_url, max_attempts, result.persist_error,
                    )
                    return
                await asyncio.sleep(0.05 * (2**attempt))
            except Exception as exc:  # noqa: BLE001 - persistence must not lose the page
                result.persist_error = type(exc).__name__
                logger.warning(
                    "Persist failed for %s: %s — page data retained in results",
                    result.final_url, result.persist_error,
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
            await self._save_results(CrawlJobResult(mode="list", seed_urls=url_list, results=results), save_to)
        return results

    async def crawl_list(self, urls: Iterable[str], *, save_to: str | None = None) -> CrawlJobResult:
        seed_urls = list(urls)
        self._log_browser_runtime()
        results = await self.crawl_many(seed_urls, save_to=None)
        job = CrawlJobResult(mode="list", seed_urls=seed_urls, results=results, saved_to=save_to)
        if save_to:
            await self._save_results(job, save_to)
        return job

    async def _discover_and_enqueue_sitemaps(
        self,
        seeds: list[str],
        limit: int,
    ) -> list[tuple[str, int, str | None, float]]:
        """Fetch robots.txt + well-known sitemaps, parse them, enqueue URLs."""
        sitemap_urls: list[tuple[str, str]] = []
        parser = SitemapParser()
        for seed in seeds:
            # 1. robots.txt sitemap directives
            robots_sitemaps = await self._robots.sitemaps(seed)
            for sm in robots_sitemaps:
                sitemap_urls.append((sm, "robots_sitemap"))
            # 2. well-known paths
            for candidate in discover_sitemap_paths(seed):
                sitemap_urls.append((candidate, "sitemap"))

        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_sitemaps: list[tuple[str, str]] = []
        for sm_url, source_kind in sitemap_urls:
            if sm_url in seen:
                continue
            seen.add(sm_url)
            unique_sitemaps.append((sm_url, source_kind))

        all_page_urls: list[tuple[str, str]] = []  # (url, detail=sitemap_url)
        hreflang_data: list[tuple[str, list]] = []  # (sitemap_url, hreflang_links)

        # BFS over sitemap indexes — fetch each level's shards concurrently
        # rather than one at a time to speed up large sitemap hierarchies
        # (ticket-065).
        current_level = [(sm_url, source_kind, 0) for sm_url, source_kind in unique_sitemaps]
        fetched: set[str] = set()
        while current_level:
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
                try:
                    response = await self.backend.fetch(sm_url)
                    return (sm_url, source_kind, depth, response)
                except Exception:
                    return (sm_url, source_kind, depth, None)

            # Process in bounded batches to respect worker limit.
            for i in range(0, len(to_fetch_now), fetch_limit):
                batch = to_fetch_now[i : i + fetch_limit]
                batch_results = await asyncio.gather(
                    *[_fetch_one(sm_url, sk, depth) for sm_url, sk, depth in batch]
                )
                for sm_url, source_kind, depth, response in batch_results:
                    if response is None or response.status != 200:
                        continue
                    doc = parser.parse(sm_url, response.body, response.headers.get("Content-Type"))
                    if doc.kind == "sitemap_index":
                        for child in doc.children:
                            if child not in fetched:
                                next_level.append((child, source_kind, depth + 1))
                    else:
                        for su in doc.urls[:self.config.sitemap_max_urls]:
                            all_page_urls.append((su.loc, sm_url))
                            if su.hreflang_links:
                                hreflang_data.append((su.loc, su.hreflang_links))

            current_level = next_level

        # Enqueue and persist hreflang
        frontier_data: list[tuple[str, int, str | None, float]] = []
        out_of_scope: list[str] = []
        for url, sm_url in all_page_urls:
            if self.config.should_crawl_url(url):
                frontier_data.append((url, 0, None, self._priority_score(url, 0)))
            else:
                out_of_scope.append(url)

        if out_of_scope:
            await self._record_out_of_scope_urls(out_of_scope, source="sitemap", detail="path_out_of_scope")

        if frontier_data:
            await self.store.enqueue_frontier(
                frontier_data,
                source="sitemap",
                source_detail=None,
            )
            # Record source detail for all in-scope URLs in one bulk call.
            in_scope_pairs = [
                (url, sm_url)
                for url, sm_url in all_page_urls
                if self.config.should_crawl_url(url)
            ]
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

    async def crawl_open(
        self,
        seed_urls: Iterable[str],
        *,
        max_urls: int | None = None,
        save_to: str | None = None,
    ) -> CrawlJobResult:
        if self.store is None:
            raise RuntimeError("crawl_open requires an AsyncpgStore for resumable DB-driven frontier management")
        if self.config.csv_urls and not self.config.csv_seed_mode:
            return await self.crawl_list(self.config.csv_urls, save_to=save_to)
        seeds = list(seed_urls)
        if self.config.csv_urls and self.config.csv_seed_mode:
            seeds = list(dict.fromkeys([*self.config.csv_urls, *seeds]))
        if self.config.seed_from_archive:
            archive_candidates: list[str] = []
            archive_targets = list(
                dict.fromkeys(
                    target
                    for seed in seeds
                    if (target := _archive_seed_target(seed)) is not None
                )
            )
            for archive_target in archive_targets:
                archive_candidates.extend(await discover_historical_urls(archive_target, self.config))
            seeds = list(dict.fromkeys([*seeds, *archive_candidates]))
        if not seeds:
            job = CrawlJobResult(mode="open", seed_urls=[], results=[], saved_to=save_to)
            if save_to:
                await self._save_results(job, save_to)
            return job
        limit = max_urls if max_urls is not None else self.config.default_open_crawl_limit
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
                "seed_urls": seeds,
                "max_urls": limit,
                "same_host_only": self.config.same_host_only,
                "respect_robots_txt": self.config.respect_robots_txt,
                "path_restriction": self.config.path_restriction,
                "path_exclude": self.config.path_exclude,
            },
        )
        # Check if this is a resume (frontier already has items from previous run)
        queued_count, pending_count, done_count = await self.store.frontier_stats()
        is_resume = (queued_count + pending_count + done_count) > 0

        if not is_resume:
            # Fresh crawl: enqueue seeds (record out-of-scope seeds without fetching)
            seed_enqueue = [
                (url, 0, None, self._priority_score(url, 0))
                for url in seeds
                if self.config.should_crawl_url(url)
            ]
            seed_skip = [url for url in seeds if not self.config.should_crawl_url(url)]
            if seed_skip:
                await self._record_out_of_scope_urls(seed_skip, source="seed", detail="path_out_of_scope")
            if seed_enqueue:
                await self.store.enqueue_frontier(seed_enqueue, source="seed")
            if self.config.discover_sitemaps and not self.config.skip_sitemaps:
                await self._discover_and_enqueue_sitemaps(seeds, limit)
        else:
            # Resume: reset stale pending items back to queued
            reset_count = await self.store.frontier_reset_all_pending_to_queued()
            if reset_count:
                logger.info("Resumed crawl: reset %d pending URLs to queued", reset_count)

        session_crawled = 0
        session_retry_attempts = 0
        # in_flight maps task → (url, depth, parent_url, retry_count)
        in_flight: dict[asyncio.Task, tuple[str, int, str | None, int]] = {}

        async def _flush_completed(
            done: set[asyncio.Task],
        ) -> None:
            nonlocal session_crawled
            nonlocal session_retry_attempts
            nonlocal _jsonl_fh
            discovered_to_enqueue: list[tuple[str, int, str | None, float]] = []
            out_of_scope_discovered: list[str] = []
            done_urls: list[str] = []

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
                done_urls.append(url)
                if result.skip_reason is not None:
                    continue
                for link in result.discovered_links:
                    if self.config.same_host_only and not self.config.is_host_allowed(link.href, seeds):
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
                # Stream the result to disk immediately while data is still
                # present, then release bulk fields to bound RSS (ticket-059).
                if _jsonl_fh is not None:
                    _jsonl_fh.write(json.dumps(serialize_crawl_result(result), ensure_ascii=False) + "\n")
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
                if limit <= 0:
                    await self.store.enqueue_frontier(discovered_to_enqueue, source="link")
                else:
                    queued_count, pending_count, done_count = await self.store.frontier_stats()
                    remaining_frontier_budget = max(0, limit - (queued_count + pending_count + done_count))
                    if remaining_frontier_budget > 0:
                        await self.store.enqueue_frontier(
                            discovered_to_enqueue[:remaining_frontier_budget], source="link"
                        )
            if done_urls:
                await self.store.frontier_mark_done(done_urls)

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
                        await self._record_out_of_scope_urls(
                            path_skipped, source="link", detail="path_out_of_scope"
                        )

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
                retry_attempts=session_retry_attempts,
                interrupted=interrupted,
            )
            if interrupted:
                logger.warning("Crawl interrupted: %d URLs crawled before stop", session_crawled)
            if _jsonl_fh is not None:
                # Append a summary record as the last line so tooling can
                # detect a complete crawl and read aggregate counts without
                # re-scanning all result lines (ticket-059).
                summary = {
                    "__type": "summary",
                    "mode": job.mode,
                    "seed_urls": job.seed_urls,
                    "crawled_count": job.crawled_count,
                    "blocked_count": job.blocked_count,
                    "persist_error_count": job.persist_error_count,
                    "retry_attempts": job.retry_attempts,
                    "interrupted": job.interrupted,
                    "saved_to": save_to,
                }
                _jsonl_fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
                _jsonl_fh.close()
                _jsonl_fh = None
            return job
        finally:
            if _jsonl_fh is not None:
                _jsonl_fh.close()
            await self.close()

    async def close(self) -> None:
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
            if (
                effective_stealth is None
                and self.config.obscura_managed
                and not self.config.analytics_detection
            ):
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
            )
        return BrowserRuntime(
            provider="chromium",
            cdp_endpoint=None,
            managed=None,
            stealth=None,
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
