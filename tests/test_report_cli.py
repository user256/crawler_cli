"""CLI wiring tests for the `report` subcommand.

The SQL behind CrawlReports is covered by the Postgres integration tests
(test_persistence_integration.py / test_persistence_coverage_gate.py); these
tests cover report selection, validation, output formats, and exit codes with
the store and reports stubbed out.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from crawler_cli.__main__ import _build_parser, _dispatch, _normalize_argv


class FakeStore:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeReports:
    instances: list["FakeReports"] = []

    def __init__(self, store, run_id=None) -> None:
        self.store = store
        self.run_id = run_id
        self.calls: list[tuple[str, dict[str, object]]] = []
        FakeReports.instances.append(self)

    async def orphan_pages(self):
        self.calls.append(("orphans", {}))
        return [{"url": "https://example.com/orphan"}]

    async def indexability_reasons(self):
        self.calls.append(("indexability", {}))
        return [
            {
                "url": "https://example.com/",
                "html_meta_allows": True,
                "http_header_allows": True,
                "overall_indexable": True,
            }
        ]

    async def redirect_chains(self):
        self.calls.append(("redirect-chains", {}))
        return [
            {
                "requested_url": "https://example.com/old",
                "final_url": "https://example.com/new",
                "initial_status_code": 301,
                "final_status_code": 200,
            }
        ]

    async def site_hub_pages(self, min_outlinks=5):
        self.calls.append(("hub-pages", {"min_outlinks": min_outlinks}))
        return [{"parent_url": "https://example.com/", "outlinks": 12}]

    async def slowest_pages(self, limit=50):
        self.calls.append(("slowest", {"limit": limit}))
        return [
            {
                "url": "https://example.com/slow",
                "ttfb_seconds": 1.2,
                "total_duration_seconds": 3.4,
                "final_status_code": 200,
            }
        ]

    async def worst_cwv_pages(self, limit=50):
        self.calls.append(("cwv", {"limit": limit}))
        return []

    async def analytics_inventory(self):
        self.calls.append(("analytics-inventory", {}))
        return [{"vendor": "ga4", "category": "analytics", "identifier": "G-TEST", "page_count": 3}]

    async def pages_missing_analytics(self, vendor=None):
        self.calls.append(("missing-analytics", {"vendor": vendor}))
        return [{"url": "https://example.com/untagged"}]

    async def pages_missing_expected_id(self, expected_id):
        self.calls.append(("missing-expected-id", {"expected_id": expected_id}))
        return [{"url": "https://example.com/wrong-id"}]


@pytest.fixture
def fake_reports(monkeypatch):
    FakeReports.instances = []
    store = FakeStore()
    monkeypatch.setattr("crawler_cli.__main__.CrawlReports", FakeReports)
    monkeypatch.setattr("crawler_cli.__main__._store_from_args", lambda args: store)
    return store


def _run(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    return asyncio.run(_dispatch(args))


def test_report_passes_through_normalize_argv():
    assert _normalize_argv(["report", "orphans"]) == ["report", "orphans"]


def test_default_runs_all_flagless_reports(fake_reports, capsys):
    assert _run(["report"]) == 0
    out = capsys.readouterr().out
    assert "# orphans (1 rows)" in out
    assert "https://example.com/orphan" in out
    assert "# cwv (0 rows)" in out
    assert "(no rows)" in out
    # missing-expected-id needs --expected-id, so the default set skips it
    assert "missing-expected-id" not in out
    assert fake_reports.closed is True


def test_explicit_selection_runs_only_named_reports(fake_reports, capsys):
    assert _run(["report", "orphans", "slowest", "--limit", "7"]) == 0
    calls = FakeReports.instances[-1].calls
    assert calls == [("orphans", {}), ("slowest", {"limit": 7})]


def test_hub_pages_forwards_min_outlinks(fake_reports):
    assert _run(["report", "hub-pages", "--min-outlinks", "9"]) == 0
    assert FakeReports.instances[-1].calls == [("hub-pages", {"min_outlinks": 9})]


def test_missing_analytics_forwards_vendor(fake_reports):
    assert _run(["report", "missing-analytics", "--vendor", "ga4"]) == 0
    assert FakeReports.instances[-1].calls == [("missing-analytics", {"vendor": "ga4"})]


def test_expected_id_joins_default_set(fake_reports):
    assert _run(["report", "--expected-id", "G-TEST"]) == 0
    called = [name for name, _ in FakeReports.instances[-1].calls]
    assert "missing-expected-id" in called


def test_missing_expected_id_without_flag_is_validation_error(fake_reports, capsys):
    assert _run(["report", "missing-expected-id"]) == 2
    assert "--expected-id" in capsys.readouterr().err


def test_unknown_report_is_validation_error(fake_reports, capsys):
    assert _run(["report", "orphan"]) == 2
    err = capsys.readouterr().err
    assert "unknown report" in err
    assert "orphans" in err  # error lists the valid names


def test_json_format_emits_object_keyed_by_report(fake_reports, capsys):
    assert _run(["report", "orphans", "cwv", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "orphans": [{"url": "https://example.com/orphan"}],
        "cwv": [],
    }


def test_json_out_writes_file(fake_reports, tmp_path):
    out = tmp_path / "report.json"
    assert _run(["report", "orphans", "--format", "json", "--out", str(out)]) == 0
    assert json.loads(out.read_text()) == {"orphans": [{"url": "https://example.com/orphan"}]}


def test_csv_requires_out_directory(fake_reports, capsys):
    assert _run(["report", "orphans", "--format", "csv"]) == 2
    assert "--out" in capsys.readouterr().err


def test_csv_writes_one_file_per_report(fake_reports, tmp_path):
    out_dir = tmp_path / "reports"
    assert _run(["report", "orphans", "cwv", "--format", "csv", "--out", str(out_dir)]) == 0
    orphans = (out_dir / "orphans.csv").read_text()
    assert orphans.splitlines() == ["url", "https://example.com/orphan"]
    # empty reports still produce their file so consumers see the run happened
    assert (out_dir / "cwv.csv").read_text() == ""


def test_missing_snapshot_schema_is_clean_validation_error(fake_reports, capsys, monkeypatch):
    import asyncpg

    async def boom(self):
        raise asyncpg.exceptions.UndefinedTableError('relation "page_run_snapshots" does not exist')

    monkeypatch.setattr(FakeReports, "orphan_pages", boom)
    assert _run(["report", "orphans"]) == 2
    err = capsys.readouterr().err
    assert "snapshot schema" in err
    assert "Traceback" not in err
    assert fake_reports.closed is True


def test_table_out_writes_file(fake_reports, tmp_path):
    out = tmp_path / "report.txt"
    assert _run(["report", "orphans", "--out", str(out)]) == 0
    assert "# orphans (1 rows)" in out.read_text()
