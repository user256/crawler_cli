"""Ticket 045: proxy pool rotation + eviction."""

import time

import pytest

from crawler_cli.config import CrawlConfig
from crawler_cli.proxy_pool import ProxyPool


def test_round_robin_cycles_through_proxies():
    pool = ProxyPool(["http://a:1", "http://b:1", "http://c:1"], rotation="round-robin")
    picks = [pool.select("https://x.test/") for _ in range(6)]
    assert picks == [
        "http://a:1",
        "http://b:1",
        "http://c:1",
        "http://a:1",
        "http://b:1",
        "http://c:1",
    ]


def test_per_host_is_sticky():
    pool = ProxyPool(["http://a:1", "http://b:1"], rotation="per-host")
    first_a = pool.select("https://one.test/")
    # repeated calls for the same host stick to the same proxy
    assert pool.select("https://one.test/x") == first_a
    assert pool.select("https://one.test/y") == first_a
    # a different host may get a different proxy
    first_b = pool.select("https://two.test/")
    assert pool.select("https://two.test/z") == first_b


def test_dedup_preserves_order():
    pool = ProxyPool(["http://a:1", "http://a:1", "http://b:1"])
    assert pool.size == 2


def test_eviction_after_consecutive_failures():
    pool = ProxyPool(
        ["http://a:1", "http://b:1"],
        rotation="round-robin",
        max_failures=2,
        cooldown_seconds=999,
    )
    # Fail "a" twice → evicted; rotation should then only serve "b".
    pool.report_failure("http://a:1")
    pool.report_failure("http://a:1")
    picks = {pool.select("https://x.test/") for _ in range(6)}
    assert picks == {"http://b:1"}, "evicted proxy must be skipped"


def test_success_resets_failure_count():
    pool = ProxyPool(["http://a:1"], max_failures=2, cooldown_seconds=999)
    pool.report_failure("http://a:1")
    pool.report_success("http://a:1")  # resets
    pool.report_failure("http://a:1")
    # only one failure since reset → not yet evicted, still served
    assert pool.select("https://x.test/") == "http://a:1"


def test_all_cooling_falls_back_to_closest_recovery():
    pool = ProxyPool(["http://a:1"], max_failures=1, cooldown_seconds=999)
    pool.report_failure("http://a:1")  # evicts the only proxy
    # Pool must still return something rather than None when all are cooling.
    assert pool.select("https://x.test/") == "http://a:1"


def test_cooldown_expiry_returns_proxy_to_rotation():
    pool = ProxyPool(["http://a:1", "http://b:1"], max_failures=1, cooldown_seconds=0.05)
    pool.report_failure("http://a:1")
    time.sleep(0.06)
    picks = {pool.select("https://x.test/") for _ in range(6)}
    assert "http://a:1" in picks, "proxy should return after cooldown"


def test_empty_pool_selects_none():
    pool = ProxyPool([])
    assert pool.select("https://x.test/") is None


def test_unknown_rotation_raises():
    with pytest.raises(ValueError):
        ProxyPool(["http://a:1"], rotation="nope")


# --- ticket 072: gateway mode ---


def test_gateway_always_returns_endpoint():
    pool = ProxyPool(["http://gw:8000"], mode="gateway")
    assert pool.is_gateway is True
    picks = {pool.select(f"https://{h}.test/") for h in ("a", "b", "c")}
    assert picks == {"http://gw:8000"}


def test_gateway_never_evicts_on_failure():
    pool = ProxyPool(["http://gw:8000"], mode="gateway", max_failures=1)
    for _ in range(10):
        pool.report_failure("http://gw:8000")
    # still served — the gateway rotates server-side, benching it would stall us
    assert pool.select("https://x.test/") == "http://gw:8000"


def test_gateway_requires_single_endpoint():
    with pytest.raises(ValueError):
        ProxyPool(["http://a:1", "http://b:1"], mode="gateway")


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        ProxyPool(["http://a:1"], mode="nope")


def test_build_proxy_pool_gateway_from_single_proxy():
    from crawler_cli.backends import build_proxy_pool

    config = CrawlConfig(proxy="http://user:pass@gw:8000", proxy_mode="gateway")
    pool = build_proxy_pool(config)
    assert pool is not None and pool.is_gateway
    assert pool.select("https://x.test/") == "http://user:pass@gw:8000"


def test_build_proxy_pool_list_mode():
    from crawler_cli.backends import build_proxy_pool

    config = CrawlConfig(proxies=["http://a:1", "http://b:1"], proxy_mode="list")
    pool = build_proxy_pool(config)
    assert pool is not None and not pool.is_gateway
    assert pool.size == 2


def test_cli_defaults_to_gateway_for_single_proxy():
    from crawler_cli.__main__ import _build_config, _build_parser

    args = _build_parser().parse_args(["crawl", "https://x.com", "--proxy", "http://user:pass@gw:8000"])
    config = _build_config(args)
    assert config.proxy_mode == "gateway"


def test_cli_explicit_proxy_mode_list_with_single_proxy():
    from crawler_cli.__main__ import _build_config, _build_parser

    args = _build_parser().parse_args(["crawl", "https://x.com", "--proxy", "http://gw:8000", "--proxy-mode", "list"])
    config = _build_config(args)
    assert config.proxy_mode == "list"


def test_cli_wires_proxy_pool(tmp_path):
    from crawler_cli.__main__ import _build_config, _build_parser

    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("# pool\nhttp://a:1\nhttp://b:1\n\n")
    args = _build_parser().parse_args(
        [
            "crawl",
            "https://x.com",
            "--proxy-file",
            str(proxy_file),
            "--proxy-rotation",
            "per-host",
            "--proxy-max-failures",
            "5",
            "--proxy-cooldown",
            "30",
        ]
    )
    config = _build_config(args)
    assert config.proxies == ["http://a:1", "http://b:1"]
    assert config.proxy_rotation == "per-host"
    assert config.proxy_max_failures == 5
    assert config.proxy_cooldown_seconds == 30.0


def test_backend_builds_pool_from_config():
    from crawler_cli.backends import AiohttpBackend

    config = CrawlConfig(proxies=["http://a:1", "http://b:1"], proxy_rotation="round-robin")
    backend = AiohttpBackend(config)
    assert backend._proxy_pool is not None
    assert backend._proxy_pool.size == 2
    # _select_proxy uses the pool when present
    assert backend._select_proxy("https://x.test/") in {"http://a:1", "http://b:1"}


def test_backend_single_proxy_when_no_pool():
    from crawler_cli.backends import AiohttpBackend

    config = CrawlConfig(proxy="http://single:8080")
    backend = AiohttpBackend(config)
    assert backend._proxy_pool is None
    assert backend._select_proxy("https://x.test/") == "http://single:8080"
