"""Unit tests for ticket 095 crawl-run selection."""

from __future__ import annotations

import pytest

from crawler_cli.persistence import DEFAULT_CRAWL_RUN_ID, MemoryStore
from crawler_cli.run_scope import RunSelectionError, resolve_reporting_run_id


@pytest.mark.asyncio
async def test_resolve_explicit_run_id() -> None:
    store = MemoryStore()
    await store.create_crawl_run("run-a", seed_urls=["https://a.example/"], config_hash="a", config={})
    assert await resolve_reporting_run_id(store, "run-a") == "run-a"


@pytest.mark.asyncio
async def test_resolve_explicit_missing_run_raises() -> None:
    store = MemoryStore()
    with pytest.raises(RunSelectionError, match="not found"):
        await resolve_reporting_run_id(store, "missing")


@pytest.mark.asyncio
async def test_resolve_single_non_legacy_auto() -> None:
    store = MemoryStore()
    await store.create_crawl_run("only-run", seed_urls=["https://a.example/"], config_hash="a", config={})
    assert await resolve_reporting_run_id(store, None) == "only-run"


@pytest.mark.asyncio
async def test_resolve_legacy_when_no_other_runs() -> None:
    store = MemoryStore()
    assert await resolve_reporting_run_id(store, None) == DEFAULT_CRAWL_RUN_ID


@pytest.mark.asyncio
async def test_resolve_multiple_runs_requires_explicit() -> None:
    store = MemoryStore()
    await store.create_crawl_run("run-a", seed_urls=["https://a.example/"], config_hash="a", config={})
    await store.create_crawl_run("run-b", seed_urls=["https://b.example/"], config_hash="b", config={})
    with pytest.raises(RunSelectionError, match="multiple crawl runs"):
        await resolve_reporting_run_id(store, None)
