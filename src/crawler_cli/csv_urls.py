from __future__ import annotations

import csv
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

    try:
        sample = text[:1024]
        dialect = csv.Sniffer().has_header(sample)
    except csv.Error:
        dialect = False

    if dialect:
        reader = csv.DictReader(text.splitlines())
        if reader.fieldnames and column in reader.fieldnames:
            for row in reader:
                value = (row.get(column) or "").strip()
                if value:
                    urls.append(value)
            return urls

    for line in text.splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            urls.append(value)
    return urls
