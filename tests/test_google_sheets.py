from __future__ import annotations

import argparse
import copy
import json

import pytest

from crawler_cli.google_sheets import (
    TEMPLATE_CONTRACT_VERSION,
    GoogleSheetsTemplatePublisher,
    PublishReceiptError,
    TemplateContractError,
    TemplateHeaderError,
    check_template_validation,
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


def _column(label):
    number = 0
    for character in label:
        number = number * 26 + ord(character) - 64
    return number


def _parse_range(a1):
    """'Tab'!B6:I10, 'Tab'!A:ZZ, 'Tab'!B6 or 'Tab' -> (tab, row1, col1, row2, col2); None = open."""
    tab, _, cells = a1.partition("!")
    tab = tab[1:-1].replace("''", "'") if tab.startswith("'") else tab
    if not cells:
        return tab, 1, 1, None, None
    bounds = []
    for part in cells.split(":"):
        letters = "".join(c for c in part if c.isalpha())
        digits = "".join(c for c in part if c.isdigit())
        bounds.append((int(digits) if digits else None, _column(letters) if letters else None))
    (row1, col1), (row2, col2) = bounds[0], bounds[-1]
    return tab, row1 or 1, col1 or 1, row2, col2


def _trim(rows):
    rows = [list(row) for row in rows]
    for row in rows:
        while row and row[-1] in ("", None):
            row.pop()
    while rows and not rows[-1]:
        rows.pop()
    return rows


class _Values:
    """A stateful grid per tab, so writes can be read back like the real API."""

    def __init__(self, header_rows=None):
        self.clears: list[str] = []
        self.updates: list[tuple[str, list[list[object]]]] = []
        self.reads: list[tuple[str, str]] = []
        self.render_options: list[str | None] = []
        header_rows = _REAL_TICKETS_LAYOUT if header_rows is None else header_rows
        self.grids: dict[str, dict[tuple[int, int], object]] = {}
        self._fill("Tickets", 1, 1, header_rows)
        # Called with (range, values) before an update is stored; may return altered values.
        self.on_update = None
        # Called with the parsed range of a values.clear.
        self.on_clear = None

    def _fill(self, tab, row1, col1, rows):
        grid = self.grids.setdefault(tab, {})
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                if value is None:
                    continue  # the API leaves the cell unchanged for null
                grid[(row1 + r, col1 + c)] = value

    def get(self, *, spreadsheetId, range, valueRenderOption=None, **_kwargs):
        self.reads.append((spreadsheetId, range))
        self.render_options.append(valueRenderOption)
        tab, row1, col1, row2, col2 = _parse_range(range)
        grid = self.grids.get(tab, {})
        if not grid:
            return _Response({})
        last_row = row2 or max(r for r, _ in grid)
        last_col = col2 or max(c for _, c in grid)
        rows = [[grid.get((r, c), "") for c in range_(col1, last_col + 1)] for r in range_(row1, last_row + 1)]
        return _Response({"values": _trim(rows)})

    def clear(self, *, range, **_kwargs):
        self.clears.append(range)
        tab, row1, col1, row2, col2 = _parse_range(range)
        if self.on_clear is not None:
            self.on_clear(tab, row1, col1, row2, col2)
        grid = self.grids.setdefault(tab, {})
        for r, c in list(grid):
            if r >= row1 and c >= col1 and (row2 is None or r <= row2) and (col2 is None or c <= col2):
                del grid[(r, c)]
        return _Response({})

    def update(self, *, range, body, **_kwargs):
        self.updates.append((range, body["values"]))
        values = body["values"]
        if self.on_update is not None:
            values = self.on_update(range, copy.deepcopy(values))
        tab, row1, col1, _row2, _col2 = _parse_range(range)
        self._fill(tab, row1, col1, values)
        return _Response({})


range_ = range


def _letter(number):
    label = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        label = chr(65 + remainder) + label
    return label


def _quote(tab):
    return "'" + tab.replace("'", "''") + "'"


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
        self.batch_targets: list[str] = []
        self.grid_reads: list[tuple[str, list[str]]] = []
        self.gets: list[str] = []
        self.creates: list[dict[str, object]] = []
        # Source template tabs, deliberately listed out of index order.
        self.source_tabs = [
            {"sheetId": 1085525035, "title": "Config", "index": 1},
            {"sheetId": 0, "title": "Tickets", "index": 0},
        ]
        self.tabs_api = _SheetTabs(self)
        # Grid data (dataValidation only) per source tab title, as includeGridData returns it.
        self.source_data: dict[str, list[dict[str, object]]] = {}
        self.source_error = None
        # The copy's data validation, (sheetId, 0-based row, 0-based column) -> rule,
        # and its tab titles by sheetId (renames in a batchUpdate are applied).
        self.copy_rules: dict[tuple[int, int, int], dict[str, object]] = {}
        self.copy_titles: dict[int, str] = {i: title for i, title in enumerate(titles, 1)}
        # updateCells value clears, as "'Tab'!B6:I" (open-ended rows).
        self.cell_clears: list[str] = []
        self.ignore_cell_clears = False
        self.values_api.on_clear = self._values_clear_drops_dropdowns

    def _values_clear_drops_dropdowns(self, tab, row1, col1, row2, col2):
        # Live, 2026-10-07: values.clear on the template's Tickets cells also
        # deleted their (UI-made) Config dropdowns; updateCells(userEnteredValue) keeps them.
        for sheet_id, row, column in list(self.copy_rules):
            if self.copy_titles.get(sheet_id) != tab:
                continue
            if row + 1 >= row1 and column + 1 >= col1 and (row2 is None or row + 1 <= row2):
                if col2 is None or column + 1 <= col2:
                    del self.copy_rules[(sheet_id, row, column)]

    def get(self, *, spreadsheetId, **kwargs):
        self.gets.append(spreadsheetId)
        if spreadsheetId != "template-sheet" and kwargs.get("ranges"):
            self.grid_reads.append((spreadsheetId, list(kwargs["ranges"])))
            return _Response(self._copy_grid(kwargs["ranges"][0]))
        if spreadsheetId == "template-sheet":
            if self.source_error is not None:
                raise self.source_error
            return _Response(
                {
                    "sheets": [
                        {
                            "properties": tab,
                            **({"data": self.source_data[tab["title"]]} if tab["title"] in self.source_data else {}),
                        }
                        for tab in self.source_tabs
                    ]
                }
            )
        return _Response(
            {
                "sheets": [
                    {"properties": {"sheetId": sheet_id, "title": title, "index": index}}
                    for index, (sheet_id, title) in enumerate(self.copy_titles.items())
                ]
            }
        )

    def create(self, *, body, **_kwargs):
        self.creates.append(body)
        self.copy_titles = {0: "Sheet1"}
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

    def _copy_grid(self, a1):
        tab, row1, col1, row2, col2 = _parse_range(a1)
        sheet_id = next(key for key, title in self.copy_titles.items() if title == tab)
        rows = [
            {
                "values": [
                    {"dataValidation": self.copy_rules[(sheet_id, r - 1, c - 1)]}
                    if (sheet_id, r - 1, c - 1) in self.copy_rules
                    else {}
                    for c in range_(col1, col2 + 1)
                ]
            }
            for r in range_(row1, row2 + 1)
        ]
        return {
            "sheets": [
                {
                    "properties": {"title": tab},
                    "data": [{"startRow": row1 - 1, "startColumn": col1 - 1, "rowData": rows}],
                }
            ]
        }

    def batchUpdate(self, **kwargs):
        self.batch_updates.append(kwargs["body"])
        self.batch_targets.append(kwargs["spreadsheetId"])
        for request in kwargs["body"]["requests"]:
            if "deleteSheet" in request:
                self.copy_titles.pop(request["deleteSheet"]["sheetId"], None)
            if "updateSheetProperties" in request:
                properties = request["updateSheetProperties"]["properties"]
                self.copy_titles[properties["sheetId"]] = properties["title"]
            if "updateCells" in request and request["updateCells"]["fields"] == "userEnteredValue":
                grid = request["updateCells"]["range"]
                tab = self.copy_titles[grid["sheetId"]]
                first_col, last_col = grid["startColumnIndex"] + 1, grid["endColumnIndex"]
                self.cell_clears.append(
                    f"{_quote(tab)}!{_letter(first_col)}{grid['startRowIndex'] + 1}:{_letter(last_col)}"
                )
                if not self.ignore_cell_clears:
                    cells = self.values_api.grids.setdefault(tab, {})
                    for r, c in list(cells):
                        if r > grid["startRowIndex"] and first_col <= c <= last_col:
                            del cells[(r, c)]
            if "setDataValidation" in request:
                grid = request["setDataValidation"]["range"]
                for r in range_(grid["startRowIndex"], grid["endRowIndex"]):
                    for c in range_(grid["startColumnIndex"], grid["endColumnIndex"]):
                        self.copy_rules[(grid["sheetId"], r, c)] = request["setDataValidation"]["rule"]
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
    assert values.reads[0] == ("copied-sheet", "'Tickets'!A1:Z40")
    assert sheets.spreadsheets_api.cell_clears == ["'Tickets'!B6:I"]
    assert not any(target.startswith("'Tickets'") for target in values.clears)  # values.clear drops dropdowns
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
    assert sheets.spreadsheets_api.cell_clears == ["'Tickets'!B5:I"]
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
    values = sheets.spreadsheets_api.values_api
    values.grids["Backlog"] = values.grids.pop("Tickets")
    contract = _contract(tickets__tab="Backlog", tickets__header_search={"max_rows": 12, "max_columns": 10})
    GoogleSheetsTemplatePublisher(_Drive(), sheets, contract).publish(
        template="template-sheet", title="Audit", tables={"Tickets": _tickets()}
    )

    values = sheets.spreadsheets_api.values_api
    assert values.reads == [("copied-sheet", "'Backlog'!A1:J12"), ("copied-sheet", "'Backlog'!B6:I6")]
    assert values.updates == [("'Backlog'!B6", [_ROW])]
    assert _add_sheet_requests(sheets) == []  # no stray "Tickets" tab is added
    assert sheets.spreadsheets_api.cell_clears == ["'Backlog'!B6:I"]


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
    receipt = GoogleSheetsTemplatePublisher(drive, sheets).publish(
        template="template-sheet", title="Audit", folder_id="client-folder", tables={"Tickets": _tickets()}
    )

    api = sheets.spreadsheets_api
    assert receipt.url == "https://docs.google.com/spreadsheets/d/rebuilt-sheet/edit"
    assert receipt.spreadsheet_id == "rebuilt-sheet"
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
    assert api.values_api.reads == [("rebuilt-sheet", "'Tickets'!A1:Z40"), ("rebuilt-sheet", "'Tickets'!B6:I6")]
    assert api.values_api.updates == [("'Tickets'!B6", [_ROW])]


def test_fallback_restores_cross_tab_dropdowns_that_copy_to_drops():
    # Ticket 420 live run: sheets.copyTo dropped every Config-sourced rule on
    # Tickets!F6:G26, so the rebuilt workbook had no Priority/Classification
    # dropdowns. The source rules are set again after the renames.
    classification = {"condition": {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": "=Config!$B$2:$B"}]}}
    priority = {"condition": {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": "=Config!$A$2:$A"}]}}
    drive, sheets = _Drive(error=_HttpError(404)), _Sheets()
    api = sheets.spreadsheets_api
    rows = [{"values": [{"dataValidation": classification}, {"dataValidation": priority}]} for _ in range(21)]
    rows[3] = {"values": [{}, {"dataValidation": priority}]}  # a gap splits the F run
    api.source_data["Tickets"] = [{"startRow": 5, "startColumn": 5, "rowData": rows}]
    api.source_data["Config"] = [{"rowData": [{"values": [{}, {}]}]}]

    GoogleSheetsTemplatePublisher(drive, sheets).publish(
        template="template-sheet", title="Audit", tables={"Tickets": _tickets()}
    )

    requests = api.batch_updates[0]["requests"]
    renames = [index for index, request in enumerate(requests) if "updateSheetProperties" in request]
    restores = [request["setDataValidation"] for request in requests if "setDataValidation" in request]
    assert all(requests.index({"setDataValidation": rule}) > max(renames) for rule in restores)
    assert restores == [
        {
            "range": {"sheetId": 501, "startRowIndex": 5, "endRowIndex": 8, "startColumnIndex": 5, "endColumnIndex": 6},
            "rule": classification,
        },
        {
            "range": {
                "sheetId": 501,
                "startRowIndex": 9,
                "endRowIndex": 26,
                "startColumnIndex": 5,
                "endColumnIndex": 6,
            },
            "rule": classification,
        },
        {
            "range": {
                "sheetId": 501,
                "startRowIndex": 5,
                "endRowIndex": 26,
                "startColumnIndex": 6,
                "endColumnIndex": 7,
            },
            "rule": priority,
        },
    ]


def test_fallback_explains_a_template_the_token_cannot_read():
    drive, sheets = _Drive(error=_HttpError(404)), _Sheets()
    sheets.spreadsheets_api.source_error = _HttpError(404)
    with pytest.raises(RuntimeError, match=r"cannot read it either \(HTTP 404\).*spreadsheets"):
        GoogleSheetsTemplatePublisher(drive, sheets).publish(
            template="template-sheet", title="Audit", tables={"Tickets": _tickets()}
        )
    assert sheets.spreadsheets_api.creates == []


def test_cli_reports_google_api_errors_instead_of_a_traceback(monkeypatch, capsys):
    # Ticket 420 live run: a drive.file-only token made --check-template and
    # the publish path die with an HttpError traceback (exit 1).
    import crawler_cli.google_sheets as google_sheets
    from crawler_cli.__main__ import _build_parser, _publish_google_sheet, _run_technical_audit_questions

    sheets = _Sheets()
    sheets.spreadsheets_api.values_api.get = lambda **_kwargs: (_ for _ in ()).throw(_HttpError(404))
    monkeypatch.setattr(google_sheets, "google_services", lambda _credentials: (_Drive(), sheets))
    args = argparse.Namespace(
        google_sheets_contract=None,
        google_sheets_credentials=None,
        google_sheets_template="template-sheet",
        google_sheets_title=None,
        google_sheets_folder=None,
    )
    assert _publish_google_sheet(args, "Audit", {"Tickets": _tickets()}) is None
    assert "Google API returned HTTP 404" in capsys.readouterr().err

    check = _build_parser().parse_args(
        ["technical-audit-questions", "--check-template", "--google-sheets-template", "template-sheet"]
    )
    assert _run_technical_audit_questions(check) == 2
    assert "template check failed: Google API returned HTTP 404" in capsys.readouterr().err

    sheets.spreadsheets_api.values_api.get = lambda **_kwargs: (_ for _ in ()).throw(KeyError("not an API error"))
    with pytest.raises(KeyError):
        _publish_google_sheet(args, "Audit", {"Tickets": _tickets()})


def test_other_drive_copy_errors_are_not_masked_by_the_fallback():
    drive, sheets = _Drive(error=_HttpError(500)), _Sheets()
    with pytest.raises(_HttpError):
        GoogleSheetsTemplatePublisher(drive, sheets).publish(
            template="template-sheet", title="Audit", tables={"Tickets": _tickets()}
        )
    assert sheets.spreadsheets_api.creates == [] and sheets.spreadsheets_api.tabs_api.copies == []


# Dropdowns on every populated ticket row (ticket 428) -------------------------

# The real template's rules, read 2026-10-07: Ticket Classification (F) from
# Config!B2:B and Priority (G) from Config!A2:A, on rows 6-26 only.
_CLASSIFICATION_RULE = {
    "condition": {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": "=Config!$B$2:$B"}]},
    "showCustomUi": True,
}
_PRIORITY_RULE = {
    "condition": {"type": "ONE_OF_RANGE", "values": [{"userEnteredValue": "=Config!$A$2:$A"}]},
    "strict": True,
}


def _many_tickets(count):
    return _tickets(*([f"ticket {n}", *_ROW[1:]] for n in range(1, count + 1)))


def _validation_requests(api):
    return [
        request["setDataValidation"]
        for body in api.batch_updates
        for request in body["requests"]
        if "setDataValidation" in request
    ]


def _seed_template_rules(rules, sheet_id, first=5, last=26):
    for row in range(first, last):
        rules[(sheet_id, row, 5)] = copy.deepcopy(_CLASSIFICATION_RULE)
        rules[(sheet_id, row, 6)] = copy.deepcopy(_PRIORITY_RULE)


def test_dropdowns_are_applied_to_every_populated_ticket_row_past_the_template_range():
    sheets = _Sheets(titles=("Tickets", "Config"))
    api = sheets.spreadsheets_api
    _seed_template_rules(api.copy_rules, sheet_id=1)

    receipt = GoogleSheetsTemplatePublisher(_Drive(), sheets).publish(
        template="template-sheet", title="Audit", tables={"Tickets": _many_tickets(30)}
    )

    # The rule is read from the copy's first data row, not hard-coded.
    assert api.grid_reads == [("copied-sheet", ["'Tickets'!B6:I6"])]
    assert _validation_requests(api) == [
        {
            "range": {"sheetId": 1, "startRowIndex": 5, "endRowIndex": 35, "startColumnIndex": 5, "endColumnIndex": 6},
            "rule": _CLASSIFICATION_RULE,
        },
        {
            "range": {"sheetId": 1, "startRowIndex": 5, "endRowIndex": 35, "startColumnIndex": 6, "endColumnIndex": 7},
            "rule": _PRIORITY_RULE,
        },
    ]
    # One batchUpdate for the dropdowns, one request per column, after the value clear.
    assert [len(body["requests"]) for body in api.batch_updates] == [1, 2]
    assert "updateCells" in api.batch_updates[0]["requests"][0]
    assert set(api.batch_targets) == {"copied-sheet"}  # never the template
    rows_with = {row for (sheet_id, row, column) in api.copy_rules if sheet_id == 1 and column == 6}
    assert rows_with == set(range(5, 35))  # rows 6-35; nothing written below the last ticket
    assert receipt.dropdowns == ("'Tickets'!F6:F35", "'Tickets'!G6:G35")
    assert receipt.as_dict()["dropdowns"] == ["'Tickets'!F6:F35", "'Tickets'!G6:G35"]
    assert "  dropdowns applied to every ticket row: 'Tickets'!F6:F35, 'Tickets'!G6:G35" in receipt.summary_lines()


def test_dropdown_extension_leaves_template_rows_below_the_last_ticket_alone():
    sheets = _Sheets(titles=("Tickets", "Config"))
    api = sheets.spreadsheets_api
    _seed_template_rules(api.copy_rules, sheet_id=1)
    before = copy.deepcopy(api.copy_rules)

    GoogleSheetsTemplatePublisher(_Drive(), sheets).publish(
        template="template-sheet", title="Audit", tables={"Tickets": _many_tickets(3)}
    )

    assert [(item["range"]["startRowIndex"], item["range"]["endRowIndex"]) for item in _validation_requests(api)] == [
        (5, 8),
        (5, 8),
    ]
    # Rows 9-26 keep the template's own rules. The old values.clear of B6:I10000
    # deleted them (live, files.copy path), which the fake reproduces.
    assert api.copy_rules == before


def test_dropdowns_reach_every_ticket_row_on_the_copy_to_fallback():
    drive, sheets = _Drive(error=_HttpError(404)), _Sheets()
    api = sheets.spreadsheets_api
    rows = [
        {"values": [{"dataValidation": _CLASSIFICATION_RULE}, {"dataValidation": _PRIORITY_RULE}]} for _ in range(21)
    ]
    api.source_data["Tickets"] = [{"startRow": 5, "startColumn": 5, "rowData": rows}]

    receipt = GoogleSheetsTemplatePublisher(drive, sheets).publish(
        template="template-sheet", title="Audit", tables={"Tickets": _many_tickets(25)}
    )

    # The restore batch rebuilds F6:G26, then the extension covers rows 6-30.
    restore, extend = api.batch_updates[0], api.batch_updates[-1]
    assert sum("setDataValidation" in request for request in restore["requests"]) == 2
    assert [request["setDataValidation"]["range"] for request in extend["requests"]] == [
        {"sheetId": 501, "startRowIndex": 5, "endRowIndex": 30, "startColumnIndex": 5, "endColumnIndex": 6},
        {"sheetId": 501, "startRowIndex": 5, "endRowIndex": 30, "startColumnIndex": 6, "endColumnIndex": 7},
    ]
    assert {row for (sheet_id, row, column) in api.copy_rules if sheet_id == 501 and column == 5} == set(range(5, 30))
    assert set(api.batch_targets) == {"rebuilt-sheet"}
    assert receipt.dropdowns == ("'Tickets'!F6:F30", "'Tickets'!G6:G30")


def test_no_dropdown_writes_without_tickets_or_without_a_first_row_rule():
    sheets = _Sheets(titles=("Tickets", "Config"))
    _seed_template_rules(sheets.spreadsheets_api.copy_rules, sheet_id=1)
    receipt = GoogleSheetsTemplatePublisher(_Drive(), sheets).publish(
        template="template-sheet", title="Audit", tables={"Tickets": [list(TICKET_COLUMNS)]}
    )
    assert _validation_requests(sheets.spreadsheets_api) == [] and receipt.dropdowns == ()
    assert sheets.spreadsheets_api.grid_reads == []  # no rule is read when there is nothing to extend it to

    sheets = _Sheets(titles=("Tickets", "Config"))  # a template with no dropdowns
    receipt = GoogleSheetsTemplatePublisher(_Drive(), sheets).publish(
        template="template-sheet", title="Audit", tables={"Tickets": _many_tickets(30)}
    )
    assert _validation_requests(sheets.spreadsheets_api) == [] and receipt.dropdowns == ()
    assert "dropdowns" not in "\n".join(receipt.summary_lines())


# Evidence tab placement (ticket 424) ------------------------------------------


def _add_sheet_requests(sheets):
    return [
        request["addSheet"]["properties"]
        for body in sheets.spreadsheets_api.batch_updates
        for request in body["requests"]
        if "addSheet" in request
    ]


def test_evidence_tabs_are_inserted_after_tickets_and_before_config():
    sheets = _publish_question_workbook(_REAL_TICKETS_LAYOUT, titles=("Tickets", "Config"))

    # Tickets is index 0 and Config index 1 in the copy, so the new tabs take
    # indexes 1 and 2 and push Config to the end: Tickets, Questions, Q16 Data, Config.
    assert _add_sheet_requests(sheets) == [
        {"title": "Questions", "index": 1},
        {"title": "Q16 Data", "index": 2},
    ]


def test_evidence_tabs_follow_tickets_wherever_it_sits():
    sheets = _publish_question_workbook(_REAL_TICKETS_LAYOUT, titles=("Cover", "Tickets", "Config"))

    assert [props["index"] for props in _add_sheet_requests(sheets)] == [2, 3]


def test_without_a_tickets_table_evidence_tabs_go_before_the_protected_config_tab():
    sheets = _Sheets(titles=("Cover", "Config"))
    GoogleSheetsTemplatePublisher(_Drive(), sheets).publish(
        template="template-sheet", title="Audit", tables={"Overview": [["Metric"]]}
    )

    assert _add_sheet_requests(sheets) == [{"title": "Overview", "index": 1}]


# Read-back receipt (ticket 424, reusing ticket 189's check) -------------------


_EVIDENCE = {
    "Questions": [["Theme", "ID", "Affected"], ["Crawl", "Q16", 12], ["Crawl", "Q17", 0.25]],
    "Q16 Data": [["url", "status"], ["https://example.com/a", 404]],
}


def _publish_with_evidence(on_update=None, tickets=None):
    sheets = _Sheets(titles=("Tickets", "Config"))
    sheets.spreadsheets_api.values_api.on_update = on_update
    receipt = GoogleSheetsTemplatePublisher(_Drive(), sheets).publish(
        template="template-sheet",
        title="Audit",
        tables={**copy.deepcopy(_EVIDENCE), "Tickets": tickets or _tickets(list(_ROW), ["second", *_ROW[1:]])},
    )
    return sheets, receipt


def test_publish_reads_every_written_range_back_and_returns_a_receipt():
    sheets, receipt = _publish_with_evidence()

    values = sheets.spreadsheets_api.values_api
    assert receipt.spreadsheet_id == "copied-sheet"
    assert receipt.url == "https://docs.google.com/spreadsheets/d/copied-sheet/edit"
    assert receipt.as_dict()["ranges"] == [
        {"tab": "Tickets", "range": "'Tickets'!B6:I7", "rows": 2},
        {"tab": "Questions", "range": "'Questions'!A1:C3", "rows": 3},
        {"tab": "Q16 Data", "range": "'Q16 Data'!A1:B2", "rows": 2},
    ]
    # The ticket rows are read back exactly; evidence tabs as their whole used range.
    assert values.reads[-3:] == [
        ("copied-sheet", "'Tickets'!B6:I7"),
        ("copied-sheet", "'Questions'"),
        ("copied-sheet", "'Q16 Data'"),
    ]
    assert values.render_options[-3:] == ["UNFORMATTED_VALUE"] * 3
    assert receipt.summary_lines()[0] == "Receipt: spreadsheet copied-sheet; 3 ranges verified by read-back"
    assert "  'Tickets'!B6:I7: 2 rows" in receipt.summary_lines()


def test_read_back_tolerates_strings_for_numbers_and_trimmed_empty_cells():
    def as_sheets_returns(_range, values):
        # Formatted strings, no trailing empty cells, CRLF stored as LF.
        rows = [[str(cell) if isinstance(cell, (int, float)) else cell for cell in row] for row in values]
        return [row[: max((i + 1 for i, cell in enumerate(row) if cell != ""), default=0)] for row in rows]

    tickets = _tickets(["multi\r\nline", "", "", "", "Issue", "High", "", ""])
    _sheets, receipt = _publish_with_evidence(as_sheets_returns, tickets=tickets)
    assert [item.rows for item in receipt.ranges] == [1, 3, 2]


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        pytest.param(
            lambda r, v: v[:-1] if r.startswith("'Tickets'") else v, "sent 2 rows, read back 1", id="lost-row"
        ),
        pytest.param(
            lambda r, v: [[*row[:1], "changed", *row[2:]] for row in v] if r.startswith("'Q16") else v,
            "'Q16 Data'!B1: sent 'status', read back 'changed'",
            id="changed-cell",
        ),
        pytest.param(
            lambda r, v: [[*row, "stale"] for row in v] if r.startswith("'Questions'") else v,
            "'Questions'!D1: sent '', read back 'stale'",
            id="extra-cell",
        ),
        pytest.param(
            lambda r, v: [row[:5] for row in v] if r.startswith("'Tickets'") else v,
            "'Tickets'!G6: sent 'High', read back ''",
            id="truncated-columns",
        ),
    ],
)
def test_a_read_back_mismatch_raises_publish_receipt_error(tamper, message):
    with pytest.raises(PublishReceiptError) as raised:
        _publish_with_evidence(tamper)

    assert message in str(raised.value)
    assert raised.value.spreadsheet_id == "copied-sheet" and raised.value.mismatches
    assert "left in place for inspection" in str(raised.value)


def test_no_tickets_means_the_first_data_row_reads_back_empty():
    sheets = _Sheets()
    values = sheets.spreadsheets_api.values_api
    values.on_update = None
    receipt = GoogleSheetsTemplatePublisher(_Drive(), sheets).publish(
        template="template-sheet", title="Audit", tables={"Tickets": [list(TICKET_COLUMNS)]}
    )
    assert receipt.as_dict()["ranges"] == [{"tab": "Tickets", "range": "'Tickets'!B6:I6", "rows": 0}]

    # A stale row the clear missed is caught.
    sheets = _Sheets(header_rows=[*_REAL_TICKETS_LAYOUT[:5], [1, "old ticket"]])
    sheets.spreadsheets_api.ignore_cell_clears = True
    with pytest.raises(PublishReceiptError, match="old ticket"):
        GoogleSheetsTemplatePublisher(_Drive(), sheets).publish(
            template="template-sheet", title="Audit", tables={"Tickets": [list(TICKET_COLUMNS)]}
        )


def test_cli_prints_the_receipt(monkeypatch, capsys):
    import crawler_cli.google_sheets as google_sheets
    from crawler_cli.__main__ import _publish_google_sheet

    sheets = _Sheets(titles=("Tickets", "Config"))
    monkeypatch.setattr(google_sheets, "google_services", lambda _credentials: (_Drive(), sheets))
    args = argparse.Namespace(
        google_sheets_contract=None,
        google_sheets_credentials=None,
        google_sheets_template="template-sheet",
        google_sheets_title=None,
        google_sheets_folder=None,
    )
    receipt = _publish_google_sheet(args, "Audit", {"Tickets": _tickets()})
    assert receipt.ranges[0].range == "'Tickets'!B6:I6"

    sheets = _Sheets(titles=("Tickets", "Config"))
    sheets.spreadsheets_api.values_api.on_update = lambda _range, values: []
    assert _publish_google_sheet(args, "Audit", {"Tickets": _tickets()}) is None
    assert "read-back of workbook copied-sheet does not match" in capsys.readouterr().err


# --check-template: dropdown sources against the contract (ticket 424) ---------


def _rule(kind, *values):
    return {"condition": {"type": kind, "values": [{"userEnteredValue": value} for value in values]}, "strict": True}


_CONFIG_RANGE = _rule("ONE_OF_RANGE", "=Config!$A$2:$A$5")
_PRIORITY_RANGE = _rule("ONE_OF_RANGE", "='Config'!B2:B")


class _TemplateSpreadsheets:
    """The template as Sheets returns it to a read-only validation check; any write fails the test."""

    def __init__(self, rules=None, config=None, header_rows=None, rows=100):
        self.values_api = _Values(header_rows)
        config = config or [
            ["Classification", "Priority"],
            ["Error", "High"],
            ["Issue", "Medium"],
            ["Warning", "Low"],
            ["Improvement"],
        ]
        self.values_api._fill("Config", 1, 1, config)
        # Rules for columns F (classification) and G (priority), on every sampled row.
        self.rules = {"F": _CONFIG_RANGE, "G": _PRIORITY_RANGE} if rules is None else rules
        self.rows = rows
        self.grid_requests: list[dict[str, object]] = []

    def get(self, **kwargs):
        self.grid_requests.append(kwargs)
        assert kwargs["includeGridData"] is True and "dataValidation" in kwargs["fields"]
        tab, row1, col1, row2, col2 = _parse_range(kwargs["ranges"][0])
        row_data = []
        for row in range(row1, min(row2, row1 + self.rows - 1) + 1):
            cells = []
            for column in range(col1, col2 + 1):
                label = _column_letter_for_test(column)
                rule = self.rules.get(label)
                rule = rule(row) if callable(rule) else rule
                cells.append({"dataValidation": rule} if rule else {})
            row_data.append({"values": cells})
        return _Response(
            {
                "sheets": [
                    {
                        "properties": {"title": tab},
                        "data": [{"startRow": row1 - 1, "startColumn": col1 - 1, "rowData": row_data}],
                    }
                ]
            }
        )

    def values(self):
        return self.values_api

    def batchUpdate(self, **_kwargs):  # pragma: no cover - asserting no writes
        raise AssertionError("the template check must not write")


def _column_letter_for_test(number):
    label = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        label = chr(65 + remainder) + label
    return label


class _TemplateSheets:
    def __init__(self, **kwargs):
        self.spreadsheets_api = _TemplateSpreadsheets(**kwargs)

    def spreadsheets(self):
        return self.spreadsheets_api


def _assert_no_writes(sheets):
    values = sheets.spreadsheets_api.values_api
    assert values.updates == [] and values.clears == []


def test_check_template_resolves_config_ranges_and_passes_when_they_match_the_contract():
    sheets = _TemplateSheets()
    report = check_template_validation(sheets, template="template-sheet")

    assert report.ok
    assert (report.header_cell, report.rows_checked) == ("B5", (6, 105))
    assert sheets.spreadsheets_api.grid_requests[0]["ranges"] == ["'Tickets'!B6:I105"]
    by_column = {check.column: check for check in report.checks}
    assert by_column["Priority"].source == "range 'Config'!B2:B"
    assert by_column["Priority"].template_values == ("High", "Medium", "Low")
    assert by_column["Ticket Classification"].cell == "F6"
    assert report.lines()[-1] == "Template check passed."
    _assert_no_writes(sheets)


def test_check_template_reports_a_clear_diff_when_config_disagrees():
    config = [["Classification", "Priority"], ["Error", "High"], ["Issue", "Medium"], ["Warning", "Critical"], ["Bug"]]
    sheets = _TemplateSheets(config=config)
    report = check_template_validation(sheets, template="template-sheet")

    assert not report.ok
    text = "\n".join(report.lines())
    assert "FAIL Priority (G6): range 'Config'!B2:B" in text
    assert "only in template: Critical" in text and "only in contract: Low" in text
    assert "only in template: Bug" in text and "only in contract: Improvement" in text
    assert "Template check FAILED" in text
    _assert_no_writes(sheets)


def test_check_template_reads_one_of_list_rules():
    rules = {
        "F": _rule("ONE_OF_LIST", "Error", "Issue", "Warning", "Improvement"),
        "G": _rule("ONE_OF_LIST", "High", "Medium", "Low", "Urgent"),
    }
    report = check_template_validation(_TemplateSheets(rules=rules), template="template-sheet")

    by_column = {check.column: check for check in report.checks}
    assert by_column["Ticket Classification"].ok and by_column["Ticket Classification"].source == "list"
    assert by_column["Priority"].only_in_template == ("Urgent",) and not report.ok


@pytest.mark.parametrize(
    ("rules", "problem"),
    [
        pytest.param({"F": _CONFIG_RANGE}, "has no data validation", id="missing"),
        pytest.param(
            {"F": _CONFIG_RANGE, "G": _rule("NUMBER_BETWEEN", "1", "3")}, "unsupported validation type", id="wrong-type"
        ),
        pytest.param(
            {"F": _CONFIG_RANGE, "G": lambda row: _PRIORITY_RANGE if row < 50 else _rule("ONE_OF_LIST", "P1", "P2")},
            "row 50 uses a different rule",
            id="rule-changes-down-the-column",
        ),
    ],
)
def test_check_template_fails_on_missing_or_inconsistent_rules(rules, problem):
    report = check_template_validation(_TemplateSheets(rules=rules), template="template-sheet")

    assert not report.ok
    assert problem in "\n".join(report.lines())


def test_check_template_notes_rows_without_validation_but_does_not_fail_on_them():
    rules = {"F": _CONFIG_RANGE, "G": lambda row: _PRIORITY_RANGE if row < 56 else None}
    report = check_template_validation(_TemplateSheets(rules=rules), template="template-sheet")

    assert report.ok
    assert "note: 50 of 100 rows checked have no validation (first: row 56)" in "\n".join(report.lines())


def test_check_template_fails_when_the_template_header_is_missing():
    with pytest.raises(TemplateHeaderError, match="template template-sheet"):
        check_template_validation(_TemplateSheets(header_rows=[["Nothing here"]]), template="template-sheet")


def test_check_template_defaults_to_the_contract_template():
    sheets = _TemplateSheets()
    check_template_validation(sheets)
    assert sheets.spreadsheets_api.grid_requests[0]["spreadsheetId"] == "1T9BRLgaFDZ99Lx3q53Av75eZZM32BIJc0nahVPQpGmU"


def test_check_template_cli_is_stand_alone_and_exits_non_zero_on_a_mismatch(monkeypatch, capsys):
    import crawler_cli.google_sheets as google_sheets
    from crawler_cli.__main__ import _build_parser, _run_technical_audit_questions

    sheets = _TemplateSheets()
    seen = []
    monkeypatch.setattr(
        google_sheets, "google_services", lambda credentials: seen.append(credentials) or (None, sheets)
    )
    args = _build_parser().parse_args(
        ["technical-audit-questions", "--check-template", "--google-sheets-template", "template-sheet"]
    )
    assert args.audit is None and args.out is None
    assert _run_technical_audit_questions(args) == 0
    out = capsys.readouterr().out
    assert "OK   Priority (G6)" in out and "Template check passed." in out
    assert seen == [None]

    bad = _TemplateSheets(config=[["Classification", "Priority"], ["Error", "High"]])
    monkeypatch.setattr(google_sheets, "google_services", lambda _credentials: (None, bad))
    assert _run_technical_audit_questions(args) == 2
    assert "only in contract: Medium, Low" in capsys.readouterr().out
    _assert_no_writes(bad)


def test_questions_cli_still_needs_audit_and_out_without_check_template(capsys):
    from crawler_cli.__main__ import _build_parser, _run_technical_audit_questions

    args = _build_parser().parse_args(["technical-audit-questions"])
    assert _run_technical_audit_questions(args) == 2
    assert "needs --audit and --out" in capsys.readouterr().err
