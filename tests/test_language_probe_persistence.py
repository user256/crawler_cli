"""Ticket 264 read path: persisted language-probe evidence decodes JSONB text (ticket 401)."""

from __future__ import annotations

import asyncio
import json

import pytest

from crawler_cli.persistence import AsyncpgStore, _language_probe_evidence_row
from crawler_cli.reports import CrawlReports


class _Conn:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    async def fetchval(self, query: str, *args: object) -> bool:
        return True

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        return self.rows


class _Acquire:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    async def __aenter__(self) -> _Conn:
        return self.conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _Pool:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.conn = _Conn(rows)

    def acquire(self) -> _Acquire:
        return _Acquire(self.conn)


def test_language_probe_evidence_rows_are_decoded_from_jsonb_text() -> None:
    assert _language_probe_evidence_row('{"record_type": "coverage", "target_count": 2}') == {
        "record_type": "coverage",
        "target_count": 2,
    }
    assert _language_probe_evidence_row({"record_type": "candidate"}) == {"record_type": "candidate"}
    with pytest.raises(ValueError):
        _language_probe_evidence_row("[1, 2]")


def test_latest_language_probe_evidence_reads_jsonb_text_rows() -> None:
    store = AsyncpgStore(dsn="postgresql://unused/db")
    store.pool = _Pool(  # type: ignore[assignment]
        [
            {"evidence_json": json.dumps({"record_type": "coverage", "target_count": 1, "complete": True})},
            {"evidence_json": json.dumps({"record_type": "candidate", "candidate_type": "language_redirect"})},
        ]
    )
    rows = asyncio.run(store.latest_language_probe_evidence("run-1"))
    assert [row["record_type"] for row in rows] == ["coverage", "candidate"]


class _NoSessionStore:
    async def resolve_reporting_run_id(self, run_id: str | None) -> str:
        return "run-1"

    async def latest_language_probe_evidence(self, run_id: str) -> list[dict[str, object]]:
        return []


def test_unprobed_run_returns_a_non_coverage_placeholder() -> None:
    rows = asyncio.run(CrawlReports(_NoSessionStore()).accept_language_probes())  # type: ignore[arg-type]
    assert rows and rows[0]["record_type"] != "coverage" and rows[0]["state"] == "not_recorded"
