"""Optional Google Sheets publication against the versioned audit contract."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any


TEMPLATE_VERSION = "crawler-cli/technical-audit-sheets/1"
_SHEET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,}$")
_SHEET_URL_PATTERN = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")
_MANIFEST_TAB = "Template Contract"
_SUMMARY_HEADERS = {
    "Overview": ["Metric", "Value"],
    "Audit Log": [
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
}
_DETAIL_TABS = (
    "Index conflicts",
    "Internal link failures",
    "Tracking parameters",
    "Orphan candidates",
    "Redirect chains",
    "Near duplicates",
    "Schema diagnostics",
    "Image issues",
    "Internal authority",
)
_MANAGED_TABS = (*_SUMMARY_HEADERS, *_DETAIL_TABS)
_MAX_ROWS = 50_000
_MAX_COLUMNS = 52


def google_sheet_id(value: str) -> str:
    """Accept a spreadsheet ID or normal Google Sheets URL."""
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
            raise RuntimeError("Set GOOGLE_DOCS_OAUTH_TOKEN_FILE or pass --google-sheets-credentials.")
        credentials = Credentials.from_authorized_user_file(token_file)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
    return build("drive", "v3", credentials=credentials), build("sheets", "v4", credentials=credentials)


def template_manifest() -> dict[str, object]:
    """Return the code-owned v1 contract (also checked into templates/)."""
    return {
        "version": TEMPLATE_VERSION,
        "manifest_tab": _MANIFEST_TAB,
        "marker_cells": {
            "A1": "technical-audit-template",
            "B1": TEMPLATE_VERSION,
        },
        "managed_tabs": {
            name: {
                "range": _managed_range(name),
                "headers": headers,
                "header_identity": "exact ordered display labels",
                "formulas_allowed": False,
            }
            for name, headers in _SUMMARY_HEADERS.items()
        }
        | {
            name: {
                "range": f"A1:AZ{_MAX_ROWS}",
                "header_identity": "exact ordered evidence keys",
                "formulas_allowed": False,
            }
            for name in _DETAIL_TABS
        },
        "unmanaged_content": "Preserve all cells, formulas, notes, and formatting outside the managed ranges.",
    }


def _managed_range(name: str) -> str:
    if name == "Overview":
        return f"A1:B{_MAX_ROWS}"
    if name == "Audit Log":
        return f"A1:L{_MAX_ROWS}"
    return f"A1:AZ{_MAX_ROWS}"


def _column_index(label: str) -> int:
    result = 0
    for char in label:
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def _range_bounds(a1_range: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", a1_range)
    if not match:
        raise ValueError(f"Invalid managed range in manifest: {a1_range}")
    return int(match[2]) - 1, int(match[4]), _column_index(match[1]) - 1, _column_index(match[3])


def _validate_template(metadata: Mapping[str, object], tables: Mapping[str, list[list[object]]]) -> dict[str, int]:
    sheets = metadata.get("sheets", [])
    if not isinstance(sheets, list):
        raise ValueError("Selected Google Sheet returned invalid tab metadata")
    by_title = {
        str(sheet.get("properties", {}).get("title")): sheet
        for sheet in sheets
        if isinstance(sheet, Mapping) and isinstance(sheet.get("properties"), Mapping)
    }
    marker = by_title.get(_MANIFEST_TAB)
    if marker is None:
        raise ValueError(f"Template is missing required '{_MANIFEST_TAB}' tab")
    marker_values = marker.get("data", [])
    first_row = marker_values[0].get("rowData", [{}])[0].get("values", []) if marker_values else []
    cells = [cell.get("userEnteredValue", {}) for cell in first_row]
    marker_version = cells[1].get("stringValue") if len(cells) > 1 else None
    if not cells or cells[0].get("stringValue") != "technical-audit-template" or marker_version != TEMPLATE_VERSION:
        raise ValueError(f"Template contract version mismatch; expected {TEMPLATE_VERSION}")

    required = set(tables) | set(_SUMMARY_HEADERS)
    missing = sorted(required - by_title.keys())
    if missing:
        raise ValueError(f"Template is missing managed tabs: {', '.join(missing)}")
    unsupported = sorted(set(tables) - set(_MANAGED_TABS))
    if unsupported:
        raise ValueError(f"Template contract does not manage tabs: {', '.join(unsupported)}")

    ids: dict[str, int] = {}
    merges = metadata.get("merges", [])
    for title in required | (set(by_title) & set(_MANAGED_TABS)):
        sheet = by_title[title]
        properties = sheet["properties"]
        ids[title] = int(properties["sheetId"])
        spec_headers = _SUMMARY_HEADERS.get(title)
        values = tables.get(title)
        expected_headers = spec_headers or (values[0] if values else None)
        if expected_headers is not None:
            grid = sheet.get("data", [])
            row_values = grid[0].get("rowData", []) if grid else []
            header_cells = row_values[0].get("values", []) if row_values else []
            actual = [
                cell.get("userEnteredValue", {}).get("stringValue") for cell in header_cells[: len(expected_headers)]
            ]
            if actual != list(expected_headers):
                raise ValueError(
                    f"Template header mismatch on '{title}': expected {list(expected_headers)!r}, got {actual!r}"
                )
        for row in sheet.get("data", []):
            for row_data in row.get("rowData", []):
                for cell in row_data.get("values", []):
                    if "formulaValue" in cell.get("userEnteredValue", {}):
                        raise ValueError(
                            f"Managed range on '{title}' contains a formula; formulas must remain unmanaged"
                        )
        bounds = _range_bounds(_managed_range(title))
        for merged in merges if isinstance(merges, list) else []:
            if merged.get("sheetId") != ids[title]:
                continue
            r0, r1 = merged.get("startRowIndex", 0), merged.get("endRowIndex", 0)
            c0, c1 = merged.get("startColumnIndex", 0), merged.get("endColumnIndex", 0)
            if r0 < bounds[1] and r1 > bounds[0] and c0 < bounds[3] and c1 > bounds[2]:
                raise ValueError(f"Merged cells intersect managed range on '{title}'")
    return ids


class GoogleSheetsTemplatePublisher:
    """Preflight a known v1 template, then replace only declared values."""

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
    ) -> str:
        template_id = google_sheet_id(template)
        # Compatibility is checked against the selected source before any copy or mutation.
        source = (
            self.sheets.spreadsheets()
            .get(
                spreadsheetId=template_id,
                includeGridData=True,
                fields="sheets(properties(sheetId,title,gridProperties),merges,data(startRow,startColumn,rowData(values(userEnteredValue))))",
            )
            .execute()
        )
        _validate_template(source, tables)

        body: dict[str, object] = {"name": title}
        if folder_id:
            body["parents"] = [folder_id]
        copied = (
            self.drive.files()
            .copy(
                fileId=template_id,
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
        requests = []
        for name in _MANAGED_TABS:
            if name not in sheet_ids:
                continue
            width = 2 if name == "Overview" else 12 if name == "Audit Log" else _MAX_COLUMNS
            requests.append(
                {
                    "updateCells": {
                        "range": {
                            "sheetId": sheet_ids[name],
                            "startRowIndex": 1,
                            "endRowIndex": _MAX_ROWS,
                            "startColumnIndex": 0,
                            "endColumnIndex": width,
                        },
                        "rows": [],
                        "fields": "userEnteredValue",
                    }
                }
            )
        if requests:
            self.sheets.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body={"requests": requests}).execute()
        for name, values in tables.items():
            self.sheets.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"'{name}'!A1",
                valueInputOption="RAW",
                body={"values": values},
            ).execute()
            sheet_id = sheet_ids[name]
            column_count = len(values[0]) if values else 1
            formatting = [
                {
                    "updateSheetProperties": {
                        "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                        "fields": "gridProperties.frozenRowCount",
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": column_count,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 0.13, "green": 0.43, "blue": 0.26},
                                "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                            }
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat)",
                    }
                },
                {
                    "autoResizeDimensions": {
                        "dimensions": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": column_count,
                        },
                    }
                },
            ]
            if len(values) > 1:
                formatting.append(
                    {
                        "setBasicFilter": {
                            "filter": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "startRowIndex": 0,
                                    "endRowIndex": len(values),
                                    "startColumnIndex": 0,
                                    "endColumnIndex": column_count,
                                },
                            }
                        }
                    }
                )
            url_columns = (
                [
                    index
                    for index, label in enumerate(values[0])
                    if isinstance(label, str) and label.casefold().replace("_", " ").replace("-", " ").endswith("url")
                ]
                if values
                else []
            )
            if url_columns:
                rich_rows = []
                for row in values[1:]:
                    cells: list[dict[str, object]] = [{} for _ in range(column_count)]
                    for column in url_columns:
                        url = row[column] if column < len(row) else None
                        if isinstance(url, str) and url.startswith(("http://", "https://")):
                            cells[column] = {"textFormatRuns": [{"startIndex": 0, "format": {"link": {"uri": url}}}]}
                    rich_rows.append({"values": cells})
                if rich_rows:
                    formatting.append(
                        {
                            "updateCells": {
                                "range": {
                                    "sheetId": sheet_id,
                                    "startRowIndex": 1,
                                    "endRowIndex": len(values),
                                    "startColumnIndex": 0,
                                    "endColumnIndex": column_count,
                                },
                                "rows": rich_rows,
                                "fields": "textFormatRuns",
                            }
                        }
                    )
            self.sheets.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id, body={"requests": formatting}
            ).execute()
        return str(copied.get("webViewLink") or f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit")


def credential_path(value: str | None) -> str | None:
    """Reject an accidental directory early without reading credentials."""
    if value is None:
        return None
    path = Path(value)
    if not path.is_file():
        raise ValueError("--google-sheets-credentials must name a credential file")
    return str(path)
