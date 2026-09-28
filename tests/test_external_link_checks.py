from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from aiohttp import web

from crawler_cli import external_link_checks as checks
from crawler_cli.authorisation import SCOPE_MANIFEST_SCHEMA_VERSION, ScopeDecision, ScopePredicate, parse_scope_manifest


class _Predicate:
    class _Manifest:
        allowed_origins = ["https://allowed.example"]
        allow_private_network = False

    manifest = _Manifest()

    def decide(self, url: str, *, purpose: str, method: str) -> ScopeDecision:
        del purpose, method
        allowed = url.startswith("https://allowed.example/")
        return ScopeDecision(allowed=allowed, reason=None if allowed else "origin")


class _Engine:
    calls: list[str] = []
    statuses: list[int] = []

    def __init__(self, config):
        self.config = config

    async def crawl(self, url: str, *, purpose: str):
        del purpose
        self.calls.append(url)
        status = self.statuses.pop(0)
        return SimpleNamespace(
            requested_url=url,
            final_url=url,
            headers={"Content-Type": "text/html", "Location": "https://allowed.example/path?token=secret"},
            status=status,
            fetch_backend="aiohttp",
            allowed_by_robots=True,
            skip_reason=None,
            challenge=None,
            redirect_chain=[{"status": status, "url": url}],
            content_type="text/html",
            wire_bytes=0,
            decoded_bytes=0,
            accounted_bytes=0,
            body_truncated=False,
        )

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_real_guarded_external_recheck_honours_robots_and_bounds_response():
    requests: list[str] = []
    base_url = ""

    async def handler(request: web.Request) -> web.StreamResponse:
        requests.append(request.path)
        if request.path == "/robots.txt":
            return web.Response(text="User-agent: *\nDisallow: /blocked\n")
        if request.path == "/redirect":
            raise web.HTTPFound(f"{base_url}/ok?token=fixture-secret")
        if request.path == "/ok":
            return web.Response(body=b"x" * 70_000)
        if request.path == "/blocked":
            return web.Response(text="must not be requested")
        return web.Response(status=404)

    app = web.Application()
    app.router.add_route("GET", "/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        assert site._server is not None and site._server.sockets
        port = site._server.sockets[0].getsockname()[1]
        base_url = f"http://127.0.0.1:{port}"
        now = datetime.now(UTC)
        predicate = ScopePredicate(
            parse_scope_manifest(
                {
                    "schema_version": SCOPE_MANIFEST_SCHEMA_VERSION,
                    "authorization_reference": "TEST-LOOPBACK-212",
                    "operator": "isolated-test",
                    "valid_from": (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "valid_until": (now + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "allowed_origins": [base_url],
                    "allowed_path_prefixes": ["/"],
                    "allowed_methods": ["GET", "HEAD"],
                    "allow_private_network": True,
                }
            )
        )

        records = await checks.collect_external_link_rechecks(
            [
                {"source_url": "https://source.example/", "target_url": f"{base_url}/blocked"},
                {"source_url": "https://source.example/", "target_url": f"{base_url}/redirect?token=fixture-secret"},
            ],
            scope_predicate=predicate,
            allow_private_network=True,
            allow_network_cidrs=("127.0.0.0/8",),
        )

        rows = {row["state"]: row for row in records[1:]}
        assert rows["robots_disallowed"]["attempts"]
        assert rows["responsive"]["attempts"][0]["body_truncated"] is True
        assert rows["responsive"]["attempts"][0]["accounted_bytes"] <= 65_536
        assert any(
            hop["url"].endswith("/redirect?token") for hop in rows["responsive"]["attempts"][0]["redirect_chain"]
        )
        assert "/robots.txt" in requests
        assert "/redirect" in requests and "/ok" in requests
        assert "/blocked" not in requests
        assert "fixture-secret" not in str(records)

        requests.clear()
        denied_by_destination_guard = await checks.collect_external_link_rechecks(
            [{"source_url": "https://source.example/", "target_url": f"{base_url}/ok"}],
            scope_predicate=predicate,
        )
        assert denied_by_destination_guard[1]["state"] in {"destination_denied", "robots_disallowed"}
        assert requests == []
    finally:
        await runner.cleanup()


def test_external_rechecks_are_bounded_scoped_and_retry_only_failures(monkeypatch):
    _Engine.calls = []
    _Engine.statuses = [503, 200]
    monkeypatch.setattr(checks, "CrawlEngine", _Engine)
    instances = [
        {
            "source_url": "https://site.example/page?session=private",
            "target_url": "https://allowed.example/fail?token=secret#fragment",
            "device": "desktop_viewport",
            "anchor_text": "Out link",
            "dom_path": "main > a:nth-of-type(1)",
            "capture_phase": "after_bounded_scroll",
            "reveal_state": "scroll_revealed",
        },
        {
            "source_url": "https://site.example/other",
            "target_url": "https://blocked.example/no-fetch",
            "device": "mobile_viewport",
        },
        {
            "source_url": "https://site.example/third",
            "target_url": "https://site.example/internal",
        },
    ]

    records = asyncio.run(checks.collect_external_link_rechecks(instances, scope_predicate=_Predicate()))

    coverage, *rows = records
    assert coverage["state"] == "partial"
    assert coverage["attempted_target_count"] == 1
    assert coverage["out_of_scope_target_count"] == 1
    assert coverage["invalid_or_internal_instance_count"] == 1
    assert len(_Engine.calls) == 2  # one initial fetch plus one transient-failure recheck
    observed = next(row for row in rows if row["state"] == "intermittent_failure")
    assert len(observed["attempts"]) == 2
    assert observed["source_page_count"] == 1
    assert "token=secret" not in str(observed)
    assert "session=private" not in str(observed)
    denied = next(row for row in rows if row["state"] == "out_of_scope")
    assert denied["attempts"] == []
    assert _Engine.calls == ["https://allowed.example/fail?token=secret"] * 2


def test_external_rechecks_cap_target_selection_deterministically(monkeypatch):
    _Engine.calls = []
    _Engine.statuses = [200] * 2
    monkeypatch.setattr(checks, "CrawlEngine", _Engine)
    instances = [
        {"source_url": "https://site.example/", "target_url": f"https://allowed.example/{path}"}
        for path in ("z", "a", "m")
    ]

    records = asyncio.run(checks.collect_external_link_rechecks(instances, scope_predicate=_Predicate(), max_targets=2))

    assert records[0]["candidate_target_count"] == 3
    assert records[0]["omitted_target_count"] == 1
    assert [row["target_url"] for row in records[1:]] == [
        "https://allowed.example/a",
        "https://allowed.example/m",
    ]
    assert _Engine.calls == ["https://allowed.example/a", "https://allowed.example/m"]


def test_private_network_permission_cannot_exceed_manifest():
    with pytest.raises(ValueError, match="scope manifest does not authorize private-network access"):
        asyncio.run(
            checks.collect_external_link_rechecks(
                [],
                scope_predicate=_Predicate(),
                allow_private_network=True,
                allow_network_cidrs=("127.0.0.0/8",),
            )
        )
