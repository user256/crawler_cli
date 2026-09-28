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
        self.updated_at = 123

    async def close(self) -> None:
        self.closed = True

    async def get_crawl_run(self, run_id):
        return {"run_id": run_id, "status": "complete", "updated_at": self.updated_at}


class FakeReports:
    instances: list["FakeReports"] = []

    def __init__(self, store, run_id=None) -> None:
        self.store = store
        self.run_id = run_id
        self.calls: list[tuple[str, dict[str, object]]] = []
        FakeReports.instances.append(self)

    async def _run_id(self):
        return self.run_id or "resolved-run"

    async def technical_audit_context(self):
        return {
            "run_id": self.run_id or "resolved-run",
            "run_status": "complete",
            "completion_state": "complete",
            "updated_at": 123,
            "parsed_html_count": 1,
            "hashed_count": 0,
            "image_reference_count": 0,
            "schema_capabilities": {
                "images_json": True,
                "links_json": True,
                "content_hash_simhash": True,
                "indexability_evidence_json": True,
            },
            "declared_allowed_hosts": ["example.com"],
            "seed_hosts": ["example.com"],
        }

    async def orphan_pages(self, *, known_urls=None):
        self.calls.append(("orphans", {} if known_urls is None else {"known_urls": known_urls}))
        if known_urls:
            return [
                {
                    "url": row["url"],
                    "candidate_type": "source_known_zero_observed_inlinks",
                    "observed_inlink_count": 0,
                    "graph_complete": True,
                    "is_crawled": False,
                    "source_labels": [row["source"]],
                    "source_observations": [row],
                    "live_validation_state": "not_requested",
                }
                for row in known_urls
            ]
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

    async def javascript_url_candidates(self):
        self.calls.append(("js-url-candidates", {}))
        return [
            {
                "source_url": "https://example.com/",
                "candidate_url": "https://example.com/hidden",
                "classification": "page",
                "follow_eligible": True,
            }
        ]

    async def css_url_candidates(self):
        self.calls.append(("css-url-candidates", {}))
        return []

    async def render_url_candidates(self):
        self.calls.append(("render-url-candidates", {}))
        return []

    async def render_attempts(self):
        self.calls.append(("render-attempts", {}))
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

    async def schema_compatibility(self):
        self.calls.append(("schema-compatibility", {}))
        return [
            {
                "url": "https://example.com/schema",
                "schema_type": "Thing",
                "parser_mode": "google-single-html-unescape-v1",
                "is_valid": True,
                "diagnostic_code": "jsonld_possible_double_escape",
                "severity": "warning",
                "script_position": 0,
                "json_pointer": "/name",
                "location_kind": "value",
                "evidence": "&amp;",
                "source_evidence": "&amp;amp;",
                "remediation": "Use JSON escapes.",
            }
        ]

    async def image_issues(self):
        self.calls.append(("image-issues", {}))
        return []

    async def internal_link_quality(self):
        self.calls.append(("internal-link-quality", {}))
        return []

    async def link_graph_metrics(self):
        self.calls.append(("link-graph-metrics", {}))
        return [{"graph_complete": True}]

    async def tracking_parameter_links(self):
        self.calls.append(("tracking-parameter-links", {}))
        return []

    async def near_duplicates(self, threshold=4, limit=5000):
        self.calls.append(("near-duplicates", {"threshold": threshold, "limit": limit}))
        return []

    async def internal_authority(self):
        self.calls.append(("internal-authority", {}))
        return []


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
    assert "js-url-candidates" not in out
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


def test_javascript_candidate_report_is_selectable(fake_reports):
    assert _run(["report", "js-url-candidates"]) == 0
    assert FakeReports.instances[-1].calls == [("js-url-candidates", {})]


def test_css_and_render_candidate_reports_are_selectable(fake_reports):
    assert _run(["report", "css-url-candidates", "render-url-candidates", "render-attempts"]) == 0
    assert FakeReports.instances[-1].calls == [
        ("css-url-candidates", {}),
        ("render-url-candidates", {}),
        ("render-attempts", {}),
    ]


def test_missing_analytics_forwards_vendor(fake_reports):
    assert _run(["report", "missing-analytics", "--vendor", "ga4"]) == 0
    assert FakeReports.instances[-1].calls == [("missing-analytics", {"vendor": "ga4"})]


def test_schema_compatibility_report_is_selectable(fake_reports, capsys):
    assert _run(["report", "schema-compatibility"]) == 0
    assert FakeReports.instances[-1].calls == [("schema-compatibility", {})]
    out = capsys.readouterr().out
    assert "jsonld_possible_double_escape" in out
    assert "https://example.com/schema" in out


def test_audit_extension_reports_are_selectable(fake_reports):
    assert (
        _run(
            [
                "report",
                "image-issues",
                "internal-link-quality",
                "tracking-parameter-links",
                "near-duplicates",
                "internal-authority",
                "--simhash-threshold",
                "6",
                "--similarity-limit",
                "250",
            ]
        )
        == 0
    )
    assert FakeReports.instances[-1].calls == [
        ("image-issues", {}),
        ("internal-link-quality", {}),
        ("tracking-parameter-links", {}),
        ("near-duplicates", {"threshold": 6, "limit": 250}),
        ("internal-authority", {}),
    ]


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


def test_technical_audit_writes_deterministic_bundle(fake_reports, tmp_path, capsys):
    out = tmp_path / "technical-audit.json"
    known_urls = tmp_path / "known-urls.csv"
    known_urls.write_text(
        "url,source\nhttps://example.com/landing,search_console\n",
        encoding="utf-8",
    )
    assert (
        _run(
            [
                "technical-audit",
                "--crawl-run-id",
                "run-42",
                "--known-url-inventory",
                str(known_urls),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    payload = json.loads(out.read_text())
    assert payload["crawl_run_id"] == "run-42"
    assert payload["schema_version"] == "crawler-cli/technical-audit/1"
    assert payload["run_context"]["snapshot_consistency"] == "stable"
    assert {check["id"] for check in payload["checks"]} >= {
        "tracking-parameter-links",
        "schema-parser-defects",
        "orphan-candidates",
    }
    assert "Wrote deterministic technical audit" in capsys.readouterr().out
    calls = FakeReports.instances[-1].calls
    called = [name for name, _ in calls]
    orphan_call = next(args for name, args in calls if name == "orphans")
    assert orphan_call["known_urls"] == [{"url": "https://example.com/landing", "source": "search_console"}]
    assert called == [
        "orphans",
        "indexability",
        "redirect-chains",
        "schema-compatibility",
        "image-issues",
        "internal-link-quality",
        "link-graph-metrics",
        "tracking-parameter-links",
        "near-duplicates",
        "internal-authority",
    ]


def test_technical_audit_downgrades_a_run_changed_during_collection(fake_reports, tmp_path):
    fake_reports.updated_at = 124
    out = tmp_path / "technical-audit.json"
    assert _run(["technical-audit", "--crawl-run-id", "run-42", "--out", str(out)]) == 0
    payload = json.loads(out.read_text())
    assert payload["run_context"]["snapshot_consistency"] == "changed_during_collection"
    assert payload["run_context"]["completion_state"] == "partial"
    assert all(check["status"] != "pass" for check in payload["checks"])


def test_live_recheck_requires_explicit_scope_manifest(fake_reports, tmp_path, capsys):
    out = tmp_path / "technical-audit.json"
    assert _run(["technical-audit", "--recheck-live", "--out", str(out)]) == 2
    assert "--recheck-live requires --scope-manifest" in capsys.readouterr().err
    assert fake_reports.closed is True


def test_live_recheck_includes_known_urls_with_scope_and_records_selection(fake_reports, tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from crawler_cli.authorisation import SCOPE_MANIFEST_SCHEMA_VERSION

    now = datetime.now(UTC)
    manifest = tmp_path / "scope.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": SCOPE_MANIFEST_SCHEMA_VERSION,
                "authorization_reference": "CHANGE-1234",
                "operator": "audit-test",
                "valid_from": (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "valid_until": (now + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "allowed_origins": ["https://example.com"],
                "allowed_path_prefixes": ["/"],
            }
        ),
        encoding="utf-8",
    )
    known_urls = tmp_path / "known.csv"
    known_urls.write_text(
        "url,source\nhttps://example.com/known,search_console\n",
        encoding="utf-8",
    )
    captured = {}

    async def collect(targets, **kwargs):
        selected = list(targets)
        captured["targets"] = selected
        captured["kwargs"] = kwargs
        return {url: {"state": "responsive", "attempts": [{"status": 200}]} for url in selected}

    monkeypatch.setattr("crawler_cli.__main__.collect_live_rechecks", collect)
    out = tmp_path / "audit.json"
    assert (
        _run(
            [
                "technical-audit",
                "--crawl-run-id",
                "run-42",
                "--known-url-inventory",
                str(known_urls),
                "--recheck-live",
                "--scope-manifest",
                str(manifest),
                "--out",
                str(out),
            ]
        )
        == 0
    )

    payload = json.loads(out.read_text())
    assert captured["targets"] == ["https://example.com/known"]
    assert captured["kwargs"]["allowed_hosts"] == ["example.com"]
    assert payload["run_context"]["audit_options"]["known_url_recheck_selected_count"] == 1
    assert payload["known_url_inventory"][0]["live_validation_state"] == "responsive"


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
