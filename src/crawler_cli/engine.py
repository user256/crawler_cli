from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlparse

from .archive import discover_historical_urls
from .backends import RateLimiter, build_backend
from .circuit_breaker import CircuitBreakerRegistry
from .config import CrawlConfig
from .detection import CMSDetector
from .extract import extract_links, extract_page_data
from .hashing import sha256_hash, simhash64
from .models import CrawlJobResult, CrawlResult, SitemapDocument
from .persistence import AsyncpgStore
from .robots import RobotsPolicyCache
from .sitemap import SitemapParser, discover_sitemap_paths


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
        self._circuit_breakers = CircuitBreakerRegistry(
            failure_threshold=config.circuit_breaker_failure_threshold,
            recovery_timeout_seconds=config.circuit_breaker_recovery_seconds,
        )
        self._cms_detector = CMSDetector() if config.cms_detection else None
        self._effective_worker_limit = max(1, config.max_concurrency)

    async def crawl(self, url: str) -> CrawlResult:
        async with self._semaphore:
            try:
                if not self.config.should_crawl_url(url):
                    return CrawlResult(
                        requested_url=url,
                        final_url=url,
                        status=0,
                        headers={},
                        content_type=None,
                        fetch_backend=self.config.backend,
                        extracted=None,
                        raw_html=None,
                        allowed_by_robots=True if self.config.respect_robots_txt else None,
                        skip_reason=f"path_out_of_scope:{self.config.path_skip_detail(url)}",
                    )
                if self.config.respect_robots_txt:
                    allowed = await self._robots.is_allowed(url)
                    if not allowed:
                        return CrawlResult(
                            requested_url=url,
                            final_url=url,
                            status=0,
                            headers={},
                            content_type=None,
                            fetch_backend=self.config.backend,
                            extracted=None,
                            raw_html=None,
                            allowed_by_robots=False,
                            skip_reason="robots_txt_disallow",
                        )
                    if self.config.honor_robots_crawl_delay:
                        await self._wait_for_host_delay(url)
                await self._rate_limiter.wait()
                host = urlparse(url).netloc.lower()
                if self.config.circuit_breaker_enabled:
                    circuit = self._circuit_breakers.for_host(host)
                    if not circuit.should_allow():
                        return CrawlResult(
                            requested_url=url,
                            final_url=url,
                            status=0,
                            headers={},
                            content_type=None,
                            fetch_backend=self.config.backend,
                            extracted=None,
                            raw_html=None,
                            allowed_by_robots=True if self.config.respect_robots_txt else None,
                            skip_reason="circuit_breaker_open",
                        )
                response = await self.backend.fetch(url)
                # Case-insensitive header lookup (Playwright returns lowercase keys)
                headers_lower = {k.lower(): v for k, v in response.headers.items()}
                content_type = headers_lower.get("content-type")
                extracted = None
                raw_html = None
                content_hash_sha256 = None
                content_hash_simhash = None
                discovered_links = []
                detected_cms = None
                if content_type and "html" in content_type.lower():
                    raw_html = response.text
                    extracted = extract_page_data(response.text, response.url, response.headers)
                    if self.config.enable_content_hashing:
                        content_hash_sha256 = sha256_hash(response.text)
                        content_hash_simhash = simhash64(response.text)
                    discovered_links = extract_links(
                        response.text,
                        response.url,
                        same_host_only=self.config.same_host_only,
                    )
                    
                    # Perform CMS detection if enabled and this is HTML content
                    if self._cms_detector is not None:
                        detected_cms = self._cms_detector.detect(response)
                
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
                )
                if self.config.circuit_breaker_enabled:
                    circuit = self._circuit_breakers.for_host(host)
                    if response.status >= 500:
                        circuit.record_failure()
                    else:
                        circuit.record_success()
                if self.store is not None:
                    await self.store.persist(result)
                return result
            except Exception as exc:
                host = urlparse(url).netloc.lower()
                if self.config.circuit_breaker_enabled:
                    self._circuit_breakers.for_host(host).record_failure()
                return CrawlResult(
                    requested_url=url,
                    final_url=url,
                    status=0,
                    headers={},
                    content_type=None,
                    fetch_backend=self.config.backend,
                    extracted=None,
                    raw_html=None,
                    allowed_by_robots=True if self.config.respect_robots_txt else None,
                    skip_reason=f"fetch_error:{type(exc).__name__}",
                )

    async def crawl_many(self, urls: Iterable[str], *, save_to: str | None = None) -> list[CrawlResult]:
        url_list = list(urls)
        results: list[CrawlResult] = []
        cursor = 0
        while cursor < len(url_list):
            batch_size = min(self._current_worker_limit(), len(url_list) - cursor)
            batch_urls = url_list[cursor : cursor + batch_size]
            tasks = [asyncio.create_task(self.crawl(url)) for url in batch_urls]
            results.extend(await asyncio.gather(*tasks))
            cursor += batch_size
        if save_to:
            await self._save_results(CrawlJobResult(mode="list", seed_urls=url_list, results=results), save_to)
        return results

    async def crawl_list(self, urls: Iterable[str], *, save_to: str | None = None) -> CrawlJobResult:
        seed_urls = list(urls)
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
        sitemap_urls: list[str] = []
        parser = SitemapParser()
        for seed in seeds:
            host = urlparse(seed).netloc.lower()
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

        # BFS over sitemap indexes
        to_fetch = [(sm_url, source_kind, 0) for sm_url, source_kind in unique_sitemaps]
        fetched: set[str] = set()
        while to_fetch:
            sm_url, source_kind, depth = to_fetch.pop(0)
            if sm_url in fetched:
                continue
            if depth > self.config.sitemap_max_depth:
                continue
            fetched.add(sm_url)
            try:
                response = await self.backend.fetch(sm_url)
                if response.status != 200:
                    continue
                doc = parser.parse(sm_url, response.body, response.headers.get("Content-Type"))
                if doc.kind == "sitemap_index":
                    for child in doc.children:
                        to_fetch.append((child, source_kind, depth + 1))
                else:
                    for su in doc.urls[:self.config.sitemap_max_urls]:
                        all_page_urls.append((su.loc, sm_url))
                        if su.hreflang_links:
                            hreflang_data.append((su.loc, su.hreflang_links))
            except Exception:
                continue

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
            # Also record source detail per URL
            for url, sm_url in all_page_urls:
                if self.config.should_crawl_url(url):
                    await self.store.record_source_by_url(url, "sitemap", detail=sm_url)

        # Persist hreflang from sitemap
        for page_url, links in hreflang_data:
            # We need to persist into hreflang_sitemap table via the store
            # Reuse existing persist logic by creating a minimal CrawlResult
            if self.store is not None:
                await self._persist_sitemap_hreflang(page_url, links)

        return frontier_data

    async def _persist_sitemap_hreflang(self, url: str, links: list) -> None:
        """Write sitemap-derived hreflang rows directly."""
        await self.store.connect()
        assert self.store.pool is not None
        async with self.store.pool.acquire() as conn:
            url_id = await self.store._get_or_create_url(conn, url)
            for link in links:
                hreflang_id = await self.store._get_or_create_lookup(
                    conn, "hreflang_languages", "language_code", link.hreflang
                )
                href_url_id = await self.store._get_or_create_url(
                    conn, link.href, classification="network", is_from_hreflang=True
                )
                await conn.execute(
                    """
                    INSERT INTO hreflang_sitemap (url_id, hreflang_id, href_url_id)
                    VALUES ($1, $2, $3)
                    ON CONFLICT DO NOTHING
                    """,
                    url_id,
                    hreflang_id,
                    href_url_id,
                )

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
            for seed in seeds:
                archive_candidates.extend(await discover_historical_urls(seed, self.config))
            seeds = list(dict.fromkeys([*seeds, *archive_candidates]))
        if not seeds:
            job = CrawlJobResult(mode="open", seed_urls=[], results=[], saved_to=save_to)
            if save_to:
                await self._save_results(job, save_to)
            return job
        limit = max_urls if max_urls is not None else self.config.default_open_crawl_limit
        results: list[CrawlResult] = []
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
                print(f"[crawler] Resumed crawl: reset {reset_count} pending URLs to queued")

        session_crawled = 0
        try:
            while True:
                if limit > 0:
                    remaining = limit - session_crawled
                    if remaining <= 0:
                        break
                    batch_size = min(self._current_worker_limit(), remaining)
                else:
                    batch_size = self._current_worker_limit()

                frontier_batch = await self.store.frontier_next_batch(batch_size)
                if not frontier_batch:
                    break

                fetch_batch: list[tuple[str, int, str | None, int]] = []
                path_skipped: list[str] = []
                for item in frontier_batch:
                    url = item[0]
                    if self.config.should_crawl_url(url):
                        fetch_batch.append(item)
                    else:
                        path_skipped.append(url)
                if path_skipped:
                    await self._record_out_of_scope_urls(
                        path_skipped,
                        source="link",
                        detail="path_out_of_scope",
                    )

                batch_results = await asyncio.gather(*(self.crawl(url) for url, _, _, _ in fetch_batch))
                results.extend(batch_results)
                session_crawled += len(batch_results)

                for result in batch_results:
                    if result.skip_reason is None:
                        await self.store.persist(result)

                discovered_to_enqueue: list[tuple[str, int, str | None, float]] = []
                out_of_scope_discovered: list[str] = []
                done_urls: list[str] = list(path_skipped)
                for (url, depth, _parent_url, retry_count), result in zip(fetch_batch, batch_results):
                    transient_error = result.status in {429, 500, 502, 503, 504} or (
                        result.skip_reason is not None and "Timeout" in result.skip_reason
                    )
                    if transient_error and retry_count < self.config.frontier_max_retries:
                        delay = self.config.frontier_retry_base_delay_seconds * (2**retry_count)
                        await self.store.frontier_mark_retry(url, retry_count + 1, delay)
                        continue
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
                    # Also enqueue hreflang targets so language variants are crawled
                    if result.extracted is not None:
                        for hl in result.extracted.hreflang_links:
                            href = hl.href
                            if self.config.same_host_only and not self.config.is_host_allowed(href, seeds):
                                continue
                            if self.config.should_crawl_url(href):
                                discovered_to_enqueue.append((href, depth + 1, url, self._priority_score(href, depth + 1)))
                            else:
                                out_of_scope_discovered.append(href)
                if out_of_scope_discovered:
                    await self._record_out_of_scope_urls(
                        list(dict.fromkeys(out_of_scope_discovered)),
                        source="link",
                        detail="path_out_of_scope",
                    )
                if discovered_to_enqueue:
                    queued_count, pending_count, done_count = await self.store.frontier_stats()
                    remaining_frontier_budget = max(0, limit - (queued_count + pending_count + done_count))
                    if remaining_frontier_budget > 0:
                        await self.store.enqueue_frontier(
                            discovered_to_enqueue[:remaining_frontier_budget],
                            source="link",
                        )
                    discovered_to_enqueue = []

                await self.store.frontier_mark_done(done_urls)

            job = CrawlJobResult(mode="open", seed_urls=seeds, results=results[:limit], saved_to=save_to)
            if save_to:
                await self._save_results(job, save_to)
            return job
        finally:
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
        for url in unique_urls:
            skip_detail = self.config.path_skip_detail(url) or detail
            await self.store.record_source_by_url(url, source, detail=skip_detail)
        await self.store.frontier_mark_done(unique_urls)

    async def _save_results(self, job: CrawlJobResult, save_to: str) -> None:
        payload = {
            "mode": job.mode,
            "seed_urls": job.seed_urls,
            "saved_to": save_to,
            "crawled_count": job.crawled_count,
            "blocked_count": job.blocked_count,
            "results": [self._result_to_dict(result) for result in job.results],
        }
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

    def _result_to_dict(self, result: CrawlResult) -> dict[str, object]:
        return {
            "requested_url": result.requested_url,
            "final_url": result.final_url,
            "status": result.status,
            "headers": result.headers,
            "content_type": result.content_type,
            "fetch_backend": result.fetch_backend,
            "raw_html": result.raw_html,
            "content_hash_sha256": result.content_hash_sha256,
            "content_hash_simhash": result.content_hash_simhash,
            "discovered_links": [
                {
                    "href": link.href,
                    "anchor_text": link.anchor_text,
                    "xpath": link.xpath,
                    "is_image": link.is_image,
                }
                for link in result.discovered_links
            ],
            "allowed_by_robots": result.allowed_by_robots,
            "skip_reason": result.skip_reason,
            "extracted": None
            if result.extracted is None
            else {
                "title": result.extracted.title,
                "meta_description": result.extracted.meta_description,
                "meta_robots": result.extracted.meta_robots.raw,
                "x_robots_tag": result.extracted.x_robots_tag.raw,
                "canonical": result.extracted.canonical,
                "x_canonical": result.extracted.x_canonical,
                "hreflang_links": [
                    {"hreflang": link.hreflang, "href": link.href, "source": link.source}
                    for link in result.extracted.hreflang_links
                ],
                "html_lang": result.extracted.html_lang,
                "headings": result.extracted.headings,
                "text": result.extracted.text,
                "word_count": result.extracted.word_count,
                "metadata": result.extracted.metadata,
            },
        }

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
