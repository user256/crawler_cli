from __future__ import annotations

from typing import Any, cast

import pytest
from aiohttp import web

from crawler_cli.__main__ import _build_auth, _build_parser
from crawler_cli.auth import AuthConfig
from crawler_cli.backends import AiohttpBackend, CurlCffiBackend
from crawler_cli.config import CrawlConfig


def test_digest_auth_config_fails_clearly() -> None:
    with pytest.raises(ValueError, match="Digest authentication is not supported"):
        AuthConfig(auth_type=cast(Any, "digest"), username="user", password="pass")


def test_digest_auth_type_is_not_accepted_by_cli() -> None:
    parser = _build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["crawl", "https://example.com", "--auth-type", "digest"])

    assert exc.value.code == 2


def test_auth_password_env_keeps_secret_out_of_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLER_TEST_PASSWORD", "env-secret")
    args = _build_parser().parse_args(
        [
            "crawl",
            "https://example.com",
            "--auth-type",
            "basic",
            "--auth-username",
            "user",
            "--auth-password-env",
            "CRAWLER_TEST_PASSWORD",
        ]
    )

    auth = _build_auth(args)

    assert auth == AuthConfig(auth_type="basic", username="user", password="env-secret")


def test_auth_password_file_trims_only_trailing_newline(tmp_path) -> None:
    secret_file = tmp_path / "auth-password"
    secret_file.write_text(" file secret \n", encoding="utf-8")
    args = _build_parser().parse_args(
        [
            "crawl",
            "https://example.com",
            "--auth-type",
            "basic",
            "--auth-username",
            "user",
            "--auth-password-file",
            str(secret_file),
        ]
    )

    auth = _build_auth(args)

    assert auth == AuthConfig(auth_type="basic", username="user", password=" file secret ")


def test_auth_password_sources_are_mutually_exclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLER_TEST_PASSWORD", "env-secret")
    args = _build_parser().parse_args(
        [
            "crawl",
            "https://example.com",
            "--auth-type",
            "basic",
            "--auth-username",
            "user",
            "--auth-password",
            "argv-secret",
            "--auth-password-env",
            "CRAWLER_TEST_PASSWORD",
        ]
    )

    with pytest.raises(ValueError, match="Provide only one"):
        _build_auth(args)


def test_auth_password_without_basic_context_fails() -> None:
    args = _build_parser().parse_args(["crawl", "https://example.com", "--auth-password", "secret"])

    with pytest.raises(ValueError, match="requires --auth-username"):
        _build_auth(args)


async def _start_app(app: web.Application) -> tuple[web.AppRunner, str]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    sockets = site._server.sockets
    assert sockets
    port = sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


@pytest.mark.asyncio
async def test_aiohttp_basic_auth_not_forwarded_to_cross_origin_redirect() -> None:
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
    backend = AiohttpBackend(
        CrawlConfig(auth=AuthConfig(auth_type="basic", username="user", password="pass"), follow_redirects=True)
    )
    try:
        result = await backend.fetch(f"{start_url}/")
    finally:
        await backend.close()
        await start_runner.cleanup()
        await destination_runner.cleanup()

    assert result.status == 200
    assert seen["start"] == "Basic dXNlcjpwYXNz"
    assert seen["destination"] is None


@pytest.mark.asyncio
async def test_curl_cffi_basic_auth_not_forwarded_to_cross_origin_redirect() -> None:
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
    backend = CurlCffiBackend(
        CrawlConfig(
            backend="curl_cffi",
            auth=AuthConfig(auth_type="basic", username="user", password="pass"),
            follow_redirects=True,
        )
    )
    try:
        result = await backend.fetch(f"{start_url}/")
    finally:
        await backend.close()
        await start_runner.cleanup()
        await destination_runner.cleanup()

    assert result.status == 200
    assert seen["start"] == "Basic dXNlcjpwYXNz"
    assert seen["destination"] is None
