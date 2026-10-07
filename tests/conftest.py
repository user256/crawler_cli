from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-playwright-smoke",
        action="store_true",
        default=False,
        help="Run real Chromium-backed Playwright smoke tests.",
    )


# Ticket 422: database-backed tests TRUNCATE every crawl table and one of them
# creates and drops a scratch database on the DSN's server. They must never be
# pointed at an operator database, so the DSN's database name has to carry this
# prefix, and database DDL needs a second, explicit opt-in.
TEST_DSN_ENV = "CRAWLER_CLI_TEST_DSN"
TEST_DATABASE_PREFIX = "crawler_cli_test_"
ALLOW_DATABASE_DDL_ENV = "CRAWLER_CLI_TEST_ALLOW_DATABASE_DDL"


def dsn_database_name(dsn: str) -> str:
    """Return the database name a libpq DSN (URL or key=value form) selects.

    An empty string means the DSN names no database (libpq would then fall
    back to the user name), which the guard treats as unsafe.
    """
    dsn = dsn.strip()
    if "://" in dsn:
        parsed = urlparse(dsn)
        query_names = parse_qs(parsed.query).get("dbname")
        if query_names:
            return query_names[-1]
        return parsed.path.lstrip("/").split("/")[0]
    name = ""
    for part in dsn.split():
        key, sep, value = part.partition("=")
        if sep and key.strip() == "dbname":
            name = value.strip().strip("'\"")
    return name


def check_test_dsn(dsn: str) -> None:
    """Raise pytest.UsageError unless ``dsn`` names a crawler_cli_test_* database.

    Plain ``str.startswith`` on the parsed name: never an SQL LIKE, whose ``_``
    is a wildcard (the 2026-06-05 incident).
    """
    name = dsn_database_name(dsn)
    if not name.startswith(TEST_DATABASE_PREFIX) or name == TEST_DATABASE_PREFIX:
        raise pytest.UsageError(
            f"{TEST_DSN_ENV} must name a scratch database whose name starts with "
            f"{TEST_DATABASE_PREFIX!r} (got {name or '<none>'!r}). The database-backed "
            "tests truncate every crawl table, so they refuse to run against any other "
            "database. See docs/testing-with-postgres.md."
        )


def pytest_configure(config: pytest.Config) -> None:
    dsn = os.environ.get(TEST_DSN_ENV, "")
    if dsn:
        check_test_dsn(dsn)


def database_ddl_allowed() -> bool:
    return os.environ.get(ALLOW_DATABASE_DDL_ENV, "") == "1"


@pytest.fixture
def allow_database_ddl() -> None:
    """Skip unless the run explicitly opted in to CREATE/DROP DATABASE (ticket 422)."""
    if not database_ddl_allowed():
        pytest.skip(f"creates and drops a database on the test server; set {ALLOW_DATABASE_DDL_ENV}=1 to run it")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-playwright-smoke"):
        return
    skip_playwright_smoke = pytest.mark.skip(
        reason="need --run-playwright-smoke to run real Chromium-backed Playwright smoke tests"
    )
    for item in items:
        if "playwright_smoke" in item.keywords:
            item.add_marker(skip_playwright_smoke)


# Postgres connection env vars that _build_dsn / _postgres_config_supplied read.
# A developer shell that exports these (e.g. CRAWLER_CLI_POSTGRES_DSN pointing at a
# local crawler DB) otherwise leaks into tests that assert the "no Postgres
# configured" default, silently flipping MemoryStore -> AsyncpgStore. Note: the
# integration suite's CRAWLER_CLI_TEST_DSN is deliberately NOT in this set.
_POSTGRES_ENV_VARS = tuple(
    f"{prefix}_{key}"
    for prefix in ("CRAWLER_CLI", "PostgreSQLCrawler")
    for key in (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_DSN",
        # Per-side compare store DSNs (ticket 122) — an exported
        # <SIDE>_POSTGRES_DSN would otherwise silently turn an artifact-only
        # compare into a store-backed one.
        "BASELINE_POSTGRES_DSN",
        "CANDIDATE_POSTGRES_DSN",
        "SOURCE_POSTGRES_DSN",
        "TARGET_POSTGRES_DSN",
    )
)


@pytest.fixture(autouse=True)
def _clear_postgres_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every test from ambient Postgres DSN env vars in the dev shell.

    Runs during setup, before the test body, so tests that intentionally set one
    of these via their own monkeypatch.setenv still see exactly what they set.
    """
    for var in _POSTGRES_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _disable_asyncpg_ssl_for_test_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ssl=False when running against CRAWLER_CLI_TEST_DSN.

    Local Docker Postgres can segfault in asyncpg's SSL probe under coverage
    tracing; CI's service container is fine either way. Only activates when the
    integration DSN is set so unit tests are untouched.
    """
    if not os.environ.get("CRAWLER_CLI_TEST_DSN"):
        return

    import asyncpg

    orig_pool = asyncpg.create_pool
    orig_connect = asyncpg.connect

    async def create_pool(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("ssl", False)
        return await orig_pool(*args, **kwargs)

    async def connect(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("ssl", False)
        return await orig_connect(*args, **kwargs)

    monkeypatch.setattr(asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(asyncpg, "connect", connect)


@pytest.fixture(autouse=True)
def _clear_registered_secrets() -> None:
    """Empty the process-wide secret registry between tests (ticket 153).

    ``crawler_cli.redaction.SECRETS`` is deliberately process-global: the CLI
    registers each credential once, at load time, and every scrubber then
    removes it verbatim. In a test session that would make one test's fixture
    credential redact another test's ordinary text, so the registry is cleared
    around every test.
    """
    from crawler_cli.redaction import SECRETS

    SECRETS.clear()
    yield
    SECRETS.clear()
