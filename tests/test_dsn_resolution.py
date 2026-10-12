"""crawler_cli.dsn: the database a DSN selects, resolved as asyncpg resolves it.

The --confirm check, delete-crawl and AsyncpgStore.drop_crawl_database act on
this name, so it must be the database asyncpg connects to, and anything
ambiguous must be refused rather than guessed (never a "postgres" default).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from crawler_cli import __main__ as cli
from crawler_cli import persistence
from crawler_cli.dsn import AmbiguousDatabaseError, resolve_dsn_database
from crawler_cli.persistence import AsyncpgStore, database_name_from_dsn

_NO_ENV: dict[str, str] = {}

_RESOLVED: list[tuple[str, dict[str, str], str]] = [
    ("postgresql://user@host/dbname", _NO_ENV, "dbname"),
    ("postgresql://u:p@localhost:5432/crawler", _NO_ENV, "crawler"),
    ("postgres://u@h/site_crawler?sslmode=disable", _NO_ENV, "site_crawler"),
    ("postgresql://u@h/crawler?sslmode=require&application_name=x", _NO_ENV, "crawler"),
    ("postgresql://u@h/crawler?dbname=crawler", _NO_ENV, "crawler"),
    ("postgresql://u@h/crawler?database=crawler", _NO_ENV, "crawler"),
    ("postgresql://u@h/%63rawler", _NO_ENV, "crawler"),
    ("postgresql://u@h/a/b", _NO_ENV, "a/b"),
    ("postgresql://u@h?dbname=crawler", _NO_ENV, "crawler"),
    ("postgresql://u@h?sslmode=disable&database=crawler", _NO_ENV, "crawler"),
    ("postgresql://u@h:5432", {"PGDATABASE": "envdb"}, "envdb"),
    ("postgresql://u@h/pathdb", {"PGDATABASE": "envdb"}, "pathdb"),
    ("postgresql:///crawler?host=/var/run/postgresql", _NO_ENV, "crawler"),
]


@pytest.mark.parametrize(("dsn", "env", "expected"), _RESOLVED)
def test_resolver_matches_asyncpg(
    dsn: str, env: dict[str, str], expected: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert resolve_dsn_database(dsn, environ=env) == expected
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
    assert params.database == expected


_AMBIGUOUS: list[tuple[str, dict[str, str]]] = [
    ("postgresql://u@h/crawler?dbname=crawler_cli_test_qa", _NO_ENV),
    ("postgresql://u@h/crawler?database=other", _NO_ENV),
    ("postgresql://u@h/%63rawler?dbname=other", _NO_ENV),
    ("postgresql://u@h/crawler?dbname=", _NO_ENV),
    ("postgresql://u@h?dbname=a&database=b", _NO_ENV),
    ("postgresql://u@h?dbname=a&dbname=a", _NO_ENV),
    ("postgresql://u@h/crawler?dbname=bad&x", _NO_ENV),
    ("postgresql://u:p@localhost:5432", _NO_ENV),
    ("postgresql://u@h:5432", {"PGDATABASE": ""}),
    ("postgresql://u@h?service=svc", {"PGDATABASE": "envdb"}),
    ("postgresql://u@h", {"PGDATABASE": "envdb", "PGSERVICE": "svc"}),
    ("postgresql://u@h/", {"PGDATABASE": "envdb"}),
    ("postgresql://u@h/?dbname=crawler", _NO_ENV),
    ("host=localhost dbname=crawler", _NO_ENV),
    ("mysql://u@h/crawler", _NO_ENV),
]


@pytest.mark.parametrize(("dsn", "env"), _AMBIGUOUS)
def test_resolver_refuses_ambiguous_dsns(dsn: str, env: dict[str, str]) -> None:
    with pytest.raises(AmbiguousDatabaseError):
        resolve_dsn_database(dsn, environ=env)


def test_database_name_from_dsn_never_defaults_to_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PGDATABASE", raising=False)
    monkeypatch.delenv("PGSERVICE", raising=False)
    with pytest.raises(ValueError, match="user name"):
        database_name_from_dsn("postgresql://u@h:5432")
    assert database_name_from_dsn("postgresql://u@h/%63rawler?sslmode=disable") == "crawler"


# --- --confirm ---------------------------------------------------------------


def _confirm_args(confirm: str | None, *, dry_run: bool = False) -> argparse.Namespace:
    return argparse.Namespace(confirm=confirm, dry_run=dry_run)


def test_confirm_compares_against_the_decoded_name() -> None:
    dsn = "postgresql://u@h/%63rawler?sslmode=disable"
    assert cli._require_confirm(_confirm_args("crawler"), dsn) is None
    assert cli._require_confirm(_confirm_args("%63rawler"), dsn) == 2


def test_confirm_with_the_query_name_does_not_authorise_the_path_database(capsys: pytest.CaptureFixture[str]) -> None:
    dsn = "postgresql://u@h/crawler?dbname=crawler_cli_test_qa"
    assert cli._require_confirm(_confirm_args("crawler_cli_test_qa"), dsn) == 2
    assert cli._require_confirm(_confirm_args("crawler"), dsn) == 2
    assert "in its path" in capsys.readouterr().err


def test_confirm_refuses_dsn_without_a_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PGDATABASE", raising=False)
    monkeypatch.delenv("PGSERVICE", raising=False)
    assert cli._require_confirm(_confirm_args("postgres"), "postgresql://u@h:5432") == 2
    assert "user name" in capsys.readouterr().err


def test_confirm_dry_run_needs_no_resolution() -> None:
    assert cli._require_confirm(_confirm_args(None, dry_run=True), "postgresql://u@h/a?dbname=b") is None


@pytest.mark.asyncio
async def test_delete_crawl_refuses_ambiguous_dsn_before_connecting(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_store(_args: argparse.Namespace) -> AsyncpgStore:
        raise AssertionError("delete-crawl connected before resolving the database")

    monkeypatch.setattr(cli, "_store_from_args", no_store)
    args = argparse.Namespace(
        postgres_dsn="postgresql://u:p@127.0.0.1:1/crawler?dbname=crawler_cli_test_qa",
        mode="drop-database",
        maintenance_dsn=None,
        confirm="crawler_cli_test_qa",
        dry_run=False,
    )
    assert await cli._run_delete_crawl(args) == 2
    assert "Refusing to delete" in capsys.readouterr().err


# --- drop_crawl_database -------------------------------------------------------


class _FakeAdmin:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    async def execute(self, sql: str, *args: Any) -> None:
        self.executed.append((sql, args))

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_connect(monkeypatch: pytest.MonkeyPatch) -> tuple[list[str], _FakeAdmin]:
    connected: list[str] = []
    admin = _FakeAdmin()

    async def connect(dsn: str, *args: Any, **kwargs: Any) -> _FakeAdmin:
        connected.append(dsn)
        return admin

    monkeypatch.setattr(persistence.asyncpg, "connect", connect)
    monkeypatch.delenv("PGDATABASE", raising=False)
    monkeypatch.delenv("PGSERVICE", raising=False)
    return connected, admin


@pytest.mark.asyncio
async def test_drop_targets_exactly_the_database_asyncpg_connects_to(
    fake_connect: tuple[list[str], _FakeAdmin],
) -> None:
    connected, admin = fake_connect
    await AsyncpgStore("postgresql://u:p@h:5432/%63rawler_x?sslmode=require").drop_crawl_database()
    # Same server, maintenance database, query (sslmode) preserved.
    assert connected == ["postgresql://u:p@h:5432/postgres?sslmode=require"]
    assert admin.executed[0][1] == ("crawler_x",)
    assert admin.executed[1][0] == 'DROP DATABASE IF EXISTS "crawler_x"'
    assert admin.closed


@pytest.mark.asyncio
async def test_drop_default_maintenance_dsn_keeps_host_but_not_database_params(
    fake_connect: tuple[list[str], _FakeAdmin],
) -> None:
    connected, admin = fake_connect
    await AsyncpgStore("postgresql:///crawler_x?host=/tmp/pg&dbname=crawler_x").drop_crawl_database()
    assert connected == ["postgresql:///postgres?host=%2Ftmp%2Fpg"]
    assert admin.executed[1][0] == 'DROP DATABASE IF EXISTS "crawler_x"'


@pytest.mark.asyncio
async def test_drop_quotes_the_identifier(fake_connect: tuple[list[str], _FakeAdmin]) -> None:
    _, admin = fake_connect
    await AsyncpgStore("postgresql://u@h/we%22ird").drop_crawl_database()
    assert admin.executed[1][0] == 'DROP DATABASE IF EXISTS "we""ird"'


@pytest.mark.parametrize(
    ("dsn", "maintenance", "match"),
    [
        ("postgresql://u@h/crawler?dbname=crawler_cli_test_qa", None, "in its path"),
        ("postgresql://u@h:5432", None, "user name"),
        ("postgresql://u@h/", None, "empty database"),
        ("postgresql://u@h/postgres", None, "protected"),
        ("postgresql://u@h/template0", None, "protected"),
        ("postgresql://u@h/template1", None, "protected"),
        ("postgresql://u@h/crawler_x", "postgresql://u@h/crawler_x", "same database"),
        ("postgresql://u@h/crawler_x", "postgresql://u@h/maint?dbname=crawler_x", "maintenance DSN"),
        ("postgresql://u@h/crawler_x", "postgresql://u@h", "maintenance DSN"),
    ],
)
@pytest.mark.asyncio
async def test_drop_refuses_ambiguous_or_protected_targets(
    fake_connect: tuple[list[str], _FakeAdmin], dsn: str, maintenance: str | None, match: str
) -> None:
    connected, admin = fake_connect
    with pytest.raises(ValueError, match=match):
        await AsyncpgStore(dsn).drop_crawl_database(maintenance_dsn=maintenance)
    assert connected == []
    assert admin.executed == []
