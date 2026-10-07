"""Ticket 422: the database-backed tests refuse a non-scratch DSN and gate DDL."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import (
    ALLOW_DATABASE_DDL_ENV,
    TEST_DSN_ENV,
    check_test_dsn,
    database_ddl_allowed,
    dsn_database_name,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("dsn", "expected"),
    [
        ("postgresql://u:p@localhost:5432/crawler_cli_test_ci", "crawler_cli_test_ci"),
        ("postgres://u@h/crawler_cli_test_x?sslmode=disable", "crawler_cli_test_x"),
        ("postgresql://u@h/crawler?dbname=crawler_cli_test_q", "crawler_cli_test_q"),
        ("postgresql://u@h:5432", ""),
        ("host=localhost dbname=crawler_cli_test_kv user=u", "crawler_cli_test_kv"),
        ("host=localhost dbname='crawler' user=u", "crawler"),
        ("host=localhost user=u", ""),
    ],
)
def test_dsn_database_name_parses_url_and_keyword_forms(dsn: str, expected: str) -> None:
    assert dsn_database_name(dsn) == expected


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://u:p@localhost:5432/crawler_cli_test_ci",
        "postgresql://u:p@localhost:5432/crawler_cli_test_t422",
        "dbname=crawler_cli_test_local host=/var/run/postgresql",
    ],
)
def test_check_test_dsn_accepts_scratch_databases(dsn: str) -> None:
    check_test_dsn(dsn)


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://u:p@localhost:5432/crawler",
        "postgresql://u:p@localhost:5432/crawler_test",
        # Would match SQL LIKE 'crawler_cli_test_%' ('_' is a wildcard); startswith refuses it.
        "postgresql://u:p@localhost:5432/crawlerXcliXtestXci",
        "postgresql://u:p@localhost:5432/CRAWLER_CLI_TEST_ci",
        "postgresql://u:p@localhost:5432/crawler_cli_test_",
        "postgresql://u:p@localhost:5432",
        "postgresql://u:p@localhost:5432/postgres",
        "postgresql://u@h/crawler_cli_test_ci?dbname=crawler",
        "host=localhost dbname=crawler",
    ],
)
def test_check_test_dsn_refuses_other_databases(dsn: str) -> None:
    with pytest.raises(pytest.UsageError, match="crawler_cli_test_"):
        check_test_dsn(dsn)


def test_database_ddl_requires_exact_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ALLOW_DATABASE_DDL_ENV, raising=False)
    assert not database_ddl_allowed()
    for value in ("", "0", "true", "yes", " 1"):
        monkeypatch.setenv(ALLOW_DATABASE_DDL_ENV, value)
        assert not database_ddl_allowed()
    monkeypatch.setenv(ALLOW_DATABASE_DDL_ENV, "1")
    assert database_ddl_allowed()


def _run_pytest(args: list[str], env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in {TEST_DSN_ENV, ALLOW_DATABASE_DDL_ENV}}
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_session_refuses_operator_dsn_before_any_test_runs() -> None:
    # Port 1 on localhost: even if the guard failed, nothing could connect.
    proc = _run_pytest(
        ["tests/test_persistence_coverage_gate.py"],
        {TEST_DSN_ENV: "postgresql://nobody:nothing@127.0.0.1:1/crawler"},
    )
    assert proc.returncode == pytest.ExitCode.USAGE_ERROR, proc.stdout + proc.stderr
    assert "crawler_cli_test_" in proc.stderr


def test_drop_probe_skips_without_ddl_opt_in() -> None:
    # A well-named DSN on an unreachable port: the DDL gate must skip before connecting.
    proc = _run_pytest(
        [
            "-rs",
            "tests/test_persistence_coverage_gate.py::test_drop_crawl_database_isolated_from_test_dsn",
        ],
        {TEST_DSN_ENV: "postgresql://nobody:nothing@127.0.0.1:1/crawler_cli_test_guard"},
    )
    assert proc.returncode == pytest.ExitCode.OK, proc.stdout + proc.stderr
    assert "1 skipped" in proc.stdout
    assert ALLOW_DATABASE_DDL_ENV in proc.stdout
