from __future__ import annotations

from pathlib import Path
import re

from crawler_cli.technical_audit import (
    TECHNICAL_AUDIT_CHECK_CONTRACT,
    audit_sheet_tables,
    build_technical_audit,
)
from crawler_cli.technical_audit_tickets import (
    TICKET_COLUMNS,
    build_ticket_register,
    load_ticket_language,
    ticketed_check_ids,
)


def _skill_contract_ids() -> list[str]:
    skill = Path(__file__).parents[1] / "skills" / "technical-seo-audit" / "SKILL.md"
    contract = skill.read_text().split("## Result model", maxsplit=1)[0]
    return re.findall(r"^\| `([^`]+)` \|", contract, flags=re.MULTILINE)


def test_runtime_contract_matches_the_skill_exactly():
    contract_ids = [item["id"] for item in TECHNICAL_AUDIT_CHECK_CONTRACT]
    language = load_ticket_language()
    language_checks = language["checks"]

    assert contract_ids == _skill_contract_ids()
    assert len(contract_ids) == 44
    assert len(contract_ids) == len(set(contract_ids))
    assert all(item["required_evidence"] and item["owner_ticket"] for item in TECHNICAL_AUDIT_CHECK_CONTRACT)
    assert list(language_checks) == contract_ids
    assert tuple(language["target_template"]["columns"]) == TICKET_COLUMNS
    for entry in language_checks.values():
        if entry.get("ticket") is False:
            continue
        assert all(entry.get(field) for field in ("label", "description", "suggested_solution", "acceptance_criteria"))


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
    assert statuses["near-duplicate-content"] == "unavailable"
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
    # Ticket 428: Overview lists the run metadata and only the checks with affected rows.
    titles = {str(check["title"]): check for check in audit["checks"]}
    check_rows = [row for row in tables["Overview"][1:] if row[0] in titles]
    assert check_rows == [[titles_of_finding, "finding"] for titles_of_finding in _finding_titles(audit)]
    assert len(check_rows) == 1


def _finding_titles(audit):
    return [str(check["title"]) for check in audit["checks"] if check["evidence"]]


def test_sheet_tables_report_ticketed_checks_without_rows_but_no_other_non_issues():
    # Ticket 428: an unavailable check that raises a collection ticket is an
    # issue; unavailable and passing checks without a ticket are not published.
    audit = build_technical_audit(crawl_run_id="run-1", reports={})
    ticketed = ticketed_check_ids(audit, load_ticket_language())
    assert ticketed and len(ticketed) == len(build_ticket_register(audit, load_ticket_language()))
    tables = audit_sheet_tables(audit, ticketed)

    titles = {str(check["id"]): str(check["title"]) for check in audit["checks"]}
    listed = {row[0] for row in tables["Overview"][1:]}
    assert {titles[identifier] for identifier in ticketed} <= listed
    assert not {titles[identifier] for identifier in set(titles) - ticketed} & listed
    assert set(tables) == {"Overview", "Audit Log"}  # no affected rows, so no detail tabs
    # Without the ticketed IDs only checks with affected rows are listed: none here.
    assert {row[0] for row in audit_sheet_tables(audit)["Overview"][1:]}.isdisjoint(titles.values())


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


def test_locale_inventory_and_search_questions_produce_evidence_backed_tickets():
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={
            "locale-content-alignment": [
                {
                    "url": "https://example.test/fr/game",
                    "html_lang": "fr",
                    "languages": "en, fr",
                    "peer_urls": "https://example.test/en/game",
                }
            ],
            "inventory-interactions": [
                {
                    "source_url": "https://example.test/games",
                    "action": "Load more",
                    "initial_document_url_count": 24,
                    "post_interaction_document_url_count": 48,
                    "requires_interaction": True,
                }
            ],
            "supplied-search-evidence": [
                {
                    "url": "https://example.test/fr/game",
                    "source": "url_inspection",
                    "export_date": "2026-09-28",
                    "is_issue": True,
                    "issue_reason": "Google-selected canonical differs from the declared canonical.",
                }
            ],
        },
        run_context={"completion_state": "complete", "locale_signature_count": 2},
    )
    statuses = {check["id"]: check["status"] for check in audit["checks"]}
    assert statuses["locale-html-lang"] == "finding"
    assert statuses["rendered-robots-links"] == "finding"
    assert statuses["supplied-search-evidence"] == "finding"

    tickets = build_ticket_register(audit, load_ticket_language())
    labels = {ticket["Label"] for ticket in tickets}
    assert "Locale pages reuse primary content across languages" in labels
    assert "Game or product inventory requires a user interaction" in labels
    search_ticket = next(
        ticket for ticket in tickets if ticket["Label"] == "Search Console reports issues the crawl cannot see"
    )
    assert "https://example.test/fr/game" in search_ticket["Notes / Documentation"]


def test_missing_material_inputs_create_specific_collection_tickets():
    audit = build_technical_audit(crawl_run_id="run-1", reports={})
    tickets = build_ticket_register(audit, load_ticket_language())
    labels = {ticket["Label"] for ticket in tickets}
    assert "Generate locale primary-content signatures" in labels
    assert "Capture inventory discovery before and after interaction" in labels
    assert "Grant Search Console access or supply exports" in labels


def test_passing_search_and_inventory_checks_publish_no_tested_evidence_tab():
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={
            "inventory-interactions": [
                {
                    "source_url": "https://example.test/games",
                    "action": "Load more",
                    "initial_document_url_count": 24,
                    "post_interaction_document_url_count": 24,
                    "requires_interaction": False,
                }
            ],
            "supplied-search-evidence": [
                {
                    "url": "https://example.test/game",
                    "source": "search_console",
                    "export_date": "2026-09-28",
                    "is_issue": False,
                }
            ],
        },
        run_context={"completion_state": "complete"},
    )

    tables = audit_sheet_tables(audit, ticketed_check_ids(audit, load_ticket_language()))

    # Ticket 428: the workbook reports actual issues only. The tested population
    # of a passing check stays in the audit JSON but gets no tab or Overview row.
    assert "Rendered robots links" not in tables and "Supplied search evidence" not in tables
    checks = {check["id"]: check for check in audit["checks"]}
    assert checks["rendered-robots-links"]["verified_evidence"][0]["source_url"] == "https://example.test/games"
    assert checks["supplied-search-evidence"]["verified_evidence"][0]["url"] == "https://example.test/game"
    listed = {row[0] for row in tables["Overview"][1:]}
    assert checks["rendered-robots-links"]["title"] not in listed
    assert checks["supplied-search-evidence"]["title"] not in listed
