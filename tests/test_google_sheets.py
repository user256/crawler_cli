from __future__ import annotations

import json
from pathlib import Path

import pytest

from crawler_cli.google_sheets import (
    GoogleSheetsTemplatePublisher,
    TEMPLATE_VERSION,
    _validate_template,
    template_manifest,
)


def test_checked_in_template_fixture_matches_the_code_contract():
    fixture = Path(__file__).parents[1] / "templates" / "technical-audit-sheets-v1.json"
    assert json.loads(fixture.read_text(encoding="utf-8")) == template_manifest()


def _tab(title: str, sheet_id: int, headers: list[str] | None = None) -> dict[str, object]:
    cells = [{"userEnteredValue": {"stringValue": value}} for value in (headers or [])]
    return {
        "properties": {"title": title, "sheetId": sheet_id, "gridProperties": {"rowCount": 1000, "columnCount": 26}},
        "data": [{"startRow": 0, "startColumn": 0, "rowData": [{"values": cells}]}],
    }


def _template() -> dict[str, object]:
    return {
        "sheets": [
            _tab("Template Contract", 1, ["technical-audit-template", TEMPLATE_VERSION]),
            _tab("Overview", 2, ["Metric", "Value"]),
            _tab(
                "Audit Log",
                3,
                [
                    "Problem",
                    "URL",
                    "Explanation",
                    "Fix",
                    "SEO Impact",
                    "Action Needed",
                    "Responsible Team",
                    "Owner",
                    "Acceptance Criteria",
                    "Retest Status",
                    "Evidence Reference",
                    "Resolved",
                ],
            ),
            _tab("Internal link failures", 4, ["URL", "Status"]),
            _tab("Notes", 5, ["Unmanaged", "Formula"]),
        ],
        "merges": [],
    }


def test_template_v1_validates_headers_and_ignores_unmanaged_tabs():
    ids = _validate_template(_template(), {"Overview": [["Metric", "Value"]]})
    assert ids["Overview"] == 2
    assert "Notes" not in ids


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
            lambda data: data.update(
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


def test_publish_preflights_before_copying_an_incompatible_template():
    data = _template()
    data["sheets"][1]["data"][0]["rowData"][0]["values"].pop()
    publisher = GoogleSheetsTemplatePublisher(_Drive(), _Sheets(data))
    with pytest.raises(ValueError, match="header mismatch"):
        publisher.publish(template="a" * 20, title="Audit", tables={"Overview": [["Metric", "Value"]]})


def test_publish_clears_stale_audit_rows_only_inside_the_declared_range():
    sheets = _CopiedSheets(_template())
    publisher = GoogleSheetsTemplatePublisher(_CopyDrive(), sheets)
    publisher.publish(
        template="a" * 20,
        title="Audit",
        tables={"Overview": [["Metric", "Value"], ["Audit schema", "v1"]]},
    )
    clear_requests = [request["updateCells"] for request in sheets.mutations[0]["requests"]]
    stale_log_clear = next(request for request in clear_requests if request["range"]["sheetId"] == 3)
    assert stale_log_clear["range"] == {
        "sheetId": 3,
        "startRowIndex": 1,
        "endRowIndex": 50_000,
        "startColumnIndex": 0,
        "endColumnIndex": 12,
    }
