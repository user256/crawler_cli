"""Input validation for operator-supplied orphan-discovery URL inventories."""

from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import urlsplit


KNOWN_URL_SOURCES = frozenset({"analytics", "search_console"})


def load_known_url_inventory(path: str | Path) -> list[dict[str, str]]:
    """Load a deterministic URL CSV without normalizing URL identity.

    The export is scoped by the selected crawl run at the CLI boundary. Source
    URLs are retained exactly (apart from surrounding whitespace) so evidence
    is not silently rewritten; credentials and non-HTTP schemes are rejected.
    An optional ``observed_at`` column preserves the source export's date or
    period label.
    """
    inventory_path = Path(path)
    with inventory_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        fields = {field.strip().lower() for field in (reader.fieldnames or [])}
        if not {"url", "source"} <= fields:
            raise ValueError(f"{inventory_path}: CSV must include url and source columns")
        rows: set[tuple[str, str, str]] = set()
        for line_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"{inventory_path}:{line_number}: row has more fields than the CSV header")
            normalized = {str(key).strip().lower(): (value or "").strip() for key, value in row.items() if key}
            url = normalized.get("url", "")
            source = normalized.get("source", "").lower()
            parsed = urlsplit(url)
            try:
                parsed.port
                valid_authority = bool(parsed.hostname) and not parsed.username and not parsed.password
            except ValueError:
                valid_authority = False
            if (
                parsed.scheme not in {"http", "https"}
                or not valid_authority
                or any(character.isspace() or ord(character) < 32 for character in url)
            ):
                raise ValueError(f"{inventory_path}:{line_number}: url must be an absolute credential-free HTTP(S) URL")
            if source not in KNOWN_URL_SOURCES:
                allowed = ", ".join(sorted(KNOWN_URL_SOURCES))
                raise ValueError(f"{inventory_path}:{line_number}: source must be one of {allowed}")
            rows.add((url, source, normalized.get("observed_at", "")))
    return [
        {"url": url, "source": source, **({"observed_at": observed_at} if observed_at else {})}
        for url, source, observed_at in sorted(rows)
    ]
