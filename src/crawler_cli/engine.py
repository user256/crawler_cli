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
from .extract import extract_links, extract_page_data
from .hashing import sha256_hash, simhash64
from .models import CrawlJobResult, CrawlResult
from .persistence import AsyncpgStore
from .robots import RobotsPolicyCache


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

    async def crawl(self, url: str) -> CrawlResult:
        async with self._semaphore:
            try:
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
                content_type = response.headers.get("Content-Type")
                extracted = None
                raw_html = None
                content_hash_sha256 = None
                content_hash_simhash = None
                discovered_links: list[str] = []
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
        tasks = [asyncio.create_task(self.crawl(url)) for url in url_list]
        results = await asyncio.gather(*tasks)
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

    async def crawl_open(
        self,
        seed_urls: Iterable[str],
        *,
        max_urls: int | None = None,
        save_to: str | None = None,
    ) -> CrawlJobResult:
        if self.store is None:
            raise RuntimeError("crawl_open requires an AsyncpgStore for resumable DB-driven frontier management")
        seeds = list(seed_urls)
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
        limit = max_urls or self.config.default_open_crawl_limit
        results: list[CrawlResult] = []
        await self.store.save_metadata(
            "crawl_open",
            {
                "seed_urls": seeds,
                "max_urls": limit,
                "same_host_only": self.config.same_host_only,
                "respect_robots_txt": self.config.respect_robots_txt,
            },
        )
        await self.store.frontier_reset_all_pending_to_queued()
        await self.store.enqueue_frontier([(url, 0, None, self._priority_score(url, 0)) for url in seeds])

        while True:
            _, _, done_count = await self.store.frontier_stats()
            remaining = limit - done_count
            if remaining <= 0:
                break

            batch_size = min(self.config.max_concurrency, remaining)
            frontier_batch = await self.store.frontier_next_batch(batch_size)
            if not frontier_batch:
                break

            batch_results = await asyncio.gather(*(self.crawl(url) for url, _, _, _ in frontier_batch))
            results.extend(batch_results)

            discovered_to_enqueue: list[tuple[str, int, str | None]] = []
            done_urls: list[str] = []
            for (url, depth, _parent_url, retry_count), result in zip(frontier_batch, batch_results):
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
                    if self.config.same_host_only and not any(self._same_host(seed, link) for seed in seeds):
                        continue
                    discovered_to_enqueue.append((link, depth + 1, url, self._priority_score(link, depth + 1)))

            await self.store.frontier_mark_done(done_urls)
            if discovered_to_enqueue:
                queued_count, pending_count, done_count = await self.store.frontier_stats()
                remaining_frontier_budget = max(0, limit - (queued_count + pending_count + done_count))
                if remaining_frontier_budget > 0:
                    await self.store.enqueue_frontier(discovered_to_enqueue[:remaining_frontier_budget])

        job = CrawlJobResult(mode="open", seed_urls=seeds, results=results[:limit], saved_to=save_to)
        if save_to:
            await self._save_results(job, save_to)
        return job

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
            "discovered_links": result.discovered_links,
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
