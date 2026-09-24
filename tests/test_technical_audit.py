from __future__ import annotations

from crawler_cli.technical_audit import audit_sheet_tables, build_technical_audit


def test_audit_is_stable_and_never_calls_candidate_checks_healthy():
    reports = {
        "indexability": [
            {
                "url": "https://example.test/a",
                "html_meta_allows": True,
                "http_header_allows": False,
                "content_extracted": True,
                "directive_evidence": [
                    {"channel": "html_meta", "user_agent": "*", "raw_value": "index", "directives": ["index"]},
                    {
                        "channel": "http_header",
                        "user_agent": "*",
                        "raw_value": "noindex",
                        "directives": ["noindex"],
                    },
                ],
            },
            {
                "url": "https://example.test/b",
                "html_meta_allows": True,
                "http_header_allows": True,
                "content_extracted": True,
                "directive_evidence": [],
            },
        ],
        "tracking-parameter-links": [
            {
                "source_url": "https://example.test/",
                "target_url": "https://example.test/a?utm_source=nav",
                "tracking_parameters": "utm_source",
            }
        ],
        "schema-compatibility": [
            {
                "url": "https://example.test/a",
                "is_valid": False,
                "diagnostic_code": "bad-json",
                "evidence": "{",
                "remediation": "Fix JSON.",
            }
        ],
        "near-duplicates": [],
    }
    context = {
        "completion_state": "complete",
        "parsed_html_count": 2,
        "hashed_count": 0,
        "schema_capabilities": {"indexability_evidence_json": True},
    }
    first = build_technical_audit(crawl_run_id="run-1", reports=reports, run_context=context)
    second = build_technical_audit(crawl_run_id="run-1", reports=reports, run_context=context)

    assert first == second
    statuses = {check["id"]: check["status"] for check in first["checks"]}
    assert statuses["indexability-directive-conflicts"] == "finding"
    assert statuses["tracking-parameter-links"] == "finding"
    assert statuses["near-duplicate-content"] == "no_observations"
    assert first["check_registry"]
    assert "canonical-targets" in {item["id"] for item in first["check_registry"]}
    assert len(first["audit_log"]) == 3
    assert first["audit_log"][0]["Evidence Reference"] == "indexability-directive-conflicts"


def test_sheet_tables_only_include_detail_tabs_with_evidence():
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={"tracking-parameter-links": [{"target_url": "https://e.test/?gclid=x"}]},
    )
    tables = audit_sheet_tables(audit)

    assert set(tables) == {"Overview"}
    assert ["Client publication ready", False] in tables["Overview"]


def test_missing_run_context_and_missing_source_are_not_reported_as_passes():
    audit = build_technical_audit(crawl_run_id="run-1", reports={"indexability": []})
    checks = {check["id"]: check for check in audit["checks"]}
    assert checks["indexability-directive-conflicts"]["status"] == "unavailable"
    assert checks["near-duplicate-content"]["status"] == "unavailable"
    assert checks["indexability-directive-conflicts"]["denominator"] is None


def test_source_provenance_is_deterministic_and_distinguishes_missing_from_empty():
    reports = {"indexability": []}
    first = build_technical_audit(crawl_run_id="run-1", reports=reports)
    second = build_technical_audit(crawl_run_id="run-1", reports=reports)

    first_coverage = first["source_coverage"]
    second_coverage = second["source_coverage"]
    assert first_coverage == second_coverage
    assert first_coverage["indexability"]["available"] is True
    assert first_coverage["indexability"]["row_count"] == 0
    assert first_coverage["indexability"]["source_digest_sha256"]
    assert first_coverage["image-issues"]["available"] is False
    assert first_coverage["image-issues"]["source_digest_sha256"] is None
    assert first["parser"]
    assert first["structured_data_parser_mode"]


def test_legacy_rows_without_explicit_directive_evidence_are_unavailable():
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={
            "indexability": [
                {
                    "url": "https://e.test/",
                    "content_extracted": True,
                    "html_meta_allows": False,
                    "http_header_allows": True,
                }
            ]
        },
        run_context={
            "completion_state": "complete",
            "parsed_html_count": 1,
            "schema_capabilities": {"indexability_evidence_json": True},
        },
    )
    check = next(check for check in audit["checks"] if check["id"] == "indexability-directive-conflicts")
    assert check["status"] == "unavailable"
    assert check["evidence"] == []
