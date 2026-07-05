"""Tests for ticket-051: --concurrency / --max-workers, DSN escaping, bare-domain argv."""
from __future__ import annotations

import argparse

import pytest

from crawler_cli.__main__ import (
    _build_config,
    _build_dsn,
    _build_parser,
    _normalize_argv,
    _postgres_config_supplied,
    _run_crawl,
)
from crawler_cli.models import CrawlJobResult
from crawler_cli.persistence import MemoryStore


# ---------------------------------------------------------------------------
# _normalize_argv: bare-domain argv
# ---------------------------------------------------------------------------

def test_normalize_bare_domain_prepends_https():
    assert _normalize_argv(["example.com"]) == ["crawl", "https://example.com"]


def test_normalize_bare_domain_with_path():
    result = _normalize_argv(["example.com/path"])
    assert result == ["crawl", "https://example.com/path"]


def test_normalize_url_with_scheme_unchanged():
    assert _normalize_argv(["https://example.com"]) == ["crawl", "https://example.com"]


def test_normalize_subcommand_unchanged():
    assert _normalize_argv(["crawl", "https://x.com"]) == ["crawl", "https://x.com"]
    assert _normalize_argv(["generate-sitemap"]) == ["generate-sitemap"]


def test_normalize_localhost():
    result = _normalize_argv(["localhost:8080"])
    assert result == ["crawl", "https://localhost:8080"]


# ---------------------------------------------------------------------------
# _build_dsn: credential URL-encoding
# ---------------------------------------------------------------------------

def _make_ns(**kwargs) -> argparse.Namespace:
    defaults = dict(
        postgres_dsn=None,
        postgres_host="localhost",
        postgres_port="5432",
        postgres_user="user",
        postgres_password="pass",
        postgres_db="db",
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_build_dsn_simple():
    ns = _make_ns()
    assert _build_dsn(ns) == "postgresql://user:pass@localhost:5432/db"


def test_build_dsn_encodes_at_in_password():
    ns = _make_ns(postgres_password="p@ss")
    dsn = _build_dsn(ns)
    assert "p%40ss" in dsn
    assert "@localhost" in dsn  # host separator is still clean


def test_build_dsn_encodes_colon_in_password():
    ns = _make_ns(postgres_password="pa:ss")
    dsn = _build_dsn(ns)
    assert "pa%3Ass" in dsn


def test_build_dsn_encodes_slash_in_password():
    ns = _make_ns(postgres_password="pa/ss")
    dsn = _build_dsn(ns)
    assert "pa%2Fss" in dsn


def test_build_dsn_encodes_special_chars_in_user():
    ns = _make_ns(postgres_user="user@domain")
    dsn = _build_dsn(ns)
    assert "user%40domain" in dsn


def test_build_dsn_passthrough_when_dsn_provided():
    ns = _make_ns(postgres_dsn="postgresql://custom:dsn@host/db")
    assert _build_dsn(ns) == "postgresql://custom:dsn@host/db"


def test_build_dsn_from_crawler_cli_postgres_dsn_env(monkeypatch):
    monkeypatch.setenv("CRAWLER_CLI_POSTGRES_DSN", "postgresql://sql_crawler:bad@localhost:5432/lottomart_com_crawler")
    ns = _make_ns()
    assert _build_dsn(ns) == "postgresql://sql_crawler:bad@localhost:5432/lottomart_com_crawler"


def test_postgres_config_supplied_when_postgres_dsn_env_set(monkeypatch):
    for key in (
        "CRAWLER_CLI_POSTGRES_HOST",
        "CRAWLER_CLI_POSTGRES_PORT",
        "CRAWLER_CLI_POSTGRES_USER",
        "CRAWLER_CLI_POSTGRES_PASSWORD",
        "CRAWLER_CLI_POSTGRES_DB",
        "CRAWLER_CLI_POSTGRES_DSN",
        "PostgreSQLCrawler_POSTGRES_HOST",
        "PostgreSQLCrawler_POSTGRES_PORT",
        "PostgreSQLCrawler_POSTGRES_USER",
        "PostgreSQLCrawler_POSTGRES_PASSWORD",
        "PostgreSQLCrawler_POSTGRES_DB",
        "PostgreSQLCrawler_POSTGRES_DSN",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CRAWLER_CLI_POSTGRES_DSN", "postgresql://u:p@localhost:5432/site_crawler")
    args = _build_parser().parse_args(["crawl", "https://x.com"])
    assert _postgres_config_supplied(args) is True


# ---------------------------------------------------------------------------
# --concurrency / --max-workers: explicit flag wins
# ---------------------------------------------------------------------------

def test_max_workers_sets_concurrency():
    args = _build_parser().parse_args(["crawl", "https://x.com", "--max-workers", "5"])
    config = _build_config(args)
    assert config.max_concurrency == 5


def test_concurrency_alias_sets_concurrency():
    args = _build_parser().parse_args(["crawl", "https://x.com", "--concurrency", "7"])
    config = _build_config(args)
    assert config.max_concurrency == 7


def test_max_workers_wins_when_both_passed():
    args = _build_parser().parse_args(
        ["crawl", "https://x.com", "--max-workers", "20", "--concurrency", "5"]
    )
    config = _build_config(args)
    assert config.max_concurrency == 20


def test_default_concurrency_is_15():
    args = _build_parser().parse_args(["crawl", "https://x.com"])
    config = _build_config(args)
    assert config.max_concurrency == 15


def test_profile_flags_enable_playwright_and_default_to_headed():
    args = _build_parser().parse_args(
        [
            "crawl",
            "https://x.com",
            "--playwright-channel",
            "msedge",
            "--playwright-user-data-dir",
            "~/Edge Data",
            "--playwright-profile-directory",
            "Profile 2",
        ]
    )
    config = _build_config(args)
    assert config.backend == "playwright"
    assert config.playwright_browser_channel == "msedge"
    assert config.playwright_user_data_dir.endswith("/Edge Data")
    assert config.playwright_profile_directory == "Profile 2"
    assert config.playwright_headless is False


def test_cdp_port_builds_local_endpoint_and_enables_playwright():
    args = _build_parser().parse_args(
        ["crawl", "https://x.com", "--playwright-cdp-port", "9222"]
    )
    config = _build_config(args)
    assert config.backend == "playwright"
    assert config.playwright_cdp_endpoint == "http://127.0.0.1:9222"


def test_cdp_host_and_port_build_endpoint():
    args = _build_parser().parse_args(
        [
            "crawl",
            "https://x.com",
            "--playwright-cdp-host",
            "192.168.1.50",
            "--playwright-cdp-port",
            "9333",
        ]
    )
    config = _build_config(args)
    assert config.playwright_cdp_endpoint == "http://192.168.1.50:9333"


def test_profile_directory_requires_user_data_dir():
    args = _build_parser().parse_args(
        ["crawl", "https://x.com", "--playwright-profile-directory", "Default"]
    )
    try:
        _build_config(args)
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit")


def test_cdp_and_profile_flags_are_mutually_exclusive():
    args = _build_parser().parse_args(
        [
            "crawl",
            "https://x.com",
            "--playwright-cdp-endpoint",
            "http://127.0.0.1:9222",
            "--playwright-user-data-dir",
            "/tmp/chrome",
        ]
    )
    try:
        _build_config(args)
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit")


def test_cdp_host_requires_cdp_port():
    args = _build_parser().parse_args(
        ["crawl", "https://x.com", "--playwright-cdp-host", "127.0.0.1"]
    )
    try:
        _build_config(args)
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit")


def test_cdp_endpoint_and_cdp_port_are_mutually_exclusive():
    args = _build_parser().parse_args(
        [
            "crawl",
            "https://x.com",
            "--playwright-cdp-endpoint",
            "http://127.0.0.1:9222",
            "--playwright-cdp-port",
            "9222",
        ]
    )
    try:
        _build_config(args)
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit")


def test_postgres_config_supplied_false_by_default(monkeypatch):
    for key in (
        "CRAWLER_CLI_POSTGRES_HOST",
        "CRAWLER_CLI_POSTGRES_PORT",
        "CRAWLER_CLI_POSTGRES_USER",
        "CRAWLER_CLI_POSTGRES_PASSWORD",
        "CRAWLER_CLI_POSTGRES_DB",
        "PostgreSQLCrawler_POSTGRES_HOST",
        "PostgreSQLCrawler_POSTGRES_PORT",
        "PostgreSQLCrawler_POSTGRES_USER",
        "PostgreSQLCrawler_POSTGRES_PASSWORD",
        "PostgreSQLCrawler_POSTGRES_DB",
    ):
        monkeypatch.delenv(key, raising=False)
    args = _build_parser().parse_args(["crawl", "https://x.com"])
    assert _postgres_config_supplied(args) is False


@pytest.mark.asyncio
async def test_run_crawl_uses_memory_store_when_postgres_not_configured(monkeypatch):
    observed: dict[str, object] = {}

    class StubEngine:
        def __init__(self, config, store=None) -> None:
            observed["store"] = store

        def request_stop(self) -> None:
            return None

        async def crawl_open(self, seeds, save_to=None):
            observed["seeds"] = list(seeds)
            return CrawlJobResult(mode="open", seed_urls=list(seeds), results=[])

        async def close(self) -> None:
            return None

    monkeypatch.setattr("crawler_cli.__main__.CrawlEngine", StubEngine)
    args = _build_parser().parse_args(["crawl", "https://x.com", "--max-pages", "1"])

    rc = await _run_crawl(args)

    assert rc == 0
    assert isinstance(observed["store"], MemoryStore)
    assert observed["seeds"] == ["https://x.com"]


@pytest.mark.asyncio
async def test_run_crawl_rejects_archive_audit_without_postgres():
    args = _build_parser().parse_args(["crawl", "https://x.com", "--archive-org-check"])
    rc = await _run_crawl(args)
    assert rc == 2
