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
