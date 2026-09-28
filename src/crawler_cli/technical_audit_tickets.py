"""Client-ticket language for deterministic technical-audit evidence.

This module deliberately does not publish a spreadsheet.  It turns a v3
technical-audit result into the exact eight values used by the standard ticket
register, while keeping unproven candidates in the evidence workbook.  A
publisher can use these pure functions after it has copied the client template.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .redaction import redact_url_without_digest
from .technical_audit_contract import TECHNICAL_AUDIT_CHECK_CONTRACT


TICKET_LANGUAGE_VERSION = "crawler-cli/technical-audit-ticket-language/2"
"""Version of the checked-in client-language mapping."""

TICKET_TEMPLATE_COLUMNS = (
    "Label",
    "Description",
    "Suggested Solution",
    "Acceptance Criteria",
    "Ticket Classification",
    "Priority",
    "How to Replicate",
    "Notes / Documentation",
)
"""Exact ordered columns in the copied client ticket-register template."""

DEFAULT_TICKET_LANGUAGE_PATH = (
    Path(__file__).resolve().parents[2] / "templates" / "technical-audit-ticket-language.json"
)

_CHECK_IDS = tuple(item["id"] for item in TECHNICAL_AUDIT_CHECK_CONTRACT)
_CHECK_ID_SET = frozenset(_CHECK_IDS)
_VALID_STATES = frozenset({"pass", "finding", "partial", "unavailable", "not_applicable"})
_URL_FIELDS = (
    "source_url",
    "url",
    "target_url",
    "variant_url",
    "control_url",
    "image_url",
    "near_duplicate_url",
    "sitemap_url",
    "final_url",
)
_OBSERVATION_FIELDS = (
    "candidate_type",
    "issue",
    "outcome",
    "reason",
    "http_status",
    "final_status_code",
    "status",
    "variant_kind",
    "simhash_distance",
)
_EXAMPLES_MARKER = re.compile(r"\n\nExamples:\n(?:\{sample_urls\}|.*?)(?=\n\n|\Z)", re.DOTALL)
_RUN_REFERENCE = re.compile(r"\b(?:in|from|for) run [^\s,.;)]+", re.IGNORECASE)
_EXTRA_SPACE = re.compile(r"[ \t]+")
_DOCUMENTATION_URL = re.compile(r"https?://[^\s)`]+")


def load_ticket_language(path: Path | None = None) -> dict[str, object]:
    """Load and validate the code-owned mapping for the client ticket register."""

    source = path or DEFAULT_TICKET_LANGUAGE_PATH
    try:
        loaded = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Cannot read ticket language mapping: {source}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Ticket language mapping is not valid JSON: {source}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("Ticket language mapping must be a JSON object")
    validate_ticket_language(loaded)
    return loaded


def validate_ticket_language(language: Mapping[str, object]) -> None:
    """Require the language mapping and deterministic check contract to stay aligned."""

    if language.get("version") != TICKET_LANGUAGE_VERSION:
        raise ValueError(f"Ticket language mapping must declare version {TICKET_LANGUAGE_VERSION}")

    target = _mapping(language.get("target_template"), "target_template")
    if target.get("tab") != "Tickets":
        raise ValueError("Ticket language mapping must target the Tickets tab")
    if target.get("header_row") != 6 or target.get("first_data_row") != 7 or target.get("start_column") != "B":
        raise ValueError("Ticket language mapping does not match the ticket-register write range")
    if tuple(target.get("columns", ())) != TICKET_TEMPLATE_COLUMNS:
        raise ValueError("Ticket language mapping columns do not match the ticket-register template")
    if set(target.get("classification_values", ())) != {"Error", "Issue", "Warning", "Improvement"}:
        raise ValueError("Ticket language mapping has invalid ticket classifications")
    if set(target.get("priority_values", ())) != {"High", "Medium", "Low"}:
        raise ValueError("Ticket language mapping has invalid ticket priorities")

    eligibility = _mapping(language.get("ticket_eligibility"), "ticket_eligibility")
    states = eligibility.get("states")
    if not isinstance(states, list) or not set(states).issubset(_VALID_STATES):
        raise ValueError("Ticket language mapping has invalid eligibility states")
    blocked = eligibility.get("blocked_qualifications")
    if not isinstance(blocked, list) or not all(isinstance(value, str) and value for value in blocked):
        raise ValueError("Ticket language mapping has invalid blocked qualifications")

    checks = _mapping(language.get("checks"), "checks")
    if tuple(checks) != _CHECK_IDS:
        missing = [identifier for identifier in _CHECK_IDS if identifier not in checks]
        unexpected = [identifier for identifier in checks if identifier not in _CHECK_ID_SET]
        raise ValueError(
            f"Ticket language checks do not match the audit contract; missing={missing}, unexpected={unexpected}"
        )
    for identifier, entry in checks.items():
        mapping = _mapping(entry, f"checks.{identifier}")
        if mapping.get("ticket") is False:
            continue
        if not mapping.get("unit"):
            raise ValueError(f"Ticket language mapping for {identifier} needs a unit")
        if mapping.get("unavailable_ticket"):
            unavailable = _mapping(mapping["unavailable_ticket"], f"checks.{identifier}.unavailable_ticket")
            _validate_ticket_fields(unavailable, f"checks.{identifier}.unavailable_ticket")
        if mapping.get("label"):
            _validate_ticket_fields(mapping, f"checks.{identifier}")


def ticket_eligibility(
    check: Mapping[str, object], language_entry: Mapping[str, object], language: Mapping[str, object]
) -> tuple[bool, str]:
    """Return whether one check has enough proof for a client remediation ticket.

    The reason is designed for the Overview tab.  It explains why a row remains
    evidence-only instead of silently discarding a deterministic check.
    """

    status = str(check.get("status") or "")
    if status not in _VALID_STATES:
        return False, f"invalid status: {status or 'missing'}"
    if language_entry.get("ticket") is False:
        prerequisite = str(language_entry.get("client_ticket_prerequisite") or "not configured for client tickets")
        return False, prerequisite
    if status == "unavailable":
        # No client-supplied input can close a gap that our own collectors do
        # not yet measure, so a "provide input" ticket would be misleading.
        if "contract_evidence_not_collected" in _qualification_codes(check.get("qualification")):
            return False, "collector not built"
        return (
            bool(language_entry.get("unavailable_ticket")),
            "missing input" if language_entry.get("unavailable_ticket") else "not tested",
        )
    eligibility = _mapping(language.get("ticket_eligibility"), "ticket_eligibility")
    allowed_states = {str(value) for value in eligibility.get("states", [])}
    if status not in allowed_states:
        return False, f"{status} rows stay in evidence until they meet the client-ticket proof rule"
    if _count(check.get("affected_count")) <= 0:
        return False, "no affected evidence"
    evidence = check.get("evidence")
    if not isinstance(evidence, list) or not any(isinstance(row, Mapping) for row in evidence):
        return False, "no evidence rows"
    blocked = {str(value) for value in eligibility.get("blocked_qualifications", [])}
    qualification_codes = _qualification_codes(check.get("qualification"))
    matching = sorted(blocked.intersection(qualification_codes))
    if matching:
        return False, f"requires qualification: {', '.join(matching)}"
    return True, "ready"


def build_technical_audit_ticket_rows(
    audit: Mapping[str, object], language: Mapping[str, object] | None = None
) -> list[dict[str, str]]:
    """Build exact template rows only for evidenced, client-actionable checks.

    Each returned mapping uses exactly :data:`TICKET_TEMPLATE_COLUMNS`, so the
    publisher can write it directly below the template headers.  This function
    never turns a partial result or an analyst-only candidate into a ticket.
    """

    mapping = dict(language) if language is not None else load_ticket_language()
    validate_ticket_language(mapping)
    checks = _audit_checks(audit)
    entries = _mapping(mapping["checks"], "checks")
    rows: list[dict[str, str]] = []
    for check in checks:
        identifier = str(check["id"])
        entry = _mapping(entries[identifier], f"checks.{identifier}")
        eligible, _reason = ticket_eligibility(check, entry, mapping)
        if not eligible:
            continue
        block = _mapping(
            entry.get("unavailable_ticket") if check.get("status") == "unavailable" else entry,
            f"checks.{identifier}",
        )
        values = _render_values(audit, check, entry, mapping)
        rows.append(
            {
                "Label": _render(block["label"], values),
                "Description": _description(_render(block["description"], values), values["inline_evidence"]),
                "Suggested Solution": _client_safe(_render(block["suggested_solution"], values)),
                "Acceptance Criteria": _client_safe(_render(block["acceptance_criteria"], values)),
                "Ticket Classification": _render(block["classification"], values),
                "Priority": _render(block["priority"], values),
                "How to Replicate": _replication_text(check, values),
                "Notes / Documentation": _notes(check, values, mapping, entry),
            }
        )
    return rows


def technical_audit_ticket_overview(
    audit: Mapping[str, object], language: Mapping[str, object] | None = None
) -> list[dict[str, object]]:
    """Return every deterministic check with its ticket decision for an Overview tab."""

    mapping = dict(language) if language is not None else load_ticket_language()
    validate_ticket_language(mapping)
    entries = _mapping(mapping["checks"], "checks")
    overview: list[dict[str, object]] = []
    for check in _audit_checks(audit):
        identifier = str(check["id"])
        eligible, reason = ticket_eligibility(check, _mapping(entries[identifier], f"checks.{identifier}"), mapping)
        overview.append(
            {
                "id": identifier,
                "status": str(check.get("status") or ""),
                "affected_count": _count(check.get("affected_count")),
                "tested_count": check.get("tested_count"),
                "denominator": check.get("denominator"),
                "detail_sheet": str(check.get("detail_sheet") or ""),
                "ticket_eligible": eligible,
                "ticket_decision": reason,
                "qualification": str(check.get("qualification") or ""),
            }
        )
    return overview


def _audit_checks(audit: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw_checks = audit.get("checks")
    if not isinstance(raw_checks, list):
        raise ValueError("Technical audit must contain a checks list")
    checks = [check for check in raw_checks if isinstance(check, Mapping)]
    identifiers = tuple(str(check.get("id") or "") for check in checks)
    if identifiers != _CHECK_IDS:
        raise ValueError("Technical audit checks do not match the ordered v3 check contract")
    return checks


def _render_values(
    audit: Mapping[str, object],
    check: Mapping[str, object],
    entry: Mapping[str, object],
    language: Mapping[str, object],
) -> dict[str, str]:
    evidence = [row for row in check.get("evidence", []) if isinstance(row, Mapping)]
    unit = str(entry.get("unit") or "records")
    denominator = _count(check.get("denominator"))
    affected = _count(check.get("affected_count"))
    values = {
        "site": _site(audit),
        "run_id": str(audit.get("crawl_run_id") or ""),
        "crawl_date": _audit_date(audit),
        "affected_count": _number(affected),
        "denominator": _number(denominator),
        "tested_count": _number(check.get("tested_count")),
        "affected_pct": _percentage(affected, denominator),
        "unit": unit,
        "sample_urls": "\n".join(_evidence_urls(evidence, limit=5)) or "No affected URL was recorded.",
        "inline_evidence": _inline_evidence(evidence),
        "evidence_tab": str(check.get("detail_sheet") or "Evidence"),
        "missing_evidence": str(check.get("required_evidence") or "the required evidence"),
        "qualification": _qualification_text(check.get("qualification"), language),
    }
    return values


def _description(rendered: str, inline_evidence: str) -> str:
    without_examples = _EXAMPLES_MARKER.sub("", rendered).strip()
    if inline_evidence:
        without_examples = f"{without_examples}\n\nEvidence\n{inline_evidence}"
    return _client_safe(without_examples)


def _replication_text(check: Mapping[str, object], values: Mapping[str, str]) -> str:
    evidence_tab = values["evidence_tab"]
    if check.get("status") == "unavailable":
        return f"Use the {evidence_tab} tab to confirm the agreed input has been supplied and recorded."
    return (
        "Review the URL and observed condition in the Description. After the change, verify the same condition "
        f"and compare it with the recorded evidence in the {evidence_tab} tab."
    )


def _notes(
    check: Mapping[str, object],
    values: Mapping[str, str],
    language: Mapping[str, object],
    entry: Mapping[str, object],
) -> str:
    if check.get("status") == "unavailable":
        return f"Required input: {values['missing_evidence']}."
    notes = f"Evidence tab: {values['evidence_tab']}; {values['affected_count']} recorded {values['unit']}; captured {values['crawl_date']}."
    qualification = _qualification_text(check.get("qualification"), language)
    references = _documentation_references(entry)
    reference_text = f" Reference: {', '.join(references)}." if references else ""
    return f"{notes} {qualification}{reference_text}".strip()


def _inline_evidence(evidence: Sequence[Mapping[str, object]]) -> str:
    lines: list[str] = []
    for row in evidence:
        urls = _evidence_urls([row], limit=2)
        if not urls:
            continue
        observation = _observation(row)
        connector = " → " if len(urls) > 1 else ""
        line = f"• {connector.join(urls)}"
        if observation:
            line = f"{line} — {observation}"
        lines.append(line)
        if len(lines) == 3:
            break
    return "\n".join(lines)


def _evidence_urls(evidence: Sequence[Mapping[str, object]], *, limit: int) -> list[str]:
    urls: list[str] = []
    for row in evidence:
        for field in _URL_FIELDS:
            value = row.get(field)
            if not isinstance(value, str) or not value.startswith(("http://", "https://")):
                continue
            redacted = redact_url_without_digest(value)
            if redacted not in urls:
                urls.append(redacted)
            if len(urls) == limit:
                return urls
    return urls


def _observation(row: Mapping[str, object]) -> str:
    observations: list[str] = []
    for field in _OBSERVATION_FIELDS:
        value = row.get(field)
        if value in (None, "", [], {}):
            continue
        if field in {"http_status", "final_status_code"}:
            observations.append(f"HTTP {value}")
        elif field == "simhash_distance":
            observations.append(f"similarity distance {value}")
        else:
            observations.append(str(value).replace("_", " "))
    return "; ".join(observations[:3])


def _qualification_codes(value: object) -> set[str]:
    if not isinstance(value, str):
        return set()
    return {piece.strip().split(":", 1)[0] for piece in value.split(";") if piece.strip()}


def _qualification_text(value: object, language: Mapping[str, object]) -> str:
    if not isinstance(value, str) or not value:
        return ""
    labels = _mapping(language.get("qualification_text", {}), "qualification_text")
    text = [str(labels.get(code) or code.replace("_", " ")) for code in _qualification_codes(value)]
    return " ".join(text)


def _documentation_references(entry: Mapping[str, object]) -> list[str]:
    notes = entry.get("notes")
    if not isinstance(notes, str):
        return []
    return list(dict.fromkeys(_DOCUMENTATION_URL.findall(notes)))


def _site(audit: Mapping[str, object]) -> str:
    context = audit.get("run_context")
    if isinstance(context, Mapping):
        origins = context.get("seed_origins")
        if isinstance(origins, list) and origins and isinstance(origins[0], str):
            hostname = urlsplit(origins[0]).hostname
            if hostname:
                return hostname
        hosts = context.get("declared_allowed_hosts")
        if isinstance(hosts, list) and hosts and isinstance(hosts[0], str):
            return hosts[0]
    return "the site"


def _audit_date(audit: Mapping[str, object]) -> str:
    context = audit.get("run_context")
    if isinstance(context, Mapping):
        for key in ("finished_at", "started_at"):
            value = context.get(key)
            if isinstance(value, str) and len(value) >= 10:
                return value[:10]
    return "the audit date"


def _render(template: object, values: Mapping[str, str]) -> str:
    if not isinstance(template, str):
        raise ValueError("Ticket language fields must be strings")
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered


def _client_safe(text: str) -> str:
    """Remove audit-run mechanics from text intended for a client ticket."""

    text = _RUN_REFERENCE.sub("", text)
    text = text.replace("across the crawled pages", "on the reviewed pages")
    text = text.replace("from the crawl", "from the available evidence")
    text = text.replace("next crawl run", "next review")
    text = text.replace("the crawl's graph", "the available link graph")
    return _EXTRA_SPACE.sub(" ", text).replace(" \n", "\n").strip()


def _number(value: object) -> str:
    return f"{_count(value):,}" if value is not None else "not recorded"


def _count(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _percentage(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "not recorded"
    return f"{round(numerator / denominator * 100):.0f}"


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Ticket language {name} must be an object")
    return value


def _validate_ticket_fields(entry: Mapping[str, object], name: str) -> None:
    for key in ("label", "description", "suggested_solution", "acceptance_criteria", "classification", "priority"):
        if not isinstance(entry.get(key), str) or not str(entry[key]).strip():
            raise ValueError(f"Ticket language {name} needs {key}")
