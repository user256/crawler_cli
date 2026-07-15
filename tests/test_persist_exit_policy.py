"""Ticket 092: persistence failures must fail automation deterministically."""

from __future__ import annotations

import json
from pathlib import Path

import asyncpg
import pytest

from crawler_cli import CrawlConfig, CrawlEngine
from crawler_cli.__main__ import _build_parser, _run_crawl
from crawler_cli.exit_codes import (
    EXIT_FAILURE,
    EXIT_INTERRUPTED,
    EXIT_SUCCESS,
    resolve_crawl_exit_code,
)
from crawler_cli.models import CrawlJobResult, CrawlResult


class FakeBackend:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    async def fetch(self, url: str):
        from crawler_cli.models import FetchResponse

        html = self.pages[url]
        return FetchResponse(
            url=url,
            requested_url=url,
            status=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            body=html.encode("utf-8"),
            text=html,
        )


class FakeRobots:
    async def is_allowed(self, url: str) -> bool:
        return True

    async def get_crawl_delay(self, url: str) -> float | None:
        return None

    async def sitemaps(self, url: str) -> list[str]:
        return []


class ControllableStore:
    """Frontier store with injectable persist / mark-done failures."""

    def __init__(
        self,
        *,
        persist_fail_urls: set[str] | None = None,
        persist_transient_then_ok: set[str] | None = None,
        mark_done_fail: bool = False,
    ) -> None:
        self.frontier: dict[str, dict[str, object]] = {}
        self.saved_metadata: dict[str, dict[str, object]] = {}
        self.persisted: list[str] = []
        self.persist_attempts: dict[str, int] = {}
        self.persist_fail_urls = persist_fail_urls or set()
        self.persist_transient_then_ok = persist_transient_then_ok or set()
        self.mark_done_fail = mark_done_fail
        self.mark_done_calls: list[list[str]] = []

    async def persist(self, result: CrawlResult) -> None:
        url = result.final_url
        self.persist_attempts[url] = self.persist_attempts.get(url, 0) + 1
        if url in self.persist_transient_then_ok and self.persist_attempts[url] < 2:
            raise asyncpg.DeadlockDetectedError()
        if url in self.persist_fail_urls:
            raise RuntimeError("simulated persist failure")
        self.persisted.append(url)

    async def save_metadata(self, key: str, value: dict[str, object]) -> None:
        self.saved_metadata[key] = value

    async def enqueue_frontier(
        self,
        frontier_data: list,
        *,
        source: str | None = None,
        source_detail: str | None = None,
    ) -> int:
        inserted = 0
        for item in frontier_data:
            url, depth, parent_url = item[0], item[1], item[2]
            priority_score = float(item[3]) if len(item) > 3 and item[3] is not None else 0.0
            if url in self.frontier:
                continue
            self.frontier[url] = {
                "depth": depth,
                "parent_url": parent_url,
                "status": "queued",
                "priority_score": priority_score,
                "retry_count": 0,
                "retry_at": 0,
            }
            inserted += 1
        return inserted

    async def frontier_reset_all_pending_to_queued(self) -> int:
        reset = 0
        for state in self.frontier.values():
            if state["status"] == "pending":
                state["status"] = "queued"
                reset += 1
        return reset

    async def frontier_next_batch(self, batch_size: int) -> list[tuple[str, int, str | None, int]]:
        batch: list[tuple[str, int, str | None, int]] = []
        for url, state in sorted(self.frontier.items()):
            if state["status"] != "queued":
                continue
            state["status"] = "pending"
            batch.append((url, int(state["depth"]), state["parent_url"], int(state.get("retry_count", 0))))  # type: ignore[arg-type]
            if len(batch) >= batch_size:
                break
        return batch

    async def frontier_mark_retry(self, url: str, retry_count: int, delay_seconds: float) -> None:
        if url in self.frontier:
            self.frontier[url]["status"] = "queued"
            self.frontier[url]["retry_count"] = retry_count

    async def frontier_mark_done(self, urls: list[str]) -> None:
        self.mark_done_calls.append(list(urls))
        if self.mark_done_fail:
            raise RuntimeError("simulated mark-done failure")
        for url in urls:
            if url in self.frontier:
                self.frontier[url]["status"] = "done"

    async def frontier_stats(self) -> tuple[int, int, int]:
        queued = sum(1 for state in self.frontier.values() if state["status"] == "queued")
        pending = sum(1 for state in self.frontier.values() if state["status"] == "pending")
        done = sum(1 for state in self.frontier.values() if state["status"] == "done")
        return queued, pending, done

    async def record_source_by_url(self, url: str, source: str, detail: str | None = None) -> None:
        return None

    async def record_sources_bulk(
        self,
        url_detail_pairs: list[tuple[str, str | None]],
        source: str,
    ) -> None:
        return None

    async def persist_sitemap_hreflang_bulk(self, page_hreflang_pairs: list) -> None:
        return None


def _page(url: str, body: str = "<html><title>t</title><body>hi</body></html>") -> dict[str, str]:
    return {url: body}


def _result(*, url: str, persist_error: str | None = None, skip_reason: str | None = None) -> CrawlResult:
    return CrawlResult(
        requested_url=url,
        final_url=url,
        status=200 if skip_reason is None else 0,
        headers={},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=None,
        raw_html=None,
        persist_error=persist_error,
        skip_reason=skip_reason,
    )


def _engine(store: ControllableStore, pages: dict[str, str], *, limit: int = 1) -> CrawlEngine:
    engine = CrawlEngine(
        CrawlConfig(max_concurrency=1, default_open_crawl_limit=limit, discover_sitemaps=False),
        store=store,
    )
    engine.backend = FakeBackend(pages)
    engine._robots = FakeRobots()
    return engine


def test_durability_states():
    durable = CrawlJobResult(mode="list", seed_urls=[], results=[_result(url="https://a/")])
    assert durable.durability == "durable"
    assert durable.persist_failed_urls == []

    partial = CrawlJobResult(
        mode="list",
        seed_urls=[],
        results=[
            _result(url="https://a/"),
            _result(url="https://b/", persist_error="RuntimeError"),
        ],
    )
    assert partial.durability == "partially_durable"
    assert partial.persist_failed_urls == ["https://b/"]

    saved_only = CrawlJobResult(
        mode="list",
        seed_urls=[],
        results=[_result(url="https://a/", persist_error="RuntimeError")],
        saved_to="/tmp/out.json",
    )
    assert saved_only.durability == "saved_output_only"


def test_resolve_crawl_exit_code_precedence():
    ok = CrawlJobResult(mode="list", seed_urls=[], results=[_result(url="https://a/")])
    assert resolve_crawl_exit_code(ok) == EXIT_SUCCESS

    failed = CrawlJobResult(
        mode="list",
        seed_urls=[],
        results=[_result(url="https://a/", persist_error="RuntimeError")],
    )
    assert resolve_crawl_exit_code(failed) == EXIT_FAILURE
    assert resolve_crawl_exit_code(failed, allow_persist_failures=True) == EXIT_SUCCESS

    interrupted = CrawlJobResult(
        mode="list",
        seed_urls=[],
        results=[_result(url="https://a/", persist_error="RuntimeError")],
        interrupted=True,
    )
    assert resolve_crawl_exit_code(interrupted) == EXIT_INTERRUPTED
    assert resolve_crawl_exit_code(interrupted, allow_persist_failures=True) == EXIT_INTERRUPTED


@pytest.mark.asyncio
async def test_persist_transient_deadlock_recovers():
    url = "https://example.com/"
    store = ControllableStore(persist_transient_then_ok={url})
    job = await _engine(store, _page(url)).crawl_open([url])
    assert job.persist_error_count == 0
    assert job.durability == "durable"
    assert store.persist_attempts[url] == 2
    assert store.frontier[url]["status"] == "done"


@pytest.mark.asyncio
async def test_terminal_persist_error_leaves_frontier_pending(tmp_path: Path):
    url = "https://example.com/"
    store = ControllableStore(persist_fail_urls={url})
    out = tmp_path / "out.jsonl"
    job = await _engine(store, _page(url)).crawl_open([url], save_to=str(out))
    assert job.persist_error_count == 1
    assert job.durability == "saved_output_only"
    assert job.persist_failed_urls == [url]
    assert store.frontier[url]["status"] == "pending"
    assert store.mark_done_calls == []

    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    summary = next(ln for ln in lines if ln.get("__type") == "summary")
    assert summary["persist_error_count"] == 1
    assert summary["persist_failed_urls"] == [url]
    assert summary["durability"] == "saved_output_only"


@pytest.mark.asyncio
async def test_mixed_persist_success_and_failure(tmp_path: Path):
    ok_url = "https://example.com/"
    bad_url = "https://example.com/bad"
    html = '<html><body><a href="https://example.com/bad">bad</a></body></html>'
    store = ControllableStore(persist_fail_urls={bad_url})
    out = tmp_path / "mixed.jsonl"
    pages = {ok_url: html, bad_url: "<html><title>bad</title></html>"}
    job = await _engine(store, pages, limit=2).crawl_open([ok_url], save_to=str(out))
    assert job.persist_error_count == 1
    assert job.durability == "partially_durable"
    assert store.frontier[ok_url]["status"] == "done"
    assert store.frontier[bad_url]["status"] == "pending"

    lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    summary = next(ln for ln in lines if ln.get("__type") == "summary")
    assert summary["durability"] == "partially_durable"
    assert bad_url in summary["persist_failed_urls"]


@pytest.mark.asyncio
async def test_mark_done_failure_after_persist_leaves_pending():
    url = "https://example.com/"
    store = ControllableStore(mark_done_fail=True)
    job = await _engine(store, _page(url)).crawl_open([url])
    assert job.persist_error_count == 0
    assert job.durability == "durable"
    assert url in store.persisted
    assert store.frontier[url]["status"] == "pending"
    assert len(store.mark_done_calls) == 1


@pytest.mark.asyncio
async def test_run_crawl_exits_nonzero_on_persist_failure(monkeypatch):
    class StubEngine:
        def __init__(self, config, store=None) -> None:
            return None

        def request_stop(self) -> None:
            return None

        async def crawl_open(self, *args, **kwargs):
            return CrawlJobResult(
                mode="open",
                seed_urls=["https://x.com"],
                results=[_result(url="https://x.com/", persist_error="RuntimeError")],
                saved_to=None,
            )

        async def close(self) -> None:
            return None

    monkeypatch.setattr("crawler_cli.__main__.CrawlEngine", StubEngine)
    args = _build_parser().parse_args(["crawl", "https://x.com", "--max-pages", "1"])
    rc = await _run_crawl(args)
    assert rc == EXIT_FAILURE


@pytest.mark.asyncio
async def test_run_crawl_allow_persist_failures_keeps_exit_zero(monkeypatch):
    class StubEngine:
        def __init__(self, config, store=None) -> None:
            return None

        def request_stop(self) -> None:
            return None

        async def crawl_open(self, *args, **kwargs):
            return CrawlJobResult(
                mode="open",
                seed_urls=["https://x.com"],
                results=[_result(url="https://x.com/", persist_error="RuntimeError")],
            )

        async def close(self) -> None:
            return None

    monkeypatch.setattr("crawler_cli.__main__.CrawlEngine", StubEngine)
    args = _build_parser().parse_args(["crawl", "https://x.com", "--max-pages", "1", "--allow-persist-failures"])
    rc = await _run_crawl(args)
    assert rc == EXIT_SUCCESS


@pytest.mark.asyncio
async def test_run_crawl_interrupt_precedes_persist_failure(monkeypatch):
    class StubEngine:
        def __init__(self, config, store=None) -> None:
            return None

        def request_stop(self) -> None:
            return None

        async def crawl_open(self, *args, **kwargs):
            return CrawlJobResult(
                mode="open",
                seed_urls=["https://x.com"],
                results=[_result(url="https://x.com/", persist_error="RuntimeError")],
                interrupted=True,
            )

        async def close(self) -> None:
            return None

    monkeypatch.setattr("crawler_cli.__main__.CrawlEngine", StubEngine)
    args = _build_parser().parse_args(["crawl", "https://x.com", "--max-pages", "1"])
    rc = await _run_crawl(args)
    assert rc == EXIT_INTERRUPTED


@pytest.mark.asyncio
async def test_list_crawl_save_to_includes_durability(tmp_path: Path):
    url = "https://example.com/"
    store = ControllableStore(persist_fail_urls={url})
    out = tmp_path / "list.json"
    engine = CrawlEngine(CrawlConfig(max_concurrency=1, discover_sitemaps=False), store=store)
    engine.backend = FakeBackend(_page(url))
    engine._robots = FakeRobots()
    job = await engine.crawl_list([url], save_to=str(out))
    assert job.durability == "saved_output_only"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["durability"] == "saved_output_only"
    assert payload["persist_error_count"] == 1
    assert payload["persist_failed_urls"] == [url]
