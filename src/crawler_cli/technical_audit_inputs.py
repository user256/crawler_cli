"""Validated, file-backed evidence inputs for the deterministic audit.

The audit does not call Google services or click arbitrary controls itself.
These adapters make supplied exports and browser interaction captures stable
inputs: the same file always produces the same audit result.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit


class AuditInputError(ValueError):
    """A supplied audit input is unreadable or lacks its evidence contract."""


def load_search_evidence(path: str | Path) -> list[dict[str, object]]:
    """Load dated Search Console/Inspection records and classify actionable rows.

    JSON accepts either a list or ``{"records": [...]}``; CSV headers use
    the same field names. Required fields are ``url``, ``source`` and
    ``export_date``. A row is actionable when Google reports a non-indexed
    state, chooses a different canonical, or a declared priority URL has zero
    impressions in the supplied period.
    """
    rows = _load_records(path)
    normalised: list[dict[str, object]] = []
    for position, record in enumerate(rows, start=1):
        url = _required(record, "url", position)
        source = _required(record, "source", position)
        export_date = _required(record, "export_date", position)
        index_status = _text(record.get("index_status") or record.get("verdict") or record.get("coverage_state"))
        google_canonical = _text(record.get("google_canonical"))
        user_canonical = _text(record.get("user_canonical"))
        impressions = _number_or_none(record.get("impressions"))
        priority = _bool(record.get("priority_url") or record.get("is_priority_url"))
        reasons: list[str] = []
        if index_status and index_status.casefold() not in {"indexed", "pass", "valid", "included"}:
            reasons.append(f"Google reports {index_status}.")
        if google_canonical and user_canonical and _normalise_url(google_canonical) != _normalise_url(user_canonical):
            reasons.append("Google-selected canonical differs from the declared canonical.")
        if priority and impressions == 0:
            reasons.append("The declared priority URL had zero impressions in the supplied period.")
        normalised.append(
            {
                "url": url,
                "source": source,
                "export_date": export_date,
                "index_status": index_status,
                "google_canonical": google_canonical,
                "user_canonical": user_canonical,
                "impressions": impressions,
                "clicks": _number_or_none(record.get("clicks")),
                "priority_url": priority,
                "is_issue": bool(reasons),
                "issue_reason": " ".join(reasons)
                or "No indexing, canonical-selection or priority-URL impression issue in this record.",
            }
        )
    return normalised


def load_inventory_interaction_evidence(path: str | Path) -> list[dict[str, object]]:
    """Load an initial-render versus interaction inventory capture.

    Each record records one page and one completed action. Required fields are
    ``source_url``, ``action``, ``initial_document_url_count`` and
    ``post_interaction_document_url_count``. The browser collector must not
    follow the interaction before recording the initial DOM.
    """
    rows = _load_records(path)
    normalised: list[dict[str, object]] = []
    for position, record in enumerate(rows, start=1):
        source_url = _required(record, "source_url", position)
        action = _required(record, "action", position)
        initial = _required_int(record, "initial_document_url_count", position)
        post = _required_int(record, "post_interaction_document_url_count", position)
        completed = _bool(record.get("completed", True))
        normalised.append(
            {
                "source_url": source_url,
                "action": action,
                "initial_document_url_count": initial,
                "post_interaction_document_url_count": post,
                "completed": completed,
                "requires_interaction": completed and post > initial,
                "evidence_url": _text(record.get("evidence_url")),
                "captured_at": _text(record.get("captured_at")),
            }
        )
    return normalised


def _load_records(path: str | Path) -> list[dict[str, object]]:
    file_path = Path(path)
    if not file_path.is_file():
        raise AuditInputError(f"evidence file does not exist: {file_path}")
    try:
        if file_path.suffix.casefold() == ".json":
            payload = json.loads(file_path.read_text(encoding="utf-8"))
            if isinstance(payload, Mapping):
                payload = payload.get("records")
            if not isinstance(payload, list):
                raise AuditInputError("JSON evidence must be a list or an object with a records list")
            rows = payload
        else:
            with file_path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError, csv.Error, json.JSONDecodeError) as exc:
        raise AuditInputError(f"could not read evidence file {file_path}: {exc}") from exc
    if not all(isinstance(row, Mapping) for row in rows):
        raise AuditInputError("every evidence record must be an object")
    return [dict(row) for row in rows]


def _required(record: Mapping[str, object], key: str, position: int) -> str:
    value = _text(record.get(key))
    if not value:
        raise AuditInputError(f"record {position} is missing required {key}")
    return value


def _required_int(record: Mapping[str, object], key: str, position: int) -> int:
    value = _number_or_none(record.get(key))
    if value is None or int(value) != value or value < 0:
        raise AuditInputError(f"record {position} has invalid {key}; expected a non-negative integer")
    return int(value)


def _number_or_none(value: object) -> int | float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value)) if "." in str(value) else int(str(value))
    except (TypeError, ValueError):
        return None


def _bool(value: object) -> bool:
    return str(value).strip().casefold() not in {"", "0", "false", "no", "n"}


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _normalise_url(value: str) -> str:
    parsed = urlsplit(value)
    return parsed._replace(fragment="").geturl().rstrip("/")
