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
        "Q1",
        "Q4",
        "Q5",
        "Q10",
        "Q12",
        "Q13",
        "Q14",
        "Q15",
        "Q16",
        "Q17",
        "Q31",
    }
    assert all(row["control_ids"] for row in answers)


def test_audit_emits_the_manual_review_register_in_contract_order():
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={},
        run_context={"completion_state": "complete", "snapshot_consistency": "stable"},
    )

    assert [row["id"] for row in audit["manual_review_answers"]] == [row["id"] for row in MANUAL_REVIEW_QUESTIONS]
    assert all(row["status"] != "pass" for row in audit["manual_review_answers"])
    assert [row["id"] for row in audit["checks"]] == [row["id"] for row in TECHNICAL_AUDIT_CHECK_CONTRACT]
    # 18 detectors from the v3 projection, the external-link recheck detector that
    # feeds external-link-integrity (ticket 402), and the three analyst-level
    # detectors (AI governance, Accept-Language, transport security) not yet
    # mapped to a v3 control (ticket 400).
    assert len(audit["detector_checks"]) == 22


NO_EXTRA_EVIDENCE_QUESTIONS = ("Q2", "Q3", "Q6", "Q7", "Q8", "Q9", "Q11")


def _definition(question_id):
    return next(row for row in MANUAL_REVIEW_QUESTIONS if row["id"] == question_id)


def _controls(statuses):
    return [
        {"id": row["id"], "status": statuses.get(row["id"], "pass"), "detail_sheet": row["detail_sheet"]}
        for row in TECHNICAL_AUDIT_CHECK_CONTRACT
    ]


def _answer(question_id, controls, collected_evidence=None):
    answers = manual_review_answer_register(controls, collected_evidence=collected_evidence)
    return next(row for row in answers if row["id"] == question_id)


def test_every_extra_evidence_requirement_has_a_unique_stable_key_and_description():
    keyed = [row for row in MANUAL_REVIEW_QUESTIONS if row["additional_evidence_key"] is not None]
    assert {row["id"] for row in keyed} == {"Q1", "Q4", "Q5", "Q10", "Q12", "Q13", "Q14", "Q15", "Q16", "Q17", "Q31"}
    keys = [row["additional_evidence_key"] for row in keyed]
    assert len(keys) == len(set(keys))
    assert all(key.isidentifier() and key == key.lower() for key in keys)
    assert all(row["additional_evidence"] for row in keyed)
    assert all(
        row["additional_evidence"] is None for row in MANUAL_REVIEW_QUESTIONS if row["additional_evidence_key"] is None
    )


def test_questions_without_extra_evidence_pass_when_their_controls_pass():
    answers = {row["id"]: row for row in manual_review_answer_register(_controls({}))}

    for question_id in NO_EXTRA_EVIDENCE_QUESTIONS:
        row = answers[question_id]
        assert row["status"] == "pass", question_id
        assert row["additional_evidence_key"] is None
        assert row["additional_evidence_required"] is None
        assert row["additional_evidence_available"] is True
        assert row["additional_evidence_reference"] is None
        assert row["missing_control_ids"] == []


def test_status_precedence_unavailable_over_finding_over_partial_over_pass():
    first, second, third = _definition("Q9")["controls"]

    assert _answer("Q9", _controls({}))["status"] == "pass"
    assert _answer("Q9", _controls({first: "partial"}))["status"] == "partial"
    assert _answer("Q9", _controls({first: "not_applicable"}))["status"] == "partial"
    assert _answer("Q9", _controls({first: "partial", second: "finding"}))["status"] == "finding"
    assert (
        _answer("Q9", _controls({first: "partial", second: "finding", third: "unavailable"}))["status"] == "unavailable"
    )


def test_missing_control_makes_the_answer_unavailable_even_with_a_finding():
    first, second = _definition("Q8")["controls"]
    controls = [row for row in _controls({first: "finding"}) if row["id"] != second]

    row = _answer("Q8", controls)

    assert row["status"] == "unavailable"
    assert row["missing_control_ids"] == [second]


def test_missing_extra_evidence_outranks_a_control_finding():
    first = _definition("Q1")["controls"][0]

    assert _answer("Q1", _controls({first: "finding"}))["status"] == "unavailable"


def test_extra_evidence_question_passes_only_with_a_referenced_evidence_entry():
    key = _definition("Q1")["additional_evidence_key"]
    controls = _controls({})

    row = _answer("Q1", controls, {key: {"detail_sheet": "Resource Robots", "rows": 42}})
    assert row["status"] == "pass"
    assert row["additional_evidence_key"] == key
    assert row["additional_evidence_required"] == _definition("Q1")["additional_evidence"]
    assert row["additional_evidence_available"] is True
    assert row["additional_evidence_reference"] == {"detail_sheet": "Resource Robots"}

    row = _answer("Q1", controls, {key: {"source": "runs/example/resource-robots.jsonl"}})
    assert row["status"] == "pass"
    assert row["additional_evidence_reference"] == {"source": "runs/example/resource-robots.jsonl"}

    first = _definition("Q1")["controls"][0]
    assert _answer("Q1", _controls({first: "finding"}), {key: {"source": "x"}})["status"] == "finding"


def test_extra_evidence_question_stays_unavailable_without_a_valid_entry():
    definition = _definition("Q1")
    key = definition["additional_evidence_key"]
    controls = _controls({})
    invalid_evidence = [
        None,
        {},
        {key: True},
        {key: "Resource Robots"},
        {key: {}},
        {key: {"detail_sheet": ""}},
        {key: {"detail_sheet": "   ", "source": None}},
        {key: {"note": "checked by hand"}},
        {definition["additional_evidence"]: True},
        {definition["additional_evidence"]: {"detail_sheet": "Resource Robots"}},
        {key.replace("_", "-"): {"detail_sheet": "Resource Robots"}},
        {key + "s": {"source": "runs/example/resource-robots.jsonl"}},
    ]

    for evidence in invalid_evidence:
        row = _answer("Q1", controls, evidence)
        assert row["status"] == "unavailable", evidence
        assert row["additional_evidence_available"] is False, evidence
        assert row["additional_evidence_reference"] is None, evidence
