from __future__ import annotations

import json
from pathlib import Path

import pytest

from crawler_cli.google_sheets import (
    GoogleSheetsTemplatePublisher,
    TEMPLATE_VERSION,
    _validated_tables,
    _validate_template,
    template_manifest,
)
from crawler_cli.technical_audit import audit_sheet_tables

_AUDIT_HEADERS = template_manifest()["managed_tabs"]["Audit Log"]["headers"]


def test_checked_in_template_fixture_matches_the_code_contract():
    fixture = Path(__file__).parents[1] / "templates" / "technical-audit-sheets-v2.json"
    assert json.loads(fixture.read_text(encoding="utf-8")) == template_manifest()


def test_recipient_tables_match_the_managed_v2_template_headers():
    action = {
        "Problem": "Internal links target a repeatedly failing URL",
        "Affected URL": "https://example.test/missing",
        "Affected URL Count": 1,
        "Finding Count": 3,
        "Unique Source Pages": 3,
        "Link Instances": 3,
        "Severity": "Medium",
        "Severity Rationale": "Three live-confirmed internal source pages.",
        "Explanation": "The target repeatedly returned 404.",
        "Fix": "Restore or replace the target.",
        "SEO Impact": "Interrupts navigation.",
        "Action Needed": "Yes",
        "Responsible Team": "Engineering",
        "Owner": "Unassigned",
        "Acceptance Criteria": "Retest the target and each source-target pair.",
        "Retest Status": "Live failure confirmed; remediation not retested",
        "Retest Date": "",
        "Resolution Evidence": "",
        "Historical Status": "503",
        "Live Status": "404",
        "Evidence Reference": "sha256:" + "a" * 64,
        "Resolved": "No",
    }
    audit = {
        "schema_version": "crawler-cli/technical-audit/2",
        "ruleset_version": "technical-audit-rules/3",
        "crawl_run_id": "run-1",
        "run_context": {"run_status": "complete", "completion_state": "complete"},
        "checks": [
            {
                "id": "performance-and-conditional-requests",
                "title": "Performance timing and conditional GETs",
                "status": "finding",
                "denominator": 1,
                "tested_count": 1,
                "affected_count": 1,
                "evidence": [{"record_type": "candidate", "url": "https://example.test/page"}],
            }
        ],
        "client_publication_gate": {"ready": True, "client_actions": [action]},
        "recipient_projection": {
            "scope": ["https://example.test/"],
            "run_date": "2026-09-25",
            "health_metrics": [],
            "coverage_caveats": "None",
            "failing_target_inventory": [
                {
                    "target_url": action["Affected URL"],
                    "link_instances": 3,
                    "unique_source_pages": 3,
                    "source_page_samples": ["https://example.test/a"],
                    "source_sample_count": 1,
                    "source_sample_complete": True,
                    "link_samples": [],
                    "evidence_reference": action["Evidence Reference"],
                }
            ],
        },
        "conditional_get_coverage": {"state": "tested"},
    }
    tables = audit_sheet_tables(audit)
    managed = template_manifest()["managed_tabs"]

    assert set(tables) == {"Overview", "Audit Log", "Failing Link Targets", "304 Recheck"}
    for name, table in tables.items():
        assert table[0] == managed[name]["headers"]
        assert name in template_manifest()["managed_tabs"]
    normalized, _ = _validated_tables(tables)
    assert normalized["Failing Link Targets"][1][3] == '["https://example.test/a"]'
    source = {
        "sheets": [
            _tab("Template Contract", 1, ["technical-audit-template", TEMPLATE_VERSION]),
            *[
                _tab(name, index + 2, list(managed[name]["headers"]))
                for index, name in enumerate(tables)
            ],
        ],
        "merges": [],
    }
    _validate_template(source, tables)


def _tab(title: str, sheet_id: int, headers: list[str] | None = None) -> dict[str, object]:
    cells = [{"userEnteredValue": {"stringValue": value}} for value in (headers or [])]
    return {
        "properties": {"title": title, "sheetId": sheet_id, "gridProperties": {"rowCount": 1000, "columnCount": 26}},
        "data": [{"startRow": 0, "startColumn": 0, "rowData": [{"values": cells}]}],
    }


def _template() -> dict[str, object]:
    template = {
        "sheets": [
            _tab("Template Contract", 1, ["technical-audit-template", TEMPLATE_VERSION]),
            _tab("Overview", 2, ["Metric", "Value"]),
            _tab(
                "Audit Log",
                3,
                list(_AUDIT_HEADERS),
            ),
            _tab("Internal link failures", 4, ["URL", "Status"]),
            _tab("Notes", 5, ["Unmanaged", "Formula"]),
        ],
        "merges": [],
    }
    template["sheets"][4]["data"][0]["rowData"].append(
        {
            "values": [
                {"userEnteredValue": {"stringValue": "note"}},
                {"userEnteredValue": {"formulaValue": "=1+1"}},
            ]
        }
    )
    return template


def test_template_v1_validates_headers_and_ignores_unmanaged_tabs():
    ids = _validate_template(_template(), {"Overview": [["Metric", "Value"]]})
    assert ids["Overview"] == 2
    assert "Notes" not in ids


def test_formula_outside_declared_range_is_preserved_as_unmanaged_content():
    data = _template()
    data["sheets"][1]["data"][0]["rowData"][0]["values"].append({"userEnteredValue": {"formulaValue": "=SUM(C2:C10)"}})
    assert _validate_template(data, {"Overview": [["Metric", "Value"]]})["Overview"] == 2


def test_payload_validation_rejects_non_scalar_and_formula_injection_remains_text():
    with pytest.raises(ValueError, match="unsupported cell type"):
        _validated_tables({"Overview": [["Metric", "Value"], ["Bad", {"nested": "object"}]]})
    normalized, _ = _validated_tables({"Overview": [["Metric", "Value"], ["Literal", "=IMPORTXML(A1)"]]})
    assert normalized["Overview"][1][1] == "=IMPORTXML(A1)"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda data: data["sheets"][0]["data"][0]["rowData"][0]["values"][1]["userEnteredValue"].update(
                stringValue="v0"
            ),
            "version mismatch",
        ),
        (lambda data: data["sheets"][1]["data"][0]["rowData"][0]["values"].pop(), "header mismatch"),
        (
            lambda data: data["sheets"][1].update(
                merges=[
                    {"sheetId": 2, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": 2}
                ]
            ),
            "Merged cells",
        ),
        (
            lambda data: data["sheets"][1]["data"][0]["rowData"].append(
                {"values": [{"userEnteredValue": {"formulaValue": "=1+1"}}]}
            ),
            "contains a formula",
        ),
    ],
)
def test_incompatible_template_is_rejected(change, message):
    data = _template()
    change(data)
    with pytest.raises(ValueError, match=message):
        _validate_template(data, {"Overview": [["Metric", "Value"]]})


class _Request:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class _Sheets:
    def __init__(self, metadata):
        self.metadata = metadata
        self.mutations = []

    def spreadsheets(self):
        return self

    def get(self, **_kwargs):
        return _Request(self.metadata)

    def batchUpdate(self, **kwargs):
        self.mutations.append(kwargs["body"])
        return _Request({"replies": []})

    def values(self):
        return self

    def update(self, **kwargs):
        self.mutations.append(kwargs)
        return _Request({})


class _Drive:
    def files(self):
        return self

    def copy(self, **_kwargs):
        raise AssertionError("incompatible template must be rejected before copying")


class _CopyDrive:
    def files(self):
        return self

    def copy(self, **_kwargs):
        return _Request(
            {"id": "copied_sheet", "webViewLink": "https://docs.google.com/spreadsheets/d/copied_sheet/edit"}
        )


class _CopiedSheets(_Sheets):
    def __init__(self, source):
        super().__init__(source)
        self.get_count = 0

    def get(self, **_kwargs):
        self.get_count += 1
        if self.get_count == 1:
            return _Request(self.metadata)
        return _Request(
            {
                "sheets": [
                    {"properties": {"title": title, "sheetId": sheet_id}}
                    for title, sheet_id in (
                        ("Overview", 2),
                        ("Audit Log", 3),
                        ("Template Contract", 1),
                        ("Internal link failures", 4),
                    )
                ]
            }
        )


class _MemorySheets:
    def __init__(self):
        self.source_id = "a" * 20
        self.workbooks = {self.source_id: _template()}
        self.rows = {
            "Overview": [["Metric", "Value"], ["Stale example", "old"]],
            "Audit Log": [
                [
                    _template()["sheets"][2]["data"][0]["rowData"][0]["values"][index]["userEnteredValue"][
                        "stringValue"
                    ]
                    for index in range(len(_AUDIT_HEADERS))
                ],
                ["Old failed link", "https://old.test/"] + [""] * (len(_AUDIT_HEADERS) - 2),
            ],
            "Internal link failures": [["URL", "Status"], ["https://old.test/", "example"]],
            "Template Contract": [["technical-audit-template", TEMPLATE_VERSION]],
            "Notes": [["Unmanaged", "Formula"], ["note", "=1+1"]],
        }
        for tab in self.workbooks[self.source_id]["sheets"]:
            title = tab["properties"]["title"]
            if title == "Notes":
                continue
            for row in self.rows[title][1:]:
                tab["data"][0]["rowData"].append(
                    {"values": [{"userEnteredValue": {"stringValue": str(value)}} for value in row]}
                )
        self.formats = {}
        self.filters = set()
        self.frozen = set()
        self.text_links = {}
        self.grids = {
            tab["properties"]["title"]: dict(tab["properties"]["gridProperties"])
            for tab in self.workbooks[self.source_id]["sheets"]
        }
        self.mutations = []
        self.fail_next_update = False
        self.tamper_after_update = False
        self.raw_options = []

    def clone(self, spreadsheet_id):
        return {name: [list(row) for row in rows] for name, rows in self.rows.items()}

    def spreadsheets(self):
        return self

    def get(self, **kwargs):
        spreadsheet_id = kwargs["spreadsheetId"]
        if spreadsheet_id == self.source_id:
            return _Request(self.workbooks[self.source_id])
        metadata = []
        for tab in self.workbooks[self.source_id]["sheets"]:
            name = tab["properties"]["title"]
            sheet_id = tab["properties"]["sheetId"]
            row_values = []
            for row_index, row in enumerate(self.rows[name]):
                cell_values = []
                for col_index, value in enumerate(row):
                    user_value = (
                        {"formulaValue": value}
                        if name == "Notes" and row_index == 1 and col_index == 1
                        else {"stringValue": str(value)}
                    )
                    cell = {"userEnteredValue": user_value}
                    if (name, row_index, col_index) in self.text_links:
                        cell["textFormatRuns"] = self.text_links[(name, row_index, col_index)]
                    if row_index == 0 and col_index == 0 and name in self.formats:
                        cell["userEnteredFormat"] = self.formats[name]
                    cell_values.append(cell)
                row_values.append({"values": cell_values})
            entry = {
                "properties": {
                    "title": name,
                    "sheetId": sheet_id,
                    "gridProperties": {**self.grids[name], "frozenRowCount": 1 if name in self.frozen else 0},
                },
                "data": [{"rowData": row_values}],
            }
            if name in self.filters:
                entry["basicFilter"] = {"range": {"sheetId": sheet_id}}
            metadata.append(entry)
        return _Request({"sheets": metadata})

    def values(self):
        return self

    def get_values(self, range_value):
        match = __import__("re").fullmatch(r"'(.+)'!A(\d+):([A-Z]+)(\d+)", range_value)
        assert match
        title, first, _, last = match.groups()
        values = self.rows[title][int(first) - 1 : int(last)]
        return {"values": [list(row) for row in values if any(cell not in (None, "") for cell in row)]}

    def get_values_request(self, **kwargs):
        return _Request(self.get_values(kwargs["range"]))

    def clear(self, **kwargs):
        self.mutations.append(("clear", kwargs["range"]))
        match = __import__("re").fullmatch(r"'(.+)'!A(\d+):([A-Z]+)(\d+)", kwargs["range"])
        assert match
        title, first, _, last = match.groups()
        rows = self.rows[title]
        start = int(first) - 1
        while len(rows) < int(last):
            rows.append([])
        for index in range(start, int(last)):
            rows[index] = []
        return _Request({})

    def update(self, **kwargs):
        self.raw_options.append(kwargs["valueInputOption"])
        self.mutations.append(("update", kwargs["range"]))
        if self.fail_next_update:
            self.fail_next_update = False
            raise RuntimeError("injected write failure")
        match = __import__("re").fullmatch(r"'(.+)'!A(\d+):([A-Z]+)(\d+)", kwargs["range"])
        assert match
        title, first, _, _ = match.groups()
        start = int(first) - 1
        rows = self.rows[title]
        for offset, row in enumerate(kwargs["body"]["values"]):
            index = start + offset
            while len(rows) <= index:
                rows.append([])
            rows[index] = list(row)
        if self.tamper_after_update:
            self.tamper_after_update = False
            rows[start][0] = "changed after write"
        return _Request({})

    def batchUpdate(self, **kwargs):
        self.mutations.append(("batch", kwargs["body"]))
        for request in kwargs["body"]["requests"]:
            if "updateSheetProperties" in request:
                properties = request["updateSheetProperties"]["properties"]
                sheet_id = properties["sheetId"]
                title = self._title(sheet_id)
                grid = properties.get("gridProperties", {})
                self.grids[title].update(grid)
                if "frozenRowCount" in grid:
                    self.frozen.add(title)
            elif "repeatCell" in request:
                sheet_id = request["repeatCell"]["range"]["sheetId"]
                title = self._title(sheet_id)
                self.formats[title] = request["repeatCell"]["cell"]["userEnteredFormat"]
            elif "setBasicFilter" in request:
                sheet_id = request["setBasicFilter"]["filter"]["range"]["sheetId"]
                self.filters.add(self._title(sheet_id))
            elif "updateCells" in request:
                update = request["updateCells"]
                title = self._title(update["range"]["sheetId"])
                start_row, start_col = update["range"]["startRowIndex"], update["range"]["startColumnIndex"]
                if not update["rows"] and "userEnteredValue" in update.get("fields", ""):
                    rows = self.rows[title]
                    while len(rows) < update["range"]["endRowIndex"]:
                        rows.append([])
                    for row_index in range(start_row, update["range"]["endRowIndex"]):
                        rows[row_index] = []
                    for key in list(self.text_links):
                        if key[0] == title and start_row <= key[1] < update["range"]["endRowIndex"]:
                            self.text_links.pop(key, None)
                for row_offset, row in enumerate(update["rows"]):
                    for column_offset, cell in enumerate(row["values"]):
                        key = (title, start_row + row_offset, start_col + column_offset)
                        if "textFormatRuns" in cell:
                            self.text_links[key] = cell["textFormatRuns"]
                        elif "textFormatRuns" in update.get("fields", ""):
                            self.text_links.pop(key, None)
        return _Request({"replies": []})

    def _title(self, sheet_id):
        return next(
            tab["properties"]["title"]
            for tab in self.workbooks[self.source_id]["sheets"]
            if tab["properties"]["sheetId"] == sheet_id
        )


class _MemoryDrive:
    def __init__(self, sheets):
        self.sheets = sheets
        self.copy_count = 0
        self.created = {}
        self.lose_copy_response = False

    def files(self):
        return self

    def get(self, **kwargs):
        file_id = kwargs["fileId"]
        if file_id == "a" * 20:
            return _Request({"mimeType": "application/vnd.google-apps.spreadsheet", "capabilities": {"canCopy": True}})
        return _Request(
            {
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "capabilities": {"canEdit": True},
                "webViewLink": f"https://docs.google.com/spreadsheets/d/{file_id}/edit",
            }
        )

    def copy(self, **kwargs):
        self.copy_count += 1
        copied_id = f"copied_{self.copy_count}"
        self.sheets.clone(copied_id)
        publication_id = kwargs["body"]["appProperties"]["crawlerCliAuditPublicationId"]
        self.created[publication_id] = copied_id
        if self.lose_copy_response:
            self.lose_copy_response = False
            raise RuntimeError("injected lost copy response")
        return _Request({"id": copied_id, "webViewLink": f"https://docs.google.com/spreadsheets/d/{copied_id}/edit"})

    def list(self, **_kwargs):
        files = [
            {
                "id": file_id,
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "webViewLink": f"https://docs.google.com/spreadsheets/d/{file_id}/edit",
                "capabilities": {"canEdit": True},
            }
            for file_id in self.created.values()
        ]
        return _Request({"files": files})


class _ValuesProxy:
    def __init__(self, sheets):
        self.sheets = sheets

    def get(self, **kwargs):
        return self.sheets.get_values_request(**kwargs)

    def clear(self, **kwargs):
        return self.sheets.clear(**kwargs)

    def update(self, **kwargs):
        return self.sheets.update(**kwargs)


def _memory_sheets():
    sheets = _MemorySheets()
    sheets.values = lambda: _ValuesProxy(sheets)
    return sheets


def test_publish_preflights_before_copying_an_incompatible_template():
    data = _template()
    data["sheets"][1]["data"][0]["rowData"][0]["values"].pop()
    sheets = _Sheets(data)
    drive = _MemoryDrive(_memory_sheets())
    sheets.spreadsheets = lambda: sheets
    sheets.get = lambda **_kwargs: _Request(data)
    publisher = GoogleSheetsTemplatePublisher(drive, sheets)
    with pytest.raises(ValueError, match="header mismatch"):
        publisher.publish(
            template="a" * 20,
            title="Audit",
            tables={"Overview": [["Metric", "Value"]]},
            receipt_path="receipt.json",
        )
    assert drive.copy_count == 0


def test_publish_clears_stale_audit_rows_only_inside_the_declared_range(tmp_path):
    sheets = _memory_sheets()
    drive = _MemoryDrive(sheets)
    publisher = GoogleSheetsTemplatePublisher(drive, sheets)
    receipt = tmp_path / "receipt.json"
    publisher.publish(
        template="a" * 20,
        title="Audit",
        tables={"Overview": [["Metric", "Value"], ["Audit schema", "v1"]]},
        receipt_path=receipt,
    )
    assert not any(cell not in (None, "") for row in sheets.rows["Audit Log"][1:] for cell in row)
    assert not any(cell not in (None, "") for row in sheets.rows["Internal link failures"][1:] for cell in row)
    assert sheets.rows["Notes"][1] == ["note", "=1+1"]
    assert drive.copy_count == 1


def test_retry_resumes_the_receipted_copy_and_keeps_formula_like_text_literal(tmp_path):
    sheets = _memory_sheets()
    sheets.fail_next_update = True
    drive = _MemoryDrive(sheets)
    publisher = GoogleSheetsTemplatePublisher(drive, sheets)
    receipt = tmp_path / "publication.json"
    actions = [
        list(_AUDIT_HEADERS),
        [
            '=IMPORTXML("https://bad.test")',
            "https://example.test/?q==SUM(1,1)",
            1,
            1,
            3,
            4,
            "Medium",
            "4 links from 3 sources",
            "e",
            "f",
            "i",
            "Yes",
            "Engineering",
            "Unassigned",
            "Acceptance",
            "No",
            "",
            "",
            "503",
            "404",
            "ref",
            "No",
        ],
    ]
    tables = {"Overview": [["Metric", "Value"], ["Audit schema", "v1"]], "Audit Log": actions}
    with pytest.raises(RuntimeError, match="injected write failure"):
        publisher.publish(template="a" * 20, title="Audit", tables=tables, receipt_path=receipt)
    failure_receipt = json.loads(receipt.read_text(encoding="utf-8"))
    assert failure_receipt["state"] == "partial"
    assert failure_receipt["spreadsheet_id"] == "copied_1"
    try:
        url = publisher.publish(
            template="a" * 20,
            title="Audit",
            tables=tables,
            receipt_path=receipt,
            resume=True,
        )
    except ValueError:
        assert sheets.rows["Audit Log"][:2] == actions
        raise
    assert url.endswith("/copied_1/edit")
    assert drive.copy_count == 1
    assert sheets.rows["Audit Log"][1] == actions[1]
    assert "RAW" in sheets.raw_options
    assert json.loads(receipt.read_text(encoding="utf-8"))["state"] == "complete"
    rich_links = [
        request
        for _kind, body in sheets.mutations
        if _kind == "batch"
        for request in body["requests"]
        if "updateCells" in request and request["updateCells"].get("fields") == "textFormatRuns"
    ]
    assert rich_links
    assert (
        rich_links[0]["updateCells"]["rows"][0]["values"][0]["textFormatRuns"][0]["format"]["link"]["uri"]
        == actions[1][1]
    )


def test_retries_refuse_to_overwrite_a_user_edit_after_a_partial_copy(tmp_path):
    sheets = _memory_sheets()
    sheets.fail_next_update = True
    drive = _MemoryDrive(sheets)
    publisher = GoogleSheetsTemplatePublisher(drive, sheets)
    receipt = tmp_path / "publication.json"
    tables = {"Overview": [["Metric", "Value"], ["Audit schema", "v1"]]}
    with pytest.raises(RuntimeError):
        publisher.publish(template="a" * 20, title="Audit", tables=tables, receipt_path=receipt)
    sheets.rows["Overview"][1] = ["Edited by user", "keep"]
    with pytest.raises(ValueError, match="refusing to overwrite edits"):
        publisher.publish(template="a" * 20, title="Audit", tables=tables, receipt_path=receipt, resume=True)
    assert drive.copy_count == 1


def test_readback_mismatch_keeps_receipt_partial_and_does_not_claim_success(tmp_path):
    sheets = _memory_sheets()
    sheets.tamper_after_update = True
    drive = _MemoryDrive(sheets)
    publisher = GoogleSheetsTemplatePublisher(drive, sheets)
    receipt = tmp_path / "publication.json"
    with pytest.raises(ValueError, match="Read-back values differ"):
        publisher.publish(
            template="a" * 20,
            title="Audit",
            tables={"Overview": [["Metric", "Value"], ["Audit schema", "v1"]]},
            receipt_path=receipt,
        )
    assert json.loads(receipt.read_text(encoding="utf-8"))["state"] == "partial"


def test_lost_copy_response_reconciles_by_drive_marker_without_duplicate(tmp_path):
    sheets = _memory_sheets()
    drive = _MemoryDrive(sheets)
    drive.lose_copy_response = True
    publisher = GoogleSheetsTemplatePublisher(drive, sheets)
    receipt = tmp_path / "publication.json"
    tables = {"Overview": [["Metric", "Value"], ["Audit schema", "v1"]]}
    with pytest.raises(RuntimeError, match="lost copy response"):
        publisher.publish(template="a" * 20, title="Audit", tables=tables, receipt_path=receipt)
    assert json.loads(receipt.read_text(encoding="utf-8"))["state"] == "copy_pending"
    publisher.publish(template="a" * 20, title="Audit", tables=tables, receipt_path=receipt, resume=True)
    assert drive.copy_count == 1


def test_large_table_writes_in_checkpointed_bounded_chunks(tmp_path):
    sheets = _memory_sheets()
    drive = _MemoryDrive(sheets)
    publisher = GoogleSheetsTemplatePublisher(drive, sheets)
    receipt = tmp_path / "publication.json"
    rows = [["Metric", "Value"], *[[f"row-{index}", index] for index in range(501)]]
    publisher.publish(template="a" * 20, title="Audit", tables={"Overview": rows}, receipt_path=receipt)
    assert [mutation for mutation in sheets.mutations if mutation[0] == "update"] == [
        ("update", "'Overview'!A2:B501"),
        ("update", "'Overview'!A502:B502"),
    ]
    assert json.loads(receipt.read_text(encoding="utf-8"))["completed_chunks"]["Overview"] == [0, 1]
