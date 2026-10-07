"""technical-audit on an older snapshot table, without a database (ticket 418).

A fake CrawlReports answers the column introspection queries from a chosen
column set and raises asyncpg's UndefinedColumnError when a query names a
snapshot column that set lacks, which is what PostgreSQL does on a table
created by an older crawler_cli.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections.abc import AsyncIterator, Iterable
from pathlib import Path

import asyncpg
import pytest

from crawler_cli.__main__ import _build_parser, _dispatch, _fetch_report
from crawler_cli.reports import SNAPSHOT_OPTIONAL_COLUMNS, TECHNICAL_AUDIT_REPORT_CAPABILITIES, CrawlReports
from crawler_cli.technical_audit import TECHNICAL_AUDIT_REPORTS

_SUPPLIED_REPORTS = {"inventory-interactions", "supplied-search-evidence"}


class _Store:
    closed = False

    async def get_crawl_run(self, run_id: str) -> dict[str, object]:
        return {"status": "complete", "mode": "crawl", "config": {}, "seed_urls": ["https://legacy.example/"]}

    async def frontier_stats(self, *, run_id: str) -> tuple[int, int, int]:
        return (0, 0, 0)

    async def iter_run_html(self, *, run_id: str) -> AsyncIterator[tuple[str, str]]:
        for item in ():
            yield item

    async def close(self) -> None:
        self.closed = True

    def __getattr__(self, name: str):  # any other store read finds nothing
        async def empty(*args: object, **kwargs: object) -> list[object]:
            return []

        return empty


class _SchemaReports(CrawlReports):
    """Answer SQL from a snapshot table that has only ``present`` optional columns."""

    present: frozenset[str] = frozenset(SNAPSHOT_OPTIONAL_COLUMNS)
    signatures = True

    def __init__(self, store: object, run_id: str | None = None) -> None:
        super().__init__(store, run_id=run_id)  # type: ignore[arg-type]
        self.queries: list[str] = []

    async def _run_id(self) -> str:
        return "legacy-run"

    async def _fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        self.queries.append(query)
        if "information_schema.columns" in query:
            return [{"column_name": name} for name in ("run_id", "url_id", "content_hash_simhash", *self.present)]
        if "information_schema.tables" in query:
            return [{"present": self.signatures}]
        # An output alias ("NULL::BOOLEAN AS content_extracted") is not a column read.
        reads = re.sub(r"\bAS\s+\w+", "", query, flags=re.IGNORECASE)
        missing = [
            column
            for column in SNAPSHOT_OPTIONAL_COLUMNS
            if column not in self.present and re.search(rf"\b{column}\b", reads)
        ]
        if missing:
            raise asyncpg.exceptions.UndefinedColumnError(f"column s.{missing[0]} does not exist")
        return []


def _reports_class(present: Iterable[str], *, signatures: bool) -> type[_SchemaReports]:
    return type("Reports", (_SchemaReports,), {"present": frozenset(present), "signatures": signatures})


def _audit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, reports: type[_SchemaReports]) -> dict[str, object]:
    store = _Store()
    monkeypatch.setattr("crawler_cli.__main__.CrawlReports", reports)
    monkeypatch.setattr("crawler_cli.__main__._store_from_args", lambda args: store)
    out = tmp_path / "audit.json"
    args = _build_parser().parse_args(["technical-audit", "--crawl-run-id", "legacy-run", "--out", str(out)])
    assert asyncio.run(_dispatch(args)) == 0
    assert store.closed
    return json.loads(out.read_text())


def test_technical_audit_runs_on_a_snapshot_table_without_any_newer_column(monkeypatch, tmp_path) -> None:
    payload = _audit(monkeypatch, tmp_path, _reports_class((), signatures=False))
    context = payload["run_context"]
    assert not any(context["schema_capabilities"][column] for column in SNAPSHOT_OPTIONAL_COLUMNS)
    assert context["heading_link_count"] is None
    assert context["locale_signature_count"] is None
    assert context["parsed_html_count"] is None
    checks = {check["id"]: check["status"] for check in payload["checks"]}
    for check_id in ("orphan-candidates", "internal-link-targets", "internal-authority", "image-markup"):
        assert checks[check_id] in {"partial", "unavailable"}, check_id


def test_locale_signature_count_needs_extraction_state_and_hreflang(monkeypatch, tmp_path) -> None:
    """A signatures table alone must not let the Q-locale query read missing snapshot columns."""
    present = [column for column in SNAPSHOT_OPTIONAL_COLUMNS if column not in {"content_extracted", "hreflang_json"}]
    payload = _audit(monkeypatch, tmp_path, _reports_class(present, signatures=True))
    assert payload["run_context"]["locale_signature_count"] is None
    assert payload["run_context"]["schema_capabilities"]["run_intent_signatures"] is True


def test_heading_link_count_is_unknown_without_links_json(monkeypatch, tmp_path) -> None:
    present = [column for column in SNAPSHOT_OPTIONAL_COLUMNS if column != "links_json"]
    payload = _audit(monkeypatch, tmp_path, _reports_class(present, signatures=True))
    assert payload["run_context"]["heading_link_count"] is None
    assert payload["run_context"]["heading_link_tested_count"] is None


def test_full_schema_still_collects_every_report(monkeypatch, tmp_path) -> None:
    fetched: list[str] = []

    async def record(reports: CrawlReports, name: str, args: argparse.Namespace) -> list[dict[str, object]]:
        fetched.append(name)
        return []

    monkeypatch.setattr("crawler_cli.__main__._fetch_report", record)
    _audit(monkeypatch, tmp_path, _reports_class(SNAPSHOT_OPTIONAL_COLUMNS, signatures=True))
    assert fetched == [name for name in TECHNICAL_AUDIT_REPORTS if name not in _SUPPLIED_REPORTS]


@pytest.mark.parametrize("name", [name for name in TECHNICAL_AUDIT_REPORTS if name not in _SUPPLIED_REPORTS])
def test_each_report_reads_only_its_declared_capabilities(name: str) -> None:
    """Keep TECHNICAL_AUDIT_REPORT_CAPABILITIES in step with the SQL each report issues.

    With only its declared optional columns present, a report must not name
    any other optional snapshot column (a report may still introspect and
    guard a column itself, as ``indexability`` does).
    """
    declared = TECHNICAL_AUDIT_REPORT_CAPABILITIES.get(name, ())
    assert set(declared) <= {*SNAPSHOT_OPTIONAL_COLUMNS, "content_hash_simhash", "run_intent_signatures"}
    reports = _reports_class(declared, signatures=True)(_Store())
    args = argparse.Namespace(simhash_threshold=4, similarity_limit=10)
    asyncio.run(_fetch_report(reports, name, args))
