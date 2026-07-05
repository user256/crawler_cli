"""Ticket 027: proxy support."""

from crawler_cli.backends import _playwright_proxy, _proxy_url
from crawler_cli.config import CrawlConfig


def test_no_proxy_returns_none():
    assert _proxy_url(CrawlConfig()) is None
    assert _playwright_proxy(CrawlConfig()) is None


def test_proxy_url_passthrough():
    config = CrawlConfig(proxy="http://proxy.example:8080")
    assert _proxy_url(config) == "http://proxy.example:8080"


def test_proxy_url_injects_auth():
    config = CrawlConfig(proxy="http://proxy.example:8080", proxy_auth="bob:secret")
    assert _proxy_url(config) == "http://bob:secret@proxy.example:8080"


def test_proxy_url_keeps_embedded_auth_over_proxy_auth():
    config = CrawlConfig(proxy="http://embedded:pw@proxy.example:8080", proxy_auth="ignored:nope")
    assert _proxy_url(config) == "http://embedded:pw@proxy.example:8080"


def test_proxy_url_socks():
    config = CrawlConfig(proxy="socks5://proxy.example:1080", proxy_auth="u:p")
    assert _proxy_url(config) == "socks5://u:p@proxy.example:1080"


def test_playwright_proxy_splits_auth():
    config = CrawlConfig(proxy="http://proxy.example:8080", proxy_auth="bob:secret")
    assert _playwright_proxy(config) == {
        "server": "http://proxy.example:8080",
        "username": "bob",
        "password": "secret",
    }


def test_playwright_proxy_server_only():
    config = CrawlConfig(proxy="http://proxy.example:8080")
    assert _playwright_proxy(config) == {"server": "http://proxy.example:8080"}


def test_cli_wires_proxy():
    from crawler_cli.__main__ import _build_config, _build_parser

    args = _build_parser().parse_args(
        ["crawl", "https://x.com", "--proxy", "http://p:8080", "--proxy-auth", "u:p"]
    )
    config = _build_config(args)
    assert config.proxy == "http://p:8080"
    assert config.proxy_auth == "u:p"
