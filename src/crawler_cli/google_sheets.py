"""Optional, narrowly-scoped Google Sheets template publisher.

Google dependencies are imported only for an explicit publish request.  The
audit itself stays fully local and deterministic.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
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


class PublishReceiptError(RuntimeError):
    """Reading the written ranges back did not return what was sent."""

    def __init__(self, message: str, *, spreadsheet_id: str, url: str, mismatches: Sequence[str]) -> None:
        super().__init__(message)
        self.spreadsheet_id = spreadsheet_id
        self.url = url
        self.mismatches = tuple(mismatches)


@dataclass(frozen=True)
class PublishedRange:
    """One range written by a publish and confirmed by reading it back."""

    tab: str
    range: str
    rows: int


@dataclass(frozen=True)
class PublishReceipt:
    """What a publish wrote, every range of it verified by a read-back."""

    spreadsheet_id: str
    url: str
    ranges: tuple[PublishedRange, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {
            "spreadsheet_id": self.spreadsheet_id,
            "url": self.url,
            "ranges": [{"tab": item.tab, "range": item.range, "rows": item.rows} for item in self.ranges],
        }

    def summary_lines(self) -> list[str]:
        lines = [f"Receipt: spreadsheet {self.spreadsheet_id}; {len(self.ranges)} ranges verified by read-back"]
        lines.extend(f"  {item.range}: {item.rows} rows" for item in self.ranges)
        return lines


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
    ) -> PublishReceipt:
        """Copy the template, write the tables, read every written range back and return a receipt.

        Raises ``PublishReceiptError`` when a read-back differs from what was
        sent, so a partial or altered write is never reported as success.
        """
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
                fields="sheets.properties(sheetId,title,index)",
            )
            .execute()
        )
        sheet_ids: dict[str, int] = {}
        sheet_indexes: dict[str, int] = {}
        for position, sheet in enumerate(metadata.get("sheets", [])):
            properties = sheet["properties"]
            sheet_ids[str(properties["title"])] = int(properties["sheetId"])
            sheet_indexes[str(properties["title"])] = int(properties.get("index", position))
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
            insert_at = _evidence_tab_index(sheet_indexes, ticket_tab, self.contract["protected_tabs"])
            requests = []
            for offset, name in enumerate(missing):
                tab_properties: dict[str, object] = {"title": name}
                if insert_at is not None:
                    tab_properties["index"] = insert_at + offset
                requests.append({"addSheet": {"properties": tab_properties}})
            created = (
                self.sheets.spreadsheets()
                .batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests})
                .execute()
            )
            for reply in created.get("replies", []):
                properties = reply.get("addSheet", {}).get("properties", {})
                if properties:
                    sheet_ids[str(properties["title"])] = int(properties["sheetId"])

        # (range read back, range shown on the receipt, tab, rows sent)
        written: list[tuple[str, str, str, list[list[object]]]] = []
        if tickets is not None and ticket_anchor is not None:
            # The client template owns the Tickets header, counter formula and
            # dropdown validation.  Write generated rows beneath that header
            # instead of clearing A:ZZ, which would erase the formula the
            # copied template uses to count tickets.
            start_index, start_row = ticket_anchor
            start_column = _column_letter(start_index)
            end_column = _column_letter(start_index + len(ticket_contract["columns"]) - 1)
            tab = _quote_tab(ticket_tab)
            self.sheets.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=f"{tab}!{start_column}{start_row}:{end_column}10000",
                body={},
            ).execute()
            data_rows = [list(row) for row in tickets[1:]]
            if data_rows:
                self.sheets.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=f"{tab}!{start_column}{start_row}",
                    valueInputOption="RAW",
                    body={"values": data_rows},
                ).execute()
            # With no tickets, the first data row is read back and must be empty.
            last_row = start_row + max(len(data_rows), 1) - 1
            ticket_range = f"{tab}!{start_column}{start_row}:{end_column}{last_row}"
            written.append((ticket_range, ticket_range, ticket_tab, data_rows))
        for name, values in generic.items():
            tab = _quote_tab(name)
            self.sheets.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=f"{tab}!A:ZZ",
                body={},
            ).execute()
            self.sheets.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"{tab}!A1",
                valueInputOption="RAW",
                body={"values": values},
            ).execute()
            width = max((len(row) for row in values), default=1) or 1
            # The whole tab is read back, so stale cells beyond the sent grid
            # (outside the A:ZZ clear) are caught as well.
            written.append((tab, f"{tab}!A1:{_column_letter(width)}{max(len(values), 1)}", name, list(values)))

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
        url = link or f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        return self._verify_written(spreadsheet_id, url, written)

    def _verify_written(
        self, spreadsheet_id: str, url: str, written: list[tuple[str, str, str, list[list[object]]]]
    ) -> PublishReceipt:
        """Read each written range back and compare it with what was sent (ticket 189's check)."""
        mismatches: list[str] = []
        ranges: list[PublishedRange] = []
        for read_range, shown_range, tab, sent in written:
            response = (
                self.sheets.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=read_range, valueRenderOption="UNFORMATTED_VALUE")
                .execute()
            )
            received = response.get("values", []) if isinstance(response, Mapping) else []
            mismatches.extend(_grid_differences(shown_range, sent, received if isinstance(received, list) else []))
            ranges.append(PublishedRange(tab=tab, range=shown_range, rows=len(sent)))
        if mismatches:
            shown = "; ".join(mismatches[:5]) + (f"; and {len(mismatches) - 5} more" if len(mismatches) > 5 else "")
            raise PublishReceiptError(
                f"read-back of workbook {spreadsheet_id} does not match what was sent: {shown}. "
                f"The workbook was left in place for inspection: {url}",
                spreadsheet_id=spreadsheet_id,
                url=url,
                mismatches=mismatches,
            )
        return PublishReceipt(spreadsheet_id=spreadsheet_id, url=url, ranges=tuple(ranges))

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

        ``copyTo`` drops data validation that refers to another tab (live run,
        ticket 420: all 42 Config-sourced Priority / Classification rules were
        lost), so every source tab's validation rules are read first and set
        again on the renamed copies in the same batch.
        """
        try:
            source = (
                self.sheets.spreadsheets()
                .get(spreadsheetId=source_id, includeGridData=True, fields=_SOURCE_TABS_FIELDS)
                .execute()
            )
        except Exception as exc:  # googleapiclient is optional; match its HttpError by shape.
            status = _http_status(exc)
            if status not in {403, 404}:
                raise
            raise RuntimeError(
                f"template {source_id} could not be copied: Drive refused files.copy and the Sheets API "
                f"cannot read it either (HTTP {status}). A drive.file token also needs the spreadsheets "
                "scope for the copyTo fallback; otherwise authorise the full drive scope or share the "
                "template with the account."
            ) from exc
        source_sheets = sorted(source.get("sheets", []), key=lambda sheet: int(sheet["properties"].get("index", 0)))
        tabs = [sheet["properties"] for sheet in source_sheets]
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
        validation_requests: list[dict[str, object]] = []
        for sheet, tab in zip(source_sheets, tabs):
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
            validation_requests.extend(_set_validation_requests(sheet, int(copied["sheetId"])))
        # Delete the placeholder first so its name cannot collide with a
        # template tab being renamed back (for example "Sheet1"), and restore
        # the validation only after the renames so "=Config!..." resolves.
        self.sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [{"deleteSheet": {"sheetId": sheet_id}} for sheet_id in placeholder_ids]
                + requests
                + validation_requests
            },
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
        return _locate_ticket_header(
            self.sheets,
            spreadsheet_id,
            name,
            header,
            self.contract["tickets"]["header_search"],
            subject=f"copied workbook {spreadsheet_id}",
            consequence="; nothing was written to it",
        )


def _locate_ticket_header(
    sheets: Any,
    spreadsheet_id: str,
    name: str,
    header: list[str],
    search: Mapping[str, Any],
    *,
    subject: str,
    consequence: str,
) -> tuple[int, int]:
    """Find the full ticket header in a workbook; return its 1-based column and the first data row."""
    window = f"A1:{_column_letter(int(search['max_columns']))}{int(search['max_rows'])}"
    found = (
        sheets.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=f"{_quote_tab(name)}!{window}").execute()
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
        f"the {name} tab of {subject} has no header row matching {' | '.join(header)} in {window}{closest}{consequence}"
    )


@dataclass(frozen=True)
class ValidationSourceCheck:
    """One contract value set compared with the template's dropdown source for that column."""

    column: str
    cell: str
    source: str
    template_values: tuple[str, ...]
    contract_values: tuple[str, ...]
    problem: str = ""
    unvalidated_rows: tuple[int, ...] = ()

    @property
    def only_in_template(self) -> tuple[str, ...]:
        return tuple(value for value in self.template_values if value not in self.contract_values)

    @property
    def only_in_contract(self) -> tuple[str, ...]:
        return tuple(value for value in self.contract_values if value not in self.template_values)

    @property
    def ok(self) -> bool:
        return not self.problem and not self.only_in_template and not self.only_in_contract


@dataclass(frozen=True)
class TemplateCheckReport:
    """Result of ``check_template_validation``; nothing is written to the template."""

    template_id: str
    tab: str
    header_cell: str
    rows_checked: tuple[int, int]
    checks: tuple[ValidationSourceCheck, ...]

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks)

    def lines(self) -> list[str]:
        first, last = self.rows_checked
        lines = [
            f"Template {self.template_id}: {self.tab} header at {self.header_cell}; "
            f"data validation read on rows {first}-{last}"
        ]
        if not self.checks:
            lines.append("FAIL the template contract has no value sets to compare")
        for check in self.checks:
            label = "OK  " if check.ok else "FAIL"
            lines.append(f"{label} {check.column} ({check.cell}): {check.source or 'no data validation'}")
            if check.problem:
                lines.append(f"     {check.problem}")
            if check.template_values or not check.ok:
                lines.append(f"     template: {', '.join(check.template_values) or '(none)'}")
                lines.append(f"     contract: {', '.join(check.contract_values)}")
            if check.only_in_template:
                lines.append(f"     only in template: {', '.join(check.only_in_template)}")
            if check.only_in_contract:
                lines.append(f"     only in contract: {', '.join(check.only_in_contract)}")
            if check.unvalidated_rows:
                rows = check.unvalidated_rows
                lines.append(
                    f"     note: {len(rows)} of {last - first + 1} rows checked have no validation "
                    f"(first: row {rows[0]})"
                )
        lines.append(
            "Template check passed." if self.ok else "Template check FAILED: the dropdowns disagree with the contract."
        )
        return lines


_DATA_VALIDATION_FIELDS = "sheets(properties(title),data(startRow,startColumn,rowData(values(dataValidation))))"
_RANGE_FORMULA = re.compile(
    r"^=?\s*(?:(?:'((?:[^']|'')+)'|([^'!]+))!)?\s*(\$?[A-Za-z]+\$?\d*(?::\$?[A-Za-z]+\$?\d*)?)\s*$"
)


def check_template_validation(
    sheets: Any,
    contract: Mapping[str, Any] | None = None,
    *,
    template: str | None = None,
    sample_rows: int = 100,
) -> TemplateCheckReport:
    """Compare the template's dropdown sources with the contract's value sets, read-only.

    The Tickets header is located as the publisher does, then the data
    validation of the first ``sample_rows`` data rows is read with
    ``spreadsheets.get`` (``includeGridData`` limited to ``dataValidation``).
    ``ONE_OF_LIST`` rules give their values directly; ``ONE_OF_RANGE`` rules
    (the Canonicals template points them at ``Config``) are resolved with a
    ``values.get`` of the referenced range.  Only reads are made.
    """
    contract = validate_template_contract(dict(contract)) if contract is not None else load_template_contract()
    tickets = contract["tickets"]
    tab = str(tickets["tab"])
    columns = [str(column) for column in tickets["columns"]]
    template_id = google_sheet_id(template or str(contract["template"]["url"]))
    start_column, first_row = _locate_ticket_header(
        sheets,
        template_id,
        tab,
        columns,
        tickets["header_search"],
        subject=f"template {template_id}",
        consequence="",
    )
    last_row = first_row + max(int(sample_rows), 1) - 1
    grid_range = (
        f"{_quote_tab(tab)}!{_column_letter(start_column)}{first_row}:"
        f"{_column_letter(start_column + len(columns) - 1)}{last_row}"
    )
    response = (
        sheets.spreadsheets()
        .get(spreadsheetId=template_id, ranges=[grid_range], includeGridData=True, fields=_DATA_VALIDATION_FIELDS)
        .execute()
    )
    # (0-based row, 0-based column) -> dataValidation rule
    rules: dict[tuple[int, int], Mapping[str, Any]] = {}
    for sheet in response.get("sheets", []):
        for block in sheet.get("data", []) or []:
            row_base, column_base = int(block.get("startRow", 0)), int(block.get("startColumn", 0))
            for row_offset, row in enumerate(block.get("rowData", []) or []):
                for column_offset, cell in enumerate(row.get("values", []) or []):
                    rule = cell.get("dataValidation") if isinstance(cell, Mapping) else None
                    if rule:
                        rules[(row_base + row_offset, column_base + column_offset)] = rule

    range_cache: dict[str, tuple[str, ...]] = {}
    positions = {_header_key(column): index for index, column in enumerate(columns)}
    checks: list[ValidationSourceCheck] = []
    for column, allowed in tickets["value_sets"].items():
        grid_column = start_column - 1 + positions[_header_key(column)]
        cell = f"{_column_letter(grid_column + 1)}{first_row}"
        contract_values = tuple(str(value).strip() for value in allowed)
        column_rules = {row: rules.get((row - 1, grid_column)) for row in range(first_row, last_row + 1)}
        unvalidated = tuple(row for row, rule in column_rules.items() if not rule)
        first_rule = column_rules[first_row]
        if not first_rule:
            checks.append(
                ValidationSourceCheck(
                    column=column,
                    cell=cell,
                    source="",
                    template_values=(),
                    contract_values=contract_values,
                    problem=f"{tab}!{cell} has no data validation, so the template has no {column} dropdown",
                    unvalidated_rows=unvalidated,
                )
            )
            continue
        source, values, problem = _resolve_validation(sheets, template_id, tab, first_rule, range_cache)
        if not problem:
            for row, rule in column_rules.items():
                if not rule or rule == first_rule:
                    continue
                other_source, other_values, other_problem = _resolve_validation(
                    sheets, template_id, tab, rule, range_cache
                )
                if other_problem or set(other_values) != set(values):
                    problem = (
                        f"row {row} uses a different rule ({other_source or other_problem}) "
                        f"from row {first_row} ({source})"
                    )
                    break
        checks.append(
            ValidationSourceCheck(
                column=column,
                cell=cell,
                source=source,
                template_values=values,
                contract_values=contract_values,
                problem=problem,
                unvalidated_rows=unvalidated,
            )
        )
    return TemplateCheckReport(
        template_id=template_id,
        tab=tab,
        header_cell=f"{_column_letter(start_column)}{first_row - 1}",
        rows_checked=(first_row, last_row),
        checks=tuple(checks),
    )


def _resolve_validation(
    sheets: Any,
    template_id: str,
    default_tab: str,
    rule: Mapping[str, Any],
    cache: dict[str, tuple[str, ...]],
) -> tuple[str, tuple[str, ...], str]:
    """Return (source description, allowed values, problem) for one dataValidation rule."""
    condition = rule.get("condition") or {}
    kind = str(condition.get("type", ""))
    entered = [str(value.get("userEnteredValue", "")) for value in condition.get("values", []) or []]
    if kind == "ONE_OF_LIST":
        return "list", _distinct(entered), ""
    if kind != "ONE_OF_RANGE":
        return f"{kind or 'unknown'} rule", (), f"unsupported validation type {kind or '(none)'}; expected a dropdown"
    formula = entered[0] if entered else ""
    matched = _RANGE_FORMULA.match(formula.strip())
    if not matched:
        return f"range {formula!r}", (), f"could not parse the dropdown source range {formula!r}"
    source_tab = (matched.group(1) or "").replace("''", "'") or (matched.group(2) or "").strip() or default_tab
    a1 = f"{_quote_tab(source_tab)}!{matched.group(3).replace('$', '')}"
    if a1 not in cache:
        response = (
            sheets.spreadsheets()
            .values()
            .get(spreadsheetId=template_id, range=a1, valueRenderOption="FORMATTED_VALUE")
            .execute()
        )
        cache[a1] = _distinct(str(cell) for row in response.get("values", []) or [] for cell in row)
    return f"range {a1}", cache[a1], ""


def _distinct(values: Any) -> tuple[str, ...]:
    """Trimmed, non-empty values in first-seen order."""
    seen: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.append(text)
    return tuple(seen)


def credential_path(value: str | None) -> str | None:
    """Reject an accidental directory early without reading credentials."""
    if value is None:
        return None
    path = Path(value)
    if not path.is_file():
        raise ValueError("--google-sheets-credentials must name a credential file")
    return str(path)


_SOURCE_TABS_FIELDS = (
    "sheets(properties(sheetId,title,index),data(startRow,startColumn,rowData(values(dataValidation))))"
)


def _set_validation_requests(sheet: Mapping[str, Any], sheet_id: int) -> list[dict[str, object]]:
    """``setDataValidation`` requests recreating a source tab's rules on ``sheet_id``.

    Rules are grouped into vertical runs of identical rules per column, so a
    dropdown applied to F6:F26 becomes one request.
    """
    cells: dict[tuple[int, int], Mapping[str, Any]] = {}
    for block in sheet.get("data", []) or []:
        row_base, column_base = int(block.get("startRow", 0)), int(block.get("startColumn", 0))
        for row_offset, row in enumerate(block.get("rowData", []) or []):
            for column_offset, cell in enumerate(row.get("values", []) or []):
                rule = cell.get("dataValidation") if isinstance(cell, Mapping) else None
                if rule:
                    cells[(row_base + row_offset, column_base + column_offset)] = rule
    requests: list[dict[str, object]] = []
    for row, column in sorted(cells, key=lambda key: (key[1], key[0])):
        rule = cells[(row, column)]
        if row > 0 and cells.get((row - 1, column)) == rule:
            continue  # inside a run that started above
        end = row + 1
        while cells.get((end, column)) == rule:
            end += 1
        requests.append(
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row,
                        "endRowIndex": end,
                        "startColumnIndex": column,
                        "endColumnIndex": column + 1,
                    },
                    "rule": dict(rule),
                }
            }
        )
    return requests


def google_api_error(exc: BaseException) -> str | None:
    """A one-line message for a Google API ``HttpError``, or None for any other exception."""
    status = _http_status(exc)
    if status is None:
        return None
    hint = ""
    if status in {401, 403, 404}:
        hint = (
            " The token cannot reach that file: check it holds the spreadsheets scope (and drive, or "
            "drive.file plus access to the file) and belongs to an account that can open it."
        )
    reason = str(getattr(exc, "reason", None) or exc).rstrip(". ")
    return f"Google API returned HTTP {status}: {reason}.{hint}"


def _http_status(exc: BaseException) -> int | None:
    """Return the HTTP status of a googleapiclient ``HttpError`` without importing it."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def _quote_tab(name: str) -> str:
    """Quote a tab name for an A1 range, doubling any apostrophe."""
    return "'" + name.replace("'", "''") + "'"


def _evidence_tab_index(indexes: Mapping[str, int], ticket_tab: str, protected: Sequence[str]) -> int | None:
    """Index for new evidence tabs: right after Tickets, else before the first protected tab (Config)."""
    if ticket_tab in indexes:
        return indexes[ticket_tab] + 1
    positions = [indexes[name] for name in protected if name in indexes]
    return min(positions) if positions else None


def _cell_text(value: object) -> str:
    """Canonical text of one cell as sent or as read back.

    Sheets returns strings for formatted reads and numbers for unformatted
    ones, drops empty and ``None`` cells, and stores line breaks as ``\\n``.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return value.replace("\r\n", "\n").replace("\r", "\n")
    return str(value)


def _cells_equal(sent: str, received: str) -> bool:
    if sent == received:
        return True
    try:
        left, right = float(sent), float(received)
    except ValueError:
        return False
    return math.isfinite(left) and math.isfinite(right) and math.isclose(left, right, rel_tol=1e-9, abs_tol=0.0)


def _trimmed_grid(rows: Sequence[object]) -> list[list[str]]:
    """Normalise a grid and drop trailing empty cells and rows, as Sheets does."""
    grid: list[list[str]] = []
    for row in rows:
        cells = [_cell_text(cell) for cell in row] if isinstance(row, (list, tuple)) else [_cell_text(row)]
        while cells and cells[-1] == "":
            cells.pop()
        grid.append(cells)
    while grid and not grid[-1]:
        grid.pop()
    return grid


def _grid_differences(range_name: str, sent: Sequence[object], received: Sequence[object]) -> list[str]:
    """Human-readable cell differences between what was sent and what was read back."""
    tab, _, start = range_name.partition("!")
    match = re.match(r"([A-Z]+)(\d+)", start)
    first_column = _column_number(match.group(1)) if match else 1
    first_row = int(match.group(2)) if match else 1
    expected, actual = _trimmed_grid(sent), _trimmed_grid(received)
    differences: list[str] = []
    if len(expected) != len(actual):
        differences.append(f"{range_name}: sent {len(expected)} rows, read back {len(actual)}")
    for row_offset in range(max(len(expected), len(actual))):
        sent_row = expected[row_offset] if row_offset < len(expected) else []
        read_row = actual[row_offset] if row_offset < len(actual) else []
        for column_offset in range(max(len(sent_row), len(read_row))):
            left = sent_row[column_offset] if column_offset < len(sent_row) else ""
            right = read_row[column_offset] if column_offset < len(read_row) else ""
            if not _cells_equal(left, right):
                cell = f"{tab}!{_column_letter(first_column + column_offset)}{first_row + row_offset}"
                differences.append(f"{cell}: sent {_preview(left)}, read back {_preview(right)}")
    return differences


def _preview(value: str, limit: int = 60) -> str:
    return repr(value if len(value) <= limit else value[: limit - 1] + "…")


def _column_number(label: str) -> int:
    number = 0
    for character in label:
        number = number * 26 + ord(character) - 64
    return number


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
