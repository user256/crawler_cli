"""Optional, narrowly-scoped Google Sheets template publisher.

Google dependencies are imported only for an explicit publish request.  The
audit itself stays fully local and deterministic.
"""

from __future__ import annotations

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


class GoogleSheetsTemplatePublisher:
    """Copy one template and replace only named, generated audit tabs."""

    def __init__(self, drive: Any, sheets: Any) -> None:
        self.drive = drive
        self.sheets = sheets

    def publish(
        self,
        *,
        template: str,
        title: str,
        tables: Mapping[str, list[list[object]]],
        folder_id: str | None = None,
        locate_ticket_header: bool = False,
    ) -> str:
        body: dict[str, object] = {"name": title}
        if folder_id:
            body["parents"] = [folder_id]
        copied = (
            self.drive.files()
            .copy(
                fileId=google_sheet_id(template),
                body=body,
                fields="id,webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        spreadsheet_id = str(copied["id"])
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
        tickets = tables.get("Tickets")
        if locate_ticket_header and tickets:
            if "Tickets" not in sheet_ids:
                raise TemplateHeaderError(
                    f"copied workbook {spreadsheet_id} has no Tickets tab; nothing was written to it"
                )
            ticket_anchor = self._ticket_header_anchor(spreadsheet_id, "Tickets", [str(cell) for cell in tickets[0]])
        missing = [title for title in tables if title not in sheet_ids]
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

        for name, values in tables.items():
            # The client template owns the Tickets header, counter formula and
            # dropdown validation.  Write generated rows beneath that header
            # instead of clearing A:ZZ, which would erase the formula the
            # copied template uses to count tickets.
            if name == "Tickets" and name in sheet_ids:
                column_count = max(len(values[0]) if values else 0, 1)
                start_index, start_row = ticket_anchor or (1, 2)
                start_column = _column_letter(start_index)
                end_column = _column_letter(start_index + column_count - 1)
                self.sheets.spreadsheets().values().clear(
                    spreadsheetId=spreadsheet_id,
                    range=f"'{name}'!{start_column}{start_row}:{end_column}10000",
                    body={},
                ).execute()
                data_rows = values[1:] if len(values) > 1 else []
                if data_rows:
                    self.sheets.spreadsheets().values().update(
                        spreadsheetId=spreadsheet_id,
                        range=f"'{name}'!{start_column}{start_row}",
                        valueInputOption="RAW",
                        body={"values": data_rows},
                    ).execute()
                continue
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
        return str(copied.get("webViewLink") or f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit")

    def _ticket_header_anchor(self, spreadsheet_id: str, name: str, header: list[str]) -> tuple[int, int]:
        """Return the 1-based column and first data row beneath the copied template's ticket header.

        Templates differ in where the header sits (row 1 column A, or row 6
        column B beneath a title block).  The whole header must appear, in
        order, in consecutive cells; an absent, partial or reordered header
        raises instead of defaulting to A2, which would overwrite client
        content and put generated fields under the wrong columns.
        """
        found = (
            self.sheets.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=f"'{name}'!A1:Z40").execute()
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
            f"matching {' | '.join(header)}{closest}; nothing was written to it"
        )


def credential_path(value: str | None) -> str | None:
    """Reject an accidental directory early without reading credentials."""
    if value is None:
        return None
    path = Path(value)
    if not path.is_file():
        raise ValueError("--google-sheets-credentials must name a credential file")
    return str(path)


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
