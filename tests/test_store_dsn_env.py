"""Ticket 122: per-side compare store DSNs resolve from the environment.

Keeps credentials out of shell history / the process list. Precedence:
``--<side>-store`` > ``--<side>-store-env VAR`` > ``CRAWLER_CLI_<SIDE>_POSTGRES_DSN``.
"""

import pytest

from crawler_cli.__main__ import _build_parser, _resolve_store_dsn, store_dsn_env_vars

INLINE = "postgresql://inline/db"
VIA_ENV_FLAG = "postgresql://env-flag/db"
VIA_FIXED_ENV = "postgresql://fixed-env/db"


def _compare_args(argv):
    return _build_parser().parse_args(["compare", *argv])


def _compare_urls_args(argv):
    return _build_parser().parse_args(["compare-urls", "--pairs", "m.csv", *argv])


def test_env_var_names_follow_build_dsn_prefixes():
    assert store_dsn_env_vars("baseline") == (
        "CRAWLER_CLI_BASELINE_POSTGRES_DSN",
        "PostgreSQLCrawler_BASELINE_POSTGRES_DSN",
    )
    assert store_dsn_env_vars("target")[0] == "CRAWLER_CLI_TARGET_POSTGRES_DSN"


def test_none_when_nothing_configured():
    args = _compare_args(["a.json", "b.json"])
    assert _resolve_store_dsn(args, "baseline") is None
    assert _resolve_store_dsn(args, "candidate") is None


def test_fixed_env_var_is_used(monkeypatch):
    monkeypatch.setenv("CRAWLER_CLI_BASELINE_POSTGRES_DSN", VIA_FIXED_ENV)
    args = _compare_args(["a.json", "b.json"])
    assert _resolve_store_dsn(args, "baseline") == VIA_FIXED_ENV
    # Sides are independent.
    assert _resolve_store_dsn(args, "candidate") is None


def test_legacy_prefix_env_var_is_used(monkeypatch):
    monkeypatch.setenv("PostgreSQLCrawler_CANDIDATE_POSTGRES_DSN", VIA_FIXED_ENV)
    args = _compare_args(["a.json", "b.json"])
    assert _resolve_store_dsn(args, "candidate") == VIA_FIXED_ENV


def test_store_env_flag_beats_fixed_env_var(monkeypatch):
    monkeypatch.setenv("CRAWLER_CLI_BASELINE_POSTGRES_DSN", VIA_FIXED_ENV)
    monkeypatch.setenv("MY_DEV_DSN", VIA_ENV_FLAG)
    args = _compare_args(["a.json", "b.json", "--baseline-store-env", "MY_DEV_DSN"])
    assert _resolve_store_dsn(args, "baseline") == VIA_ENV_FLAG


def test_inline_flag_wins_over_everything(monkeypatch):
    monkeypatch.setenv("CRAWLER_CLI_BASELINE_POSTGRES_DSN", VIA_FIXED_ENV)
    monkeypatch.setenv("MY_DEV_DSN", VIA_ENV_FLAG)
    args = _compare_args(
        ["a.json", "b.json", "--baseline-store", INLINE, "--baseline-store-env", "MY_DEV_DSN"]
    )
    assert _resolve_store_dsn(args, "baseline") == INLINE


def test_store_env_flag_naming_unset_var_raises(monkeypatch):
    monkeypatch.delenv("NOPE_DSN", raising=False)
    args = _compare_args(["a.json", "b.json", "--baseline-store-env", "NOPE_DSN"])
    with pytest.raises(ValueError, match="NOPE_DSN"):
        _resolve_store_dsn(args, "baseline")


def test_store_env_flag_naming_empty_var_raises(monkeypatch):
    monkeypatch.setenv("EMPTY_DSN", "")
    args = _compare_args(["a.json", "b.json", "--baseline-store-env", "EMPTY_DSN"])
    with pytest.raises(ValueError, match="EMPTY_DSN"):
        _resolve_store_dsn(args, "baseline")


@pytest.mark.parametrize("side", ["source", "target"])
def test_compare_urls_sides_resolve_from_env(monkeypatch, side):
    monkeypatch.setenv(f"CRAWLER_CLI_{side.upper()}_POSTGRES_DSN", VIA_FIXED_ENV)
    args = _compare_urls_args([])
    assert _resolve_store_dsn(args, side) == VIA_FIXED_ENV


@pytest.mark.parametrize("side", ["source", "target"])
def test_compare_urls_inline_and_env_flag(monkeypatch, side):
    monkeypatch.setenv("PAIR_DSN", VIA_ENV_FLAG)
    args = _compare_urls_args([f"--{side}-store-env", "PAIR_DSN"])
    assert _resolve_store_dsn(args, side) == VIA_ENV_FLAG

    args = _compare_urls_args([f"--{side}-store", INLINE])
    assert _resolve_store_dsn(args, side) == INLINE


def test_missing_attrs_namespace_is_tolerated():
    # Programmatic callers building a minimal Namespace must not blow up.
    import argparse

    assert _resolve_store_dsn(argparse.Namespace(), "baseline") is None
