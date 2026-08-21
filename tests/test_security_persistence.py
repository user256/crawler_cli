"""Retention behaviour for the security tables (ticket 153).

Tickets 041 and 042 established the precedent for crawl data: retention is
always scoped to an exact run id, always offers a dry run that reports counts
without mutating anything, and never deletes by pattern. These tests hold the
security tables to the same rules.

They run against a recording connection double rather than a live PostgreSQL
instance, because what is being asserted is the shape of the SQL — which rows
are touched, and under which run id — rather than the behaviour of the server.
The integration suite exercises the same helpers against real PostgreSQL.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from crawler_cli.persistence import CRAWL_TABLES, SCHEMA_STATEMENTS
from crawler_cli.security_persistence import (
    SECURITY_SCHEMA_STATEMENTS,
    SECURITY_TABLES,
    delete_run_security_data,
    purge_run_security_evidence,
    record_run_retention,
    security_run_stats,
    store_finding_payload,
)


class RecordingConnection:
    """Records every statement and its arguments; returns canned counts."""

    def __init__(self, counts: dict[str, int] | None = None) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.fetched: list[tuple[str, tuple[Any, ...]]] = []
        self._counts = counts or {}

    async def execute(self, query: str, *args: Any) -> str:
        self.executed.append((" ".join(query.split()), args))
        return "OK"

    async def fetchval(self, query: str, *args: Any) -> Any:
        normalised = " ".join(query.split())
        self.fetched.append((normalised, args))
        for table, value in self._counts.items():
            if f"FROM {table} " in normalised or normalised.endswith(f"FROM {table}"):
                return value
        return 0

    def statements(self) -> list[str]:
        return [query for query, _ in self.executed]


# --- schema wiring ------------------------------------------------------------


def test_security_tables_are_part_of_the_main_schema() -> None:
    joined = "\n".join(SCHEMA_STATEMENTS)
    for table in SECURITY_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in joined


def test_security_tables_are_owned_by_crawler_cli() -> None:
    """They must appear in CRAWL_TABLES or a truncate/delete would miss them."""
    for table in SECURITY_TABLES:
        assert table in CRAWL_TABLES


def test_security_tables_are_truncated_before_their_parents() -> None:
    """Child rows precede crawl_runs so a cascade order is never ambiguous."""
    assert CRAWL_TABLES.index("security_evidence_raw") < CRAWL_TABLES.index("crawl_runs")
    assert CRAWL_TABLES.index("security_evidence_raw") < CRAWL_TABLES.index("security_findings")


def test_every_security_row_is_run_scoped() -> None:
    """A run id column is what makes exact-run retention possible at all."""
    for statement in SECURITY_SCHEMA_STATEMENTS:
        if "CREATE TABLE" in statement:
            assert "run_id TEXT" in statement
            assert "REFERENCES crawl_runs(run_id) ON DELETE CASCADE" in statement


# --- writing ---------------------------------------------------------------------


def test_store_finding_payload_writes_only_redacted_fields() -> None:
    conn = RecordingConnection()
    payload = {
        "schema_version": "crawler-cli/security-finding/1",
        "rule_id": "crawler-cli.test.rule",
        "title": "Title",
        "category": "cookies",
        "description": "Description",
        "severity": "medium",
        "confidence": "high",
        "status": "observed",
        "source": "response_header",
        "detector": "test",
        "detector_version": "1.0.0",
        "url": "https://example.com/?token=[REDACTED]",
        "url_digest": "hmac-sha256:abc",
        "host": "example.com",
        "observed_at": "2026-08-21T12:00:00Z",
        "evidence": {"cookie_name": "SESSIONID"},
        "evidence_truncated": False,
    }
    asyncio.run(store_finding_payload(conn, payload, run_id="run-153"))
    statement, args = conn.executed[0]
    assert statement.startswith("INSERT INTO security_findings")
    assert args[0] == "run-153"
    assert args[12] == "https://example.com/?token=[REDACTED]"
    assert json.loads(args[16]) == {"cookie_name": "SESSIONID"}


def test_record_run_retention_upserts_the_three_choices() -> None:
    conn = RecordingConnection()
    asyncio.run(
        record_run_retention(
            conn,
            run_id="run-153",
            retain_raw_html=False,
            retain_response_headers=True,
            retain_raw_security_evidence=False,
            note="authorised assessment",
        )
    )
    statement, args = conn.executed[0]
    assert "INSERT INTO security_run_retention" in statement
    assert args == ("run-153", False, True, False, "authorised assessment")


# --- retention ----------------------------------------------------------------------


def test_stats_count_each_security_table_for_one_run() -> None:
    conn = RecordingConnection({"security_findings": 4, "security_evidence_raw": 2, "security_run_retention": 1})
    stats = asyncio.run(security_run_stats(conn, run_id="run-153"))
    assert stats == {"security_findings": 4, "security_evidence_raw": 2, "security_run_retention": 1}
    assert all(args == ("run-153",) for _query, args in conn.fetched)
    assert all("WHERE run_id = $1" in query for query, _args in conn.fetched)


def test_dry_run_purge_reports_counts_and_changes_nothing() -> None:
    conn = RecordingConnection({"security_findings": 4, "security_evidence_raw": 2})
    result = asyncio.run(purge_run_security_evidence(conn, run_id="run-153", dry_run=True))
    assert result["raw_evidence_rows"] == 2
    assert result["dry_run"] == 1
    assert conn.executed == []


def test_purge_removes_raw_evidence_but_keeps_findings() -> None:
    conn = RecordingConnection({"security_evidence_raw": 2, "security_findings": 4})
    asyncio.run(purge_run_security_evidence(conn, run_id="run-153"))
    statements = conn.statements()
    assert any(statement.startswith("DELETE FROM security_evidence_raw") for statement in statements)
    assert not any(statement.startswith("DELETE FROM security_findings") for statement in statements)
    assert any("raw_evidence_purged_at" in statement for statement in statements)


def test_dropping_findings_is_a_separate_stronger_choice() -> None:
    conn = RecordingConnection({"security_evidence_raw": 2, "security_findings": 4})
    result = asyncio.run(purge_run_security_evidence(conn, run_id="run-153", drop_findings=True))
    assert result["finding_rows"] == 4
    assert any(statement.startswith("DELETE FROM security_findings") for statement in conn.statements())


def test_every_purge_statement_names_the_exact_run_id() -> None:
    conn = RecordingConnection()
    asyncio.run(purge_run_security_evidence(conn, run_id="run-153", drop_findings=True))
    for statement, args in conn.executed:
        assert "WHERE run_id = $1" in statement
        assert args == ("run-153",)
        assert "LIKE" not in statement.upper()


def test_delete_run_security_data_covers_every_security_table() -> None:
    conn = RecordingConnection()
    asyncio.run(delete_run_security_data(conn, run_id="run-153"))
    deleted = {statement.split()[2] for statement in conn.statements()}
    assert deleted == set(SECURITY_TABLES)
    assert all(args == ("run-153",) for _statement, args in conn.executed)


def test_delete_run_security_data_dry_run_changes_nothing() -> None:
    conn = RecordingConnection({"security_findings": 7})
    result = asyncio.run(delete_run_security_data(conn, run_id="run-153", dry_run=True))
    assert result["security_findings"] == 7
    assert result["dry_run"] == 1
    assert conn.executed == []


# --- CLI wiring ---------------------------------------------------------------------


def test_compact_crawl_exposes_separate_security_retention_flags() -> None:
    """Purging raw evidence and deleting findings are distinct CLI choices."""
    from crawler_cli.__main__ import _build_parser

    args = _build_parser().parse_args(["compact-crawl", "--crawl-run-id", "run-153", "--drop-security-evidence"])
    assert args.drop_security_evidence is True
    assert args.drop_security_findings is False
    assert args.crawl_run_id == "run-153"


def test_compact_crawl_security_flags_default_to_off() -> None:
    from crawler_cli.__main__ import _build_parser

    args = _build_parser().parse_args(["compact-crawl"])
    assert args.drop_security_evidence is False
    assert args.drop_security_findings is False
