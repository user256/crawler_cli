"""Question registry for the Questions tab of the technical audit template.

Each question is phrased so that Yes means a problem, carries a deterministic
``issue_if`` rule, and names the contract checks and inputs that answer it.
The JSON file is the source of truth; the review document is rendered from it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .technical_audit import TECHNICAL_AUDIT_CHECK_CONTRACT, TECHNICAL_AUDIT_LEGACY_CHECK_ID_ALIASES
from .technical_audit_tickets import _placeholders, _render, _sample_urls, ticket_sheet_table


QUESTION_STATUSES = ("Issue", "Healthy", "Needs validation", "Pending")
CLASSIFICATIONS = ("Error", "Issue", "Warning", "Improvement")
PRIORITIES = ("High", "Medium", "Low")
_REQUIRED_FIELDS = (
    "id",
    "theme",
    "area",
    "original_question",
    "question",
    "issue_if",
    "unit",
    "group",
    "requires",
    "checks",
    "why",
)
_TICKETLESS_GROUPS = frozenset({"external", "run-gate"})


class QuestionRegistryError(ValueError):
    """The question registry is inconsistent with the audit contract."""


def default_question_registry_path() -> Path:
    return Path(__file__).parents[2] / "templates" / "technical-audit-questions.json"


def default_site_profile_example_path() -> Path:
    return Path(__file__).parents[2] / "templates" / "site-profile.example.json"


def load_question_registry(path: str | Path | None = None) -> dict[str, object]:
    target = Path(path) if path else default_question_registry_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QuestionRegistryError(f"could not load question registry {target}: {exc}") from exc
    validate_question_registry(payload)
    return payload


def validate_question_registry(
    registry: Mapping[str, object], site_profile: Mapping[str, object] | None = None
) -> None:
    """Raise on any entry that the question runner could not evaluate faithfully."""

    questions = registry.get("questions")
    groups = registry.get("groups")
    vocabulary = registry.get("requires_vocabulary")
    if not isinstance(questions, list) or not isinstance(groups, Mapping) or not isinstance(vocabulary, Mapping):
        raise QuestionRegistryError("registry needs questions, groups and requires_vocabulary")
    contract_ids = {str(check["id"]) for check in TECHNICAL_AUDIT_CHECK_CONTRACT}
    errors: list[str] = []
    seen: set[str] = set()
    for entry in questions:
        if not isinstance(entry, Mapping):
            errors.append(f"non-object entry: {entry!r}")
            continue
        qid = str(entry.get("id"))
        missing = [field for field in _REQUIRED_FIELDS if not entry.get(field) and field != "checks"]
        if missing:
            errors.append(f"{qid}: missing {', '.join(missing)}")
        if qid in seen:
            errors.append(f"{qid}: duplicate id")
        seen.add(qid)
        group = entry.get("group")
        if group not in groups:
            errors.append(f"{qid}: unknown group {group!r}")
        for check in entry.get("checks") or []:
            if check not in contract_ids:
                errors.append(f"{qid}: unknown contract check {check!r}")
        if not entry.get("checks") and not entry.get("new_detector") and group not in {"external", "heuristic"}:
            errors.append(f"{qid}: needs a contract check or a new_detector")
        for requirement in entry.get("requires") or []:
            if requirement not in vocabulary:
                errors.append(f"{qid}: unknown requirement {requirement!r}")
        if entry.get("profile_keys") and "site-profile" not in (entry.get("requires") or []):
            errors.append(f"{qid}: profile_keys without the site-profile requirement")
        if group not in _TICKETLESS_GROUPS:
            if entry.get("classification") not in CLASSIFICATIONS:
                errors.append(f"{qid}: classification must be one of {CLASSIFICATIONS}")
            if entry.get("priority") not in PRIORITIES:
                errors.append(f"{qid}: priority must be one of {PRIORITIES}")
        if site_profile is not None:
            for key in entry.get("profile_keys") or []:
                if _profile_value(site_profile, str(key)) is None:
                    errors.append(f"{qid}: site profile lacks {key!r}")
    if errors:
        raise QuestionRegistryError("; ".join(errors))


def _profile_value(profile: Mapping[str, object], dotted_key: str) -> object | None:
    value: object = profile
    for part in dotted_key.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None
        value = value[part]
    return value


def questions_markdown(registry: Mapping[str, object]) -> str:
    """Render the reviewer-facing document; regenerate it whenever the JSON changes."""

    questions = registry["questions"]
    groups = registry["groups"]
    assert isinstance(questions, list) and isinstance(groups, Mapping)
    lines = [
        "# Technical audit questions",
        "",
        "Generated from [`templates/technical-audit-questions.json`](../templates/technical-audit-questions.json); "
        "edit the JSON, not this file. Every question is phrased so that **Yes means a problem**; "
        "`Issue if` is the rule that makes the answer Yes.",
        "",
        "## Statuses",
        "",
    ]
    statuses = registry.get("statuses", {})
    assert isinstance(statuses, Mapping)
    lines += [f"- **{name}**: {text}" for name, text in statuses.items()]
    lines += ["", "## Groups", "", "| Group | Answerable | Ticket policy | Questions |", "|---|---|---|---|"]
    for name, policy in groups.items():
        assert isinstance(policy, Mapping)
        ids = ", ".join(str(q["id"]) for q in questions if q["group"] == name)
        lines.append(f"| {name} | {policy['answerable']} | {policy['ticket']} | {ids} |")
    theme = None
    for entry in questions:
        if entry["theme"] != theme:
            theme = entry["theme"]
            lines += ["", f"## {theme}"]
        lines += ["", f"### {entry['id']} · {entry['area']}", "", f"**{entry['question']}**", ""]
        lines.append(f"- Issue if: {entry['issue_if']}")
        lines.append(f"- Why it matters: {entry['why']}")
        ticket = f"{entry['classification']} / {entry['priority']}" if entry.get("classification") else "no ticket"
        lines.append(f"- Group: {entry['group']} · Ticket: {ticket} · Unit: {entry['unit']}")
        lines.append(f"- Needs: {', '.join(entry['requires'])}")
        if entry["id"] in ANSWERERS:
            lines.append(f"- Runner: answered today ({ANSWERERS[entry['id']].basis})")
        owners = [f"`{check}`" for check in entry["checks"]]
        if entry.get("new_detector"):
            owners.append(f"new detector `{entry['new_detector']}`")
        lines.append(f"- Evidence owners: {', '.join(owners) or 'outside crawler_cli'}")
        if entry.get("profile_keys"):
            lines.append(f"- Site profile keys: {', '.join(f'`{key}`' for key in entry['profile_keys'])}")
        if entry.get("sheet_answerable_was"):
            lines.append(f"- Sheet said answerable: {entry['sheet_answerable_was']} (changed)")
        if entry.get("note"):
            lines.append(f"- Note: {entry['note']}")
        lines.append(f"- Original: {entry['original_question']}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Runner: answer each registry question from one technical-audit JSON bundle.
#
# A question is answered only by an explicit answerer that knows exactly which
# evidence rows belong to it.  Contract checks often hold a narrower or wider
# population than the question asks about, so mapping a question to a check
# status would overstate or understate the answer.  Everything without an
# answerer is reported as Pending with the reason, never as Healthy.

MAX_DATA_TAB_ROWS = 50_000
QUESTION_SHEET_COLUMNS = (
    "Theme",
    "ID",
    "Area",
    "Question",
    "Answer",
    "Status",
    "Affected",
    "Tested",
    "Issue if",
    "Why it matters",
    "Basis / notes",
    "Evidence tab",
    "Ticket",
)
# Registry entries, audits and answers are JSON documents.
Json = Mapping[str, Any]
_TAB_UNSAFE = re.compile(r"[\[\]\*\?/\\:']")


@dataclass(frozen=True)
class Evidence:
    """What an answerer observed for one question."""

    rows: list[dict[str, object]] = field(default_factory=list)
    denominator: int | None = None
    available: bool = True
    # False when the answerer tests only part of what the question asks.
    scope_complete: bool = True
    coverage_complete: bool = True
    qualification: str | None = None
    note: str = ""
    language_check: str | None = None


@dataclass(frozen=True)
class Answerer:
    basis: str
    answer: Callable[[Json, Json, Json | None], Evidence]


def _check(audit: Json, identifier: str) -> Json | None:
    """Find a check by contract ID, accepting schema-v1 IDs in older saved audits."""
    for check in audit.get("checks", []) or []:
        if not isinstance(check, Mapping):
            continue
        check_id = str(check.get("id"))
        if identifier in {check_id, TECHNICAL_AUDIT_LEGACY_CHECK_ID_ALIASES.get(check_id)}:
            return check
    return None


def _from_check(
    identifier: str,
    *,
    keep: Callable[[Json], bool] | None = None,
    scope_note: str = "",
    distinct_url: bool = False,
) -> Callable[[Json, Json, Json | None], Evidence]:
    def answer(audit: Json, _question: Json, _profile: object) -> Evidence:
        check = _check(audit, identifier)
        if check is None or check.get("status") == "unavailable":
            required = check.get("required_evidence") if check else None
            return Evidence(
                available=False, note=f"{identifier} not collected: {required or 'check missing from audit'}"
            )
        rows = [dict(row) for row in check.get("evidence", []) or [] if isinstance(row, Mapping)]
        if keep is not None:
            rows = [row for row in rows if keep(row)]
        if distinct_url:
            rows = _distinct_by_url(rows)
        return Evidence(
            rows=rows,
            denominator=_int_or_none(check.get("denominator")),
            scope_complete=not scope_note,
            coverage_complete=check.get("coverage_state") == "complete",
            qualification=str(check["qualification"]) if check.get("qualification") else None,
            note=scope_note,
            language_check=identifier,
        )

    return answer


def _with_template(
    template: str,
    inner: Callable[[Json, Json, Json | None], Evidence],
) -> Callable[[Json, Json, Json | None], Evidence]:
    """Restrict an answer's rows to URLs whose path matches a site-profile template."""

    def answer(audit: Json, question: Json, profile: Json | None) -> Evidence:
        pattern = _profile_value(profile or {}, f"templates.{template}.pattern")
        if not isinstance(pattern, str):
            return Evidence(available=False, note=f"site profile lacks templates.{template}.pattern")
        evidence = inner(audit, question, profile)
        if not evidence.available:
            return evidence
        compiled = re.compile(pattern)
        rows = [row for row in evidence.rows if compiled.search(_path_and_query(_row_url(row)))]
        return Evidence(**{**evidence.__dict__, "rows": rows})

    return answer


def _heading_link(row: Json) -> bool:
    return bool(re.search(r"/h[23](?:\[\d+\])?(?:/|$)", str(row.get("xpath", "")), re.IGNORECASE))


def _excessive_outlinks(audit: Json, question: Json, profile: object) -> Evidence:
    limit = int(dict(question.get("threshold") or {}).get("max_unique_internal_outlinks", 300))
    evidence = _from_check("internal-authority")(audit, question, None)
    if not evidence.available:
        return evidence
    rows = [row for row in evidence.rows if (_int_or_none(row.get("unique_outlinks")) or 0) > limit]
    rows.sort(key=lambda row: -(_int_or_none(row.get("unique_outlinks")) or 0))
    return Evidence(**{**evidence.__dict__, "rows": rows, "qualification": None, "language_check": None})


def _run_gate(audit: Json, question: Json, profile: object) -> Evidence:
    context = audit.get("run_context")
    if not isinstance(context, Mapping) or not context:
        return Evidence(available=False, note="audit has no run_context")
    limit = float(dict(question.get("threshold") or {}).get("max_failure_share", 0.02))
    html = _int_or_none(context.get("html_count")) or 0
    failures: list[dict[str, object]] = []

    def fail(condition: str, observed: object, expected: object) -> None:
        failures.append({"condition": condition, "observed": observed, "expected": expected})

    if context.get("completion_state") != "complete":
        fail("run completion state", context.get("completion_state"), "complete")
    if context.get("snapshot_consistency") == "changed_during_collection":
        fail("run changed while the audit read it", "changed_during_collection", "stable")
    pending = _int_or_none(context.get("frontier_pending")) or 0
    if pending:
        fail("frontier URLs still pending", pending, 0)
    for key, label in (
        ("unparsed_html_count", "HTML responses not parsed"),
        ("challenged_count", "bot-challenge responses"),
    ):
        count = _int_or_none(context.get(key))
        if count and html and count / html > limit:
            fail(label, f"{count:,} of {html:,}", f"<= {limit:.0%}")
    return Evidence(rows=failures, denominator=1)


ANSWERERS: dict[str, Answerer] = {
    "Q13": Answerer("orphan-candidates rows", _from_check("orphan-candidates")),
    "Q14": Answerer("internal-authority unique_outlinks above threshold", _excessive_outlinks),
    "Q16": Answerer("schema-parser-diagnostics rows", _from_check("schema-parser-diagnostics")),
    "Q21": Answerer(
        "near-duplicate-content rows on the inventory template",
        _with_template(
            "inventory",
            _from_check(
                "near-duplicate-content",
                scope_note="Near-duplicates only; the thin-content word-count test is not implemented yet.",
                distinct_url=True,
            ),
        ),
    ),
    "Q22": Answerer(
        "internal-link-targets error targets",
        _from_check(
            "internal-link-targets",
            scope_note="Only 4xx/5xx targets are tested; redirect, noindex and non-canonical targets are not yet.",
        ),
    ),
    "Q23": Answerer("supplied pre/post-interaction inventory capture", _from_check("rendered-robots-links")),
    "Q26": Answerer("run_context completeness gate", _run_gate),
    "Q30": Answerer("supplied Search Console / URL Inspection records", _from_check("supplied-search-evidence")),
    "Q32": Answerer("locale-html-lang shared-signature rows", _from_check("locale-html-lang")),
    "Q39": Answerer(
        "internal-link-targets error targets linked from an H2/H3",
        _from_check(
            "internal-link-targets",
            keep=_heading_link,
            scope_note="Only 4xx/5xx targets are tested; redirecting and non-canonical heading links are not yet.",
        ),
    ),
    "Q94": Answerer(
        "indexability-segmentation header/meta robots conflicts",
        _from_check(
            "indexability-segmentation",
            scope_note="Robots header/meta conflicts only; Link canonical header vs HTML canonical is not yet tested.",
        ),
    ),
}


def answer_questions(
    audit: Json,
    registry: Json,
    site_profile: Json | None = None,
) -> list[dict[str, object]]:
    """Return one answer per registry question, in registry order."""

    questions = [entry for entry in registry["questions"] if isinstance(entry, Mapping)]
    by_id = {str(entry["id"]): entry for entry in questions}
    gate = _answer_one(by_id["Q26"], audit, site_profile, gate_ok=True) if "Q26" in by_id else None
    gate_ok = gate is not None and gate["status"] == "Healthy"
    answers = []
    for entry in questions:
        if gate is not None and entry["id"] == "Q26":
            answers.append(gate)
        else:
            answers.append(_answer_one(entry, audit, site_profile, gate_ok=gate_ok))
    return answers


def _answer_one(
    entry: Json,
    audit: Json,
    profile: Json | None,
    *,
    gate_ok: bool,
) -> dict[str, object]:
    qid = str(entry["id"])
    group = str(entry["group"])
    notes: list[str] = []
    answer: dict[str, Any] = {
        "id": qid,
        "group": group,
        "status": "Pending",
        "answer": "",
        "affected_count": None,
        "denominator": None,
        "notes": notes,
        "rows": [],
        "ticket": False,
        "language_check": None,
        "qualification": None,
    }
    if group == "external":
        notes.append("Outside crawler_cli: " + ", ".join(str(item) for item in entry["requires"]))
        return answer
    answerer = ANSWERERS.get(qid)
    if answerer is None:
        owners = [*entry.get("checks", []), *([entry["new_detector"]] if entry.get("new_detector") else [])]
        notes.append("Not answered by the runner yet; needs " + ", ".join(str(item) for item in owners))
        return answer
    evidence = answerer.answer(audit, entry, profile)
    notes.append(f"Basis: {answerer.basis}.")
    if evidence.note:
        notes.append(evidence.note)
    if not evidence.available:
        return answer
    rows = evidence.rows
    affected = len(rows)
    answer.update(
        affected_count=affected,
        denominator=evidence.denominator,
        rows=rows,
        language_check=evidence.language_check,
        qualification=evidence.qualification,
    )
    matched = _meets_threshold(affected, evidence.denominator, entry.get("threshold"))
    if matched is None:
        notes.append("Share threshold needs a population size the evidence does not give.")
    complete = evidence.coverage_complete and (gate_ok or group == "run-gate")
    if not complete:
        notes.append("Coverage is incomplete for this run, so counts are a lower bound.")
    if matched:
        answer["answer"] = "Yes"
        review = group == "heuristic" or evidence.qualification in {"review_required", "coverage_required"}
        if review:
            answer["status"] = "Needs validation"
            notes.append("Candidates for review, not confirmed defects; confirm before raising a ticket.")
        elif not complete:
            answer["status"] = "Needs validation"
            answer["ticket"] = group != "run-gate"
        else:
            answer["status"] = "Issue"
            answer["ticket"] = group != "run-gate"
        if evidence.qualification == "recheck_required":
            notes.append("Statuses come from the saved crawl; recheck the sample live before assigning.")
    elif matched is None:
        answer["status"] = "Needs validation"
    else:
        if affected:
            notes.append(f"{affected:,} rows found, below the reporting threshold.")
        if complete and evidence.scope_complete:
            answer.update(status="Healthy", answer="No")
        else:
            answer["status"] = "Needs validation"
            answer["answer"] = "No (partial)"
    return answer


def _meets_threshold(affected: int, denominator: int | None, threshold: object) -> bool | None:
    rule = dict(threshold) if isinstance(threshold, Mapping) else {}
    if affected < int(rule.get("min_affected", 1)):
        return False
    share = rule.get("min_share")
    if share is None:
        return True
    if not denominator:
        return None
    return affected / denominator >= float(share)


def question_ticket_rows(
    audit: Json,
    registry: Json,
    answers: Sequence[Json],
    language: Json | None = None,
) -> list[dict[str, str]]:
    """Draft one Tickets row per answer flagged for a ticket.

    Suggested solution and acceptance criteria come from the ticket-language
    entry of the check that supplied the rows, when there is one.  The draft is
    meant for the tech-audit-tickets skill to finish in house style.
    """

    entries = {str(entry["id"]): entry for entry in registry["questions"]}
    language_checks = (language or {}).get("checks", {})
    rows: list[dict[str, str]] = []
    for answer in answers:
        if not answer.get("ticket"):
            continue
        entry = entries[str(answer["id"])]
        evidence = answer.get("rows") or []
        tab = data_tab_name(entry)
        affected = int(answer.get("affected_count") or 0)
        pseudo_check = {
            "id": answer.get("language_check") or answer["id"],
            "affected_count": affected,
            "denominator": answer.get("denominator"),
            "tested_count": answer.get("denominator"),
            "detail_sheet": tab,
            "qualification": answer.get("qualification"),
        }
        values = _placeholders(audit, pseudo_check, evidence)
        values["unit"] = str(entry["unit"])
        source = language_checks.get(answer.get("language_check")) if isinstance(language_checks, Mapping) else None
        source = source if isinstance(source, Mapping) else {}
        classification, priority = _ticket_grade(entry)
        count = f"{affected:,} {entry['unit']}"
        tested = ""
        if answer.get("denominator"):
            # Contract denominators count parsed HTML pages, whatever the question's unit.
            share = f" ({values['affected_pct']})" if entry["unit"] == "pages" else ""
            tested = f", across {int(answer['denominator']):,} pages tested{share}"
        description = "\n\n".join(
            part
            for part in (
                f"{entry['question']} Yes: {count}{tested} in run {values['run_id']}.",
                f"Rule: {entry['issue_if']}",
                str(entry["why"]),
                f"See the {tab} tab for every row."
                + (f"\n\nExamples:\n{values['sample_urls']}" if values["sample_urls"] else ""),
            )
            if part
        )
        notes = "\n\n".join(
            part
            for part in (
                f"Question {entry['id']} ({entry['theme']} / {entry['area']}).",
                str(entry.get("note") or ""),
                *(str(note) for note in answer.get("notes", []) or []),
            )
            if part
        )
        rows.append(
            {
                "question_id": str(entry["id"]),
                "Label": f"{entry['id']} {entry['area']}: {count}",
                "Description": description,
                "Suggested Solution": _render(source.get("suggested_solution", ""), values),
                "Acceptance Criteria": _render(source.get("acceptance_criteria", ""), values)
                or f"The next crawl answers {entry['id']} with No: {entry['issue_if']}",
                "Ticket Classification": classification,
                "Priority": priority,
                "How to Replicate": (
                    f"Run `crawler-cli technical-audit --crawl-run-id {values['run_id']}` then "
                    f"`crawler-cli technical-audit-questions`, and open the {tab} tab."
                ),
                "Notes / Documentation": notes,
            }
        )
    return rows


def _ticket_grade(entry: Json) -> tuple[str, str]:
    classification = str(entry.get("classification") or "Issue")
    priority = str(entry.get("priority") or "Medium")
    if entry.get("group") == "best-practice":
        if classification in {"Error", "Issue"}:
            classification = "Warning"
        if priority == "High":
            priority = "Medium"
    return classification, priority


def data_tab_name(entry: Json) -> str:
    return _TAB_UNSAFE.sub(" ", f"{entry['id']} {entry['area']}")[:50].strip()


def questions_sheet_tables(
    audit: Json,
    registry: Json,
    answers: Sequence[Json],
    tickets: Sequence[Mapping[str, str]],
) -> dict[str, list[list[object]]]:
    """Questions tab with answers, the Tickets tab, and one data tab per Yes answer."""

    entries = {str(entry["id"]): entry for entry in registry["questions"]}
    ticket_numbers: dict[str, int] = {}
    for number, ticket in enumerate(tickets, start=1):
        ticket_numbers[str(ticket["question_id"])] = number
    question_rows: list[list[object]] = [list(QUESTION_SHEET_COLUMNS)]
    data_tabs: dict[str, list[list[object]]] = {}
    for answer in answers:
        entry = entries[str(answer["id"])]
        rows = answer.get("rows") or []
        tab = ""
        if rows and answer.get("answer") == "Yes":
            tab = data_tab_name(entry)
            data_tabs[tab] = _data_table(rows)
        denominator = answer.get("denominator")
        question_rows.append(
            [
                entry["theme"],
                entry["id"],
                entry["area"],
                entry["question"],
                answer.get("answer", ""),
                answer["status"],
                "" if answer.get("affected_count") is None else answer["affected_count"],
                "" if denominator is None else denominator,
                entry["issue_if"],
                entry["why"],
                " ".join(str(note) for note in answer.get("notes", []) or []),
                tab,
                ticket_numbers.get(str(entry["id"]), ""),
            ]
        )
    return {"Questions": question_rows, "Tickets": ticket_sheet_table(list(tickets)), **data_tabs}


def _data_table(rows: Sequence[Json]) -> list[list[object]]:
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(str(key))
    table: list[list[object]] = [list(columns)]
    for row in rows[:MAX_DATA_TAB_ROWS]:
        table.append([_cell(row.get(column)) for column in columns])
    if len(rows) > MAX_DATA_TAB_ROWS:
        table.append([f"Truncated: {len(rows) - MAX_DATA_TAB_ROWS:,} more rows are in the answers JSON."])
    return table


def _cell(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return "" if value is None else value
    return json.dumps(value, sort_keys=True, default=str)


def _distinct_by_url(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    kept = []
    for row in rows:
        url = _row_url(row)
        if url not in seen:
            seen.add(url)
            kept.append(row)
    return kept


def _row_url(row: Json) -> str:
    samples = _sample_urls([row])
    return samples[0] if samples else ""


def _path_and_query(url: str) -> str:
    match = re.match(r"^[a-z]+://[^/?#]*", url, re.IGNORECASE)
    rest = url[match.end() :] if match else url
    return rest or "/"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
