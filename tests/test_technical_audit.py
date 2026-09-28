from __future__ import annotations

from pathlib import Path
import re

from crawler_cli.technical_audit import (
    TECHNICAL_AUDIT_CHECK_CONTRACT,
    audit_sheet_tables,
    build_technical_audit,
)


def _skill_contract_ids() -> list[str]:
    skill = Path(__file__).parents[1] / "skills" / "technical-seo-audit" / "SKILL.md"
    contract = skill.read_text().split("## Result model", maxsplit=1)[0]
    return re.findall(r"^\| `([^`]+)` \|", contract, flags=re.MULTILINE)


def test_runtime_contract_matches_the_skill_exactly():
    contract_ids = [item["id"] for item in TECHNICAL_AUDIT_CHECK_CONTRACT]

    assert contract_ids == _skill_contract_ids()
    assert len(contract_ids) == 44
    assert len(contract_ids) == len(set(contract_ids))
    assert all(item["required_evidence"] and item["owner_ticket"] for item in TECHNICAL_AUDIT_CHECK_CONTRACT)


def test_audit_is_stable_and_never_calls_candidate_checks_healthy():
    reports = {
        "indexability": [
            {
                "url": "https://example.test/a",
                "html_meta_allows": True,
                "http_header_allows": False,
                "content_extracted": True,
            },
            {
                "url": "https://example.test/b",
                "html_meta_allows": True,
                "http_header_allows": True,
                "content_extracted": True,
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
    context = {"completion_state": "complete", "parsed_html_count": 2, "hashed_count": 0}
    first = build_technical_audit(crawl_run_id="run-1", reports=reports, run_context=context)
    second = build_technical_audit(crawl_run_id="run-1", reports=reports, run_context=context)

    assert first == second
    statuses = {check["id"]: check["status"] for check in first["checks"]}
    assert statuses["indexability-segmentation"] == "finding"
    assert statuses["parameter-and-faceted-controls"] == "finding"
    assert statuses["near-duplicate-content"] == "not_applicable"
    assert first["check_registry"]
    assert "canonical-target-validation" in {item["id"] for item in first["check_registry"]}
    assert [check["id"] for check in first["checks"]] == [item["id"] for item in TECHNICAL_AUDIT_CHECK_CONTRACT]
    assert all(
        check["status"] in {"pass", "finding", "partial", "unavailable", "not_applicable"} for check in first["checks"]
    )
    assert first["check_id_aliases"]["tracking-parameter-links"] == "parameter-and-faceted-controls"
    assert len(first["audit_log"]) == 3


def test_sheet_tables_only_include_detail_tabs_with_evidence():
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={"tracking-parameter-links": [{"target_url": "https://e.test/?gclid=x"}]},
    )
    tables = audit_sheet_tables(audit)

    assert set(tables) == {"Overview", "Audit Log", "Tracking parameters"}
    assert tables["Audit Log"][0][0] == "Problem"
    assert tables["Tracking parameters"][0] == ["target_url"]


def test_missing_run_context_and_missing_source_are_not_reported_as_passes():
    audit = build_technical_audit(crawl_run_id="run-1", reports={"indexability": []})
    checks = {check["id"]: check for check in audit["checks"]}
    assert checks["indexability-segmentation"]["status"] == "partial"
    assert checks["near-duplicate-content"]["status"] == "unavailable"
    assert checks["indexability-segmentation"]["denominator"] is None
    assert checks["robots-controls"]["status"] == "unavailable"


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
