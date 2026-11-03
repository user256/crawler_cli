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

    with pytest.raises(ValueError, match=r"^--auth-password requires --auth-username or --auth-type basic$"):
        _build_auth(args)


def test_auth_password_env_without_basic_context_names_env_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRAWLER_TEST_PASSWORD", "env-secret")
    args = _build_parser().parse_args(["crawl", "https://example.com", "--auth-password-env", "CRAWLER_TEST_PASSWORD"])

    with pytest.raises(ValueError, match=r"^--auth-password-env requires --auth-username or --auth-type basic$"):
        _build_auth(args)


def test_auth_password_file_without_basic_context_names_file_flag(tmp_path) -> None:
    secret_file = tmp_path / "auth-password"
    secret_file.write_text("file-secret\n", encoding="utf-8")
    args = _build_parser().parse_args(["crawl", "https://example.com", "--auth-password-file", str(secret_file)])

    with pytest.raises(ValueError, match=r"^--auth-password-file requires --auth-username or --auth-type basic$"):
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
        # Loopback fixture server: the ticket-149 destination guard is off here
        # so this test proves credential scoping, not address policy.
        CrawlConfig(
            auth=AuthConfig(auth_type="basic", username="user", password="pass"),
            follow_redirects=True,
            destination_guard="off",
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
            destination_guard="off",
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


def test_header_flag_builds_seed_scoped_custom_headers() -> None:
    args = _build_parser().parse_args(
        [
            "crawl",
            "https://shop.example.com/",
            "--header",
            'Signature-Agent: "https://shopify.com"',
            "--header",
            "Signature: sig1=:abc==:",
        ]
    )

    auth = _build_auth(args)

    assert auth == AuthConfig(
        domain="shop.example.com",
        custom_headers={"Signature-Agent": '"https://shopify.com"', "Signature": "sig1=:abc==:"},
    )
    assert auth.enabled
    assert auth.applies_to("https://shop.example.com/products/x")
    assert not auth.applies_to("https://cdn.example.net/x.js")
    assert auth.auth_headers() == auth.custom_headers


def test_headers_file_accepts_name_value_lines_and_header_flag_overrides(tmp_path) -> None:
    headers_file = tmp_path / "shopify.headers"
    headers_file.write_text(
        "# issued from Shopify admin\n"
        'Signature-Input: sig1=("@authority" "signature-agent");tag="web-bot-auth"\n'
        "\n"
        'Signature-Agent: "https://shopify.com"\n',
        encoding="utf-8",
    )
    args = _build_parser().parse_args(
        [
            "crawl",
            "https://shop.example.com",
            "--headers-file",
            str(headers_file),
            "--header",
            'Signature-Agent: "https://override.example"',
        ]
    )

    auth = _build_auth(args)

    assert auth is not None
    assert auth.custom_headers == {
        "Signature-Input": 'sig1=("@authority" "signature-agent");tag="web-bot-auth"',
        "Signature-Agent": '"https://override.example"',
    }


def test_headers_file_accepts_json_object(tmp_path) -> None:
    headers_file = tmp_path / "headers.json"
    headers_file.write_text(
        '{"X-Crawl-Token": "abc", "Signature-Agent": "\\"https://shopify.com\\""}', encoding="utf-8"
    )
    args = _build_parser().parse_args(["crawl", "https://shop.example.com", "--headers-file", str(headers_file)])

    auth = _build_auth(args)

    assert auth is not None
    assert auth.custom_headers == {"X-Crawl-Token": "abc", "Signature-Agent": '"https://shopify.com"'}


@pytest.mark.parametrize("bad", ["NoColonHere", ": value-only", "Bad Name: value"])
def test_malformed_header_flag_is_rejected(bad: str) -> None:
    args = _build_parser().parse_args(["crawl", "https://shop.example.com", "--header", bad])

    with pytest.raises(ValueError, match="--header"):
        _build_auth(args)


def test_no_headers_and_no_auth_keeps_auth_disabled() -> None:
    args = _build_parser().parse_args(["crawl", "https://shop.example.com"])

    assert _build_auth(args) is None


@pytest.mark.asyncio
async def test_aiohttp_custom_headers_sent_to_seed_host_only() -> None:
    seen: dict[str, str | None] = {}

    def make_handler(name: str):
        async def handler(request: web.Request) -> web.Response:
            seen[name] = request.headers.get("Signature-Agent")
            return web.Response(text="ok")

        return handler

    seed_app = web.Application()
    seed_app.router.add_get("/", make_handler("seed"))
    other_app = web.Application()
    other_app.router.add_get("/", make_handler("other"))
    seed_runner, seed_url = await _start_app(seed_app)
    other_runner, other_url = await _start_app(other_app)
    seed_host = seed_url.removeprefix("http://")
    backend = AiohttpBackend(
        CrawlConfig(
            auth=AuthConfig(domain=seed_host, custom_headers={"Signature-Agent": '"https://shopify.com"'}),
            destination_guard="off",
        )
    )
    try:
        seed_result = await backend.fetch(f"{seed_url}/")
        other_result = await backend.fetch(f"{other_url}/")
    finally:
        await backend.close()
        await seed_runner.cleanup()
        await other_runner.cleanup()

    assert seed_result.status == 200 and other_result.status == 200
    assert seen["seed"] == '"https://shopify.com"'
    assert seen["other"] is None
