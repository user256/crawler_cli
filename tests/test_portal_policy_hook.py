from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from urllib.parse import urlparse

import pytest
from aiohttp import web

from crawler_cli.__main__ import _build_config, _build_parser
from crawler_cli.backends import AiohttpBackend, _PinnedResolver
from crawler_cli.budget import RunBudget, RunBudgetExhausted
from crawler_cli.config import CrawlConfig
from crawler_cli.engine import CrawlEngine
from crawler_cli.portal_policy import (
    ConnectionPurpose,
    PinnedConnection,
    PortalPolicyError,
    policy_capabilities,
)


async def _start_app(app: web.Application) -> tuple[web.AppRunner, str]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = site._server.sockets
    assert sockets
    return runner, f"http://127.0.0.1:{sockets[0].getsockname()[1]}"


@dataclass
class RecordingPolicy:
    calls: list[tuple[str, ConnectionPurpose]] = field(default_factory=list)

    async def authorize(self, url: str, purpose: ConnectionPurpose) -> PinnedConnection:
        self.calls.append((url, purpose))
        parsed = urlparse(url)
        assert parsed.hostname
        return PinnedConnection(
            hostname=parsed.hostname,
            port=parsed.port or 80,
            address="127.0.0.1",
        )


@pytest.mark.asyncio
async def test_policy_pins_initial_request_and_every_redirect() -> None:
    policy = RecordingPolicy()
    target = ""

    async def start(_request: web.Request) -> web.StreamResponse:
        raise web.HTTPFound(target)

    async def finish(_request: web.Request) -> web.Response:
        return web.Response(text="guarded")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/finish", finish)
    runner, base = await _start_app(app)
    backend = AiohttpBackend(CrawlConfig(portal_connection_policy=policy, challenge_escalate_to_browser=False))
    guarded_base = base.replace("127.0.0.1", "localhost")
    target = f"{guarded_base}/finish"
    try:
        result = await backend.fetch_for_purpose(f"{guarded_base}/start", "initial")
    finally:
        await backend.close()
        await runner.cleanup()

    assert result.status == 200
    assert result.text == "guarded"
    assert result.redirect_chain == [{"url": f"{guarded_base}/start", "status": 302}]
    assert policy.calls == [(f"{guarded_base}/start", "initial"), (f"{guarded_base}/finish", "redirect")]


@pytest.mark.asyncio
async def test_portal_aiohttp_budget_blocks_before_a_second_connection() -> None:
    calls = 0
    policy = RecordingPolicy()

    async def page(_request: web.Request) -> web.Response:
        nonlocal calls
        calls += 1
        return web.Response(body=b"abc", content_type="text/plain")

    app = web.Application()
    app.router.add_get("/page", page)
    runner, base = await _start_app(app)
    guarded_url = f"{base.replace('127.0.0.1', 'localhost')}/page"
    config = CrawlConfig(
        portal_connection_policy=policy,
        challenge_escalate_to_browser=False,
        respect_robots_txt=False,
        max_requests=1,
        max_response_bytes=10,
    )
    backend = AiohttpBackend(config)
    backend.set_run_budget(RunBudget(max_requests=1, max_response_bytes=10))
    try:
        first = await backend.fetch_for_purpose(guarded_url, "initial")
        with pytest.raises(RunBudgetExhausted, match="before request emission"):
            await backend.fetch_for_purpose(guarded_url, "initial")
    finally:
        await backend.close()
        await runner.cleanup()

    assert first.body == b"abc"
    assert calls == 1


@pytest.mark.asyncio
async def test_portal_aiohttp_budget_settles_stream_bytes_not_content_length() -> None:
    policy = RecordingPolicy()

    async def page(request: web.Request) -> web.StreamResponse:
        # Chunked response has no Content-Length. Aggregate accounting must
        # come from the actual stream reads.
        response = web.StreamResponse(headers={"Content-Type": "text/plain"})
        await response.prepare(request)
        await response.write(b"abc")
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_get("/page", page)
    runner, base = await _start_app(app)
    guarded_url = f"{base.replace('127.0.0.1', 'localhost')}/page"
    config = CrawlConfig(
        portal_connection_policy=policy,
        challenge_escalate_to_browser=False,
        respect_robots_txt=False,
        max_bytes=13,
        max_response_bytes=10,
    )
    backend = AiohttpBackend(config)
    budget = RunBudget(max_bytes=13, max_response_bytes=10)
    backend.set_run_budget(budget)
    try:
        await backend.fetch_for_purpose(guarded_url, "initial")
        await backend.fetch_for_purpose(guarded_url, "initial")
    finally:
        await backend.close()
        await runner.cleanup()

    snapshot = await budget.snapshot()
    assert snapshot.response_bytes == 6
    assert snapshot.requests_started == 2


@pytest.mark.asyncio
async def test_portal_engine_routes_robots_through_the_budgeted_policy_path() -> None:
    policy = RecordingPolicy()

    async def robots(_request: web.Request) -> web.Response:
        return web.Response(text="User-agent: *\nAllow: /\n", content_type="text/plain")

    async def page(_request: web.Request) -> web.Response:
        return web.Response(text="guarded", content_type="text/html")

    app = web.Application()
    app.router.add_get("/robots.txt", robots)
    app.router.add_get("/page", page)
    runner, base = await _start_app(app)
    guarded_url = f"{base.replace('127.0.0.1', 'localhost')}/page"
    engine = CrawlEngine(
        CrawlConfig(
            portal_connection_policy=policy,
            challenge_escalate_to_browser=False,
            rate_limit_per_second=0,
            max_requests=2,
            max_response_bytes=1_000,
        )
    )
    try:
        result = await engine.crawl(guarded_url)
    finally:
        await engine.close()
        await runner.cleanup()

    assert result.status == 200
    assert [purpose for _url, purpose in policy.calls] == ["robots", "initial"]


@pytest.mark.asyncio
async def test_engine_routes_sitemap_connections_through_policy() -> None:
    policy = RecordingPolicy()

    async def sitemap(_request: web.Request) -> web.Response:
        return web.Response(text="<urlset/>", content_type="application/xml")

    app = web.Application()
    app.router.add_get("/sitemap.xml", sitemap)
    runner, base = await _start_app(app)
    guarded_base = base.replace("127.0.0.1", "localhost")
    engine = CrawlEngine(
        CrawlConfig(
            portal_connection_policy=policy,
            challenge_escalate_to_browser=False,
            respect_robots_txt=False,
            rate_limit_per_second=0,
        )
    )
    try:
        result = await engine._bounded_fetch_response(f"{guarded_base}/sitemap.xml")
    finally:
        await engine.close()
        await runner.cleanup()

    assert result is not None
    assert result.status == 200
    assert policy.calls == [(f"{guarded_base}/sitemap.xml", "sitemap")]


@pytest.mark.asyncio
async def test_policy_mismatch_fails_before_any_connection() -> None:
    class BadPolicy:
        async def authorize(self, _url: str, _purpose: ConnectionPurpose) -> PinnedConnection:
            return PinnedConnection(hostname="wrong.example", port=80, address="127.0.0.1")

    backend = AiohttpBackend(CrawlConfig(portal_connection_policy=BadPolicy(), challenge_escalate_to_browser=False))
    with pytest.raises(PortalPolicyError, match="hostname does not match"):
        await backend.fetch_for_purpose("http://example.test/", "initial")
    await backend.close()


@pytest.mark.asyncio
async def test_policy_cannot_claim_to_pin_a_different_literal_ip() -> None:
    class DifferentAddressPolicy:
        async def authorize(self, _url: str, _purpose: ConnectionPurpose) -> PinnedConnection:
            return PinnedConnection(hostname="127.0.0.1", port=80, address="127.0.0.2")

    backend = AiohttpBackend(
        CrawlConfig(portal_connection_policy=DifferentAddressPolicy(), challenge_escalate_to_browser=False)
    )
    with pytest.raises(PortalPolicyError, match="literal-IP"):
        await backend.fetch_for_purpose("http://127.0.0.1/", "initial")
    await backend.close()


@pytest.mark.asyncio
async def test_pinned_resolver_never_returns_dns_or_a_different_origin() -> None:
    resolver = _PinnedResolver(PinnedConnection(hostname="approved.test", port=443, address="127.0.0.1"))

    result = await resolver.resolve("approved.test", 443)

    assert result[0]["host"] == "127.0.0.1"
    with pytest.raises(PortalPolicyError, match="differs"):
        await resolver.resolve("other.test", 443)


def test_policy_capabilities_never_claim_browser_or_live_compare_coverage() -> None:
    disabled = policy_capabilities(None).as_dict()
    enabled = policy_capabilities(RecordingPolicy()).as_dict()

    assert disabled["connection_guard_protocol"] is None
    assert disabled["guarded_paths"]["initial_url"] is False
    assert enabled["connection_guard_protocol"] == "portal-url-policy/1"
    assert enabled["guarded_paths"] == {
        "initial_url": True,
        "http_redirect": True,
        "sitemap": True,
        "browser_navigation": False,
        "browser_subresources": False,
        "live_compare": False,
    }


def test_policy_rejects_unguarded_backends_and_browser_escalation() -> None:
    policy = RecordingPolicy()
    with pytest.raises(ValueError, match="requires the aiohttp backend"):
        CrawlConfig(
            backend="playwright",
            portal_connection_policy=policy,
            challenge_escalate_to_browser=False,
        )
    with pytest.raises(ValueError, match="challenge_escalate_to_browser=False"):
        CrawlConfig(portal_connection_policy=policy)


def test_normal_crawl_command_loads_local_policy_without_fd3(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("portal_policy_test_module")
    module.factory = RecordingPolicy
    monkeypatch.setitem(sys.modules, module.__name__, module)
    args = _build_parser().parse_args(
        ["crawl", "http://example.test/", "--portal-url-policy", f"{module.__name__}:factory"]
    )

    config = _build_config(args)

    assert isinstance(config.portal_connection_policy, RecordingPolicy)
    assert config.challenge_escalate_to_browser is False
