from __future__ import annotations

import pytest

from crawler_cli.backends import PlaywrightBackend
from crawler_cli.config import CrawlConfig


class StubResponse:
    def __init__(self) -> None:
        self.status = 200
        self.headers = {"content-type": "text/html; charset=utf-8"}


class StubPage:
    def __init__(self) -> None:
        self.url = ""
        self.default_timeout: int | None = None
        self.navigation_timeout: int | None = None
        self.network_idle_timeout: int | None = None
        self.closed = False

    def set_default_timeout(self, timeout_ms: int) -> None:
        self.default_timeout = timeout_ms

    def set_default_navigation_timeout(self, timeout_ms: int) -> None:
        self.navigation_timeout = timeout_ms

    async def goto(self, url: str, *, timeout: int, wait_until: str) -> StubResponse:
        assert wait_until == "domcontentloaded"
        self.url = url
        assert timeout == 1000
        return StubResponse()

    async def wait_for_load_state(self, state: str, *, timeout: int) -> None:
        assert state == "networkidle"
        self.network_idle_timeout = timeout

    async def content(self) -> str:
        return f"<html><body>{self.url}</body></html>"

    async def close(self) -> None:
        self.closed = True


class StubContext:
    def __init__(self) -> None:
        self.pages: list[StubPage] = []
        self.closed = False

    async def new_page(self) -> StubPage:
        page = StubPage()
        self.pages.append(page)
        return page

    async def close(self) -> None:
        self.closed = True


class StubPlaywrightBackend(PlaywrightBackend):
    def __init__(self, config: CrawlConfig) -> None:
        super().__init__(config)
        self.contexts: list[StubContext] = []

    async def _create_context_locked(self) -> None:
        self._context = StubContext()
        self.contexts.append(self._context)
        self._context_request_count = 0
        self._context_recycle_requested = False

    async def _ensure_started(self):
        if self._browser is not None:
            return
        self._browser = object()
        await self._create_context_locked()


@pytest.mark.asyncio
async def test_playwright_backend_recycles_context_after_request_cap():
    backend = StubPlaywrightBackend(
        CrawlConfig(
            backend="playwright",
            timeout_seconds=1.0,
            max_requests_per_context=2,
            playwright_network_idle_timeout_seconds=0.5,
        )
    )

    first = await backend.fetch("https://example.com/1")
    second = await backend.fetch("https://example.com/2")
    third = await backend.fetch("https://example.com/3")

    assert first.status == 200
    assert second.status == 200
    assert third.status == 200
    assert len(backend.contexts) == 2
    assert backend.contexts[0].closed is True
    assert backend.contexts[1].closed is False
    assert backend.contexts[0].pages[0].default_timeout == 1000
    assert backend.contexts[0].pages[0].navigation_timeout == 1000
    assert backend.contexts[0].pages[0].network_idle_timeout == 500

    await backend.close()

    assert backend.contexts[1].closed is True
