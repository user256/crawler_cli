from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re

import pytest

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


_A1_RANGE = re.compile(r"^'(?P<tab>[^']+)'(?:!(?P<c1>[A-Z]+)(?P<r1>\d+)(?::(?P<c2>[A-Z]+)(?P<r2>\d+)?)?)?$")


def _column_number(label: str) -> int:
    number = 0
    for character in label:
        number = number * 26 + ord(character) - 64
    return number


class _TicketSheets:
    """Cell-level stand-in for the Sheets values API.

    Like the real API it stores cells by position, skips ``None`` on write,
    returns only the requested range from ``values.get`` and drops trailing
    empty cells and rows from the response.
    """

    def __init__(self, *, fail_readback_once: str | None = None, receipt_path: Path | None = None):
        self.clear_calls = []
        self.update_calls = []
        self.batch_calls = []
        self.get_ranges = []
        self.tabs = {"Tickets"}
        self.cells: dict[str, dict[tuple[int, int], object]] = {}
        self.fail_readback_once = fail_readback_once
        self.receipt_path = receipt_path
        self.receipt_state_at_tab_readback = {}

    def spreadsheets(self):
        return self

    def values(self):
        return self

    @staticmethod
    def _bounds(a1_range: str) -> tuple[str, int, int, int | None, int | None]:
        match = _A1_RANGE.match(a1_range)
        assert match, a1_range
        if not match["c1"]:
            return match["tab"], 1, 1, None, None
        first_row, first_column = int(match["r1"]), _column_number(match["c1"])
        if not match["c2"]:
            return match["tab"], first_row, first_column, first_row, first_column
        last_row = int(match["r2"]) if match["r2"] else None
        return match["tab"], first_row, first_column, last_row, _column_number(match["c2"])

    def clear(self, **kwargs):
        self.clear_calls.append(kwargs)
        tab, first_row, first_column, last_row, last_column = self._bounds(kwargs["range"])
        grid = self.cells.setdefault(tab, {})
        for row, column in list(grid):
            if first_row <= row <= (last_row or row) and first_column <= column <= (last_column or column):
                del grid[(row, column)]
        return _Request({})

    def update(self, **kwargs):
        self.update_calls.append(kwargs)
        tab, first_row, first_column, _last_row, _last_column = self._bounds(kwargs["range"])
        grid = self.cells.setdefault(tab, {})
        for row_offset, row in enumerate(kwargs["body"]["values"]):
            for column_offset, value in enumerate(row):
                if value is None:  # The API leaves the cell untouched.
                    continue
                grid[(first_row + row_offset, first_column + column_offset)] = value
        return _Request({})

    def batchUpdate(self, **kwargs):
        self.batch_calls.append(kwargs)
        for request in kwargs["body"]["requests"]:
            self.tabs.add(request["addSheet"]["properties"]["title"])
        return _Request({})

    def read(self, a1_range: str) -> list[list[object]]:
        tab, first_row, first_column, last_row, last_column = self._bounds(a1_range)
        grid = self.cells.get(tab, {})
        last_row = last_row or max((row for row, _column in grid), default=first_row)
        last_column = last_column or max((column for _row, column in grid), default=first_column)
        rows = []
        for row in range(first_row, last_row + 1):
            values = [grid.get((row, column), "") for column in range(first_column, last_column + 1)]
            while values and values[-1] == "":
                values.pop()
            rows.append(values)
        while rows and not rows[-1]:
            rows.pop()
        return rows

    def get(self, **kwargs):
        if kwargs.get("fields") == "sheets.properties.title":
            return _Request({"sheets": [{"properties": {"title": title}} for title in sorted(self.tabs)]})
        if kwargs["spreadsheetId"] != "copied-sheet":
            return _Request({"values": [list(TICKET_TEMPLATE_COLUMNS)]})
        a1_range = kwargs["range"]
        self.get_ranges.append(a1_range)
        tab = self._bounds(a1_range)[0]
        if tab != "Tickets" and self.receipt_path is not None:
            state = json.loads(self.receipt_path.read_text())["state"]
            self.receipt_state_at_tab_readback.setdefault(tab, []).append(state)
        if tab == self.fail_readback_once:
            self.fail_readback_once = None
            raise RuntimeError(f"transient failure reading {tab}")
        values = self.read(a1_range)
        return _Request({"values": values} if values else {})


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
    assert [request["addSheet"]["properties"]["title"] for request in sheets.batch_calls[0]["body"]["requests"]] == [
        "Audit Controls",
        "Manual Review",
    ]
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


def _manual_review_row(index: int) -> dict[str, object]:
    return {
        "id": f"MR-{index}",
        "question": f"Question {index}?",
        "status": "needs_evidence",
        "control_ids": ["metadata-basics"],
        "additional_evidence_required": None,
        "additional_evidence_available": None,
    }


def test_audit_tabs_write_bounded_blocks_that_read_back_through_the_real_api_shape(tmp_path: Path):
    sheets = _TicketSheets()
    receipt = tmp_path / "ticket-register-receipt.json"

    GoogleSheetsTicketRegisterPublisher(_TicketDrive(), sheets).publish(
        audit=_audit(), title="Example tickets", receipt_path=receipt
    )

    assert json.loads(receipt.read_text())["state"] == "verified"
    tab_updates = {call["range"]: call["body"]["values"] for call in sheets.update_calls}
    assert set(tab_updates) == {"'Tickets'!B7:I10", "'Audit Controls'!A1:I45", "'Manual Review'!A1:F1"}
    assert "'Audit Controls'!A1:I45" in sheets.get_ranges
    assert "'Manual Review'!A1:F1" in sheets.get_ranges
    # Unavailable controls carry null counts; they are written as blanks.
    assert all(cell is not None for row in tab_updates["'Audit Controls'!A1:I45"] for cell in row)
    assert tab_updates["'Audit Controls'!A1:I45"][1][3:5] == ["", ""]
    # The previous "'<Tab>'!A1" readback is a single cell against the real API,
    # and even the full block comes back with the blank cells trimmed.
    assert sheets.read("'Audit Controls'!A1") == [["Control"]]
    assert sheets.read("'Audit Controls'!A1") != tab_updates["'Audit Controls'!A1:I45"]
    assert sheets.read("'Audit Controls'!A1:I45")[1][3] == ""


def test_resume_after_an_audit_tab_failure_verifies_both_tabs_before_the_receipt(tmp_path: Path):
    receipt = tmp_path / "ticket-register-receipt.json"
    drive = _TicketDrive()
    sheets = _TicketSheets(fail_readback_once="Manual Review", receipt_path=receipt)
    audit = {**_audit(), "manual_review_answers": [_manual_review_row(1)]}

    with pytest.raises(RuntimeError, match="Manual Review"):
        GoogleSheetsTicketRegisterPublisher(drive, sheets).publish(
            audit=audit, title="Example tickets", receipt_path=receipt
        )
    assert json.loads(receipt.read_text())["state"] == "writing"

    sheets.update_calls.clear()
    sheets.receipt_state_at_tab_readback.clear()
    GoogleSheetsTicketRegisterPublisher(drive, sheets).publish(
        audit=audit, title="Example tickets", receipt_path=receipt, resume=True
    )

    assert len(drive.copy_calls) == 1
    # Ticket rows already matched, so only the audit tabs are rewritten.
    assert [call["range"] for call in sheets.update_calls] == ["'Audit Controls'!A1:I45", "'Manual Review'!A1:F2"]
    # Two reads per tab while the receipt says "writing": the header probe that
    # proves the tab is ours (ticket 403), then the readback.
    assert sheets.receipt_state_at_tab_readback == {
        "Audit Controls": ["writing", "writing"],
        "Manual Review": ["writing", "writing"],
    }
    assert json.loads(receipt.read_text())["state"] == "verified"
    assert sheets.read("'Manual Review'!A1:F2")[1] == ["MR-1", "Question 1?", "needs_evidence", "metadata-basics"]


def test_rerun_with_fewer_manual_review_rows_leaves_no_stale_rows():
    sheets = _TicketSheets()
    publisher = GoogleSheetsTicketRegisterPublisher(_TicketDrive(), sheets)
    payload = ticket_register_payload(_audit())

    publisher._write_audit_register_tabs(
        "copied-sheet", {**payload, "manual_review_rows": [_manual_review_row(index) for index in range(1, 4)]}
    )
    assert len(sheets.read("'Manual Review'")) == 4
    publisher._write_audit_register_tabs("copied-sheet", {**payload, "manual_review_rows": [_manual_review_row(1)]})

    assert [row[0] for row in sheets.read("'Manual Review'")] == ["Question", "MR-1"]
    assert {"range": "'Manual Review'", "spreadsheetId": "copied-sheet", "body": {}} in sheets.clear_calls


# --- 403: never wipe a client tab that merely shares a name ----------------------


def test_register_publisher_refuses_to_clear_a_foreign_tab_with_the_same_name(tmp_path: Path):
    drive = _TicketDrive()
    sheets = _TicketSheets()
    sheets.tabs.add("Audit Controls")
    sheets.cells["Audit Controls"] = {(1, 1): "Client notes", (2, 1): "Keep me"}
    with pytest.raises(ValueError, match="Refusing to overwrite the existing Audit Controls tab"):
        GoogleSheetsTicketRegisterPublisher(drive, sheets).publish(
            audit=_audit(), title="Example tickets", receipt_path=tmp_path / "receipt.json"
        )
    assert sheets.cells["Audit Controls"][(2, 1)] == "Keep me"
    assert not any(call["range"].startswith("'Audit Controls'") for call in sheets.clear_calls)


def test_register_publisher_still_rewrites_its_own_tab_on_a_rerun(tmp_path: Path):
    drive = _TicketDrive()
    sheets = _TicketSheets()
    GoogleSheetsTicketRegisterPublisher(drive, sheets).publish(
        audit=_audit(), title="Example tickets", receipt_path=tmp_path / "first.json"
    )
    sheets.cells["Audit Controls"][(60, 1)] = "stale row from an earlier, longer run"
    GoogleSheetsTicketRegisterPublisher(drive, sheets).publish(
        audit=_audit(), title="Example tickets", receipt_path=tmp_path / "second.json"
    )
    assert (60, 1) not in sheets.cells["Audit Controls"]
