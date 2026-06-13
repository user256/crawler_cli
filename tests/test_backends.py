from __future__ import annotations

import sys
import types

import pytest

from crawler_cli.backends import CurlCffiBackend, PlaywrightBackend
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
        self.waited_selector: str | None = None
        self.waited_selector_timeout: int | None = None
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

    async def wait_for_selector(self, selector: str, *, timeout: int) -> None:
        self.waited_selector = selector
        self.waited_selector_timeout = timeout

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


class EnsureStartedBackend(PlaywrightBackend):
    def __init__(self, config: CrawlConfig) -> None:
        super().__init__(config)
        self.created_context = False

    async def _create_context_locked(self) -> None:
        self._context = object()
        self._context_request_count = 0
        self._context_recycle_requested = False
        self.created_context = True


class StubCurlStreamResponse:
    """Mimics a curl_cffi streaming Response: aiter_content yields chunks."""

    def __init__(self, chunks: list[bytes], headers: dict[str, str], *, status: int = 200,
                 chunk_delay: float = 0.0) -> None:
        self._chunks = chunks
        self.headers = headers
        self.status_code = status
        self.url = "https://example.com/"
        self.closed = False
        self._chunk_delay = chunk_delay

    async def aiter_content(self):
        import asyncio
        for chunk in self._chunks:
            if self._chunk_delay:
                await asyncio.sleep(self._chunk_delay)
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class StubCurlSession:
    def __init__(self, response: StubCurlStreamResponse) -> None:
        self._response = response
        self.get_kwargs: dict | None = None

    async def get(self, url: str, **kwargs):
        self.get_kwargs = kwargs
        self._response.url = url
        return self._response

    async def close(self) -> None:
        return None


def _curl_backend_with(response: StubCurlStreamResponse, **config_kwargs) -> CurlCffiBackend:
    backend = CurlCffiBackend(CrawlConfig(backend="curl_cffi", **config_kwargs))
    backend._session = StubCurlSession(response)  # type: ignore[assignment]
    return backend


@pytest.mark.asyncio
async def test_curl_cffi_reports_ttfb_below_total():
    response = StubCurlStreamResponse(
        [b"<html>", b"<body>hi</body>", b"</html>"],
        {"Content-Type": "text/html; charset=utf-8"},
        chunk_delay=0.01,
    )
    backend = _curl_backend_with(response)

    result = await backend.fetch("https://example.com/")

    assert result.status == 200
    assert result.text == "<html><body>hi</body></html>"
    assert result.ttfb_seconds is not None
    assert result.elapsed_seconds is not None
    assert result.ttfb_seconds < result.elapsed_seconds
    assert response.closed is True
    # streaming must be requested
    assert backend._session.get_kwargs["stream"] is True  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_curl_cffi_caps_body_at_max_response_bytes():
    big = b"x" * 10_000
    response = StubCurlStreamResponse(
        [big, big, big],
        {"Content-Type": "text/html"},
    )
    backend = _curl_backend_with(response, max_response_bytes=5_000)

    result = await backend.fetch("https://example.com/")

    assert len(result.body) == 5_000
    assert result.body_truncated is True


@pytest.mark.asyncio
async def test_curl_cffi_skips_binary_content_type():
    response = StubCurlStreamResponse(
        [b"%PDF-1.7" + b"\x00" * 100_000],
        {"Content-Type": "application/pdf"},
    )
    backend = _curl_backend_with(response)

    result = await backend.fetch("https://example.com/doc.pdf")

    # only a sniff buffer is retained, not the whole payload
    assert len(result.body) <= 256
    assert result.body_truncated is True


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


@pytest.mark.asyncio
async def test_playwright_backend_waits_for_selector():
    backend = StubPlaywrightBackend(
        CrawlConfig(
            backend="playwright",
            timeout_seconds=1.0,
            playwright_network_idle_timeout_seconds=0.0,
            playwright_wait_for_selector="div.app-ready",
            playwright_wait_for_selector_timeout_seconds=3.0,
        )
    )
    await backend.fetch("https://example.com/spa")
    page = backend.contexts[0].pages[0]
    assert page.waited_selector == "div.app-ready"
    assert page.waited_selector_timeout == 3000
    await backend.close()


@pytest.mark.asyncio
async def test_playwright_backend_skips_selector_wait_when_unset():
    backend = StubPlaywrightBackend(
        CrawlConfig(
            backend="playwright",
            timeout_seconds=1.0,
            playwright_network_idle_timeout_seconds=0.0,
        )
    )
    await backend.fetch("https://example.com/")
    page = backend.contexts[0].pages[0]
    assert page.waited_selector is None
    await backend.close()


@pytest.mark.asyncio
async def test_playwright_backend_can_connect_to_existing_cdp_endpoint(monkeypatch):
    class FakeChromium:
        def __init__(self) -> None:
            self.connected_endpoint: str | None = None
            self.launch_called = False

        async def connect_over_cdp(self, endpoint: str):
            self.connected_endpoint = endpoint
            return object()

        async def launch(self, *, headless: bool):
            self.launch_called = True
            return object()

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = FakeChromium()

        async def start(self):
            return self

        async def stop(self) -> None:
            return None

    fake_playwright = FakePlaywright()
    async_api_module = types.ModuleType("playwright.async_api")
    async_api_module.async_playwright = lambda: fake_playwright
    playwright_module = types.ModuleType("playwright")
    playwright_module.async_api = async_api_module
    monkeypatch.setitem(sys.modules, "playwright", playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api_module)

    backend = EnsureStartedBackend(
        CrawlConfig(
            backend="playwright",
            playwright_cdp_endpoint="http://127.0.0.1:9222",
        )
    )

    await backend._ensure_started()

    assert fake_playwright.chromium.connected_endpoint == "http://127.0.0.1:9222"
    assert fake_playwright.chromium.launch_called is False
    assert backend.created_context is True
