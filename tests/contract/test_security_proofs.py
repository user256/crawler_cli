"""Security proofs for the portal integration contract (ticket 3344).

Proves, with running code rather than documentation:

(a) credentials and DSNs have an invocation path that never touches process
    argv, and never appear in log output or saved artifacts; and
(b) Basic and Bearer credentials are attached to the configured site and are
    STRIPPED on cross-origin redirects, while surviving same-origin redirects.
"""

from __future__ import annotations

import json
import logging

import pytest
from aiohttp import web

from crawler_cli.__main__ import _build_auth, _build_parser
from crawler_cli.auth import AuthConfig
from crawler_cli.backends import AiohttpBackend, CurlCffiBackend, PlaywrightBackend
from crawler_cli.config import CrawlConfig
from crawler_cli.engine import CrawlEngine
from crawler_cli.persistence import MemoryStore
from crawler_cli.serialization import serialize_crawl_job

BASIC_SECRET = "argv-free-basic-secret"
BEARER_SECRET = "argv-free-bearer-secret"


async def _start_app(app: web.Application) -> tuple[web.AppRunner, str]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = site._server.sockets
    assert sockets
    port = sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


# --- (a) secrets stay out of argv ----------------------------------------------


def test_bearer_token_env_keeps_secret_out_of_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLER_TEST_TOKEN", BEARER_SECRET)
    argv = ["crawl", "https://example.com", "--auth-type", "bearer", "--auth-token-env", "CRAWLER_TEST_TOKEN"]
    assert BEARER_SECRET not in " ".join(argv)
    auth = _build_auth(_build_parser().parse_args(argv))
    assert auth is not None
    assert auth.token == BEARER_SECRET
    assert auth.auth_headers() == {"Authorization": f"Bearer {BEARER_SECRET}"}


def test_bearer_token_file_keeps_secret_out_of_argv(tmp_path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text(f"{BEARER_SECRET}\n", encoding="utf-8")
    argv = ["crawl", "https://example.com", "--auth-type", "bearer", "--auth-token-file", str(token_file)]
    auth = _build_auth(_build_parser().parse_args(argv))
    assert auth is not None
    assert auth.token == BEARER_SECRET


def test_bearer_token_sources_are_mutually_exclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLER_TEST_TOKEN", BEARER_SECRET)
    args = _build_parser().parse_args(
        ["crawl", "https://example.com", "--auth-token", "argv-token", "--auth-token-env", "CRAWLER_TEST_TOKEN"]
    )
    with pytest.raises(ValueError, match="Provide only one"):
        _build_auth(args)


def test_unset_token_env_fails_without_leaking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRAWLER_TEST_TOKEN", raising=False)
    args = _build_parser().parse_args(["crawl", "https://example.com", "--auth-token-env", "CRAWLER_TEST_TOKEN"])
    with pytest.raises(ValueError, match="CRAWLER_TEST_TOKEN"):
        _build_auth(args)


# --- (a) secrets stay out of logs and artifacts --------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "auth",
    [
        AuthConfig(auth_type="basic", username="user", password=BASIC_SECRET),
        AuthConfig(auth_type="bearer", token=BEARER_SECRET),
    ],
    ids=["basic", "bearer"],
)
async def test_authenticated_crawl_logs_and_artifact_never_contain_secret(auth: AuthConfig, caplog, capsys) -> None:
    """A DEBUG-level authenticated crawl (with a redirect hop) leaks no secret
    into log records, stdout/stderr, or the serialized artifact."""

    async def start(request: web.Request) -> web.StreamResponse:
        raise web.HTTPMovedPermanently("/dest")

    async def dest(request: web.Request) -> web.Response:
        return web.Response(text="<html><body><p>ok</p></body></html>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/dest", dest)
    runner, base = await _start_app(app)

    caplog.set_level(logging.DEBUG)
    config = CrawlConfig(
        auth=auth,
        follow_redirects=True,
        respect_robots_txt=False,
        same_host_only=False,
        enable_content_hashing=True,
    )
    engine = CrawlEngine(config, store=MemoryStore())
    try:
        job = await engine.crawl_list([f"{base}/start"])
    finally:
        await engine.close()
        await runner.cleanup()

    assert job.results and job.results[0].status == 200
    captured = capsys.readouterr()
    for secret in (BASIC_SECRET, BEARER_SECRET):
        assert secret not in caplog.text
        for record in caplog.records:
            assert secret not in str(record.args)
        assert secret not in captured.out
        assert secret not in captured.err
        # Saved artifacts must be safe to hand to downstream systems: response
        # headers only, no request Authorization material.
        assert secret not in json.dumps(serialize_crawl_job(job))


# --- (b) credential scope across redirects -------------------------------------


def _backend(backend_cls, auth: AuthConfig):
    name_map = {
        AiohttpBackend: "aiohttp",
        CurlCffiBackend: "curl_cffi",
        PlaywrightBackend: "playwright",
    }
    return backend_cls(
        CrawlConfig(
            backend=name_map[backend_cls],
            auth=auth,
            follow_redirects=True,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_cls", [AiohttpBackend, CurlCffiBackend, PlaywrightBackend], ids=["aiohttp", "curl_cffi", "playwright"])
async def test_bearer_token_not_forwarded_to_cross_origin_redirect(backend_cls) -> None:
    seen: dict[str, str | None] = {}
    redirect_to = ""

    async def start(request: web.Request) -> web.StreamResponse:
        seen["start"] = request.headers.get("Authorization")
        raise web.HTTPFound(redirect_to)

    async def destination(request: web.Request) -> web.Response:
        seen["destination"] = request.headers.get("Authorization")
        return web.Response(text="ok")

    start_app = web.Application()
    start_app.router.add_get("/", start)
    destination_app = web.Application()
    destination_app.router.add_get("/", destination)
    start_runner, start_url = await _start_app(start_app)
    destination_runner, destination_url = await _start_app(destination_app)
    redirect_to = f"{destination_url}/"
    backend = _backend(backend_cls, AuthConfig(auth_type="bearer", token=BEARER_SECRET))
    try:
        result = await backend.fetch(f"{start_url}/")
    finally:
        await backend.close()
        await start_runner.cleanup()
        await destination_runner.cleanup()

    assert result.status == 200
    assert seen["start"] == f"Bearer {BEARER_SECRET}"
    assert seen["destination"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_cls", [AiohttpBackend, CurlCffiBackend, PlaywrightBackend], ids=["aiohttp", "curl_cffi", "playwright"])
@pytest.mark.parametrize(
    "auth",
    [
        AuthConfig(auth_type="basic", username="user", password="pass"),
        AuthConfig(auth_type="bearer", token=BEARER_SECRET),
    ],
    ids=["basic", "bearer"],
)
async def test_credentials_survive_same_origin_redirect(backend_cls, auth: AuthConfig) -> None:
    """Same-origin hops (e.g. /old -> /new during a migration crawl) must keep
    the credentials, or authenticated staging crawls would 401 mid-chain."""
    seen: dict[str, str | None] = {}

    async def start(request: web.Request) -> web.StreamResponse:
        seen["start"] = request.headers.get("Authorization")
        raise web.HTTPMovedPermanently("/dest")

    async def dest(request: web.Request) -> web.Response:
        seen["dest"] = request.headers.get("Authorization")
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/dest", dest)
    runner, base = await _start_app(app)
    backend = _backend(backend_cls, auth)
    try:
        result = await backend.fetch(f"{base}/start")
    finally:
        await backend.close()
        await runner.cleanup()

    assert result.status == 200
    assert seen["start"] is not None
    assert seen["dest"] == seen["start"]


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_cls", [AiohttpBackend, CurlCffiBackend, PlaywrightBackend], ids=["aiohttp", "curl_cffi", "playwright"])
async def test_domain_scoped_auth_not_sent_to_other_hosts(backend_cls) -> None:
    """--auth is host-scoped via AuthConfig.domain: a fetch of a different host
    must not carry the Authorization header at all."""
    seen: dict[str, str | None] = {}

    async def page(request: web.Request) -> web.Response:
        seen["page"] = request.headers.get("Authorization")
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/", page)
    runner, base = await _start_app(app)
    auth = AuthConfig(auth_type="bearer", token=BEARER_SECRET, domain="protected.example")
    backend = _backend(backend_cls, auth)
    try:
        result = await backend.fetch(f"{base}/")
    finally:
        await backend.close()
        await runner.cleanup()

    assert result.status == 200
    assert seen["page"] is None
