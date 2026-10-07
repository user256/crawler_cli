from __future__ import annotations

import argparse
import copy
import json

import pytest

from crawler_cli.google_sheets import (
    TEMPLATE_CONTRACT_VERSION,
    GoogleSheetsTemplatePublisher,
    TemplateContractError,
    TemplateHeaderError,
    google_sheet_id,
    load_template_contract,
    validate_template_contract,
)
from crawler_cli.technical_audit_tickets import TICKET_COLUMNS, load_ticket_language


class _Response:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


# The real template's Tickets tab, read 2026-10-07: a title block, the ticket
# counter formula in B3, the header at B5 and prefilled row numbers in column A.
_REAL_TICKETS_LAYOUT = [
    [],
    ["", "", "", "This is a template, make a copy and avoid writing tickets until you have"],
    ["", '=CONCATENATE("Count of tickets: ",COUNTA(B6:B))'],
    ["", "Audit performed by: John Doe"],
    ["", *TICKET_COLUMNS],
    [1],
    [2],
]


class _HttpError(Exception):
    """Shaped like googleapiclient.errors.HttpError."""

    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.resp = type("Resp", (), {"status": status})()


class _DriveFiles:
    def __init__(self, error=None):
        self.error = error
        self.copies: list[dict[str, object]] = []
        self.moves: list[dict[str, object]] = []

    def copy(self, **kwargs):
        self.copies.append(kwargs)
        if self.error is not None:
            raise self.error
        return _Response(
            {"id": "copied-sheet", "webViewLink": "https://docs.google.com/spreadsheets/d/copied-sheet/edit"}
        )

    def get(self, **_kwargs):
        return _Response({"parents": ["root-folder"]})

    def update(self, **kwargs):
        self.moves.append(kwargs)
        return _Response({})


class _Drive:
    def __init__(self, error=None):
        self.files_api = _DriveFiles(error)

    def files(self):
        return self.files_api


class _Values:
    def __init__(self, header_rows=None):
        self.clears: list[str] = []
        self.updates: list[tuple[str, list[list[object]]]] = []
        self.reads: list[tuple[str, str]] = []
        self.header_rows = _REAL_TICKETS_LAYOUT if header_rows is None else header_rows

    def get(self, *, spreadsheetId, range, **_kwargs):
        self.reads.append((spreadsheetId, range))
        return _Response({"values": self.header_rows})

    def clear(self, *, range, **_kwargs):
        self.clears.append(range)
        return _Response({})

    def update(self, *, range, body, **_kwargs):
        self.updates.append((range, body["values"]))
        return _Response({})


class _SheetTabs:
    def __init__(self, parent):
        self.parent = parent
        self.copies: list[tuple[str, int, str]] = []

    def copyTo(self, *, spreadsheetId, sheetId, body):
        self.copies.append((spreadsheetId, sheetId, body["destinationSpreadsheetId"]))
        title = next(tab["title"] for tab in self.parent.source_tabs if tab["sheetId"] == sheetId)
        return _Response({"sheetId": 500 + len(self.copies), "title": f"Copy of {title}"})


class _Spreadsheets:
    def __init__(self, titles=("Tickets",), header_rows=None):
        self.values_api = _Values(header_rows)
        self.titles = titles
        self.batch_updates: list[dict[str, object]] = []
        self.gets: list[str] = []
        self.creates: list[dict[str, object]] = []
        # Source template tabs, deliberately listed out of index order.
        self.source_tabs = [
            {"sheetId": 1085525035, "title": "Config", "index": 1},
            {"sheetId": 0, "title": "Tickets", "index": 0},
        ]
        self.tabs_api = _SheetTabs(self)

    def get(self, *, spreadsheetId, **_kwargs):
        self.gets.append(spreadsheetId)
        if spreadsheetId == "template-sheet":
            return _Response({"sheets": [{"properties": tab} for tab in self.source_tabs]})
        return _Response(
            {"sheets": [{"properties": {"sheetId": i, "title": title}} for i, title in enumerate(self.titles, 1)]}
        )

    def create(self, *, body, **_kwargs):
        self.creates.append(body)
        return _Response(
            {
                "spreadsheetId": "rebuilt-sheet",
                "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/rebuilt-sheet/edit",
                "sheets": [{"properties": {"sheetId": 0, "title": "Sheet1"}}],
            }
        )

    def sheets(self):
        return self.tabs_api

    def values(self):
        return self.values_api

    def batchUpdate(self, **kwargs):
        self.batch_updates.append(kwargs["body"])
        added = [request["addSheet"]["properties"] for request in kwargs["body"]["requests"] if "addSheet" in request]
        return _Response(
            {"replies": [{"addSheet": {"properties": {**props, "sheetId": 100 + i}}} for i, props in enumerate(added)]}
        )


class _Sheets:
    def __init__(self, titles=("Tickets",), header_rows=None):
        self.spreadsheets_api = _Spreadsheets(titles, header_rows)

    def spreadsheets(self):
        return self.spreadsheets_api


_ROW = ["ticket", "", "", "", "Issue", "High", "", ""]


def _tickets(*rows):
    return [list(TICKET_COLUMNS), *(rows or (list(_ROW),))]


def test_plain_audit_publish_writes_beneath_the_real_template_header_not_at_a2():
    # Ticket 406: `technical-audit --google-sheets-template` used to clear
    # 'Tickets'!A2:H10000 and write at A2, over the count formula and header.
    sheets = _Sheets()
    GoogleSheetsTemplatePublisher(_Drive(), sheets).publish(
        template="template-sheet",
        title="Audit",
        tables={"Overview": [["Metric", "Value"]], "Tickets": _tickets()},
    )

    values = sheets.spreadsheets_api.values_api
    assert values.reads == [("copied-sheet", "'Tickets'!A1:Z40")]
    assert "'Tickets'!B6:I10000" in values.clears
    assert ("'Tickets'!B6", [_ROW]) in values.updates
    assert not any(target.startswith("'Tickets'!A") for target in [*values.clears, *(u[0] for u in values.updates)])


@pytest.mark.parametrize(
    "header",
    [
        pytest.param(["Unrecognised header"], id="absent"),
        pytest.param(list(TICKET_COLUMNS[:4]), id="partial"),
        pytest.param([TICKET_COLUMNS[1], TICKET_COLUMNS[0], *TICKET_COLUMNS[2:]], id="reordered"),
        pytest.param([TICKET_COLUMNS[0], "Notes", *TICKET_COLUMNS[1:]], id="inserted-column"),
    ],
)
def test_plain_audit_publish_fails_before_any_write_when_the_ticket_header_does_not_match(header):
    sheets = _Sheets(titles=("Tickets", "Config"), header_rows=[*_TITLE_BLOCK, ["", *header]])

    with pytest.raises(TemplateHeaderError, match="nothing was written"):
        GoogleSheetsTemplatePublisher(_Drive(), sheets).publish(
            template="template-sheet",
            title="Audit",
            tables={"Overview": [["Metric"]], "Audit Log": [["Problem"]], "Tickets": _tickets()},
        )

    values = sheets.spreadsheets_api.values_api
    assert values.clears == [] and values.updates == []
    assert sheets.spreadsheets_api.batch_updates == []


def _publish_question_workbook(header_rows, titles=("Tickets",)):
    sheets = _Sheets(titles, header_rows)
    GoogleSheetsTemplatePublisher(_Drive(), sheets).publish(
        template="template-sheet",
        title="Audit",
        tables={"Questions": [["Theme", "ID"]], "Q16 Data": [["url"]], "Tickets": _tickets()},
    )
    return sheets


_TITLE_BLOCK = [["Client title"], ["Existing note"]]


@pytest.mark.parametrize(
    "header",
    [
        pytest.param(["Unrecognised header"], id="absent"),
        pytest.param(list(TICKET_COLUMNS[:4]), id="partial"),
        pytest.param([TICKET_COLUMNS[1], TICKET_COLUMNS[0], *TICKET_COLUMNS[2:]], id="reordered"),
        pytest.param([TICKET_COLUMNS[0], "Notes", *TICKET_COLUMNS[1:]], id="inserted-column"),
    ],
)
def test_question_publish_fails_before_any_write_when_the_ticket_header_does_not_match(header):
    # Ticket 406: never default to A2 or clear client rows in the copied workbook.
    sheets = _Sheets(header_rows=[*_TITLE_BLOCK, ["", *header]])

    with pytest.raises(TemplateHeaderError, match="nothing was written"):
        GoogleSheetsTemplatePublisher(_Drive(), sheets).publish(
            template="template-sheet",
            title="Audit",
            tables={"Questions": [["Theme"]], "Q16 Data": [["url"]], "Tickets": _tickets()},
        )

    values = sheets.spreadsheets_api.values_api
    assert values.clears == [] and values.updates == []
    assert sheets.spreadsheets_api.batch_updates == []


def test_question_publish_fails_when_the_copied_template_has_no_tickets_tab():
    with pytest.raises(TemplateHeaderError, match="no Tickets tab"):
        _publish_question_workbook([], titles=("Questions",))


def test_question_publish_writes_beneath_a_full_header_under_a_title_block():
    header = [*_TITLE_BLOCK, [], ["", " label ", *TICKET_COLUMNS[1:]]]
    sheets = _publish_question_workbook(header, titles=("Questions", "Tickets"))

    values = sheets.spreadsheets_api.values_api
    assert "'Tickets'!B5:I10000" in values.clears
    assert ("'Tickets'!B5", [_ROW]) in values.updates


def test_header_found_at_any_row_so_the_old_row_six_assumption_does_not_matter():
    for header_row in (1, 5, 6, 12):
        rows = [[] for _ in range(header_row - 1)] + [["", *TICKET_COLUMNS]]
        sheets = _publish_question_workbook(rows)
        assert ("'Tickets'!B" + str(header_row + 1), [_ROW]) in sheets.spreadsheets_api.values_api.updates


# Template contract -----------------------------------------------------------


def test_default_contract_matches_the_generated_columns_and_the_ticket_language():
    contract = load_template_contract()
    language = load_ticket_language()

    assert tuple(contract["tickets"]["columns"]) == TICKET_COLUMNS
    assert contract["tickets"]["columns"] == language["target_template"]["columns"]
    assert google_sheet_id(contract["template"]["url"]) == google_sheet_id(language["target_template"]["url"])
    assert contract["tickets"]["value_sets"]["Priority"] == language["target_template"]["priority_values"]
    assert (
        contract["tickets"]["value_sets"]["Ticket Classification"]
        == language["target_template"]["classification_values"]
    )
    layout = contract["verified_layout"]
    assert (layout["header_cell"], layout["first_data_row"]) == ("B5", 6)


def test_template_defaults_to_the_contract_template_id():
    drive = _Drive()
    GoogleSheetsTemplatePublisher(drive, _Sheets()).publish(title="Audit", tables={"Tickets": _tickets()})

    assert drive.files_api.copies[0]["fileId"] == "1T9BRLgaFDZ99Lx3q53Av75eZZM32BIJc0nahVPQpGmU"


def _contract(**changes):
    contract = copy.deepcopy(load_template_contract())
    for key, value in changes.items():
        target = contract
        *parents, leaf = key.split("__")
        for parent in parents:
            target = target[parent]
        target[leaf] = value
    return contract


def test_contract_names_the_tickets_tab_and_header_search_window():
    sheets = _Sheets(titles=("Backlog",))
    contract = _contract(tickets__tab="Backlog", tickets__header_search={"max_rows": 12, "max_columns": 10})
    GoogleSheetsTemplatePublisher(_Drive(), sheets, contract).publish(
        template="template-sheet", title="Audit", tables={"Tickets": _tickets()}
    )

    values = sheets.spreadsheets_api.values_api
    assert values.reads == [("copied-sheet", "'Backlog'!A1:J12")]
    assert values.updates == [("'Backlog'!B6", [_ROW])]
    assert sheets.spreadsheets_api.batch_updates == []  # no stray "Tickets" tab is added


@pytest.mark.parametrize(
    ("tables", "message"),
    [
        pytest.param(
            {"Tickets": [list(TICKET_COLUMNS[:-1]), _ROW[:-1]]}, "differ from the template contract", id="columns"
        ),
        pytest.param({"Tickets": _tickets(["x", "", "", "", "Bug", "High", "", ""])}, "Bug", id="classification"),
        pytest.param({"Tickets": _tickets(["x", "", "", "", "Issue", "Urgent", "", ""])}, "Urgent", id="priority"),
        pytest.param({"Tickets": _tickets(), "Config": [["Priority"]]}, "Config", id="protected-tab"),
    ],
)
def test_tables_that_break_the_contract_fail_before_the_template_is_copied(tables, message):
    drive, sheets = _Drive(), _Sheets()
    with pytest.raises(TemplateContractError, match=message):
        GoogleSheetsTemplatePublisher(drive, sheets).publish(template="template-sheet", title="Audit", tables=tables)

    assert drive.files_api.copies == []
    assert sheets.spreadsheets_api.values_api.clears == [] and sheets.spreadsheets_api.values_api.updates == []


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"version": "other/1"}, id="version"),
        pytest.param({"template__url": "/home/user/template.xlsx"}, id="template-url"),
        pytest.param({"tickets__tab": ""}, id="tab"),
        pytest.param({"tickets__columns": ["Label", "label"]}, id="duplicate-columns"),
        pytest.param({"tickets__header_search": {"max_rows": 0, "max_columns": 26}}, id="search-rows"),
        pytest.param({"tickets__header_search": {"max_rows": 40, "max_columns": 3}}, id="search-too-narrow"),
        pytest.param({"tickets__value_sets": {"Severity": ["High"]}}, id="unknown-value-set"),
        pytest.param({"protected_tabs": ["Tickets"]}, id="protected-tickets-tab"),
    ],
)
def test_malformed_contract_is_rejected(changes):
    with pytest.raises(TemplateContractError):
        validate_template_contract(_contract(**changes))


def test_contract_file_errors_are_validation_errors(tmp_path):
    missing = tmp_path / "missing.json"
    with pytest.raises(TemplateContractError, match="could not load"):
        load_template_contract(missing)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"version": TEMPLATE_CONTRACT_VERSION}), encoding="utf-8")
    with pytest.raises(TemplateContractError, match="template.url"):
        load_template_contract(bad)


def test_cli_reports_a_bad_contract_before_reading_credentials(tmp_path, capsys):
    from crawler_cli.__main__ import _publish_google_sheet

    args = argparse.Namespace(
        google_sheets_contract=str(tmp_path / "missing.json"),
        google_sheets_credentials="/nonexistent/credentials.json",
        google_sheets_template=None,
        google_sheets_title=None,
        google_sheets_folder=None,
    )
    assert _publish_google_sheet(args, "Audit", {"Tickets": _tickets()}) is None
    assert "could not load template contract" in capsys.readouterr().err


# sheets.copyTo fallback for drive.file tokens --------------------------------


@pytest.mark.parametrize("status", [403, 404])
def test_refused_drive_copy_rebuilds_the_template_tab_by_tab(status):
    drive, sheets = _Drive(error=_HttpError(status)), _Sheets()
    url = GoogleSheetsTemplatePublisher(drive, sheets).publish(
        template="template-sheet", title="Audit", folder_id="client-folder", tables={"Tickets": _tickets()}
    )

    api = sheets.spreadsheets_api
    assert url == "https://docs.google.com/spreadsheets/d/rebuilt-sheet/edit"
    assert api.creates == [{"properties": {"title": "Audit"}}]
    # Template order (Tickets, then Config), into the new workbook.
    assert api.tabs_api.copies == [
        ("template-sheet", 0, "rebuilt-sheet"),
        ("template-sheet", 1085525035, "rebuilt-sheet"),
    ]
    assert api.batch_updates[0]["requests"] == [
        {"deleteSheet": {"sheetId": 0}},
        {"updateSheetProperties": {"properties": {"sheetId": 501, "title": "Tickets"}, "fields": "title"}},
        {"updateSheetProperties": {"properties": {"sheetId": 502, "title": "Config"}, "fields": "title"}},
    ]
    assert drive.files_api.moves == [
        {
            "fileId": "rebuilt-sheet",
            "addParents": "client-folder",
            "removeParents": "root-folder",
            "fields": "id",
            "supportsAllDrives": True,
        }
    ]
    # The header is still checked on the destination before writing.
    assert api.values_api.reads == [("rebuilt-sheet", "'Tickets'!A1:Z40")]
    assert api.values_api.updates == [("'Tickets'!B6", [_ROW])]


def test_other_drive_copy_errors_are_not_masked_by_the_fallback():
    drive, sheets = _Drive(error=_HttpError(500)), _Sheets()
    with pytest.raises(_HttpError):
        GoogleSheetsTemplatePublisher(drive, sheets).publish(
            template="template-sheet", title="Audit", tables={"Tickets": _tickets()}
        )
    assert sheets.spreadsheets_api.creates == [] and sheets.spreadsheets_api.tabs_api.copies == []
