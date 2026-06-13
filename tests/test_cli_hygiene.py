"""Tests for ticket-051: --concurrency / --max-workers, DSN escaping, bare-domain argv."""
from __future__ import annotations

import argparse

from crawler_cli.__main__ import (
    _build_config,
    _build_dsn,
    _build_parser,
    _normalize_argv,
)


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
