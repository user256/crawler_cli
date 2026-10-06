"""Regression tests for the master reconciliation QA fixes (tickets 400-401)."""

from __future__ import annotations

import asyncio
import json

import pytest

from crawler_cli.persistence import AsyncpgStore, _language_probe_evidence_row
from crawler_cli.reports import CrawlReports
from crawler_cli.technical_audit import build_technical_audit


class _Conn:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.queries: list[str] = []

    async def fetchval(self, query: str, *args: object) -> bool:
        self.queries.append(query)
        return True

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        self.queries.append(query)
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


# --- 401: ticket 264 read path -----------------------------------------------------


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
    assert rows[0]["target_count"] == 1


class _NoSessionStore:
    async def resolve_reporting_run_id(self, run_id: str | None) -> str:
        return "run-1"

    async def latest_language_probe_evidence(self, run_id: str) -> list[dict[str, object]]:
        return []


def test_unprobed_run_keeps_accept_language_detector_unavailable() -> None:
    reports = CrawlReports(_NoSessionStore())  # type: ignore[arg-type]
    rows = asyncio.run(reports.accept_language_probes())
    assert rows and rows[0]["record_type"] != "coverage"
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={"accept-language-probes": rows},
        run_context={"completion_state": "complete", "parsed_html_count": 1},
    )
    check = next(item for item in audit["detector_checks"] if item["id"] == "accept-language-variation")
    assert (check["status"], check["qualification"]) == ("unavailable", "requires_explicit_accept_language_probe")


# --- 400: the three post-contract detectors stay in the audit as detectors ---------


def test_post_contract_detectors_are_emitted_as_detector_checks() -> None:
    audit = build_technical_audit(
        crawl_run_id="run-1", reports={}, run_context={"completion_state": "complete", "parsed_html_count": 1}
    )
    detector_ids = {row["id"] for row in audit["detector_checks"]}
    control_ids = {row["id"] for row in audit["checks"]}
    for identifier in ("ai-crawler-governance", "accept-language-variation", "transport-security"):
        assert identifier in detector_ids and identifier not in control_ids


# --- 402: the external-link control sees real recheck evidence --------------------


def _recheck_rows(state: str, coverage_state: str = "complete") -> list[dict[str, object]]:
    return [
        {
            "record_type": "coverage",
            "record_kind": "external_link_recheck_coverage",
            "state": coverage_state,
            "attempted_target_count": 1,
            "out_of_scope_target_count": 0,
        },
        {
            "record_type": "observation",
            "record_kind": "external_link_recheck",
            "source_url": "https://example.com/a",
            "target_url": "https://partner.example/page",
            "state": state,
            "attempts": [],
        },
    ]


def _external_link_control(reports: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    audit = build_technical_audit(
        crawl_run_id="run-1", reports=reports, run_context={"completion_state": "complete", "parsed_html_count": 1}
    )
    return next(row for row in audit["checks"] if row["id"] == "external-link-integrity")


def test_external_link_control_is_unavailable_without_rechecks() -> None:
    control = _external_link_control({})
    assert control["status"] == "unavailable"


def test_external_link_control_finds_a_hard_recheck_failure() -> None:
    control = _external_link_control({"external-link-rechecks": _recheck_rows("http_failure")})
    assert control["status"] == "finding"
    assert control["affected_count"] == 1
    assert control["evidence"][0]["target_url"] == "https://partner.example/page"


def test_external_link_control_passes_only_on_a_complete_clean_recheck() -> None:
    assert _external_link_control({"external-link-rechecks": _recheck_rows("responsive")})["status"] == "pass"
    bounded = _external_link_control({"external-link-rechecks": _recheck_rows("responsive", "bounded")})
    assert bounded["status"] != "pass"
