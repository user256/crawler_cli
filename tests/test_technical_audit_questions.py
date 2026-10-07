from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from crawler_cli.__main__ import _run_technical_audit_questions
from crawler_cli.html_audit import inspect_stored_html
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
        "rate_limited_count": 0,
        "ttfb_sample_count": 100,
        "ttfb_early_median_ms": 120.0,
        "ttfb_late_median_ms": 130.0,
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
    # Supplied-input questions stay Pending until a bundle is attached.
    assert (
        answers["Q18"]["status"] == "Pending"
        and "No google-render-inspection observations" in answers["Q18"]["notes"][1]
    )
    assert answers["Q104"]["status"] == "Pending" and answers["Q104"]["notes"][0].startswith("Outside crawler_cli")
    # A scope-limited answer with no rows cannot be called healthy.
    assert answers["Q94"]["status"] == "Pending"


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


def test_rate_limit_gate_downgrades_crawl_answers_without_a_ticket() -> None:
    answers = _by_id(answer_questions(_audit(rate_limited_count=2), load_question_registry()))

    assert (answers["Q81"]["answer"], answers["Q81"]["status"], answers["Q81"]["ticket"]) == ("Yes", "Issue", False)
    assert answers["Q16"]["status"] == "Needs validation"


def test_internal_link_redirect_and_canonical_rows_answer_q22_and_q72() -> None:
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={
            "internal-link-quality": [
                {
                    "issue": "redirect_target",
                    "source_url": f"{SITE}/source",
                    "target_url": f"{SITE}/guide/",
                    "final_url": f"{SITE}/guide",
                },
                {
                    "issue": "noncanonical_target",
                    "source_url": f"{SITE}/other",
                    "target_url": f"{SITE}/old",
                    "target_canonical": f"{SITE}/new",
                },
            ]
        },
        run_context=_context(),
    )
    answers = _by_id(answer_questions(audit, load_question_registry()))
    assert (answers["Q22"]["answer"], answers["Q22"]["status"], answers["Q22"]["affected_count"]) == ("Yes", "Issue", 2)
    assert (answers["Q72"]["answer"], answers["Q72"]["status"], answers["Q72"]["affected_count"]) == ("Yes", "Issue", 1)


def test_soft404_source_candidates_need_validation() -> None:
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={
            "soft404-error-routes": [
                {"url": f"{SITE}/missing", "final_status_code": 200, "signature_source": "title", "signature": "404"}
            ]
        },
        run_context=_context(stored_html_count=1),
    )
    answer = _by_id(answer_questions(audit, load_question_registry()))["Q42"]
    assert (answer["answer"], answer["status"], answer["ticket"]) == ("Yes", "Needs validation", False)


def test_discovery_source_difference_is_a_review_candidate() -> None:
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={
            "discovery-source-provenance": [
                {
                    "url": f"{SITE}/legacy",
                    "in_sitemap": True,
                    "internally_linked": False,
                    "issue": "sitemap_only",
                }
            ]
        },
        run_context=_context(run_sitemap_source_count=1),
    )
    answer = _by_id(answer_questions(audit, load_question_registry()))["Q82"]
    assert (answer["answer"], answer["status"], answer["ticket"]) == ("Yes", "Needs validation", False)


def test_raw_html_questions_are_answered_from_stored_source() -> None:
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={
            "stored-html": [
                {"url": f"{SITE}/lang", "kind": "html-lang-self-hreflang-mismatch"},
                {"url": f"{SITE}/duplicate", "kind": "duplicate-title"},
                {"url": f"{SITE}/body", "kind": "head-only-element-in-body"},
                {"url": f"{SITE}/outline", "kind": "heading-level-skip", "overall_indexable": True},
                {
                    "url": f"{SITE}/canonical",
                    "kind": "missing-canonical",
                    "overall_indexable": True,
                    "final_status_code": 200,
                },
                {"url": f"{SITE}/relative", "kind": "relative-canonical", "canonical": "/relative"},
                {"url": f"{SITE}/retired", "kind": "canonical-to-homepage", "canonical": f"{SITE}/"},
                {"url": f"{SITE}/parity", "kind": "html-header-canonical-mismatch"},
            ],
            "metadata-duplicates": [
                {
                    "url": f"{SITE}/title-a\n{SITE}/title-b",
                    "field": "title",
                    "value": "Shared title",
                    "count": 2,
                }
            ],
            "indexability": [],
            "nonhtml-search-assets": [{"url": f"{SITE}/guide.pdf", "final_status_code": 200}],
            "hreflang-validation": [
                {"url": f"{SITE}/en/page", "kind": "locale-path-language-mismatch", "locale_folder": "en"}
            ],
        },
        run_context=_context(stored_html_count=6, nonhtml_document_count=1),
    )

    answers = _by_id(answer_questions(audit, load_question_registry()))
    for qid in ("Q8", "Q10", "Q11", "Q12", "Q15", "Q41", "Q71", "Q73", "Q80", "Q87", "Q94"):
        assert (answers[qid]["answer"], answers[qid]["status"], answers[qid]["affected_count"]) == ("Yes", "Issue", 1)


def test_raw_html_questions_distinguish_clean_and_unavailable_evidence() -> None:
    clean = build_technical_audit(
        crawl_run_id="run-1",
        reports={
            "stored-html": [],
            "metadata-duplicates": [],
            "indexability": [],
            "nonhtml-search-assets": [],
            "hreflang-validation": [],
        },
        run_context=_context(stored_html_count=2, nonhtml_document_count=1),
    )
    clean_answers = _by_id(answer_questions(clean, load_question_registry()))
    for qid in ("Q8", "Q10", "Q11", "Q12", "Q15", "Q41", "Q71", "Q73", "Q80", "Q87", "Q94"):
        assert (clean_answers[qid]["answer"], clean_answers[qid]["status"]) == ("No", "Healthy")

    unavailable = build_technical_audit(crawl_run_id="run-1", reports={}, run_context=_context())
    unavailable_answers = _by_id(answer_questions(unavailable, load_question_registry()))
    for qid in ("Q8", "Q10", "Q11", "Q12", "Q15", "Q41", "Q71", "Q73", "Q80", "Q87", "Q94"):
        assert unavailable_answers[qid]["status"] == "Pending"


def test_raw_html_inspector_preserves_source_only_findings() -> None:
    findings = inspect_stored_html(
        f"{SITE}/page",
        """
        <html lang="en"><head>
          <title>One</title><title>Two</title>
          <meta name="description" content="one"><meta name="description" content="two">
          <link rel="canonical" href="/page"><link rel="alternate" hreflang="fr" href="https://example.com/page">
        </head><body><h1>One</h1><h3>Skipped</h3><meta name="robots" content="noindex"></body></html>
        """,
    )
    kinds = {str(row["kind"]) for row in findings}
    assert {"duplicate-title", "duplicate-meta-description", "relative-canonical"} <= kinds
    assert {"head-only-element-in-body", "heading-level-skip", "html-lang-self-hreflang-mismatch"} <= kinds


def test_semantic_question_inputs_answer_toc_and_landmark_questions() -> None:
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={
            "semantic-html": [
                {
                    "url": f"{SITE}/shell",
                    "landmark_eligible": True,
                    "missing_required_landmarks": True,
                    "toc_eligible": False,
                },
                {
                    "url": f"{SITE}/guide",
                    "landmark_eligible": True,
                    "missing_required_landmarks": False,
                    "toc_eligible": True,
                    "missing_h2_fragment_toc": True,
                },
            ]
        },
        run_context=_context(stored_html_count=2),
    )
    answers = _by_id(answer_questions(audit, load_question_registry()))
    assert (answers["Q51"]["answer"], answers["Q51"]["status"]) == ("Yes", "Needs validation")
    assert (answers["Q58"]["answer"], answers["Q58"]["status"], answers["Q58"]["affected_count"]) == ("Yes", "Issue", 1)


def test_profile_and_image_question_inputs_preserve_policy_coverage() -> None:
    profile = {
        "templates": {
            "listing": {"pattern": r"^/listing/$", "indexable": True},
            "profile_subtab": {"pattern": r"^/user/[^/]+/reviews/$", "indexable": False},
            "profile": {"pattern": r"^/user/[^/]+/$", "indexable": True},
            "taxonomy": {"pattern": r"^/category/[^/]+/$", "indexable": True},
        },
        "empty_profile_rule": {"max_main_content_words": 40},
    }
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={
            "profile-indexability-pages": [
                {"url": f"{SITE}/listing/", "noindex": True, "in_sitemap": False},
                {
                    "url": f"{SITE}/user/a/reviews/",
                    "status": 200,
                    "indexable": True,
                    "canonical": f"{SITE}/user/a/reviews/",
                },
                {"url": f"{SITE}/user/a/", "word_count": 10, "indexable": True, "in_sitemap": False},
                {"url": f"{SITE}/category/a/", "noindex": True, "inlink_percentile": 0.95},
            ],
            "semantic-html": [
                {
                    "url": f"{SITE}/images",
                    "main_image_eligible": True,
                    "main_image_count": 3,
                    "main_images_without_figure_and_figcaption": 2,
                }
            ],
        },
        run_context=_context(stored_html_count=1),
    )
    answers = _by_id(answer_questions(audit, load_question_registry(), profile))
    assert (answers["Q20"]["answer"], answers["Q20"]["status"]) == ("Yes", "Needs validation")
    for qid in ("Q36", "Q37", "Q78"):
        assert (answers[qid]["answer"], answers[qid]["status"], answers[qid]["affected_count"]) == ("Yes", "Issue", 1)
    assert (answers["Q54"]["answer"], answers["Q54"]["status"], answers["Q54"]["affected_count"]) == (
        "Yes",
        "Needs validation",
        2,
    )


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
    assert tables["Tickets"][int(questions["Q16"][12])][0].startswith("Q16 Structured data: 1 page")
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
    for number in (97, 98, 99, 100, 101, 103, 104):
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
    assert "1 page, across 10,852 pages tested (<1%)" in q16["Description"]


def test_ticket_keeps_the_share_for_a_qualified_population_of_the_finding_unit() -> None:
    # "993 pages across 9,211 indexable pages" is a like-for-like share.
    audit = _audit()
    registry = load_question_registry()
    answers = [
        {**answer, "ticket": True, "affected_count": 993, "denominator": 9_211, "denominator_unit": "indexable pages"}
        for answer in answer_questions(audit, registry)
        if answer["id"] == "Q16"
    ]
    (q16,) = question_ticket_rows(audit, registry, answers, load_ticket_language())
    assert "993 pages, across 9,211 indexable pages tested (11%)" in q16["Description"]


def test_ticket_share_never_rounds_a_finding_away() -> None:
    from crawler_cli.technical_audit_tickets import _share

    assert _share(500, 627_923) == "<1%"
    assert _share(0, 10) == "0%"
    assert _share(999, 1_000) == ">99%"
    assert _share(10, 10) == "100%"
    assert _share(1, 0) == ""


def test_ticket_names_the_denominator_unit_when_it_differs_from_the_finding_unit() -> None:
    # Ticket 416: Q22 counts links, but its contract denominator counts parsed pages.
    audit = _audit()
    registry = load_question_registry()
    answers = answer_questions(audit, registry)
    tickets = {
        row["question_id"]: row for row in question_ticket_rows(audit, registry, answers, load_ticket_language())
    }

    assert _by_id(answers)["Q22"]["denominator_unit"] == "pages"
    assert "Yes: 2 links, across 100 pages tested in run run-1." in tickets["Q22"]["Description"]
    assert "Yes: 1 page, across 100 pages tested (1%) in run run-1." in tickets["Q16"]["Description"]


def test_every_answered_question_carries_an_explicit_denominator_unit() -> None:
    for answer in answer_questions(_audit(), load_question_registry()):
        if answer["denominator"] is not None:
            assert answer["denominator_unit"] not in {None, "items"}, answer["id"]


def test_unit_label_uses_singular_for_one() -> None:
    from crawler_cli.technical_audit_evidence import unit_label

    assert unit_label(1, "host-agent policies") == "1 host-agent policy"
    assert unit_label(2, "host-agent policies") == "2 host-agent policies"
    assert unit_label(1, "URLs") == "1 URL" and unit_label(1, "URL families") == "1 URL family"
    assert unit_label(1, "user agents") == "1 user agent" and unit_label(1_200, "pages") == "1,200 pages"
