"""robots.txt and sitemaps on browser (--js) runs.

Regression for 2026-11-20: a --js crawl reported every URL as
``robots_txt_disallow``. robots.txt was fetched through the Playwright page
path, so a browser that failed to launch made robots "unreachable" (RFC 9309:
disallow everything), and a working browser would have returned Chromium's
rendered ``<pre>`` wrapper rather than the robots text.
"""

from __future__ import annotations

import pytest
from aiohttp import web

from crawler_cli.backends import ObscuraFetchBackend, PlaywrightBackend
from crawler_cli.config import CrawlConfig
from crawler_cli.engine import CrawlEngine
from crawler_cli.models import FetchResponse

ROBOTS = "User-agent: *\nSitemap: {base}/sitemap.xml\n"
RULED_ROBOTS = "User-agent: *\nDisallow: /private\nSitemap: {base}/sitemap.xml\n"
SITEMAP = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{base}/</loc></url></urlset>'


async def _start_app(robots_body: str = ROBOTS) -> tuple[web.AppRunner, str, list[str]]:
    hits: list[str] = []
    base_holder: dict[str, str] = {}

    async def robots(request: web.Request) -> web.Response:
        hits.append(request.path)
        return web.Response(text=robots_body.format(base=base_holder["base"]), content_type="text/plain")

    async def sitemap(request: web.Request) -> web.Response:
        hits.append(request.path)
        return web.Response(text=SITEMAP.format(base=base_holder["base"]), content_type="application/xml")

    app = web.Application()
    app.router.add_get("/robots.txt", robots)
    app.router.add_get("/sitemap.xml", sitemap)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base_holder["base"] = f"http://127.0.0.1:{port}"
    return runner, base_holder["base"], hits


def _browser_config(**overrides) -> CrawlConfig:
    return CrawlConfig(
        backend="playwright",
        respect_robots_txt=True,
        allow_private_network=True,
        allow_network_cidrs=("127.0.0.0/8",),
        **overrides,
    )


def _install_browser_stub(engine: CrawlEngine, *, documents: str = "fail") -> list[str]:
    """Stand in for Chromium.

    Pages render normally. For robots.txt and sitemaps, ``documents="fail"``
    raises like a missing browser; ``"wrap"`` returns what ``page.content()``
    gives for a plain-text document: the text inside Chromium's ``<pre>``.
    """
    assert isinstance(engine.backend, PlaywrightBackend)
    browser_calls: list[str] = []

    async def fake_fetch(url: str) -> FetchResponse:
        browser_calls.append(url)
        if url.endswith(("/robots.txt", ".xml")):
            if documents == "fail":
                raise RuntimeError("BrowserType.launch: Executable doesn't exist")
            base = url.rsplit("/", 1)[0]
            html = (
                '<html><head><meta name="color-scheme" content="light dark"></head><body>'
                '<pre style="word-wrap: break-word; white-space: pre-wrap;">'
                + RULED_ROBOTS.format(base=base)
                + "</pre></body></html>"
            )
        else:
            html = "<html><head><title>Home</title></head><body><p>hello</p></body></html>"
        return FetchResponse(
            url=url,
            requested_url=url,
            status=200,
            headers={"content-type": "text/html"},
            body=html.encode(),
            text=html,
        )

    engine.backend.fetch = fake_fetch  # type: ignore[method-assign]
    return browser_calls


@pytest.mark.asyncio
@pytest.mark.parametrize("destination_guard", ["resolver", "off"])
async def test_js_backend_allows_a_rule_less_user_agent_group(destination_guard):
    runner, base, hits = await _start_app()
    try:
        engine = CrawlEngine(_browser_config(destination_guard=destination_guard))
        browser_calls = _install_browser_stub(engine)
        try:
            result = await engine.crawl(f"{base}/")
            decision = await engine._robots.check(f"{base}/any/path")
        finally:
            await engine.close()
    finally:
        await runner.cleanup()

    assert result.skip_reason is None
    assert result.allowed_by_robots is True
    assert decision.allowed is True
    assert "/robots.txt" in hits
    assert not any(url.endswith("/robots.txt") for url in browser_calls)


@pytest.mark.asyncio
async def test_js_backend_reads_robots_text_not_a_rendered_wrapper():
    runner, base, _hits = await _start_app()
    try:
        engine = CrawlEngine(_browser_config())
        _install_browser_stub(engine)
        try:
            sitemaps = await engine._robots.sitemaps(f"{base}/")
        finally:
            await engine.close()
    finally:
        await runner.cleanup()

    assert sitemaps == [f"{base}/sitemap.xml"]


@pytest.mark.asyncio
@pytest.mark.parametrize("destination_guard", ["resolver", "off"])
async def test_js_backend_honours_rules_a_rendered_wrapper_would_hide(destination_guard):
    runner, base, _hits = await _start_app(RULED_ROBOTS)
    try:
        engine = CrawlEngine(_browser_config(destination_guard=destination_guard))
        _install_browser_stub(engine, documents="wrap")
        try:
            private = await engine._robots.check(f"{base}/private/page")
            public = await engine._robots.check(f"{base}/public")
            sitemaps = await engine._robots.sitemaps(f"{base}/")
        finally:
            await engine.close()
    finally:
        await runner.cleanup()

    assert private.allowed is False
    assert private.matched_rule == "Disallow: /private"
    assert public.allowed is True
    assert sitemaps == [f"{base}/sitemap.xml"]


@pytest.mark.asyncio
async def test_js_backend_fetches_sitemaps_over_http():
    runner, base, hits = await _start_app()
    try:
        engine = CrawlEngine(_browser_config())
        browser_calls = _install_browser_stub(engine)
        try:
            response = await engine._fetch_for_purpose(f"{base}/sitemap.xml", "sitemap")
        finally:
            await engine.close()
    finally:
        await runner.cleanup()

    assert response.status == 200
    assert response.text.startswith("<?xml")
    assert "/sitemap.xml" in hits
    assert browser_calls == []


@pytest.mark.asyncio
async def test_robots_fetch_failure_is_logged(caplog):
    engine = CrawlEngine(_browser_config())

    async def boom(url, purpose):
        raise RuntimeError("Executable doesn't exist")

    engine._robots._fetch_response = boom
    try:
        with caplog.at_level("WARNING", logger="crawler_cli.robots"):
            allowed = await engine._robots.is_allowed("https://example.com/")
    finally:
        await engine.close()

    assert allowed is False
    assert any("robots.txt fetch failed" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_document_backend_is_closed_with_the_engine():
    runner, base, _hits = await _start_app()
    try:
        engine = CrawlEngine(_browser_config())
        _install_browser_stub(engine)
        await engine._fetch_for_purpose(f"{base}/sitemap.xml", "sitemap")
        document_backend = engine._document_backend
        assert document_backend is not None
        closed: list[bool] = []
        original_close = document_backend.close

        async def tracking_close() -> None:
            closed.append(True)
            await original_close()

        document_backend.close = tracking_close  # type: ignore[method-assign]
        await engine.close()
    finally:
        await runner.cleanup()

    assert closed == [True]
    assert engine._document_backend is None


def test_obscura_cdp_documents_keep_the_obscura_proxy():
    engine = CrawlEngine(_browser_config(obscura_enabled=True, obscura_proxy="http://gateway.example:8080"))
    document_backend = engine._get_document_backend()
    assert document_backend is not None
    assert document_backend._select_proxy("https://example.com/robots.txt") == "http://gateway.example:8080"


def test_obscura_proxy_wins_over_general_proxy_for_documents():
    """Mirror the managed Obscura browser, which prefers obscura_proxy."""
    engine = CrawlEngine(
        _browser_config(
            destination_guard="off",
            obscura_enabled=True,
            obscura_proxy="http://obscura.example:8080",
            proxy="http://general.example:3128",
        )
    )
    document_backend = engine._get_document_backend()
    assert document_backend is not None
    assert document_backend._select_proxy("https://example.com/robots.txt") == "http://obscura.example:8080"


def test_plain_playwright_documents_use_the_general_proxy():
    engine = CrawlEngine(_browser_config(destination_guard="off", proxy="http://general.example:3128"))
    document_backend = engine._get_document_backend()
    assert document_backend is not None
    assert document_backend._select_proxy("https://example.com/robots.txt") == "http://general.example:3128"


def test_obscura_subprocess_backend_keeps_its_own_raw_document_path():
    """``obscura fetch --dump original`` already returns robots and sitemaps raw, through obscura_proxy."""
    engine = CrawlEngine(
        CrawlConfig(
            obscura_enabled=True,
            obscura_fetch_subprocess=True,
            obscura_proxy="http://gateway.example:8080",
            respect_robots_txt=True,
        )
    )
    assert isinstance(engine.backend, ObscuraFetchBackend)
    assert engine._get_document_backend() is None
    argv = engine.backend._build_argv(
        "https://example.com/robots.txt", raw=engine.backend._is_raw_url("https://example.com/robots.txt")
    )
    assert "--dump" in argv and "--proxy" in argv
