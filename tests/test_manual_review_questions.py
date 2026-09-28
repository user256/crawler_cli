from __future__ import annotations

from crawler_cli.manual_review_questions import MANUAL_REVIEW_QUESTIONS, manual_review_answer_register
from crawler_cli.technical_audit import build_technical_audit
from crawler_cli.technical_audit_contract import TECHNICAL_AUDIT_CHECK_CONTRACT


def test_manual_review_register_covers_every_explicit_question_without_inferred_passes():
    assert [row["id"] for row in MANUAL_REVIEW_QUESTIONS] == [
        *[f"Q{number}" for number in range(1, 18)],
        "Q31",
    ]
    controls = [
        {"id": row["id"], "status": "pass", "detail_sheet": row["detail_sheet"], "affected_count": 0}
        for row in TECHNICAL_AUDIT_CHECK_CONTRACT
    ]
    answers = manual_review_answer_register(controls)

    assert len(answers) == 18
    assert {row["id"] for row in answers if row["status"] == "unavailable"} >= {
        "Q1", "Q4", "Q5", "Q10", "Q12", "Q13", "Q14", "Q15", "Q16", "Q17", "Q31"
    }
    assert all(row["control_ids"] for row in answers)


def test_audit_emits_the_manual_review_register_in_contract_order():
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={},
        run_context={"completion_state": "complete", "snapshot_consistency": "stable"},
    )

    assert [row["id"] for row in audit["manual_review_answers"]] == [
        row["id"] for row in MANUAL_REVIEW_QUESTIONS
    ]
    assert all(row["status"] != "pass" for row in audit["manual_review_answers"])
    assert [row["id"] for row in audit["checks"]] == [row["id"] for row in TECHNICAL_AUDIT_CHECK_CONTRACT]
    assert len(audit["detector_checks"]) == 18
