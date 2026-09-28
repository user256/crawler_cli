"""Optional Google Sheets publication against the versioned audit contract."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
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
_MAX_TABLE_BYTES = 8_000_000
_WRITE_CHUNK_ROWS = 500
_SPREADSHEET_MIME = "application/vnd.google-apps.spreadsheet"
_RECEIPT_VERSION = 1


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


def _column_label(index: int) -> str:
    label = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        label = chr(ord("A") + remainder) + label
    return label


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _source_contract_digest(source: Mapping[str, object]) -> str:
    # The preflight field mask includes all entered values and grid metadata;
    # hashing it binds resume to the exact selected template, including its
    # unmanaged formulas and example content.
    return _digest({"manifest": template_manifest(), "source": source})


def _unmanaged_content_digest(metadata: Mapping[str, object]) -> str:
    cells_outside_managed: list[object] = []
    sheets = metadata.get("sheets", [])
    for sheet in sheets if isinstance(sheets, list) else []:
        if not isinstance(sheet, Mapping):
            continue
        properties = sheet.get("properties", {})
        if not isinstance(properties, Mapping):
            continue
        title = str(properties.get("title", ""))
        bounds = _range_bounds(_managed_range(title)) if title in _MANAGED_TABS else None
        merges = sheet.get("merges", [])
        for merged in merges if isinstance(merges, list) else []:
            if not isinstance(merged, Mapping):
                continue
            r0, r1 = int(merged.get("startRowIndex", 0)), int(merged.get("endRowIndex", 0))
            c0, c1 = int(merged.get("startColumnIndex", 0)), int(merged.get("endColumnIndex", 0))
            if bounds and r0 < bounds[1] and r1 > bounds[0] and c0 < bounds[3] and c1 > bounds[2]:
                continue
            cells_outside_managed.append((title, "merge", r0, r1, c0, c1))
        blocks = sheet.get("data", [])
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, Mapping):
                continue
            start_row = int(block.get("startRow", 0))
            start_column = int(block.get("startColumn", 0))
            rows = block.get("rowData", [])
            for row_index, row in enumerate(rows if isinstance(rows, list) else []):
                if not isinstance(row, Mapping):
                    continue
                cells = row.get("values", [])
                for column_index, cell in enumerate(cells if isinstance(cells, list) else []):
                    if not isinstance(cell, Mapping):
                        continue
                    absolute_row = start_row + row_index
                    absolute_column = start_column + column_index
                    if bounds and (bounds[0] <= absolute_row < bounds[1] and bounds[2] <= absolute_column < bounds[3]):
                        continue
                    content = {
                        field: cell[field]
                        for field in ("userEnteredValue", "userEnteredFormat", "note", "textFormatRuns")
                        if field in cell and cell[field] not in ({}, [], None)
                    }
                    if content:
                        cells_outside_managed.append((title, absolute_row, absolute_column, content))
    return _digest(cells_outside_managed)


def _managed_body_digest(metadata: Mapping[str, object], title: str) -> str:
    bounds = _range_bounds(_managed_range(title))
    sheets = metadata.get("sheets", [])
    body_cells: list[object] = []
    for sheet in sheets if isinstance(sheets, list) else []:
        if not isinstance(sheet, Mapping):
            continue
        properties = sheet.get("properties", {})
        if not isinstance(properties, Mapping) or properties.get("title") != title:
            continue
        blocks = sheet.get("data", [])
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, Mapping):
                continue
            start_row = int(block.get("startRow", 0))
            start_column = int(block.get("startColumn", 0))
            rows = block.get("rowData", [])
            for row_offset, row in enumerate(rows if isinstance(rows, list) else []):
                if not isinstance(row, Mapping):
                    continue
                cells = row.get("values", [])
                for column_offset, cell in enumerate(cells if isinstance(cells, list) else []):
                    if not isinstance(cell, Mapping):
                        continue
                    row_index, column_index = start_row + row_offset, start_column + column_offset
                    if row_index == 0 or not (
                        bounds[0] <= row_index < bounds[1] and bounds[2] <= column_index < bounds[3]
                    ):
                        continue
                    content = {
                        key: cell[key]
                        for key in ("userEnteredValue", "textFormatRuns")
                        if key in cell and cell[key] not in ({}, [], None)
                    }
                    if content:
                        body_cells.append((row_index, column_index, content))
    return _digest(body_cells)


def _grid_targets(
    metadata: Mapping[str, object], tables: Mapping[str, list[list[object]]]
) -> dict[str, tuple[int, int]]:
    sheets = metadata.get("sheets", [])
    if not isinstance(sheets, list):
        raise ValueError("Selected Google Sheet returned invalid grid metadata")
    targets: dict[str, tuple[int, int]] = {}
    total_cells = 0
    for sheet in sheets:
        if not isinstance(sheet, Mapping) or not isinstance(sheet.get("properties"), Mapping):
            continue
        properties = sheet["properties"]
        title = str(properties.get("title", ""))
        grid = properties.get("gridProperties", {})
        if not isinstance(grid, Mapping):
            raise ValueError(f"Template tab '{title}' has invalid grid properties")
        rows = int(grid.get("rowCount", 1000))
        columns = int(grid.get("columnCount", 26))
        if title in _MANAGED_TABS:
            rows = max(rows, len(tables.get(title, [])))
            columns = max(columns, 2 if title == "Overview" else 12 if title == "Audit Log" else _MAX_COLUMNS)
            if rows > _MAX_ROWS:
                raise ValueError(f"Managed grid '{title}' exceeds the {_MAX_ROWS}-row contract")
            targets[title] = (rows, columns)
        total_cells += rows * columns
    if total_cells > 10_000_000:
        raise ValueError("Template plus managed audit grids would exceed Google Sheets' 10-million-cell workbook limit")
    missing = (set(tables) | set(_SUMMARY_HEADERS)) - set(targets)
    if missing:
        raise ValueError(f"Template is missing managed tabs: {', '.join(sorted(missing))}")
    return targets


def _validated_tables(tables: Mapping[str, list[list[object]]]) -> tuple[dict[str, list[list[object]]], str]:
    normalized = {name: [list(row) for row in rows] for name, rows in tables.items()}
    total_cells = 0
    for name, rows in normalized.items():
        if name not in _MANAGED_TABS:
            raise ValueError(f"Template contract does not manage tab '{name}'")
        if len(rows) > _MAX_ROWS:
            raise ValueError(f"Tab '{name}' exceeds the {_MAX_ROWS}-row publication limit")
        if not rows or not rows[0]:
            raise ValueError(f"Tab '{name}' must contain a header row")
        width = len(rows[0])
        allowed_width = 2 if name == "Overview" else 12 if name == "Audit Log" else _MAX_COLUMNS
        if width > allowed_width or any(len(row) != width for row in rows):
            raise ValueError(f"Tab '{name}' has inconsistent or unsupported column widths")
        for row in rows:
            for cell in row:
                if cell is not None and not isinstance(cell, (str, bool, int, float)):
                    raise ValueError(f"Tab '{name}' contains unsupported cell type {type(cell).__name__}")
                if isinstance(cell, float) and not math.isfinite(cell):
                    raise ValueError(f"Tab '{name}' contains a non-finite numeric cell")
        total_cells += len(rows) * width
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    if len(payload.encode("utf-8")) > _MAX_TABLE_BYTES:
        raise ValueError(f"Google Sheets payload exceeds the {_MAX_TABLE_BYTES}-byte safety limit")
    if total_cells > _MAX_ROWS * _MAX_COLUMNS:
        raise ValueError("Google Sheets payload exceeds the managed-cell safety limit")
    return normalized, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_receipt(path: Path, receipt: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _read_grid(
    sheets: Any, spreadsheet_id: str, title: str, width: int, first_row: int, last_row: int
) -> list[list[object]]:
    if last_row < first_row:
        return []
    response = (
        sheets.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"'{title}'!A{first_row}:{_column_label(width)}{last_row}",
            valueRenderOption="UNFORMATTED_VALUE",
        )
        .execute()
    )
    values = response.get("values", [])
    return [list(row) for row in values] if isinstance(values, list) else []


def _read_links(
    sheets: Any, spreadsheet_id: str, title: str, first_row: int, last_row: int, width: int
) -> dict[tuple[int, int], str | None]:
    if last_row < first_row:
        return {}
    response = (
        sheets.spreadsheets()
        .get(
            spreadsheetId=spreadsheet_id,
            ranges=[f"'{title}'!A{first_row}:{_column_label(width)}{last_row}"],
            includeGridData=True,
            fields="sheets(data(startRow,startColumn,rowData(values(textFormatRuns,userEnteredFormat))))",
        )
        .execute()
    )
    result: dict[tuple[int, int], str | None] = {}
    for sheet in response.get("sheets", []):
        for block in sheet.get("data", []):
            row_base, column_base = int(block.get("startRow", 0)), int(block.get("startColumn", 0))
            for row_offset, row in enumerate(block.get("rowData", [])):
                for column_offset, cell in enumerate(row.get("values", [])):
                    uri = None
                    runs = cell.get("textFormatRuns", [])
                    for run in runs:
                        link = run.get("format", {}).get("link", {})
                        if link.get("uri"):
                            uri = str(link["uri"])
                            break
                    if uri is None:
                        direct_link = cell.get("userEnteredFormat", {}).get("textFormat", {}).get("link", {})
                        if direct_link.get("uri"):
                            uri = str(direct_link["uri"])
                    result[(row_base + row_offset, column_base + column_offset)] = uri
    return result


def _grid_matches(actual: list[list[object]], expected: list[list[object]]) -> bool:
    def trim(rows: list[list[object]]) -> list[list[object]]:
        result = [list(row) for row in rows]
        for row in result:
            while row and row[-1] in (None, ""):
                row.pop()
        while result and not result[-1]:
            result.pop()
        return result

    return trim(actual) == trim(expected)


def _expected_links_present(
    links: Mapping[tuple[int, int], str | None],
    rows: list[list[object]],
    columns: list[int],
    first_row: int,
) -> bool:
    for row_offset, row in enumerate(rows):
        for column in columns:
            value = row[column]
            expected = value if isinstance(value, str) and value.startswith(("http://", "https://")) else None
            if links.get((first_row - 1 + row_offset, column)) != expected:
                return False
    return True


def _header_style_is_complete(sheet: Mapping[str, object], *, filtered: bool) -> bool:
    properties = sheet.get("properties", {})
    if not isinstance(properties, Mapping):
        return False
    grid = properties.get("gridProperties", {})
    if not isinstance(grid, Mapping) or grid.get("frozenRowCount") != 1:
        return False
    if filtered and not sheet.get("basicFilter"):
        return False
    data = sheet.get("data", [])
    data_rows = data if isinstance(data, list) else []
    rows = data_rows[0].get("rowData", []) if data_rows and isinstance(data_rows[0], Mapping) else []
    cells = rows[0].get("values", []) if rows and isinstance(rows[0], Mapping) else []
    header_format = cells[0].get("userEnteredFormat", {}) if cells and isinstance(cells[0], Mapping) else {}
    if not isinstance(header_format, Mapping):
        return False
    background = header_format.get("backgroundColor", {})
    text_format = header_format.get("textFormat", {})
    return (
        background == {"red": 0.13, "green": 0.43, "blue": 0.26}
        and isinstance(text_format, Mapping)
        and text_format.get("bold") is True
    )


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
    for title in required | (set(by_title) & set(_MANAGED_TABS)):
        sheet = by_title[title]
        properties = sheet["properties"]
        ids[title] = int(properties["sheetId"])
        bounds = _range_bounds(_managed_range(title))
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
        grid_blocks = sheet.get("data", [])
        for block in grid_blocks if isinstance(grid_blocks, list) else []:
            if not isinstance(block, Mapping):
                continue
            start_row, start_column = int(block.get("startRow", 0)), int(block.get("startColumn", 0))
            for row_index, row_data in enumerate(block.get("rowData", [])):
                if not isinstance(row_data, Mapping):
                    continue
                for column_index, cell in enumerate(row_data.get("values", [])):
                    row_number, column_number = start_row + row_index, start_column + column_index
                    if not (bounds[0] <= row_number < bounds[1] and bounds[2] <= column_number < bounds[3]):
                        continue
                    if isinstance(cell, Mapping) and "formulaValue" in cell.get("userEnteredValue", {}):
                        raise ValueError(
                            f"Managed range on '{title}' contains a formula; formulas must remain unmanaged"
                        )
        merges = sheet.get("merges", [])
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
        receipt_path: str | Path,
        folder_id: str | None = None,
        resume: bool = False,
    ) -> str:
        normalized_tables, tables_digest = _validated_tables(tables)
        template_id = google_sheet_id(template)
        receipt_file = Path(receipt_path)
        if receipt_file.exists() and not resume:
            raise ValueError(f"Publication receipt already exists; pass resume=True to reconcile {receipt_file}")
        if resume and not receipt_file.exists():
            raise ValueError("Cannot resume: publication receipt does not exist")
        source_file = (
            self.drive.files().get(fileId=template_id, fields="id,mimeType,capabilities(canCopy),webViewLink").execute()
        )
        if source_file.get("mimeType") != _SPREADSHEET_MIME:
            raise ValueError("Selected template is not a native Google spreadsheet")
        if not resume and source_file.get("capabilities", {}).get("canCopy") is False:
            raise ValueError("Google Drive reports that this account cannot copy the selected template")
        if folder_id and not resume:
            destination = (
                self.drive.files().get(fileId=folder_id, fields="id,mimeType,capabilities(canAddChildren)").execute()
            )
            if destination.get("mimeType") != "application/vnd.google-apps.folder":
                raise ValueError("--google-sheets-folder must identify a Google Drive folder")
            if destination.get("capabilities", {}).get("canAddChildren") is False:
                raise ValueError("Google Drive reports that this account cannot add files to the destination folder")

        # Compatibility and API authorization are verified before the copy.
        source = (
            self.sheets.spreadsheets()
            .get(
                spreadsheetId=template_id,
                includeGridData=True,
                fields="sheets(properties(sheetId,title,gridProperties),merges,data(startRow,startColumn,rowData(values(userEnteredValue,userEnteredFormat,note,textFormatRuns))))",
            )
            .execute()
        )
        _validate_template(source, normalized_tables)
        grid_targets = _grid_targets(source, normalized_tables)
        source_contract = _source_contract_digest(source)
        unmanaged_source_digest = _unmanaged_content_digest(source)
        source_baselines = {}
        source_content_baselines = {}
        for name in _MANAGED_TABS:
            if name not in grid_targets:
                continue
            width = 2 if name == "Overview" else 12 if name == "Audit Log" else _MAX_COLUMNS
            original = _read_grid(self.sheets, template_id, name, width, 2, grid_targets[name][0])
            source_baselines[name] = _digest(original)
            source_content_baselines[name] = _managed_body_digest(source, name)

        if receipt_file.exists():
            try:
                receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(
                    "Publication receipt is unreadable; preserve it and inspect the partial copy manually"
                ) from exc
            if not isinstance(receipt, dict):
                raise ValueError("Publication receipt has an invalid shape")
            if (
                receipt.get("receipt_version") != _RECEIPT_VERSION
                or receipt.get("template_id") != template_id
                or receipt.get("template_contract_digest") != source_contract
                or receipt.get("tables_digest") != tables_digest
                or receipt.get("title") != title
                or receipt.get("folder_id") != folder_id
            ):
                raise ValueError("Publication receipt does not match this template and audit; refusing to resume")
            spreadsheet_id = str(receipt.get("spreadsheet_id", ""))
        else:
            receipt = {
                "receipt_version": _RECEIPT_VERSION,
                "state": "copy_pending",
                "template_id": template_id,
                "title": title,
                "folder_id": folder_id,
                "template_contract_digest": source_contract,
                "tables_digest": tables_digest,
                "publication_id": uuid.uuid4().hex,
                "spreadsheet_id": None,
                "url": None,
                "cleared_tabs": {},
                "completed_chunks": {},
                "linked_chunks": {},
                "formatted_tabs": [],
                "preclear_digests": source_baselines,
                "preclear_content_digests": source_content_baselines,
            }
            # Record an idempotency key before copy; a lost API response can be
            # reconciled by Drive appProperties without creating another file.
            _write_receipt(receipt_file, receipt)

        spreadsheet_id = str(receipt.get("spreadsheet_id") or "")
        if not spreadsheet_id and resume:
            publication_id = str(receipt.get("publication_id", ""))
            if not publication_id:
                raise ValueError("Publication receipt has no Drive reconciliation key")
            found = (
                self.drive.files()
                .list(
                    q=f"appProperties has {{ key='crawlerCliAuditPublicationId' and value='{publication_id}' }}",
                    fields="files(id,mimeType,webViewLink,capabilities(canEdit))",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                )
                .execute()
                .get("files", [])
            )
            if len(found) != 1:
                raise ValueError(
                    "Copy outcome is not uniquely known yet; receipt retained and no new copy was created. "
                    "Retry reconciliation later or inspect the Drive folder."
                )
            copied_file = found[0]
            spreadsheet_id = str(copied_file.get("id", ""))
            receipt["spreadsheet_id"] = spreadsheet_id
            receipt["url"] = copied_file.get("webViewLink")
            receipt["state"] = "copy_created"
            _write_receipt(receipt_file, receipt)
        elif not spreadsheet_id:
            body: dict[str, object] = {
                "name": title,
                "appProperties": {"crawlerCliAuditPublicationId": str(receipt["publication_id"])},
            }
            if folder_id:
                body["parents"] = [folder_id]
            copied_file = (
                self.drive.files()
                .copy(
                    fileId=template_id,
                    body=body,
                    fields="id,webViewLink",
                    supportsAllDrives=True,
                )
                .execute()
            )
            spreadsheet_id = str(copied_file["id"])
            receipt["spreadsheet_id"] = spreadsheet_id
            receipt["url"] = (
                copied_file.get("webViewLink") or f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
            )
            receipt["state"] = "copy_created"
            _write_receipt(receipt_file, receipt)

        copied_file = (
            self.drive.files()
            .get(
                fileId=spreadsheet_id,
                fields="id,mimeType,capabilities(canEdit),webViewLink",
            )
            .execute()
        )
        if copied_file.get("mimeType") != _SPREADSHEET_MIME:
            raise ValueError("Receipt destination is no longer a native Google spreadsheet")
        if copied_file.get("capabilities", {}).get("canEdit") is False:
            raise ValueError("Copied spreadsheet is no longer editable by this account")
        sheet_url = str(receipt.get("url") or copied_file.get("webViewLink") or "")

        metadata = (
            self.sheets.spreadsheets()
            .get(
                spreadsheetId=spreadsheet_id,
                fields="sheets(properties(sheetId,title,gridProperties),basicFilter,data(startRow,startColumn,rowData(values(userEnteredValue,userEnteredFormat,note,textFormatRuns))))",
                includeGridData=True,
            )
            .execute()
        )
        copied_titles = {
            str(sheet.get("properties", {}).get("title"))
            for sheet in metadata.get("sheets", [])
            if isinstance(sheet, Mapping)
        }
        expected_titles = {str(sheet.get("properties", {}).get("title")) for sheet in source.get("sheets", [])}
        if copied_titles != expected_titles:
            raise ValueError("Copied spreadsheet tab set differs from the validated template")
        sheet_ids = {
            str(sheet["properties"]["title"]): int(sheet["properties"]["sheetId"])
            for sheet in metadata.get("sheets", [])
        }
        metadata_by_title = {
            str(sheet.get("properties", {}).get("title")): sheet
            for sheet in metadata.get("sheets", [])
            if isinstance(sheet, Mapping)
        }
        resize_requests = []
        for sheet in metadata.get("sheets", []):
            properties = sheet.get("properties", {})
            name = str(properties.get("title", ""))
            if name not in grid_targets:
                continue
            grid = properties.get("gridProperties", {})
            target_rows, target_columns = grid_targets[name]
            fields = []
            target_grid: dict[str, int] = {}
            if int(grid.get("rowCount", 1000)) < target_rows:
                target_grid["rowCount"] = target_rows
                fields.append("gridProperties.rowCount")
            if int(grid.get("columnCount", 26)) < target_columns:
                target_grid["columnCount"] = target_columns
                fields.append("gridProperties.columnCount")
            if fields:
                resize_requests.append(
                    {
                        "updateSheetProperties": {
                            "properties": {"sheetId": sheet_ids[name], "gridProperties": target_grid},
                            "fields": ",".join(fields),
                        }
                    }
                )
        if resize_requests:
            self.sheets.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id, body={"requests": resize_requests}
            ).execute()
        clear_receipts = receipt.setdefault("cleared_tabs", {})
        chunk_receipts = receipt.setdefault("completed_chunks", {})
        link_receipts = receipt.setdefault("linked_chunks", {})
        formatted_receipts = receipt.setdefault("formatted_tabs", [])
        formatting_started = receipt.setdefault("formatting_started", [])

        # Persist a baseline for every managed tab before the first destructive
        # operation. This distinguishes an untouched copy from a user-edited
        # partial copy when a later invocation resumes.
        preclear_digests = receipt.setdefault("preclear_digests", {})
        preclear_content_digests = receipt.setdefault("preclear_content_digests", {})
        for name in _MANAGED_TABS:
            if name not in sheet_ids:
                continue
            width = 2 if name == "Overview" else 12 if name == "Audit Log" else _MAX_COLUMNS
            if name not in preclear_digests:
                original = _read_grid(self.sheets, spreadsheet_id, name, width, 2, grid_targets[name][0])
                if resume and any(cell not in (None, "") for row in original for cell in row):
                    raise ValueError(
                        f"Cannot prove managed tab '{name}' is unchanged since copy; inspect the receipt destination manually"
                    )
                preclear_digests[name] = _digest(original)
            preclear_content_digests.setdefault(name, source_content_baselines[name])
        _write_receipt(receipt_file, receipt)

        try:
            for name in _MANAGED_TABS:
                if name not in sheet_ids:
                    continue
                width = 2 if name == "Overview" else 12 if name == "Audit Log" else _MAX_COLUMNS
                grid_rows = grid_targets[name][0]
                if not clear_receipts.get(name):
                    current = _read_grid(self.sheets, spreadsheet_id, name, width, 2, grid_rows)
                    current_digest = _digest(current)
                    previous_digest = preclear_digests.get(name)
                    if current_digest not in {previous_digest, _digest([])}:
                        raise ValueError(
                            f"Managed tab '{name}' changed since the interrupted publication; refusing to overwrite edits"
                        )
                    current_content_digest = _managed_body_digest(metadata, name)
                    if current_content_digest not in {
                        preclear_content_digests.get(name),
                        _digest([]),
                    }:
                        raise ValueError(
                            f"Managed rich text on '{name}' changed since the interrupted publication; refusing to overwrite edits"
                        )
                    if current_digest != _digest([]) or current_content_digest != _digest([]):
                        if grid_rows > 1:
                            self.sheets.spreadsheets().batchUpdate(
                                spreadsheetId=spreadsheet_id,
                                body={
                                    "requests": [
                                        {
                                            "updateCells": {
                                                "range": {
                                                    "sheetId": sheet_ids[name],
                                                    "startRowIndex": 1,
                                                    "endRowIndex": grid_rows,
                                                    "startColumnIndex": 0,
                                                    "endColumnIndex": width,
                                                },
                                                "rows": [],
                                                "fields": "userEnteredValue,textFormatRuns",
                                            }
                                        }
                                    ]
                                },
                            ).execute()
                    clear_receipts[name] = True
                    receipt["state"] = "writing"
                    _write_receipt(receipt_file, receipt)

                values = normalized_tables.get(name)
                if values is None:
                    continue
                chunks = values[1:]
                completed = chunk_receipts.setdefault(name, [])
                for chunk_index, offset in enumerate(range(0, len(chunks), _WRITE_CHUNK_ROWS)):
                    chunk = chunks[offset : offset + _WRITE_CHUNK_ROWS]
                    first_row = offset + 2
                    last_row = first_row + len(chunk) - 1
                    chunk_range = f"'{name}'!A{first_row}:{_column_label(len(values[0]))}{last_row}"
                    current = _read_grid(self.sheets, spreadsheet_id, name, len(values[0]), first_row, last_row)
                    if chunk_index in completed:
                        if not _grid_matches(current, chunk):
                            raise ValueError(
                                f"Previously written chunk {chunk_index} on '{name}' changed; refusing to overwrite edits"
                            )
                        continue
                    if _grid_matches(current, chunk):
                        completed.append(chunk_index)
                        _write_receipt(receipt_file, receipt)
                        continue
                    if any(cell not in (None, "") for row in current for cell in row):
                        raise ValueError(
                            f"Uncheckpointed data on '{name}' differs from the audit; refusing to overwrite edits"
                        )
                    self.sheets.spreadsheets().values().update(
                        spreadsheetId=spreadsheet_id,
                        range=chunk_range,
                        valueInputOption="RAW",
                        body={"values": chunk},
                    ).execute()
                    completed.append(chunk_index)
                    _write_receipt(receipt_file, receipt)

                if name not in formatted_receipts and name in formatting_started and resume:
                    if _header_style_is_complete(metadata_by_title[name], filtered=len(values) > 1):
                        formatted_receipts.append(name)
                        _write_receipt(receipt_file, receipt)
                    else:
                        raise ValueError(
                            f"Formatting on '{name}' is ambiguous after interruption; refusing to overwrite possible user edits"
                        )
                if name not in formatted_receipts:
                    formatting_started.append(name)
                    _write_receipt(receipt_file, receipt)
                    column_count = len(values[0])
                    formatting = [
                        {
                            "updateSheetProperties": {
                                "properties": {"sheetId": sheet_ids[name], "gridProperties": {"frozenRowCount": 1}},
                                "fields": "gridProperties.frozenRowCount",
                            }
                        },
                        {
                            "repeatCell": {
                                "range": {
                                    "sheetId": sheet_ids[name],
                                    "startRowIndex": 0,
                                    "endRowIndex": 1,
                                    "startColumnIndex": 0,
                                    "endColumnIndex": column_count,
                                },
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
                        },
                        {
                            "autoResizeDimensions": {
                                "dimensions": {
                                    "sheetId": sheet_ids[name],
                                    "dimension": "COLUMNS",
                                    "startIndex": 0,
                                    "endIndex": column_count,
                                }
                            }
                        },
                    ]
                    if len(values) > 1:
                        formatting.append(
                            {
                                "setBasicFilter": {
                                    "filter": {
                                        "range": {
                                            "sheetId": sheet_ids[name],
                                            "startRowIndex": 0,
                                            "endRowIndex": len(values),
                                            "startColumnIndex": 0,
                                            "endColumnIndex": column_count,
                                        },
                                    }
                                }
                            }
                        )
                    self.sheets.spreadsheets().batchUpdate(
                        spreadsheetId=spreadsheet_id, body={"requests": formatting}
                    ).execute()
                    formatted_receipts.append(name)
                    _write_receipt(receipt_file, receipt)

                url_columns = [
                    index
                    for index, label in enumerate(values[0])
                    if isinstance(label, str) and label.casefold().replace("_", " ").replace("-", " ").endswith("url")
                ]
                if url_columns and chunks:
                    linked = link_receipts.setdefault(name, [])
                    for chunk_index, offset in enumerate(range(0, len(chunks), _WRITE_CHUNK_ROWS)):
                        chunk = chunks[offset : offset + _WRITE_CHUNK_ROWS]
                        first_row = offset + 2
                        last_row = first_row + len(chunk) - 1
                        if chunk_index in linked:
                            links = _read_links(self.sheets, spreadsheet_id, name, first_row, last_row, len(values[0]))
                            if not _expected_links_present(links, chunk, url_columns, first_row):
                                raise ValueError(
                                    f"Previously linked URL cells on '{name}' changed; refusing to overwrite edits"
                                )
                            continue
                        existing_links = (
                            _read_links(self.sheets, spreadsheet_id, name, first_row, last_row, len(values[0]))
                            if resume
                            else {}
                        )
                        link_requests = []
                        for column in url_columns:
                            cells = []
                            for row_offset, row in enumerate(chunk):
                                value = row[column]
                                expected_uri = (
                                    value
                                    if isinstance(value, str) and value.startswith(("http://", "https://"))
                                    else None
                                )
                                existing_uri = existing_links.get((first_row - 1 + row_offset, column))
                                if resume and existing_uri not in (None, expected_uri):
                                    raise ValueError(
                                        f"URL link on '{name}' row {first_row + row_offset} changed; refusing to overwrite edits"
                                    )
                                if expected_uri:
                                    cell = {
                                        "textFormatRuns": [{"startIndex": 0, "format": {"link": {"uri": expected_uri}}}]
                                    }
                                else:
                                    cell = {}
                                cells.append({"values": [cell]})
                            link_requests.append(
                                {
                                    "updateCells": {
                                        "range": {
                                            "sheetId": sheet_ids[name],
                                            "startRowIndex": first_row - 1,
                                            "endRowIndex": last_row,
                                            "startColumnIndex": column,
                                            "endColumnIndex": column + 1,
                                        },
                                        "rows": cells,
                                        "fields": "textFormatRuns",
                                    }
                                }
                            )
                        self.sheets.spreadsheets().batchUpdate(
                            spreadsheetId=spreadsheet_id, body={"requests": link_requests}
                        ).execute()
                        linked.append(chunk_index)
                        _write_receipt(receipt_file, receipt)

            # Read back data, tab identity, and essential formatting before claiming success.
            final = (
                self.sheets.spreadsheets()
                .get(
                    spreadsheetId=spreadsheet_id,
                    includeGridData=True,
                    fields="sheets(properties(title,gridProperties),merges,basicFilter,data(startRow,startColumn,rowData(values(userEnteredValue,userEnteredFormat,note,textFormatRuns))))",
                )
                .execute()
            )
            final_by_title = {
                str(sheet.get("properties", {}).get("title")): sheet
                for sheet in final.get("sheets", [])
                if isinstance(sheet, Mapping)
            }
            if set(final_by_title) != expected_titles:
                raise ValueError("Read-back tab set does not match the validated template")
            if _unmanaged_content_digest(final) != unmanaged_source_digest:
                raise ValueError("Read-back unmanaged cells/formulas differ from the source template")
            for name, values in normalized_tables.items():
                actual = _read_grid(self.sheets, spreadsheet_id, name, len(values[0]), 1, len(values))
                if not _grid_matches(actual, values):
                    raise ValueError(f"Read-back values differ from the requested audit table on '{name}'")
                sheet = final_by_title[name]
                if not _header_style_is_complete(sheet, filtered=len(values) > 1):
                    raise ValueError(f"Read-back formatting validation failed on '{name}'")
                url_columns = [
                    index
                    for index, label in enumerate(values[0])
                    if isinstance(label, str) and label.casefold().replace("_", " ").replace("-", " ").endswith("url")
                ]
                data = sheet.get("data", [])
                readback_rows = data[0].get("rowData", []) if data and isinstance(data[0], Mapping) else []
                for row_index, row in enumerate(values[1:], start=1):
                    if row_index >= len(readback_rows) or not isinstance(readback_rows[row_index], Mapping):
                        continue
                    readback_cells = readback_rows[row_index].get("values", [])
                    for column in url_columns:
                        url = row[column]
                        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                            continue
                        cell = readback_cells[column] if column < len(readback_cells) else {}
                        runs = cell.get("textFormatRuns", []) if isinstance(cell, Mapping) else []
                        linked = False
                        for run in runs if isinstance(runs, list) else []:
                            if not isinstance(run, Mapping):
                                continue
                            run_format = run.get("format", {})
                            if not isinstance(run_format, Mapping):
                                continue
                            link = run_format.get("link", {})
                            if isinstance(link, Mapping) and link.get("uri") == url:
                                linked = True
                                break
                        if not linked:
                            raise ValueError(f"Read-back URL-link validation failed on '{name}' row {row_index + 1}")
            for name in set(_MANAGED_TABS) - set(normalized_tables):
                if name not in sheet_ids:
                    continue
                width = 2 if name == "Overview" else 12 if name == "Audit Log" else _MAX_COLUMNS
                stale_rows = _read_grid(self.sheets, spreadsheet_id, name, width, 2, grid_targets[name][0])
                if any(cell not in (None, "") for row in stale_rows for cell in row):
                    raise ValueError(f"Read-back found stale or edited data on empty managed tab '{name}'")
            receipt["state"] = "complete"
            receipt["completed_at"] = datetime.now(timezone.utc).isoformat()
            _write_receipt(receipt_file, receipt)
        except Exception as exc:
            receipt["state"] = "partial"
            receipt["last_error_type"] = type(exc).__name__
            _write_receipt(receipt_file, receipt)
            raise
        return sheet_url


def credential_path(value: str | None) -> str | None:
    """Reject an accidental directory early without reading credentials."""
    if value is None:
        return None
    path = Path(value)
    if not path.is_file():
        raise ValueError("--google-sheets-credentials must name a credential file")
    return str(path)
