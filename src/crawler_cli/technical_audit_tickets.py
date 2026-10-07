"""Map deterministic audit results into the client Tickets tab contract."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path


TICKET_COLUMNS = (
    "Label",
    "Description",
    "Suggested Solution",
    "Acceptance Criteria",
    "Ticket Classification",
    "Priority",
    "How to Replicate",
    "Notes / Documentation",
)


class TicketLanguageError(ValueError):
    """The ticket-language file cannot faithfully map the audit contract."""


def default_ticket_language_path() -> Path:
    return Path(__file__).parents[2] / "templates" / "technical-audit-ticket-language.json"


def load_ticket_language(path: str | Path | None = None) -> dict[str, object]:
    target = Path(path) if path else default_ticket_language_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TicketLanguageError(f"could not load ticket language {target}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("checks"), dict):
        raise TicketLanguageError("ticket language must be an object with a checks object")
    return payload


def build_ticket_register(audit: Mapping[str, object], language: Mapping[str, object]) -> list[dict[str, str]]:
    """Create exact template-column ticket rows with inline sample evidence.

    This is intentionally a pure projection: the audit JSON remains the
    evidence bundle, while Sheets publishing is an optional final transport.
    """
    contract = audit.get("check_contract")
    checks = audit.get("checks")
    language_checks = language.get("checks")
    if not isinstance(contract, list) or not isinstance(checks, list) or not isinstance(language_checks, Mapping):
        raise TicketLanguageError("audit and language need check contracts")
    contract_ids = [str(item["id"]) for item in contract if isinstance(item, Mapping)]
    if set(contract_ids) != set(str(key) for key in language_checks):
        missing = sorted(set(contract_ids).difference(language_checks))
        extra = sorted(set(language_checks).difference(contract_ids))
        raise TicketLanguageError(f"ticket language IDs differ from audit contract; missing={missing}, extra={extra}")
    entries = {str(item["id"]): item for item in checks if isinstance(item, Mapping)}
    if set(entries) != set(contract_ids):
        raise TicketLanguageError("audit check rows differ from its contract")
    shared = language.get("shared_text", {})
    if not isinstance(shared, Mapping):
        shared = {}
    qualification_text = language.get("qualification_text", {})
    if not isinstance(qualification_text, Mapping):
        qualification_text = {}
    rows: list[dict[str, str]] = []
    for identifier in contract_ids:
        check = entries[identifier]
        entry = language_checks[identifier]
        if not isinstance(entry, Mapping) or entry.get("ticket") is False:
            continue
        source = _ticket_source(check, entry)
        if source is None:
            continue
        status = str(check.get("status", "unavailable"))
        evidence = check.get("evidence", [])
        values = _placeholders(audit, check, evidence)
        description = _render(source.get("description"), values)
        notes = _render(source.get("notes", ""), values)
        if status == "partial":
            suffix = _render(shared.get("partial_suffix", ""), values)
            description = _append(description, suffix)
            notes = _append(notes, suffix)
        qualification = str(check.get("qualification") or "").split(":", 1)[0]
        qualification_note = _render(qualification_text.get(qualification, ""), values)
        notes = _append(notes, qualification_note)
        notes = _append(notes, _inline_evidence(identifier, check, evidence))
        rows.append(
            {
                "Label": _render(source.get("label", identifier), values),
                "Description": description,
                "Suggested Solution": _render(source.get("suggested_solution", ""), values),
                "Acceptance Criteria": _render(source.get("acceptance_criteria", ""), values),
                "Ticket Classification": _render(
                    source.get("classification", entry.get("classification", "Issue")), values
                ),
                "Priority": _render(source.get("priority", entry.get("priority", "Medium")), values),
                "How to Replicate": _render(source.get("how_to_replicate", entry.get("how_to_replicate", "")), values),
                "Notes / Documentation": notes,
            }
        )
    return rows


def ticketed_check_ids(audit: Mapping[str, object], language: Mapping[str, object]) -> set[str]:
    """IDs of the audit checks that ``build_ticket_register`` turns into a ticket."""
    checks = audit.get("checks")
    language_checks = language.get("checks")
    if not isinstance(checks, list) or not isinstance(language_checks, Mapping):
        return set()
    ticketed: set[str] = set()
    for check in checks:
        if not isinstance(check, Mapping):
            continue
        entry = language_checks.get(str(check.get("id")))
        if isinstance(entry, Mapping) and _ticket_source(check, entry) is not None:
            ticketed.add(str(check["id"]))
    return ticketed


def _ticket_source(check: Mapping[str, object], entry: Mapping[str, object]) -> Mapping[str, object] | None:
    """The ticket-language entry a check is ticketed from, or None when it gets no ticket."""
    if entry.get("ticket") is False:
        return None
    status = str(check.get("status", "unavailable"))
    if status == "finding" or (status == "partial" and _integer(check.get("affected_count")) > 0):
        return entry
    unavailable = entry.get("unavailable_ticket")
    if status == "unavailable" and isinstance(unavailable, Mapping):
        return unavailable
    return None


def ticket_sheet_table(rows: list[Mapping[str, str]]) -> list[list[object]]:
    return [list(TICKET_COLUMNS), *[[row.get(column, "") for column in TICKET_COLUMNS] for row in rows]]


def _placeholders(audit: Mapping[str, object], check: Mapping[str, object], evidence: object) -> dict[str, str]:
    context = audit.get("run_context", {})
    context = context if isinstance(context, Mapping) else {}
    hosts = context.get("seed_hosts", [])
    site = str(hosts[0]) if isinstance(hosts, list) and hosts else "the audited site"
    denominator = _integer_or_blank(check.get("denominator"))
    population = _integer(check.get("denominator"))
    affected = _integer(check.get("affected_count"))
    return {
        "site": site,
        "run_id": str(audit.get("crawl_run_id", "")),
        "crawl_date": str(context.get("created_at", ""))[:10],
        "affected_count": f"{affected:,}",
        "denominator": denominator,
        "tested_count": _integer_or_blank(check.get("tested_count")),
        # denominator is display text ("10,852"); compute from the raw count.
        "affected_pct": _share(affected, population),
        "unit": _unit_for(check),
        "sample_urls": "\n".join(_sample_urls(evidence)),
        "evidence_tab": str(check.get("detail_sheet", "Evidence")),
        "missing_evidence": str(check.get("required_evidence", "")),
        "qualification": str(check.get("qualification") or ""),
    }


def _inline_evidence(identifier: str, check: Mapping[str, object], evidence: object) -> str:
    samples = _sample_urls(evidence)
    summary = (
        f"Contract check: {identifier}. Evidence tab: {check.get('detail_sheet', '')}. "
        f"Run: {check.get('coverage_state', '')}; affected: {_integer(check.get('affected_count'))}; "
        f"tested: {_integer_or_blank(check.get('tested_count')) or 'not collected'}."
    )
    return _append(
        summary,
        "Sample URLs:\n" + "\n".join(samples)
        if samples
        else "No URL-level sample is available; see the stated evidence requirement.",
    )


def _sample_urls(evidence: object) -> list[str]:
    if not isinstance(evidence, list):
        return []
    urls: list[str] = []
    for row in evidence:
        if not isinstance(row, Mapping):
            continue
        for key in ("url", "source_url", "requested_url", "target_url", "candidate_url"):
            value = row.get(key)
            if isinstance(value, str) and value.startswith(("https://", "http://")) and value not in urls:
                urls.append(value)
                break
        if len(urls) == 5:
            break
    return urls


def _share(affected: int, population: int) -> str:
    """Whole-percent share; a non-zero count never rounds to 0% or a partial one to 100%."""

    if not population:
        return ""
    pct = round(100 * affected / population)
    if affected and pct == 0:
        return "<1%"
    if affected < population and pct == 100:
        return ">99%"
    return f"{pct}%"


def _unit_for(check: Mapping[str, object]) -> str:
    identifier = str(check.get("id", ""))
    if identifier in {"internal-link-targets", "external-link-integrity"}:
        return "links"
    if identifier in {"schema-parser-diagnostics"}:
        return "blocks"
    if identifier in {"supplied-search-evidence"}:
        return "records"
    return "pages"


def _render(value: object, values: Mapping[str, str]) -> str:
    text = str(value or "")
    for key, replacement in values.items():
        text = text.replace("{" + key + "}", replacement)
    return text


def _append(left: str, right: str) -> str:
    return "\n\n".join(part for part in (left.strip(), right.strip()) if part)


def _integer(value: object) -> int:
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0


def _integer_or_blank(value: object) -> str:
    return f"{_integer(value):,}" if value is not None else ""
