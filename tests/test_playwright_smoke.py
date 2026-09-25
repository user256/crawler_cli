from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
import os

import pytest
import pytest_asyncio
from aiohttp import web

from crawler_cli.auth import AuthConfig
from crawler_cli.backends import PlaywrightBackend
from crawler_cli.config import CrawlConfig
from crawler_cli.compare_renders import compare_rendered_result
from crawler_cli.cookies import Cookie
from crawler_cli.engine import CrawlEngine


pytestmark = pytest.mark.playwright_smoke

_BASIC_USERNAME = "ticket097"
_BASIC_PASSWORD = "smoke-secret"
_EXPECTED_AUTH = "Basic " + base64.b64encode(f"{_BASIC_USERNAME}:{_BASIC_PASSWORD}".encode("utf-8")).decode("ascii")


@dataclass(slots=True)
class SmokeSite:
    host: str
    port: int
    api_checks: list[dict[str, bool]] = field(default_factory=list)

    @property
    def auth_domain(self) -> str:
        return f"{self.host}:{self.port}"

    def url(self, path: str) -> str:
        return f"http://{self.host}:{self.port}{path}"


def _authorized(request: web.Request) -> bool:
    return request.headers.get("Authorization") == _EXPECTED_AUTH


@pytest_asyncio.fixture
async def playwright_smoke_site(unused_tcp_port: int) -> SmokeSite:
    site = SmokeSite(host="127.0.0.1", port=unused_tcp_port)

    async def redirect_auth(request: web.Request) -> web.StreamResponse:
        if not _authorized(request):
            raise web.HTTPUnauthorized(headers={"WWW-Authenticate": 'Basic realm="ticket-097"'})
        raise web.HTTPFound("/spa")

    async def spa(request: web.Request) -> web.Response:
        if not _authorized(request):
            raise web.HTTPUnauthorized(headers={"WWW-Authenticate": 'Basic realm="ticket-097"'})
        html = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Ticket 097 smoke</title>
    <style>
      #background-image { width: 80px; height: 40px; background-image: url('/hero.svg?source=background'); }
    </style>
  </head>
  <body>
    <main id="root">loading</main>
    <img id="hero-image" src="/hero.svg?source=img" width="32" height="16" style="width:96px;height:48px" />
    <div id="background-image"></div>
    <script>
      (async () => {
        const root = document.getElementById('root');
        root.textContent = 'booting';
        await new Promise((resolve) => setTimeout(resolve, 50));
        const response = await fetch('/api/data', { credentials: 'include' });
        const payload = await response.json();
        if (!response.ok) {
          root.textContent = 'error';
          return;
        }
        document.title = 'Ticket 097 ready';
        root.textContent = payload.message;
        const ready = document.createElement('div');
        ready.className = 'app-ready';
        ready.dataset.auth = String(payload.auth_ok);
        ready.dataset.cookie = String(payload.cookie_ok);
        ready.textContent = payload.message;
        document.body.appendChild(ready);
        const link = document.createElement('a');
        link.href = '/hydrated';
        link.textContent = 'Hydrated link';
        document.body.appendChild(link);
        requestAnimationFrame(() => {
          document.body.style.paddingTop = '1px';
        });
      })();
    </script>
    <div aria-hidden="true" style="height: 1800px"></div>
    <div id="lazy-sentinel"></div>
    <script>
      new IntersectionObserver((entries, observer) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        const link = document.createElement('a');
        link.href = '/scroll-revealed';
        link.textContent = 'Scroll revealed link';
        document.body.appendChild(link);
        observer.disconnect();
      }).observe(document.getElementById('lazy-sentinel'));
    </script>
  </body>
</html>
"""
        return web.Response(text=html, content_type="text/html")

    async def api_data(request: web.Request) -> web.Response:
        auth_ok = _authorized(request)
        cookie_ok = "session=ticket-097" in request.headers.get("Cookie", "")
        site.api_checks.append({"auth_ok": auth_ok, "cookie_ok": cookie_ok})
        await asyncio.sleep(0.15)
        payload = {
            "message": "Rendered smoke path",
            "auth_ok": auth_ok,
            "cookie_ok": cookie_ok,
        }
        if not auth_ok:
            return web.json_response(payload, status=401)
        if not cookie_ok:
            return web.json_response(payload, status=400)
        return web.json_response(payload)

    async def ok_page(_request: web.Request) -> web.Response:
        return web.Response(text="<html><body><h1>Recovered</h1></body></html>", content_type="text/html")

    async def hero_image(_request: web.Request) -> web.Response:
        return web.Response(
            text='<svg xmlns="http://www.w3.org/2000/svg" width="32" height="16"></svg>',
            content_type="image/svg+xml",
        )

    async def hang(_request: web.Request) -> web.Response:
        await asyncio.sleep(2.0)
        return web.Response(text="<html><body>too late</body></html>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/redirect-auth", redirect_auth)
    app.router.add_get("/spa", spa)
    app.router.add_get("/api/data", api_data)
    app.router.add_get("/hero.svg", hero_image)
    app.router.add_get("/ok", ok_page)
    app.router.add_get("/hang", hang)

    runner = web.AppRunner(app)
    await runner.setup()
    server = web.TCPSite(runner, site.host, site.port)
    await server.start()
    try:
        yield site
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_crawl_engine_real_playwright_smoke(playwright_smoke_site: SmokeSite) -> None:
    config = CrawlConfig(
        backend="playwright",
        # Loopback fixture server; browser URL interception has its own suite.
        destination_guard="off",
        timeout_seconds=5.0,
        playwright_network_idle_timeout_seconds=1.0,
        playwright_wait_for_selector=".app-ready",
        playwright_wait_for_selector_timeout_seconds=2.0,
        max_requests_per_context=1,
        collect_web_vitals=True,
        discover_render_urls=True,
        capture_render_baseline=True,
        capture_render_link_states=True,
        capture_render_image_layout=True,
        playwright_executable_path=os.environ.get("CRAWLER_CLI_TEST_CHROMIUM_EXECUTABLE", ""),
        auth=AuthConfig(
            auth_type="basic",
            username=_BASIC_USERNAME,
            password=_BASIC_PASSWORD,
            domain=playwright_smoke_site.auth_domain,
        ),
        scoped_cookies=[
            Cookie(
                name="session",
                value="ticket-097",
                domain=playwright_smoke_site.host,
                path="/",
            )
        ],
    )
    engine = CrawlEngine(config)
    backend = engine.backend
    assert isinstance(backend, PlaywrightBackend)

    try:
        first = await engine.crawl(playwright_smoke_site.url("/redirect-auth"))
        recycled_context = backend._context
        second = await engine.crawl(playwright_smoke_site.url("/redirect-auth?run=2"))
        next_recycled_context = backend._context
    finally:
        await backend.close()

    assert first.status == 200
    assert first.fetch_backend == "playwright"
    # The authenticated route is fulfilled from route.fetch(); Chromium renders
    # the redirected SPA response but keeps the navigation URL at the requested
    # route, so the crawl result must record that actual browser URL.
    assert first.final_url == playwright_smoke_site.url("/redirect-auth")
    assert first.raw_html is not None and "Rendered smoke path" in first.raw_html
    assert first.render_raw_html is not None and "loading" in first.render_raw_html
    assert first.extracted is not None and "Rendered smoke path" in first.extracted.text
    assert first.browser_runtime is not None
    assert first.browser_runtime.provider == "chromium"
    assert first.ttfb_seconds is not None and first.ttfb_seconds >= 0
    assert first.total_duration_seconds is not None and first.total_duration_seconds >= first.ttfb_seconds
    assert first.lcp_ms is None or first.lcp_ms >= 0
    assert first.cls is None or first.cls >= 0
    assert first.inp_ms is None or first.inp_ms >= 0
    assert any(
        candidate.source_kind == "render_dom" and candidate.url == playwright_smoke_site.url("/hydrated")
        for candidate in first.render_url_candidates
    )
    parity = compare_rendered_result(first)
    assert parity.state == "complete"
    assert parity.raw is not None and parity.raw.title == "Ticket 097 smoke"
    assert parity.rendered is not None and parity.rendered.title == "Ticket 097 ready"
    assert any(finding.code == "metadata_render_dependency" for finding in parity.findings)
    assert any(finding.code == "internal_links_added_after_render" for finding in parity.findings)
    assert first.render_link_capture is not None
    assert first.render_link_capture["state"] == "complete"
    assert first.render_link_capture["controls_activated"] is False
    assert any(
        row.get("href") == playwright_smoke_site.url("/scroll-revealed")
        and row.get("capture_phase") == "after_bounded_scroll"
        and row.get("reveal_state") == "scroll_revealed"
        for row in first.render_link_observations
    )
    assert first.render_image_capture is not None
    assert first.render_image_capture["state"] == "complete"
    hero_image = next(row for row in first.render_image_observations if row.get("source_kind") == "img")
    assert (hero_image["natural_width"], hero_image["natural_height"]) == (32, 16)
    assert (hero_image["display_width"], hero_image["display_height"]) == (96, 48)
    assert hero_image["width_attribute"] == "32"
    assert any(row.get("source_kind") == "css_background" for row in first.render_image_observations)
    assert any(
        candidate.source_kind == "render_network"
        and candidate.url == playwright_smoke_site.url("/api/data")
        and candidate.outcome == "finished"
        and candidate.status == 200
        for candidate in first.render_url_candidates
    )

    assert second.status == 200
    assert recycled_context is not None
    assert next_recycled_context is not None
    assert recycled_context is not next_recycled_context

    assert playwright_smoke_site.api_checks
    assert all(check["auth_ok"] for check in playwright_smoke_site.api_checks)
    assert all(check["cookie_ok"] for check in playwright_smoke_site.api_checks)

    assert backend._context is None
    assert backend._browser is None
    assert backend._playwright is None
    assert backend._active_pages == 0
    assert not backend._tracked_browser_pids


@pytest.mark.asyncio
async def test_playwright_backend_recovers_after_timeout_and_cleans_up(playwright_smoke_site: SmokeSite) -> None:
    backend = PlaywrightBackend(
        CrawlConfig(
            backend="playwright",
            # Loopback fixture server; see the note above.
            destination_guard="off",
            timeout_seconds=0.2,
            playwright_network_idle_timeout_seconds=0.0,
            playwright_executable_path=os.environ.get("CRAWLER_CLI_TEST_CHROMIUM_EXECUTABLE", ""),
        )
    )

    try:
        with pytest.raises(Exception):
            await backend.fetch(playwright_smoke_site.url("/hang"))

        assert backend._active_pages == 0

        backend.config.timeout_seconds = 2.0
        recovered = await backend.fetch(playwright_smoke_site.url("/ok"))
        assert recovered.status == 200
        assert "Recovered" in recovered.text
    finally:
        await backend.close()

    assert backend._context is None
    assert backend._browser is None
    assert backend._playwright is None
    assert backend._active_pages == 0
    assert not backend._tracked_browser_pids
