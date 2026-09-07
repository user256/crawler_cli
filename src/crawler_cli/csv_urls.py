from __future__ import annotations

import csv
from itertools import chain
from pathlib import Path


def load_urls_from_csv(path: str | Path, *, column: str = "url") -> list[str]:
    """Load crawl URLs from a CSV file or plain newline-delimited list."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    urls: list[str] = []
    text = file_path.read_text(encoding="utf-8")
    if not text.strip():
        return urls

    reader = csv.reader(text.splitlines())
    first_row = next(reader, [])
    headers = [header.strip() for header in first_row]
    if column in headers:
        column_index = headers.index(column)
        for row in reader:
            value = (row[column_index] if len(row) > column_index else "").strip()
            if value:
                urls.append(value)
        return urls

    for row in chain((first_row,), reader):
        value = ",".join(row).strip()
        if value and not value.startswith("#"):
            urls.append(value)
    return urls


def load_labelled_urls_from_csv(
    path: str | Path, *, column: str = "url", label_column: str = "template"
) -> list[tuple[str, str | None]]:
    """Load crawl URLs with an optional operator-supplied template label.

    The label column is optional: a plain URL list, or a CSV without that
    header, yields ``None`` for every label so callers fall back to computed
    path strata.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {file_path}")

    text = file_path.read_text(encoding="utf-8")
    if not text.strip():
        return []

    reader = csv.reader(text.splitlines())
    first_row = next(reader, [])
    headers = [header.strip() for header in first_row]
    if column not in headers or label_column not in headers:
        return [(url, None) for url in load_urls_from_csv(file_path, column=column)]

    url_index = headers.index(column)
    label_index = headers.index(label_column)
    labelled: list[tuple[str, str | None]] = []
    for row in reader:
        url = (row[url_index] if len(row) > url_index else "").strip()
        if not url:
            continue
        label = (row[label_index] if len(row) > label_index else "").strip()
        labelled.append((url, label or None))
    return labelled
