from __future__ import annotations

import pytest

from crawler_cli.google_sheets import GoogleSheetsTemplatePublisher, TemplateHeaderError
from crawler_cli.technical_audit_tickets import TICKET_COLUMNS


class _Response:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class _DriveFiles:
    def copy(self, **_kwargs):
        return _Response(
            {"id": "copied-sheet", "webViewLink": "https://docs.google.com/spreadsheets/d/copied-sheet/edit"}
        )


class _Drive:
    def files(self):
        return _DriveFiles()


class _Values:
    def __init__(self):
        self.clears: list[str] = []
        self.updates: list[tuple[str, list[list[object]]]] = []

    def clear(self, *, range, **_kwargs):
        self.clears.append(range)
        return _Response({})

    def update(self, *, range, body, **_kwargs):
        self.updates.append((range, body["values"]))
        return _Response({})


class _Spreadsheets:
    def __init__(self, titles=("Tickets",)):
        self.values_api = _Values()
        self.titles = titles
        self.batch_updates: list[dict[str, object]] = []

    def get(self, **_kwargs):
        return _Response(
            {"sheets": [{"properties": {"sheetId": i, "title": title}} for i, title in enumerate(self.titles, 1)]}
        )

    def values(self):
        return self.values_api

    def batchUpdate(self, **kwargs):
        self.batch_updates.append(kwargs["body"])
        added = [request["addSheet"]["properties"] for request in kwargs["body"]["requests"] if "addSheet" in request]
        return _Response(
            {"replies": [{"addSheet": {"properties": {**props, "sheetId": 100 + i}}} for i, props in enumerate(added)]}
        )


class _Sheets:
    def __init__(self, titles=("Tickets",)):
        self.spreadsheets_api = _Spreadsheets(titles)

    def spreadsheets(self):
        return self.spreadsheets_api


def test_ticket_publish_preserves_template_header_and_formula_area():
    sheets = _Sheets()
    publisher = GoogleSheetsTemplatePublisher(_Drive(), sheets)
    row = ["ticket"] * len(TICKET_COLUMNS)

    publisher.publish(
        template="template-sheet",
        title="Audit",
        tables={"Tickets": [list(TICKET_COLUMNS), row]},
    )

    values = sheets.spreadsheets_api.values_api
    assert values.clears == ["'Tickets'!A2:H10000"]
    assert values.updates == [("'Tickets'!A2", [row])]


def test_ticket_publish_can_locate_a_header_beneath_a_title_block():
    sheets = _Sheets()
    header_rows = [[], [], ["", "Count of tickets: 0"], [], [], ["", *TICKET_COLUMNS]]
    sheets.spreadsheets_api.values_api.get = lambda **_kwargs: _Response({"values": header_rows})
    row = ["ticket"] * len(TICKET_COLUMNS)

    GoogleSheetsTemplatePublisher(_Drive(), sheets).publish(
        template="template-sheet",
        title="Audit",
        tables={"Tickets": [list(TICKET_COLUMNS), row]},
        locate_ticket_header=True,
    )

    values = sheets.spreadsheets_api.values_api
    assert values.clears == ["'Tickets'!B7:I10000"]
    assert values.updates == [("'Tickets'!B7", [row])]


def _publish_question_workbook(header_rows, titles=("Tickets",)):
    sheets = _Sheets(titles)
    sheets.spreadsheets_api.values_api.get = lambda **_kwargs: _Response({"values": header_rows})
    row = ["ticket"] * len(TICKET_COLUMNS)
    GoogleSheetsTemplatePublisher(_Drive(), sheets).publish(
        template="template-sheet",
        title="Audit",
        tables={"Questions": [["Theme", "ID"]], "Q16 Data": [["url"]], "Tickets": [list(TICKET_COLUMNS), row]},
        locate_ticket_header=True,
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
    sheets = _Sheets()
    sheets.spreadsheets_api.values_api.get = lambda **_kwargs: _Response({"values": [*_TITLE_BLOCK, ["", *header]]})

    with pytest.raises(TemplateHeaderError, match="nothing was written"):
        GoogleSheetsTemplatePublisher(_Drive(), sheets).publish(
            template="template-sheet",
            title="Audit",
            tables={"Questions": [["Theme"]], "Q16 Data": [["url"]], "Tickets": [list(TICKET_COLUMNS), ["x"] * 8]},
            locate_ticket_header=True,
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
    assert ("'Tickets'!B5", [["ticket"] * len(TICKET_COLUMNS)]) in values.updates
