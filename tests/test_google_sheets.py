from __future__ import annotations

from crawler_cli.google_sheets import GoogleSheetsTemplatePublisher
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
    def __init__(self):
        self.values_api = _Values()

    def get(self, **_kwargs):
        return _Response({"sheets": [{"properties": {"sheetId": 1, "title": "Tickets"}}]})

    def values(self):
        return self.values_api

    def batchUpdate(self, **_kwargs):
        return _Response({})


class _Sheets:
    def __init__(self):
        self.spreadsheets_api = _Spreadsheets()

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
