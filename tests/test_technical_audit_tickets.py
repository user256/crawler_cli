from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from crawler_cli.google_sheets import GoogleSheetsTicketRegisterPublisher, ticket_register_payload
from crawler_cli.technical_audit_contract import TECHNICAL_AUDIT_CHECK_CONTRACT
from crawler_cli.technical_audit_tickets import (
    TICKET_TEMPLATE_COLUMNS,
    build_technical_audit_ticket_rows,
    load_ticket_language,
    technical_audit_ticket_overview,
)


def _audit() -> dict[str, object]:
    checks = [
        {
            "id": contract["id"],
            "status": "unavailable",
            "affected_count": 0,
            "tested_count": None,
            "denominator": None,
            "detail_sheet": contract["detail_sheet"],
            "required_evidence": contract["required_evidence"],
            "qualification": f"missing_required_evidence: {contract['required_evidence']}",
            "evidence": [],
        }
        for contract in TECHNICAL_AUDIT_CHECK_CONTRACT
    ]
    return {
        "schema_version": "crawler-cli/technical-audit/3",
        "crawl_run_id": "run-1",
        "run_context": {"seed_origins": ["https://example.test/"], "finished_at": "2026-09-28T12:00:00+00:00"},
        "checks": checks,
    }


def _check(audit: dict[str, object], identifier: str) -> dict[str, object]:
    return next(check for check in audit["checks"] if check["id"] == identifier)  # type: ignore[index,return-value]


def test_ticket_mapping_matches_the_deterministic_contract_and_client_template():
    language = load_ticket_language()

    assert tuple(language["checks"]) == tuple(item["id"] for item in TECHNICAL_AUDIT_CHECK_CONTRACT)  # type: ignore[index]
    assert tuple(language["target_template"]["columns"]) == TICKET_TEMPLATE_COLUMNS  # type: ignore[index]
    assert language["target_template"]["header_row"] == 6  # type: ignore[index]
    assert language["target_template"]["start_column"] == "B"  # type: ignore[index]
    assert language["target_template"]["first_data_row"] == 7  # type: ignore[index]


def test_only_evidenced_findings_become_client_tickets_with_inline_evidence():
    audit = _audit()
    check = _check(audit, "indexability-segmentation")
    check.update(
        {
            "status": "finding",
            "affected_count": 1,
            "tested_count": 10,
            "denominator": 10,
            "qualification": "live_confirmed",
            "evidence": [
                {
                    "source_url": "https://example.test/category?token=private-value",
                    "target_url": "https://example.test/retired",
                    "candidate_type": "conflicting_robots_directives",
                    "http_status": 404,
                }
            ],
        }
    )

    rows = build_technical_audit_ticket_rows(audit)
    finding = next(row for row in rows if row["Label"] == "Conflicting indexability directives")

    assert tuple(finding) == TICKET_TEMPLATE_COLUMNS
    assert (
        "Evidence\n• https://example.test/category?token=[REDACTED] → https://example.test/retired"
        in finding["Description"]
    )
    assert "conflicting robots directives; HTTP 404" in finding["Description"]
    assert "private-value" not in finding["Description"]
    assert "crawler-cli" not in finding["Description"].lower()
    assert "run-1" not in finding["Description"]
    assert "crawler-cli" not in finding["How to Replicate"].lower()
    assert "Index conflicts" in finding["Notes / Documentation"]


def test_analyst_only_candidates_and_partials_stay_out_of_the_client_register():
    audit = _audit()
    candidates = {
        "internal-authority": ("partial", "incomplete_graph"),
        "image-markup": ("finding", "review_required"),
        "url-host-and-variants": ("partial", "bounded_or_incomplete_current_probe"),
        "parameter-and-faceted-controls": ("finding", "analyst_only; combined_v2_detectors"),
        "metadata-basics": ("finding", "analyst_only"),
        "near-duplicate-content": ("partial", "bounded_or_incomplete_coverage"),
    }
    for identifier, (status, qualification) in candidates.items():
        check = _check(audit, identifier)
        check.update(
            {
                "status": status,
                "affected_count": 2,
                "tested_count": 10,
                "denominator": 10,
                "qualification": qualification,
                "evidence": [{"url": f"https://example.test/{identifier}", "candidate_type": "candidate"}],
            }
        )

    rows = build_technical_audit_ticket_rows(audit)
    assert [row["Label"] for row in rows] == [
        "Authorise an external-link recheck",
        "Provide regional access for locale redirect testing",
        "Supply verified search-bot access logs",
        "Grant Search Console access or supply exports",
    ]

    overview = {row["id"]: row for row in technical_audit_ticket_overview(audit)}
    assert overview["image-markup"]["ticket_eligible"] is False
    assert "grouped by distinct element" in str(overview["image-markup"]["ticket_decision"])
    assert overview["parameter-and-faceted-controls"]["ticket_eligible"] is False
    assert "intentional interface state" in str(overview["parameter-and-faceted-controls"]["ticket_decision"])


def test_ticket_enabled_candidate_needs_a_confirmed_status_and_unblocked_qualification():
    audit = _audit()
    check = _check(audit, "canonical-declarations")
    check.update(
        {
            "status": "finding",
            "affected_count": 1,
            "tested_count": 1,
            "denominator": 1,
            "qualification": "analyst_only",
            "evidence": [{"url": "https://example.test/canonical", "candidate_type": "missing_canonical"}],
        }
    )

    assert "Missing, multiple or malformed canonical tags" not in [
        row["Label"] for row in build_technical_audit_ticket_rows(audit)
    ]

    confirmed = deepcopy(audit)
    confirmed_check = _check(confirmed, "canonical-declarations")
    confirmed_check["qualification"] = "live_confirmed"
    rows = build_technical_audit_ticket_rows(confirmed)
    canonical = next(row for row in rows if row["Label"] == "Missing, multiple or malformed canonical tags")
    assert (
        "developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls"
        in canonical["Notes / Documentation"]
    )


def test_sheets_payload_uses_the_copied_template_write_range_and_exact_columns():
    payload = ticket_register_payload(_audit())

    assert payload["ticket_headers"] == list(TICKET_TEMPLATE_COLUMNS)
    assert payload["ticket_range"] == "'Tickets'!B7:I10"
    assert len(payload["ticket_rows"]) == 4
    assert len(payload["overview_rows"]) == 44


def test_each_default_remediation_row_has_inline_evidence_and_no_collection_mechanics():
    audit = _audit()
    language = load_ticket_language()
    expected_labels = []
    for check in audit["checks"]:  # type: ignore[index]
        entry = language["checks"][check["id"]]  # type: ignore[index]
        if entry.get("ticket") is False:
            continue
        expected_labels.append(entry["label"])
        check.update(
            {
                "status": "finding",
                "affected_count": 1,
                "tested_count": 1,
                "denominator": 1,
                "qualification": "live_confirmed",
                "evidence": [{"url": f"https://example.test/{check['id']}", "candidate_type": "confirmed_defect"}],
            }
        )

    rows = build_technical_audit_ticket_rows(audit, language)

    assert [row["Label"] for row in rows] == expected_labels
    assert all("Evidence\n• https://example.test/" in row["Description"] for row in rows)
    assert all("crawler-cli" not in row["Description"].lower() for row in rows)
    assert all("run-1" not in row["Description"] for row in rows)
    assert all("crawler-cli" not in row["How to Replicate"].lower() for row in rows)


class _Request:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class _TicketDrive:
    def __init__(self):
        self.copy_calls = []

    def files(self):
        return self

    def get(self, **_kwargs):
        return _Request(
            {
                "id": "1T9BRLgaFDZ99Lx3q53Av75eZZM32BIJc0nahVPQpGmU",
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "capabilities": {"canCopy": True},
            }
        )

    def copy(self, **kwargs):
        self.copy_calls.append(kwargs)
        return _Request(
            {"id": "copied-sheet", "webViewLink": "https://docs.google.com/spreadsheets/d/copied-sheet/edit"}
        )


class _TicketSheets:
    def __init__(self):
        self.clear_calls = []
        self.update_calls = []
        self.written_rows = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def clear(self, **kwargs):
        self.clear_calls.append(kwargs)
        return _Request({})

    def update(self, **kwargs):
        self.update_calls.append(kwargs)
        self.written_rows = kwargs["body"]["values"]
        return _Request({})

    def get(self, **kwargs):
        if kwargs["spreadsheetId"] == "copied-sheet":
            return _Request({"values": self.written_rows})
        return _Request({"values": [list(TICKET_TEMPLATE_COLUMNS)]})


def test_ticket_register_publisher_copies_the_source_template_and_readbacks_written_rows(tmp_path: Path):
    drive = _TicketDrive()
    sheets = _TicketSheets()
    receipt = tmp_path / "ticket-register-receipt.json"

    url = GoogleSheetsTicketRegisterPublisher(drive, sheets).publish(
        audit=_audit(),
        title="Example tickets",
        receipt_path=receipt,
    )

    assert url == "https://docs.google.com/spreadsheets/d/copied-sheet/edit"
    assert drive.copy_calls[0]["body"] == {"name": "Example tickets"}
    assert sheets.clear_calls[0]["range"] == "'Tickets'!B7:I"
    assert sheets.update_calls[0]["range"] == "'Tickets'!B7:I10"
    assert sheets.update_calls[0]["valueInputOption"] == "RAW"
    published_receipt = json.loads(receipt.read_text())
    assert published_receipt["state"] == "verified"
    assert published_receipt["ticket_count"] == 4
    assert published_receipt["template_id"] == "1T9BRLgaFDZ99Lx3q53Av75eZZM32BIJc0nahVPQpGmU"
    assert published_receipt["spreadsheet_id"] == "copied-sheet"
    assert published_receipt["ticket_payload_digest"]

    resumed_url = GoogleSheetsTicketRegisterPublisher(drive, sheets).publish(
        audit=_audit(),
        title="Example tickets",
        receipt_path=receipt,
        resume=True,
    )
    assert resumed_url == url
    assert len(drive.copy_calls) == 1
