"""Optional, narrowly-scoped Google Sheets template publisher.

Google dependencies are imported only for an explicit publish request.  The
audit itself stays fully local and deterministic.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any


_SHEET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,}$")
_SHEET_URL_PATTERN = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")


def google_sheet_id(value: str) -> str:
    """Accept a spreadsheet ID or normal Google Sheets URL, never a Drive path."""
    matched = _SHEET_URL_PATTERN.search(value)
    identifier = matched.group(1) if matched else value.strip()
    if not _SHEET_ID_PATTERN.fullmatch(identifier):
        raise ValueError("--google-sheets-template must be a Google Sheets URL or spreadsheet ID")
    return identifier


def google_services(credentials_file: str | None = None) -> tuple[Any, Any]:
    """Return authenticated Drive and Sheets clients for an explicit publish."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("Google Sheets publishing requires `pip install crawler-cli[google-sheets]`.") from exc

    scopes = ("https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/spreadsheets")
    if credentials_file:
        credentials = service_account.Credentials.from_service_account_file(credentials_file, scopes=scopes)
    else:
        token_file = os.environ.get("GOOGLE_DOCS_OAUTH_TOKEN_FILE")
        if not token_file:
            raise RuntimeError(
                "Set GOOGLE_DOCS_OAUTH_TOKEN_FILE or pass --google-sheets-credentials for Google Sheets publishing."
            )
        # Keep the scopes granted during the explicit OAuth flow. Supplying a
        # broader list here cannot expand a refresh token and makes an
        # otherwise-valid Drive-authorised token look unusable.
        credentials = Credentials.from_authorized_user_file(token_file)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
    return build("drive", "v3", credentials=credentials), build("sheets", "v4", credentials=credentials)


class TemplateHeaderError(ValueError):
    """The copied template's Tickets header does not match the generated columns."""


class TemplateContractError(ValueError):
    """The template contract is malformed, or the generated tables break it."""


TEMPLATE_CONTRACT_VERSION = "crawler-cli/google-sheets-template-contract/1"


def default_template_contract_path() -> Path:
    return Path(__file__).parents[2] / "templates" / "google-sheets-template-contract.json"


def load_template_contract(path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate the template contract the publisher maps tables through."""
    target = Path(path) if path else default_template_contract_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TemplateContractError(f"could not load template contract {target}: {exc}") from exc
    return validate_template_contract(payload, source=str(target))


def validate_template_contract(payload: object, *, source: str = "template contract") -> dict[str, Any]:
    def fail(message: str) -> TemplateContractError:
        return TemplateContractError(f"{source}: {message}")

    if not isinstance(payload, dict):
        raise fail("must be a JSON object")
    if payload.get("version") != TEMPLATE_CONTRACT_VERSION:
        raise fail(f"version must be {TEMPLATE_CONTRACT_VERSION!r}")
    template = payload.get("template")
    if not isinstance(template, dict) or not isinstance(template.get("url"), str):
        raise fail("template.url must be a Google Sheets URL or spreadsheet ID")
    try:
        google_sheet_id(template["url"])
    except ValueError as exc:
        raise fail(f"template.url is not a Google Sheets URL or spreadsheet ID: {template['url']!r}") from exc
    tickets = payload.get("tickets")
    if not isinstance(tickets, dict):
        raise fail("tickets must be an object")
    if not isinstance(tickets.get("tab"), str) or not tickets["tab"].strip():
        raise fail("tickets.tab must be a non-empty tab name")
    columns = tickets.get("columns")
    if (
        not isinstance(columns, list)
        or not columns
        or not all(isinstance(column, str) and column.strip() for column in columns)
    ):
        raise fail("tickets.columns must be a non-empty list of column names")
    if len({_header_key(column) for column in columns}) != len(columns):
        raise fail("tickets.columns must not repeat a column")
    search = tickets.get("header_search", {"max_rows": 40, "max_columns": 26})
    if not isinstance(search, dict):
        raise fail("tickets.header_search must be an object")
    for key, ceiling in (("max_rows", 1000), ("max_columns", 702)):
        value = search.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= ceiling:
            raise fail(f"tickets.header_search.{key} must be an integer from 1 to {ceiling}")
    if search["max_columns"] < len(columns):
        raise fail("tickets.header_search.max_columns is narrower than the ticket header")
    value_sets = tickets.get("value_sets", {})
    if not isinstance(value_sets, dict):
        raise fail("tickets.value_sets must be an object")
    known = {_header_key(column) for column in columns}
    for column, allowed in value_sets.items():
        if _header_key(column) not in known:
            raise fail(f"tickets.value_sets names {column!r}, which is not a ticket column")
        if not isinstance(allowed, list) or not allowed or not all(isinstance(value, str) for value in allowed):
            raise fail(f"tickets.value_sets[{column!r}] must be a non-empty list of strings")
    protected = payload.get("protected_tabs", [])
    if not isinstance(protected, list) or not all(isinstance(name, str) for name in protected):
        raise fail("protected_tabs must be a list of tab names")
    if tickets["tab"] in protected:
        raise fail("the tickets tab cannot also be a protected tab")
    return {
        **payload,
        "tickets": {**tickets, "header_search": search, "value_sets": value_sets},
        "protected_tabs": protected,
    }


class GoogleSheetsTemplatePublisher:
    """Copy one template and replace only named, generated audit tabs.

    The template ID, Tickets tab name, ticket columns, allowed dropdown values
    and protected tabs come from a template contract
    (``templates/google-sheets-template-contract.json`` by default).  The
    generated ``Tickets`` table is always written beneath the copied
    workbook's own header, which is located and checked before any write;
    there is no fixed-row or A2 fallback.
    """

    def __init__(self, drive: Any, sheets: Any, contract: Mapping[str, Any] | None = None) -> None:
        self.drive = drive
        self.sheets = sheets
        self.contract = validate_template_contract(dict(contract)) if contract is not None else load_template_contract()

    def publish(
        self,
        *,
        title: str,
        tables: Mapping[str, list[list[object]]],
        template: str | None = None,
        folder_id: str | None = None,
    ) -> str:
        ticket_contract = self.contract["tickets"]
        ticket_tab = str(ticket_contract["tab"])
        tickets = tables.get("Tickets")
        generic = {name: values for name, values in tables.items() if name != "Tickets"}
        # Refuse a table set that breaks the contract before anything is
        # copied: nothing is created or written for a bad request.
        blocked = sorted(name for name in generic if name in {ticket_tab, *self.contract["protected_tabs"]})
        if blocked:
            raise TemplateContractError(
                f"generated tables would overwrite template-owned tabs {blocked}; nothing was copied or written"
            )
        if tickets is not None:
            self._check_generated_tickets(tickets)

        source_id = google_sheet_id(template or str(self.contract["template"]["url"]))
        spreadsheet_id, link = self._copy_template(source_id, title, folder_id)
        metadata = (
            self.sheets.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                fields="sheets.properties(sheetId,title)",
            )
            .execute()
        )
        sheet_ids = {
            str(sheet["properties"]["title"]): int(sheet["properties"]["sheetId"])
            for sheet in metadata.get("sheets", [])
        }
        # Verify the destination Tickets header before the first write to the
        # copy, so a changed template fails without touching client content.
        ticket_anchor: tuple[int, int] | None = None
        if tickets is not None:
            if ticket_tab not in sheet_ids:
                raise TemplateHeaderError(
                    f"copied workbook {spreadsheet_id} has no {ticket_tab} tab; nothing was written to it"
                )
            ticket_anchor = self._ticket_header_anchor(spreadsheet_id, ticket_tab, list(ticket_contract["columns"]))
        missing = [name for name in generic if name not in sheet_ids]
        if missing:
            created = (
                self.sheets.spreadsheets()
                .batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={"requests": [{"addSheet": {"properties": {"title": name}}} for name in missing]},
                )
                .execute()
            )
            for reply in created.get("replies", []):
                properties = reply.get("addSheet", {}).get("properties", {})
                if properties:
                    sheet_ids[str(properties["title"])] = int(properties["sheetId"])

        if tickets is not None and ticket_anchor is not None:
            # The client template owns the Tickets header, counter formula and
            # dropdown validation.  Write generated rows beneath that header
            # instead of clearing A:ZZ, which would erase the formula the
            # copied template uses to count tickets.
            start_index, start_row = ticket_anchor
            start_column = _column_letter(start_index)
            end_column = _column_letter(start_index + len(ticket_contract["columns"]) - 1)
            self.sheets.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=f"'{ticket_tab}'!{start_column}{start_row}:{end_column}10000",
                body={},
            ).execute()
            data_rows = tickets[1:]
            if data_rows:
                self.sheets.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=f"'{ticket_tab}'!{start_column}{start_row}",
                    valueInputOption="RAW",
                    body={"values": data_rows},
                ).execute()
        for name, values in generic.items():
            self.sheets.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=f"'{name}'!A:ZZ",
                body={},
            ).execute()
            self.sheets.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"'{name}'!A1",
                valueInputOption="RAW",
                body={"values": values},
            ).execute()

        # A template's formatting remains intact.  These requests provide a
        # usable green header only for detail tabs created by this run.
        created_ids = [sheet_ids[name] for name in missing]
        if created_ids:
            self.sheets.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "repeatCell": {
                                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                                "cell": {
                                    "userEnteredFormat": {
                                        "backgroundColor": {"red": 0.13, "green": 0.43, "blue": 0.26},
                                        "textFormat": {
                                            "bold": True,
                                            "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                                        },
                                    }
                                },
                                "fields": "userEnteredFormat(backgroundColor,textFormat)",
                            }
                        }
                        for sheet_id in created_ids
                    ]
                },
            ).execute()
        return link or f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"

    def _check_generated_tickets(self, tickets: list[list[object]]) -> None:
        """The generated Tickets table must use the contract's columns and dropdown values."""
        ticket_contract = self.contract["tickets"]
        columns = [str(column) for column in ticket_contract["columns"]]
        header = [_header_key(cell) for cell in tickets[0]] if tickets else []
        if header != [_header_key(column) for column in columns]:
            raise TemplateContractError(
                f"generated Tickets columns {list(tickets[0]) if tickets else []} differ from the template "
                f"contract {columns}; nothing was copied or written"
            )
        positions = {_header_key(column): index for index, column in enumerate(columns)}
        for column, allowed in ticket_contract["value_sets"].items():
            index = positions[_header_key(column)]
            permitted = {_header_key(value) for value in allowed} | {""}
            for row_number, row in enumerate(tickets[1:], start=1):
                value = row[index] if index < len(row) else ""
                if _header_key(value) not in permitted:
                    raise TemplateContractError(
                        f"generated ticket {row_number} has {column} {value!r}, outside the template's "
                        f"dropdown values {allowed}; nothing was copied or written"
                    )

    def _copy_template(self, source_id: str, title: str, folder_id: str | None) -> tuple[str, str | None]:
        """Copy the template with Drive, or tab by tab when a drive.file token is refused."""
        body: dict[str, object] = {"name": title}
        if folder_id:
            body["parents"] = [folder_id]
        try:
            copied = (
                self.drive.files()
                .copy(fileId=source_id, body=body, fields="id,webViewLink", supportsAllDrives=True)
                .execute()
            )
        except Exception as exc:  # googleapiclient is optional; match its HttpError by shape.
            if _http_status(exc) not in {403, 404}:
                raise
            return self._copy_template_tabs(source_id, title, folder_id)
        return str(copied["id"]), copied.get("webViewLink")

    def _copy_template_tabs(self, source_id: str, title: str, folder_id: str | None) -> tuple[str, str | None]:
        """Rebuild the template in a new workbook with ``sheets.copyTo``.

        A ``drive.file`` token cannot copy a file this app did not create, but
        the Sheets scope can still copy each tab with its formatting, formulas
        and data validation.  Tabs are copied in template order, the default
        empty tab is removed, and each ``Copy of X`` is renamed back to ``X``
        so cross-tab references such as the Config dropdown sources resolve.
        """
        source = (
            self.sheets.spreadsheets()
            .get(spreadsheetId=source_id, fields="sheets.properties(sheetId,title,index)")
            .execute()
        )
        tabs = sorted(
            (sheet["properties"] for sheet in source.get("sheets", [])),
            key=lambda properties: int(properties.get("index", 0)),
        )
        if not tabs:
            raise RuntimeError(f"template {source_id} has no tabs to copy")
        created = (
            self.sheets.spreadsheets()
            .create(
                body={"properties": {"title": title}},
                fields="spreadsheetId,spreadsheetUrl,sheets.properties(sheetId,title)",
            )
            .execute()
        )
        spreadsheet_id = str(created["spreadsheetId"])
        placeholder_ids = [int(sheet["properties"]["sheetId"]) for sheet in created.get("sheets", [])]
        requests: list[dict[str, object]] = []
        for tab in tabs:
            copied = (
                self.sheets.spreadsheets()
                .sheets()
                .copyTo(
                    spreadsheetId=source_id,
                    sheetId=int(tab["sheetId"]),
                    body={"destinationSpreadsheetId": spreadsheet_id},
                )
                .execute()
            )
            requests.append(
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": int(copied["sheetId"]), "title": str(tab["title"])},
                        "fields": "title",
                    }
                }
            )
        # Delete the placeholder first so its name cannot collide with a
        # template tab being renamed back (for example "Sheet1").
        self.sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"deleteSheet": {"sheetId": sheet_id}} for sheet_id in placeholder_ids] + requests},
        ).execute()
        if folder_id:
            previous = self.drive.files().get(fileId=spreadsheet_id, fields="parents", supportsAllDrives=True).execute()
            self.drive.files().update(
                fileId=spreadsheet_id,
                addParents=folder_id,
                removeParents=",".join(previous.get("parents", [])),
                fields="id",
                supportsAllDrives=True,
            ).execute()
        return spreadsheet_id, created.get("spreadsheetUrl")

    def _ticket_header_anchor(self, spreadsheet_id: str, name: str, header: list[str]) -> tuple[int, int]:
        """Return the 1-based column and first data row beneath the copied template's ticket header.

        Templates differ in where the header sits (row 1 column A, or row 5
        column B beneath a title block in the Canonicals template).  The whole
        header must appear, in order, in consecutive cells within the
        contract's search window; an absent, partial or reordered header
        raises instead of defaulting to A2, which would overwrite client
        content and put generated fields under the wrong columns.
        """
        search = self.contract["tickets"]["header_search"]
        window = f"A1:{_column_letter(int(search['max_columns']))}{int(search['max_rows'])}"
        found = (
            self.sheets.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=f"'{name}'!{window}").execute()
        )
        expected = [_header_key(cell) for cell in header]
        closest = ""
        for row_index, row in enumerate(found.get("values", []), start=1):
            cells = [_header_key(cell) for cell in row]
            for column_index, cell in enumerate(cells, start=1):
                if cell != expected[0]:
                    continue
                actual = cells[column_index - 1 : column_index - 1 + len(expected)]
                if actual == expected:
                    return column_index, row_index + 1
                closest = closest or (
                    f"; found at {_column_letter(column_index)}{row_index}: "
                    + " | ".join(str(value) for value in row[column_index - 1 : column_index - 1 + len(expected)])
                )
        raise TemplateHeaderError(
            f"the {name} tab of copied workbook {spreadsheet_id} has no header row "
            f"matching {' | '.join(header)} in {window}{closest}; nothing was written to it"
        )


def credential_path(value: str | None) -> str | None:
    """Reject an accidental directory early without reading credentials."""
    if value is None:
        return None
    path = Path(value)
    if not path.is_file():
        raise ValueError("--google-sheets-credentials must name a credential file")
    return str(path)


def _http_status(exc: BaseException) -> int | None:
    """Return the HTTP status of a googleapiclient ``HttpError`` without importing it."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _header_key(value: object) -> str:
    return " ".join(str(value).split()).casefold()


def _column_letter(column_count: int) -> str:
    """Return a Sheets column label for a positive 1-based count."""
    label = ""
    current = column_count
    while current:
        current, remainder = divmod(current - 1, 26)
        label = chr(65 + remainder) + label
    return label
