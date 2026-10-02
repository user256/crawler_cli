"""Import target/referrer pairs from backlink-tool exports.

Backlink providers commonly label tab-delimited UTF-16 files as ``.csv``.
This parser accepts that export shape without coupling the crawler to a
particular provider or attempting to crawl the referring domains.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class BacklinkImportError(ValueError):
    """The supplied backlink export cannot provide usable source evidence."""


@dataclass(frozen=True, slots=True)
class BacklinkImport:
    """Validated inbound-link evidence ready for ``record_sources_bulk``."""

    pairs: list[tuple[str, str | None]]
    total_rows: int
    skipped_rows: int


def _decode_export(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def _header_key(value: str | None) -> str:
    return (value or "").strip().casefold()


def _url(value: str | None) -> str | None:
    candidate = (value or "").strip()
    if not candidate:
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    return candidate


def load_backlink_import(
    path: str | Path,
    *,
    target_column: str = "Target URL",
    referring_column: str = "Referring page URL",
) -> BacklinkImport:
    """Read an inbound-link export into target/referrer source evidence.

    ``target_column`` identifies the crawled-site page. ``referring_column``
    is optional evidence: invalid or blank referring URLs do not prevent the
    target from being recorded as backlink-sourced.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise BacklinkImportError(f"backlink file not found: {file_path}")
    try:
        text = _decode_export(file_path)
    except UnicodeDecodeError as exc:
        raise BacklinkImportError(f"could not decode backlink file {file_path}") from exc
    if not text.strip():
        raise BacklinkImportError(f"backlink file is empty: {file_path}")

    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel_tab if "\t" in text.partition("\n")[0] else csv.excel
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    if not reader.fieldnames:
        raise BacklinkImportError(f"backlink file has no header row: {file_path}")
    headers = {_header_key(header): header for header in reader.fieldnames}
    target_key = headers.get(_header_key(target_column))
    if target_key is None:
        available = ", ".join(str(header) for header in reader.fieldnames)
        raise BacklinkImportError(f"missing target column {target_column!r}; found: {available}")
    referring_key = headers.get(_header_key(referring_column))

    pairs: list[tuple[str, str | None]] = []
    total_rows = 0
    skipped_rows = 0
    for row in reader:
        total_rows += 1
        target = _url(row.get(target_key))
        if target is None:
            skipped_rows += 1
            continue
        referring = _url(row.get(referring_key)) if referring_key else None
        pairs.append((target, referring))
    if not pairs:
        raise BacklinkImportError(f"no valid {target_column!r} URLs in backlink file {file_path}")
    return BacklinkImport(pairs=pairs, total_rows=total_rows, skipped_rows=skipped_rows)
