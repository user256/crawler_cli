from __future__ import annotations

import gzip
import json
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
from crawler_cli.serialization import serialize_crawl_job


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
        with pytest.raises(RunBudgetExhausted, match="max_requests exhausted"):
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
async def test_budgeted_policy_fetch_reports_wire_decoded_and_typed_partial_stop() -> None:
    policy = RecordingPolicy()
    source = b"abcdefghijklmnopqrstuvwxyz"

    async def page(_request: web.Request) -> web.Response:
        return web.Response(body=source, content_type="text/html")

    app = web.Application()
    app.router.add_get("/page", page)
    runner, base = await _start_app(app)
    guarded_url = f"{base.replace('127.0.0.1', 'localhost')}/page"
    budget = RunBudget(max_bytes=16, max_response_bytes=100)
    backend = AiohttpBackend(
        CrawlConfig(
            portal_connection_policy=policy,
            challenge_escalate_to_browser=False,
            respect_robots_txt=False,
            max_bytes=16,
            max_response_bytes=100,
        )
    )
    backend.set_run_budget(budget)
    try:
        result = await backend.fetch_for_purpose(guarded_url, "initial")
    finally:
        await backend.close()
        await runner.cleanup()

    assert result.body == source[:16]
    assert result.wire_bytes == result.decoded_bytes == result.accounted_bytes == 16
    assert result.body_truncated is True
    assert result.body_truncation_reason == "max_bytes"
    assert (await budget.snapshot()).stop_reason == "max_bytes"


@pytest.mark.asyncio
async def test_budgeted_policy_fetch_keeps_wire_and_gzip_decoded_counters_distinct() -> None:
    policy = RecordingPolicy()
    source = b"<html><body>" + (b"repeatable " * 100) + b"</body></html>"
    encoded = gzip.compress(source)

    async def page(_request: web.Request) -> web.Response:
        return web.Response(body=encoded, headers={"Content-Type": "text/html", "Content-Encoding": "gzip"})

    app = web.Application()
    app.router.add_get("/page", page)
    runner, base = await _start_app(app)
    guarded_url = f"{base.replace('127.0.0.1', 'localhost')}/page"
    backend = AiohttpBackend(
        CrawlConfig(
            portal_connection_policy=policy,
            challenge_escalate_to_browser=False,
            respect_robots_txt=False,
            max_bytes=len(source) + 1,
            max_response_bytes=len(source) + 1,
        )
    )
    budget = RunBudget(max_bytes=len(source) + 1, max_response_bytes=len(source) + 1)
    backend.set_run_budget(budget)
    try:
        result = await backend.fetch_for_purpose(guarded_url, "initial")
    finally:
        await backend.close()
        await runner.cleanup()

    assert result.body == source
    assert result.wire_bytes == len(encoded)
    assert result.decoded_bytes == len(source)
    assert result.accounted_bytes == result.decoded_bytes
    assert result.body_truncated is False
    snapshot = await budget.snapshot()
    assert snapshot.wire_bytes == len(encoded)
    assert snapshot.decoded_bytes == len(source)
    assert snapshot.accounted_bytes == len(source)


@pytest.mark.asyncio
async def test_budgeted_policy_fetch_stops_gzip_expansion_at_accounted_byte_cap() -> None:
    policy = RecordingPolicy()
    source = b"<html><body>" + (b"expand " * 100) + b"</body></html>"
    encoded = gzip.compress(source)
    assert len(encoded) < 100 < len(source)

    async def page(_request: web.Request) -> web.Response:
        return web.Response(body=encoded, headers={"Content-Type": "text/html", "Content-Encoding": "gzip"})

    app = web.Application()
    app.router.add_get("/page", page)
    runner, base = await _start_app(app)
    guarded_url = f"{base.replace('127.0.0.1', 'localhost')}/page"
    budget = RunBudget(max_bytes=100, max_response_bytes=10_000)
    backend = AiohttpBackend(
        CrawlConfig(
            portal_connection_policy=policy,
            challenge_escalate_to_browser=False,
            respect_robots_txt=False,
            max_bytes=100,
            max_response_bytes=10_000,
        )
    )
    backend.set_run_budget(budget)
    try:
        result = await backend.fetch_for_purpose(guarded_url, "initial")
    finally:
        await backend.close()
        await runner.cleanup()

    assert result.body_truncated is True
    assert result.body_truncation_reason == "max_bytes"
    assert result.wire_bytes < result.decoded_bytes == result.accounted_bytes == 100
    snapshot = await budget.snapshot()
    assert snapshot.accounted_bytes == 100
    assert snapshot.accounted_bytes <= budget.max_bytes


@pytest.mark.asyncio
async def test_budgeted_policy_fetch_drains_large_gzip_decoder_tail_under_new_leases() -> None:
    """A tiny compressed body can require several decoded-output leases.

    zlib retains source bytes in ``unconsumed_tail`` once its output limit is
    reached. They must be decoded before another socket read, otherwise a
    permitted body larger than one 64 KiB lease is silently truncated.
    """
    policy = RecordingPolicy()
    source = (b"large gzip body " * 12_500) + b"end"  # > 64 KiB after decode
    encoded = gzip.compress(source)
    assert len(source) > 64 * 1024
    assert len(encoded) < 64 * 1024

    async def page(_request: web.Request) -> web.Response:
        return web.Response(body=encoded, headers={"Content-Type": "text/html", "Content-Encoding": "gzip"})

    app = web.Application()
    app.router.add_get("/page", page)
    runner, base = await _start_app(app)
    guarded_url = f"{base.replace('127.0.0.1', 'localhost')}/page"
    cap = len(source) + 1
    budget = RunBudget(max_bytes=cap, max_response_bytes=cap)
    backend = AiohttpBackend(
        CrawlConfig(
            portal_connection_policy=policy,
            challenge_escalate_to_browser=False,
            respect_robots_txt=False,
            max_bytes=cap,
            max_response_bytes=cap,
        )
    )
    backend.set_run_budget(budget)
    try:
        result = await backend.fetch_for_purpose(guarded_url, "initial")
    finally:
        await backend.close()
        await runner.cleanup()

    assert result.body == source
    assert result.body_truncated is False
    assert result.wire_bytes == len(encoded)
    assert result.decoded_bytes == result.accounted_bytes == len(source)
    assert (await budget.snapshot()).accounted_bytes == len(source)


@pytest.mark.asyncio
async def test_budgeted_policy_fetch_decodes_all_concatenated_gzip_members() -> None:
    policy = RecordingPolicy()
    first = b"<html><body>first "
    second = b"second</body></html>"
    encoded = gzip.compress(first) + gzip.compress(second)
    budget_cap = max(len(encoded), len(first + second)) + 1

    async def page(_request: web.Request) -> web.Response:
        return web.Response(body=encoded, headers={"Content-Type": "text/html", "Content-Encoding": "gzip"})

    app = web.Application()
    app.router.add_get("/page", page)
    runner, base = await _start_app(app)
    guarded_url = f"{base.replace('127.0.0.1', 'localhost')}/page"
    backend = AiohttpBackend(
        CrawlConfig(
            portal_connection_policy=policy,
            challenge_escalate_to_browser=False,
            respect_robots_txt=False,
            max_bytes=budget_cap,
            max_response_bytes=len(encoded) + 1,
        )
    )
    backend.set_run_budget(RunBudget(max_bytes=budget_cap, max_response_bytes=budget_cap))
    try:
        result = await backend.fetch_for_purpose(guarded_url, "initial")
    finally:
        await backend.close()
        await runner.cleanup()

    assert result.body == first + second
    assert result.body_truncated is False
    assert result.decoded_bytes == len(first + second)


@pytest.mark.asyncio
async def test_incomplete_gzip_body_is_opaque_to_engine_extraction_and_hashing() -> None:
    policy = RecordingPolicy()
    encoded = gzip.compress(b"<html><title>must not parse</title><a href='/next'>next</a></html>")[:-4]

    async def page(_request: web.Request) -> web.Response:
        return web.Response(body=encoded, headers={"Content-Type": "text/html", "Content-Encoding": "gzip"})

    app = web.Application()
    app.router.add_get("/page", page)
    runner, base = await _start_app(app)
    guarded_url = f"{base.replace('127.0.0.1', 'localhost')}/page"
    engine = CrawlEngine(
        CrawlConfig(
            portal_connection_policy=policy,
            challenge_escalate_to_browser=False,
            respect_robots_txt=False,
            rate_limit_per_second=0,
            enable_content_hashing=True,
        )
    )
    try:
        result = await engine.crawl(guarded_url)
    finally:
        await engine.close()
        await runner.cleanup()

    assert result.body_truncated is True
    assert result.body_truncation_reason == "incomplete_content_encoding"
    assert result.skip_reason == "body_truncated"
    assert result.extracted is None
    assert result.raw_html is None
    assert result.content_hash_sha256 is None
    assert result.content_hash_simhash is None


@pytest.mark.asyncio
@pytest.mark.parametrize("content_encoding", ["br", "gzip, br"])
async def test_unsupported_or_composite_content_encoding_is_opaque_to_engine(content_encoding: str) -> None:
    policy = RecordingPolicy()

    async def page(_request: web.Request) -> web.Response:
        return web.Response(
            body=b"<html><title>must not parse</title></html>",
            headers={"Content-Type": "text/html", "Content-Encoding": content_encoding},
        )

    app = web.Application()
    app.router.add_get("/page", page)
    runner, base = await _start_app(app)
    guarded_url = f"{base.replace('127.0.0.1', 'localhost')}/page"
    engine = CrawlEngine(
        CrawlConfig(
            portal_connection_policy=policy,
            challenge_escalate_to_browser=False,
            respect_robots_txt=False,
            rate_limit_per_second=0,
            enable_content_hashing=True,
        )
    )
    try:
        result = await engine.crawl(guarded_url)
    finally:
        await engine.close()
        await runner.cleanup()

    assert result.body_truncated is True
    assert result.body_truncation_reason == "unsupported_content_encoding"
    assert result.skip_reason == "body_truncated"
    assert result.extracted is None
    assert result.raw_html is None
    assert result.content_hash_sha256 is None


@pytest.mark.asyncio
async def test_crawl_many_save_includes_budget_summary_in_v2_artifact(tmp_path) -> None:
    policy = RecordingPolicy()

    async def page(_request: web.Request) -> web.Response:
        return web.Response(text="<html><body>" + ("x" * 100) + "</body></html>")

    app = web.Application()
    app.router.add_get("/page", page)
    runner, base = await _start_app(app)
    guarded_url = f"{base.replace('127.0.0.1', 'localhost')}/page"
    output = tmp_path / "many.json"
    engine = CrawlEngine(
        CrawlConfig(
            portal_connection_policy=policy,
            challenge_escalate_to_browser=False,
            respect_robots_txt=False,
            rate_limit_per_second=0,
            max_concurrency=1,
            max_bytes=20,
            max_response_bytes=1_000,
        )
    )
    try:
        results = await engine.crawl_many([guarded_url, guarded_url], save_to=str(output))
    finally:
        await engine.close()
        await runner.cleanup()

    assert len(results) == 1
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == "crawler-cli/crawl-artifact/2"
    assert artifact["budget_requests_started"] == 1
    assert artifact["budget_accounted_bytes"] == 20
    assert artifact["budget_stop_reason"] == "max_bytes"


@pytest.mark.asyncio
async def test_budgeted_crawl_returns_partial_job_and_never_extracts_or_hashes_a_prefix() -> None:
    policy = RecordingPolicy()

    async def page(_request: web.Request) -> web.Response:
        return web.Response(text="<html><title>must not parse</title><a href='/next'>next</a></html>")

    app = web.Application()
    app.router.add_get("/page", page)
    runner, base = await _start_app(app)
    guarded_url = f"{base.replace('127.0.0.1', 'localhost')}/page"
    engine = CrawlEngine(
        CrawlConfig(
            portal_connection_policy=policy,
            challenge_escalate_to_browser=False,
            respect_robots_txt=False,
            rate_limit_per_second=0,
            max_concurrency=1,
            max_bytes=20,
            max_response_bytes=1_000,
            enable_content_hashing=True,
        )
    )
    try:
        job = await engine.crawl_list([guarded_url, guarded_url])
    finally:
        await engine.close()
        await runner.cleanup()

    assert job.budget_stop_reason == "max_bytes"
    assert job.budget_accounted_bytes == 20
    assert job.budget_requests_started == 1
    assert len(job.results) == 1
    result = job.results[0]
    assert result.skip_reason == "body_truncated"
    assert result.body_truncated is True
    assert result.extracted is None
    assert result.raw_html is None
    assert result.content_hash_sha256 is None
    assert result.content_hash_simhash is None
    artifact = serialize_crawl_job(job)
    assert artifact["budget_stop_reason"] == "max_bytes"
    assert artifact["budget_accounted_bytes"] == 20


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


@pytest.mark.asyncio
async def test_guarded_path_only_advertises_decodable_encodings() -> None:
    """aiohttp's default Accept-Encoding follows installed optional codecs.

    With ``auto_decompress=False`` this path must decode whatever it asked
    for, so it pins the header rather than inheriting "br"/"zstd".
    """
    seen: list[str] = []

    async def page(request: web.Request) -> web.Response:
        seen.append(request.headers.get("Accept-Encoding", ""))
        return web.Response(text="ok", content_type="text/html")

    app = web.Application()
    app.router.add_get("/p", page)
    runner, base = await _start_app(app)
    guarded_base = base.replace("127.0.0.1", "localhost")
    backend = AiohttpBackend(
        CrawlConfig(portal_connection_policy=RecordingPolicy(), challenge_escalate_to_browser=False)
    )
    try:
        result = await backend.fetch_for_purpose(f"{guarded_base}/p", "initial")
    finally:
        await backend.close()
        await runner.cleanup()

    assert seen == ["gzip, deflate"]
    assert result.text == "ok"
    assert result.body_truncated is False


@pytest.mark.asyncio
async def test_guarded_robots_fetch_sends_no_crawl_credentials() -> None:
    """Robots resolution keeps the credential-free header set it always had."""
    seen: dict[str, str | None] = {}

    async def robots(request: web.Request) -> web.Response:
        seen["cookie"] = request.headers.get("Cookie")
        seen["auth"] = request.headers.get("Authorization")
        seen["custom"] = request.headers.get("X-Crawl-Secret")
        return web.Response(text="User-agent: *\nAllow: /\n", content_type="text/plain")

    async def page(request: web.Request) -> web.Response:
        seen["page_cookie"] = request.headers.get("Cookie")
        return web.Response(text="ok", content_type="text/html")

    app = web.Application()
    app.router.add_get("/robots.txt", robots)
    app.router.add_get("/p", page)
    runner, base = await _start_app(app)
    guarded_base = base.replace("127.0.0.1", "localhost")
    config = CrawlConfig(
        portal_connection_policy=RecordingPolicy(),
        challenge_escalate_to_browser=False,
        cookies={"session": "SECRET"},
        request_headers={"X-Crawl-Secret": "SECRET"},
    )
    backend = AiohttpBackend(config)
    try:
        await backend.fetch_for_purpose(f"{guarded_base}/robots.txt", "robots")
        await backend.fetch_for_purpose(f"{guarded_base}/p", "initial")
    finally:
        await backend.close()
        await runner.cleanup()

    assert seen["cookie"] is None
    assert seen["auth"] is None
    assert seen["custom"] is None
    # The page request is unchanged: only robots is stripped.
    assert seen["page_cookie"] == "session=SECRET"


@pytest.mark.asyncio
async def test_plain_response_cap_truncation_still_extracts_on_legacy_backends() -> None:
    """The opaque-body rule is scoped to the budget-aware guarded path.

    An ordinary crawl that clips a long page at ``max_response_bytes`` keeps
    the pre-3685 behaviour instead of silently becoming a skipped result.
    """
    body = b"<html><head><title>T</title></head><body>" + b"x" * 5000 + b"</body></html>"

    async def page(_request: web.Request) -> web.Response:
        return web.Response(body=body, content_type="text/html")

    app = web.Application()
    app.router.add_get("/", page)
    runner, base = await _start_app(app)
    engine = CrawlEngine(CrawlConfig(max_response_bytes=1000, respect_robots_txt=False, backend="aiohttp"))
    try:
        result = await engine.crawl(f"{base}/")
    finally:
        await engine.backend.close()
        await runner.cleanup()

    assert result.body_truncated is True
    assert result.body_truncation_reason is None
    assert result.skip_reason is None
    assert result.extracted is not None
