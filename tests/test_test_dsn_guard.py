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


# A clean environment: no PGDATABASE / PGSERVICE leaking in from the dev shell.
_NO_ENV: dict[str, str] = {}

# DSNs the guard accepts, with the database asyncpg connects to and the env.
_ACCEPTED: list[tuple[str, dict[str, str], str]] = [
    ("postgresql://u:p@localhost:5432/crawler_cli_test_ci", _NO_ENV, "crawler_cli_test_ci"),
    ("postgres://u@h/crawler_cli_test_x?sslmode=disable", _NO_ENV, "crawler_cli_test_x"),
    ("postgresql://u:p@localhost:5432/crawler_cli_test_t422", _NO_ENV, "crawler_cli_test_t422"),
    # Path and query agree.
    ("postgresql://u@h/crawler_cli_test_q?dbname=crawler_cli_test_q", _NO_ENV, "crawler_cli_test_q"),
    ("postgresql://u@h/crawler_cli_test_q?database=crawler_cli_test_q", _NO_ENV, "crawler_cli_test_q"),
    # Percent-encoded path is decoded the way asyncpg decodes it.
    ("postgresql://u@h/%63rawler_cli_test_enc", _NO_ENV, "crawler_cli_test_enc"),
    # No path: the query parameter applies.
    ("postgresql://u@h?dbname=crawler_cli_test_qp", _NO_ENV, "crawler_cli_test_qp"),
    ("postgresql://u@h?sslmode=disable&database=crawler_cli_test_qp", _NO_ENV, "crawler_cli_test_qp"),
    # No path, no query: PGDATABASE, exactly as asyncpg falls back.
    ("postgresql://u@h:5432", {"PGDATABASE": "crawler_cli_test_env"}, "crawler_cli_test_env"),
    # A path makes PGDATABASE irrelevant (asyncpg ignores it).
    ("postgresql://u@h/crawler_cli_test_p", {"PGDATABASE": "crawler"}, "crawler_cli_test_p"),
]


@pytest.mark.parametrize(("dsn", "env", "expected"), _ACCEPTED)
def test_accepted_dsn_resolves_to_the_database_asyncpg_selects(dsn: str, env: dict[str, str], expected: str) -> None:
    assert dsn_database_name(dsn, environ=env) == expected
    check_test_dsn(dsn, environ=env)


@pytest.mark.parametrize(("dsn", "env", "expected"), _ACCEPTED)
def test_guard_matches_asyncpg_own_parser(
    dsn: str, env: dict[str, str], expected: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """For every DSN the guard lets through, asyncpg connects to that very database."""
    connect_utils = pytest.importorskip("asyncpg.connect_utils")
    for var in ("PGDATABASE", "PGSERVICE", "PGSERVICEFILE", "PGUSER", "PGHOST", "PGPORT"):
        monkeypatch.delenv(var, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    _, params = connect_utils._parse_connect_dsn_and_args(
        dsn=dsn,
        host=None,
        port=None,
        user=None,
        password=None,
        passfile=None,
        database=None,
        ssl=None,
        service=None,
        servicefile=str(tmp_path / "no-pg_service.conf"),
        direct_tls=None,
        server_settings=None,
        target_session_attrs=None,
        krbsrvname=None,
        gsslib=None,
    )
    assert params.database == expected == dsn_database_name(dsn, environ=env)


def test_qa_finding_query_dbname_cannot_mask_operator_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """2026-10 QA (P1): the old guard read ?dbname= but asyncpg connects to the path."""
    dsn = "postgresql://u@h/crawler?dbname=crawler_cli_test_qa"
    connect_utils = pytest.importorskip("asyncpg.connect_utils")
    monkeypatch.delenv("PGDATABASE", raising=False)
    _, params = connect_utils._parse_connect_dsn_and_args(
        dsn=dsn,
        host=None,
        port=None,
        user=None,
        password=None,
        passfile=None,
        database=None,
        ssl=None,
        service=None,
        servicefile=str(tmp_path / "no-pg_service.conf"),
        direct_tls=None,
        server_settings=None,
        target_session_attrs=None,
        krbsrvname=None,
        gsslib=None,
    )
    assert params.database == "crawler"
    with pytest.raises(pytest.UsageError, match="'crawler' in its path"):
        check_test_dsn(dsn, environ=_NO_ENV)


@pytest.mark.parametrize(
    ("dsn", "env"),
    [
        ("postgresql://u:p@localhost:5432/crawler", _NO_ENV),
        ("postgresql://u:p@localhost:5432/crawler_test", _NO_ENV),
        # Would match SQL LIKE 'crawler_cli_test_%' ('_' is a wildcard); startswith refuses it.
        ("postgresql://u:p@localhost:5432/crawlerXcliXtestXci", _NO_ENV),
        ("postgresql://u:p@localhost:5432/CRAWLER_CLI_TEST_ci", _NO_ENV),
        ("postgresql://u:p@localhost:5432/crawler_cli_test_", _NO_ENV),
        ("postgresql://u:p@localhost:5432/postgres", _NO_ENV),
        # Path and query disagree, in either direction and for both parameter names.
        ("postgresql://u@h/crawler?dbname=crawler_cli_test_qa", _NO_ENV),
        ("postgresql://u@h/crawler?database=crawler_cli_test_qa", _NO_ENV),
        ("postgresql://u@h/crawler_cli_test_ci?dbname=crawler", _NO_ENV),
        ("postgresql://u@h/crawler_cli_test_ci?database=crawler", _NO_ENV),
        ("postgresql://u@h/%63rawler?dbname=crawler_cli_test_qa", _NO_ENV),
        ("postgresql://u@h/crawler_cli_test_ci?dbname=", _NO_ENV),
        # Percent-encoded operator name.
        ("postgresql://u@h/%63rawler", _NO_ENV),
        # Repeated or conflicting query parameters.
        ("postgresql://u@h?dbname=crawler_cli_test_a&database=crawler", _NO_ENV),
        ("postgresql://u@h?dbname=crawler&dbname=crawler_cli_test_a", _NO_ENV),
        ("postgresql://u@h?dbname=crawler_cli_test_a&dbname=crawler_cli_test_a", _NO_ENV),
        ("postgresql://u@h/crawler_cli_test_a?dbname=bad&x", _NO_ENV),
        # No database at all: asyncpg would fall back to PGDATABASE or the user name.
        ("postgresql://u:p@localhost:5432", _NO_ENV),
        ("postgresql://crawler_cli_test_user@localhost:5432", _NO_ENV),
        ("postgresql://u@h:5432", {"PGDATABASE": "crawler"}),
        ("postgresql://u@h:5432", {"PGDATABASE": ""}),
        ("postgresql://u@h?service=svc", {"PGDATABASE": "crawler_cli_test_env"}),
        ("postgresql://u@h", {"PGDATABASE": "crawler_cli_test_env", "PGSERVICE": "svc"}),
        # "/" is a path: asyncpg sends an empty name and the server picks the user.
        ("postgresql://u@h/", {"PGDATABASE": "crawler_cli_test_env"}),
        ("postgresql://u@h/?dbname=crawler_cli_test_q", _NO_ENV),
        # Not a URL asyncpg accepts.
        ("host=localhost dbname=crawler", _NO_ENV),
        ("dbname=crawler_cli_test_local host=/var/run/postgresql", _NO_ENV),
        ("mysql://u@h/crawler_cli_test_x", _NO_ENV),
    ],
)
def test_check_test_dsn_refuses_other_or_ambiguous_databases(dsn: str, env: dict[str, str]) -> None:
    with pytest.raises(pytest.UsageError, match="crawler_cli_test_"):
        check_test_dsn(dsn, environ=env)


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


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://nobody:nothing@127.0.0.1:1/crawler",
        # The QA finding: a test-looking ?dbname= must not mask the path's database.
        "postgresql://nobody:nothing@127.0.0.1:1/crawler?dbname=crawler_cli_test_qa",
    ],
)
def test_session_refuses_operator_dsn_before_any_test_runs(dsn: str) -> None:
    # Port 1 on localhost: even if the guard failed, nothing could connect.
    proc = _run_pytest(["tests/test_persistence_coverage_gate.py"], {TEST_DSN_ENV: dsn})
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
