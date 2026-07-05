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
    cwv_payload: dict | None = None

    def __init__(self) -> None:
        self.url = ""
        self.default_timeout: int | None = None
        self.navigation_timeout: int | None = None
        self.network_idle_timeout: int | None = None
        self.waited_selector: str | None = None
        self.waited_selector_timeout: int | None = None
        self.closed = False

    async def evaluate(self, _script: str):
        return self.cwv_payload

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
        self.added_cookies: list[dict] = []

    async def new_page(self) -> StubPage:
        page = StubPage()
        self.pages.append(page)
        return page

    async def add_cookies(self, cookies: list[dict]) -> None:
        self.added_cookies.extend(cookies)

    async def add_init_script(self, script: str) -> None:
        self.init_scripts = getattr(self, "init_scripts", [])
        self.init_scripts.append(script)

    async def close(self) -> None:
        self.closed = True


class PersistentStubContext:
    def __init__(self) -> None:
        self.closed = False
        self.added_cookies: list[dict] = []
        self.init_scripts: list[str] = []

    async def add_cookies(self, cookies: list[dict]) -> None:
        self.added_cookies.extend(cookies)

    async def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)

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
        cookie_payload = self._playwright_cookie_payload()
        if cookie_payload:
            await self._context.add_cookies(cookie_payload)

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

    def __init__(
        self, chunks: list[bytes], headers: dict[str, str], *, status: int = 200, chunk_delay: float = 0.0
    ) -> None:
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
async def test_fetch_resilient_retries_gateway_on_failure():
    # Gateway mode: a status-0 (connection) failure is retried through the same
    # endpoint until a non-zero status, up to proxy_gateway_max_retries.
    fail = StubCurlStreamResponse([], {"Content-Type": "text/html"}, status=0)
    ok = StubCurlStreamResponse([b"<html>ok</html>"], {"Content-Type": "text/html"}, status=200)
    backend = CurlCffiBackend(
        CrawlConfig(backend="curl_cffi", proxy="http://gw:8000", proxy_mode="gateway", proxy_gateway_max_retries=3)
    )

    seq = [fail, fail, ok]

    class _SeqSession:
        async def get(self, url, **kwargs):
            seq[0].url = url
            return seq.pop(0)

        async def close(self):
            return None

    backend._session = _SeqSession()  # type: ignore[assignment]
    result = await backend.fetch_resilient("https://x.test/")
    assert result.status == 200
    assert seq == []  # consumed exactly fail, fail, ok


@pytest.mark.asyncio
async def test_fetch_resilient_does_not_retry_non_gateway():
    # List mode (or no proxy): fetch_resilient is a single fetch; the pool's own
    # eviction handles bad proxies, not retry-in-place.
    fail = StubCurlStreamResponse([], {"Content-Type": "text/html"}, status=0)
    backend = CurlCffiBackend(CrawlConfig(backend="curl_cffi"))
    calls = {"n": 0}

    class _CountSession:
        async def get(self, url, **kwargs):
            calls["n"] += 1
            fail.url = url
            return fail

        async def close(self):
            return None

    backend._session = _CountSession()  # type: ignore[assignment]
    result = await backend.fetch_resilient("https://x.test/")
    assert result.status == 0
    assert calls["n"] == 1


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


def test_playwright_proxy_setting_from_gateway():
    backend = PlaywrightBackend(
        CrawlConfig(backend="playwright", proxy="http://user:pass@gw:8000", proxy_mode="gateway")
    )
    setting = backend._playwright_proxy_setting()
    assert setting == {"server": "http://gw:8000", "username": "user", "password": "pass"}


def test_playwright_proxy_setting_from_list():
    backend = PlaywrightBackend(CrawlConfig(backend="playwright", proxies=["http://a.proxy:3128"], proxy_mode="list"))
    setting = backend._playwright_proxy_setting()
    assert setting["server"] == "http://a.proxy:3128"


def test_playwright_proxy_setting_none_without_proxy():
    backend = PlaywrightBackend(CrawlConfig(backend="playwright"))
    assert backend._playwright_proxy_setting() is None


@pytest.mark.asyncio
async def test_managed_obscura_argv_includes_gateway_proxy(monkeypatch):
    # Obscura managed spawn should pick up the general gateway proxy when no
    # explicit --obscura-proxy is set (ticket 073).
    import asyncio as _asyncio

    spawned = {}

    class _Proc:
        returncode = None
        stderr = None

        def terminate(self):
            self.returncode = 0

        async def wait(self):
            return 0

    async def _fake_exec(*argv, **kwargs):
        spawned["argv"] = list(argv)
        return _Proc()

    class _FakeBrowser:
        async def close(self):
            pass

    class _FakeChromium:
        async def connect_over_cdp(self, endpoint):
            return _FakeBrowser()

    class _FakePW:
        chromium = _FakeChromium()

        async def stop(self):
            pass

    monkeypatch.setattr(_asyncio, "create_subprocess_exec", _fake_exec)
    backend = PlaywrightBackend(
        CrawlConfig(
            backend="playwright",
            obscura_enabled=True,
            obscura_managed=True,
            obscura_stealth=True,
            proxy="http://user:pass@gw:8000",
            proxy_mode="gateway",
        )
    )
    backend._playwright = _FakePW()
    await backend._start_managed_obscura()
    argv = spawned["argv"]
    assert "--proxy" in argv
    assert "http://user:pass@gw:8000" in argv
    assert "--stealth" in argv


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
async def test_playwright_backend_collects_web_vitals():
    StubPage.cwv_payload = {"lcp": 1234.5, "cls": 0.07, "inp": 88.0}
    try:
        backend = StubPlaywrightBackend(
            CrawlConfig(
                backend="playwright",
                timeout_seconds=1.0,
                playwright_network_idle_timeout_seconds=0.0,
                collect_web_vitals=True,
            )
        )
        result = await backend.fetch("https://example.com/")
        assert result.lcp_ms == 1234.5
        assert result.cls == 0.07
        assert result.inp_ms == 88.0
        await backend.close()
    finally:
        StubPage.cwv_payload = None


@pytest.mark.asyncio
async def test_playwright_backend_web_vitals_null_when_disabled():
    StubPage.cwv_payload = {"lcp": 999.0, "cls": 0.5, "inp": 10.0}
    try:
        backend = StubPlaywrightBackend(
            CrawlConfig(
                backend="playwright",
                timeout_seconds=1.0,
                playwright_network_idle_timeout_seconds=0.0,
                collect_web_vitals=False,
            )
        )
        result = await backend.fetch("https://example.com/")
        # disabled → not read, all null even though the page would report values
        assert result.lcp_ms is None
        assert result.cls is None
        assert result.inp_ms is None
        await backend.close()
    finally:
        StubPage.cwv_payload = None


@pytest.mark.asyncio
async def test_playwright_backend_web_vitals_tolerate_missing_payload():
    StubPage.cwv_payload = None  # shim never ran / page returned null
    backend = StubPlaywrightBackend(
        CrawlConfig(
            backend="playwright",
            timeout_seconds=1.0,
            playwright_network_idle_timeout_seconds=0.0,
            collect_web_vitals=True,
        )
    )
    result = await backend.fetch("https://example.com/")
    assert result.lcp_ms is None and result.cls is None and result.inp_ms is None
    await backend.close()


@pytest.mark.asyncio
async def test_playwright_backend_adds_scoped_cookies_to_jar():
    from crawler_cli.cookies import Cookie

    backend = StubPlaywrightBackend(
        CrawlConfig(
            backend="playwright",
            timeout_seconds=1.0,
            playwright_network_idle_timeout_seconds=0.0,
            scoped_cookies=[
                Cookie(name="a", value="1", domain="example.com", path="/", secure=True),
                Cookie(name="hostonly", value="2"),  # no domain → skipped for jar
            ],
        )
    )
    await backend.fetch("https://example.com/")
    added = backend.contexts[0].added_cookies
    names = {c["name"] for c in added}
    assert names == {"a"}, "host-less cookie must not go into the browser jar"
    assert added[0]["domain"] == "example.com"
    assert added[0]["secure"] is True
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


@pytest.mark.asyncio
async def test_playwright_backend_can_launch_persistent_profile(monkeypatch):
    persistent_context = PersistentStubContext()

    class FakeChromium:
        def __init__(self) -> None:
            self.connected_endpoint: str | None = None
            self.launch_called = False
            self.persistent_user_data_dir: str | None = None
            self.persistent_kwargs: dict[str, object] | None = None

        async def connect_over_cdp(self, endpoint: str):
            self.connected_endpoint = endpoint
            return object()

        async def launch(self, **kwargs):
            self.launch_called = True
            return object()

        async def launch_persistent_context(self, user_data_dir: str, **kwargs):
            self.persistent_user_data_dir = user_data_dir
            self.persistent_kwargs = kwargs
            return persistent_context

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

    backend = PlaywrightBackend(
        CrawlConfig(
            backend="playwright",
            playwright_browser_channel="msedge",
            playwright_user_data_dir="/tmp/edge-user-data",
            playwright_profile_directory="Profile 7",
            playwright_headless=False,
        )
    )

    await backend._ensure_started()

    assert fake_playwright.chromium.connected_endpoint is None
    assert fake_playwright.chromium.launch_called is False
    assert fake_playwright.chromium.persistent_user_data_dir == "/tmp/edge-user-data"
    assert fake_playwright.chromium.persistent_kwargs == {
        "user_agent": "crawler_cli/0.1",
        "ignore_https_errors": False,
        "extra_http_headers": {},
        "headless": False,
        "channel": "msedge",
        "args": ["--profile-directory=Profile 7"],
    }

    await backend.close()

    assert persistent_context.closed is True
