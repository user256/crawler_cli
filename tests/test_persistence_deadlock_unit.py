"""Unit tests for AsyncpgStore deadlock retry (no PostgreSQL required)."""

from __future__ import annotations

import asyncpg
import pytest

from crawler_cli.models import CrawlResult, DiscoveredLink
from crawler_cli.persistence import AsyncpgStore, _snapshot_link_inventory


@pytest.mark.asyncio
async def test_retry_on_deadlock_succeeds_after_transient_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    store = AsyncpgStore("postgresql://unused/db")
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("crawler_cli.persistence.asyncio.sleep", fake_sleep)

    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise asyncpg.DeadlockDetectedError()
        return "ok"

    assert await store._retry_on_deadlock(flaky) == "ok"
    assert calls["n"] == 3
    assert sleeps == [0.05, 0.1]


@pytest.mark.asyncio
async def test_retry_on_deadlock_exhausts_and_reraises(monkeypatch: pytest.MonkeyPatch) -> None:
    store = AsyncpgStore("postgresql://unused/db")

    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr("crawler_cli.persistence.asyncio.sleep", fake_sleep)

    async def always_deadlock() -> None:
        raise asyncpg.SerializationError()

    with pytest.raises(asyncpg.SerializationError):
        await store._retry_on_deadlock(always_deadlock, _attempts=3)


def test_snapshot_link_inventory_keeps_external_links_without_expanding_frontier():
    result = CrawlResult(
        requested_url="https://site.example/",
        final_url="https://site.example/",
        status=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=None,
        raw_html=(
            '<a href="/internal">Internal</a>'
            '<a href="https://external.example/no" rel="nofollow">External</a>'
        ),
        discovered_links=[DiscoveredLink("https://site.example/internal", "Internal", "/a[1]", False)],
    )

    links = _snapshot_link_inventory(result)

    assert [(link.href, link.follow) for link in links] == [
        ("https://site.example/internal", True),
        ("https://external.example/no", False),
    ]
