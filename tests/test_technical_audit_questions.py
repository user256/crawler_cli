from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from crawler_cli.__main__ import _run_technical_audit_questions
from crawler_cli.technical_audit import build_technical_audit
from crawler_cli.technical_audit_questions import (
    QuestionRegistryError,
    answer_questions,
    default_site_profile_example_path,
    load_question_registry,
    question_ticket_rows,
    questions_markdown,
    questions_sheet_tables,
    validate_question_registry,
)
from crawler_cli.technical_audit_tickets import load_ticket_language


DOC = Path(__file__).parents[1] / "docs" / "technical-audit-questions.md"


def test_registry_covers_every_template_question_once() -> None:
    registry = load_question_registry()
    ids = [entry["id"] for entry in registry["questions"]]
    assert sorted(ids, key=lambda qid: int(qid[1:])) == [f"Q{number}" for number in range(1, 105)]


def test_example_site_profile_satisfies_every_profile_key() -> None:
    registry = load_question_registry()
    profile = json.loads(default_site_profile_example_path().read_text(encoding="utf-8"))
    validate_question_registry(registry, profile)


def test_unknown_contract_check_is_rejected() -> None:
    registry = load_question_registry()
    registry["questions"][0]["checks"] = ["not-a-contract-check"]
    with pytest.raises(QuestionRegistryError, match="unknown contract check"):
        validate_question_registry(registry)


def test_missing_profile_key_is_reported_per_question() -> None:
    registry = load_question_registry()
    with pytest.raises(QuestionRegistryError, match="Q23: site profile lacks 'templates.inventory'"):
        validate_question_registry(registry, {"templates": {}})


def test_review_document_is_generated_from_registry() -> None:
    assert DOC.read_text(encoding="utf-8") == questions_markdown(load_question_registry())


# --- runner ---------------------------------------------------------------

SITE = "https://example.com"


def _context(**overrides: object) -> dict[str, object]:
    context: dict[str, object] = {
        "run_status": "complete",
        "completion_state": "complete",
        "snapshot_consistency": "stable",
        "parsed_html_count": 100,
        "html_count": 100,
        "hashed_count": 100,
        "unparsed_html_count": 0,
        "challenged_count": 0,
        "frontier_pending": 0,
        "seed_hosts": ["example.com"],
        "created_at": "2026-10-01T00:00:00",
    }
    context.update(overrides)
    return context


def _audit(**context: object) -> dict[str, object]:
    reports = {
        "internal-link-quality": [
            {
                "issue": "error_target",
                "source_url": f"{SITE}/a",
                "target_url": f"{SITE}/gone",
                "target_status": 404,
                "xpath": "/html/body/main/h2[1]/a",
            },
            {
                "issue": "error_target",
                "source_url": f"{SITE}/b",
                "target_url": f"{SITE}/gone",
                "target_status": 404,
                "xpath": "/html/body/main/p[3]/a",
            },
        ],
        "schema-compatibility": [{"url": f"{SITE}/a", "is_valid": False}, {"url": f"{SITE}/b", "is_valid": True}],
        "orphans": [{"url": f"{SITE}/lonely"}],
        "internal-authority": [
            {"url": f"{SITE}/", "unique_outlinks": 450, "unique_inlinks": 99},
            {"url": f"{SITE}/a", "unique_outlinks": 40, "unique_inlinks": 3},
        ],
        "near-duplicates": [
            {"url": f"{SITE}/casino/games/x", "near_duplicate_url": f"{SITE}/casino/games/y", "simhash_distance": 1},
            {"url": f"{SITE}/news/x", "near_duplicate_url": f"{SITE}/news/y", "simhash_distance": 2},
        ],
        "indexability": [],
    }
    return build_technical_audit(crawl_run_id="run-1", reports=reports, run_context=_context(**context))


def _by_id(answers: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(answer["id"]): answer for answer in answers}


def test_complete_run_answers_implemented_questions_and_leaves_the_rest_pending() -> None:
    answers = _by_id(answer_questions(_audit(), load_question_registry()))

    assert answers["Q26"]["status"] == "Healthy"
    assert (answers["Q16"]["status"], answers["Q16"]["affected_count"], answers["Q16"]["ticket"]) == ("Issue", 1, True)
    assert answers["Q22"]["status"] == "Issue" and answers["Q22"]["affected_count"] == 2
    assert answers["Q39"]["affected_count"] == 1
    assert answers["Q14"]["status"] == "Issue" and answers["Q14"]["rows"][0]["url"] == f"{SITE}/"
    # Orphans carry coverage_required, so they are candidates, never an automatic ticket.
    assert (answers["Q13"]["status"], answers["Q13"]["ticket"]) == ("Needs validation", False)
    assert answers["Q2"]["status"] == "Pending" and "url-host-and-variants" in answers["Q2"]["notes"][0]
    assert answers["Q18"]["status"] == "Pending" and answers["Q18"]["notes"][0].startswith("Outside crawler_cli")
    # A scope-limited answer with no rows cannot be called healthy.
    assert answers["Q94"]["status"] == "Needs validation" and answers["Q94"]["answer"] == "No (partial)"


def test_failed_run_gate_downgrades_every_crawl_answer() -> None:
    answers = _by_id(
        answer_questions(_audit(completion_state="running", frontier_pending=12), load_question_registry())
    )

    assert answers["Q26"]["status"] == "Issue" and answers["Q26"]["ticket"] is False
    assert {row["condition"] for row in answers["Q26"]["rows"]} == {
        "run completion state",
        "frontier URLs still pending",
    }
    assert (answers["Q16"]["status"], answers["Q16"]["ticket"]) == ("Needs validation", True)
    assert "Healthy" not in {answer["status"] for answer in answers.values()}


def test_profile_template_scopes_inventory_question() -> None:
    registry = load_question_registry()
    without = _by_id(answer_questions(_audit(), registry))["Q21"]
    profile = {"templates": {"inventory": {"pattern": r"^/casino/games/"}}}
    with_profile = _by_id(answer_questions(_audit(), registry, profile))["Q21"]

    assert without["status"] == "Pending" and "templates.inventory" in " ".join(without["notes"])
    assert with_profile["affected_count"] == 1
    assert with_profile["rows"][0]["url"] == f"{SITE}/casino/games/x"


def test_sheet_tables_link_questions_to_tickets_and_data_tabs() -> None:
    audit = _audit()
    registry = load_question_registry()
    answers = answer_questions(audit, registry)
    tickets = question_ticket_rows(audit, registry, answers, load_ticket_language())
    tables = questions_sheet_tables(audit, registry, answers, tickets)

    questions = {row[1]: row for row in tables["Questions"][1:]}
    assert len(questions) == 104
    assert questions["Q16"][4:6] == ["Yes", "Issue"]
    assert questions["Q16"][11] == "Q16 Structured data" and "Q16 Structured data" in tables
    assert tables["Tickets"][int(questions["Q16"][12])][0].startswith("Q16 Structured data: 1 pages")
    assert questions["Q2"][11] == "" and questions["Q2"][12] == ""
    ticket = next(row for row in tickets if row["question_id"] == "Q22")
    assert ticket["Suggested Solution"]  # reused from the internal-link-targets ticket language
    assert "https://example.com/a" in ticket["Description"]


def test_cli_writes_answers_without_database(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps(_audit(), default=str), encoding="utf-8")
    out = tmp_path / "answers.json"
    args = argparse.Namespace(
        audit=str(audit_path),
        out=str(out),
        site_profile=None,
        questions=None,
        ticket_language=None,
        google_sheets_template=None,
        google_sheets_title=None,
        google_sheets_folder=None,
        google_sheets_credentials=None,
    )

    assert _run_technical_audit_questions(args) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload["answers"]) == 104 and payload["crawl_run_id"] == "run-1"


def test_new_questions_remain_pending_without_dedicated_answerers() -> None:
    registry = load_question_registry()
    audit = _audit()
    answers = answer_questions(audit, registry)
    by_id = _by_id(answers)
    for number in range(97, 105):
        answer = by_id[f"Q{number}"]
        assert answer["status"] == "Pending"
        assert answer["answer"] == "" and answer["affected_count"] is None
        assert answer["rows"] == [] and answer["ticket"] is False
        reason = "Outside crawler_cli" if number == 104 else "Not answered by the runner yet"
        assert answer["notes"][0].startswith(reason)
    tickets = question_ticket_rows(audit, registry, answers, load_ticket_language())
    assert not {ticket["question_id"] for ticket in tickets} & {f"Q{n}" for n in range(97, 105)}


def test_ticket_percentages_survive_thousands_separated_denominators() -> None:
    audit = _audit(parsed_html_count=10_852, html_count=10_852)
    registry = load_question_registry()
    tickets = question_ticket_rows(audit, registry, answer_questions(audit, registry), load_ticket_language())

    q16 = next(row for row in tickets if row["question_id"] == "Q16")
    assert "1 pages, across 10,852 pages tested (0%)" in q16["Description"]
