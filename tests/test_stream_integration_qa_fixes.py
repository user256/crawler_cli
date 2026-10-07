"""Regression tests for the QA fixes made when Streams A, B and C were merged (tickets 392-398)."""

from __future__ import annotations

import asyncio
import re

from crawler_cli.__main__ import _OPT_IN_REPORTS, _REPORT_NAMES
from crawler_cli.reports import CrawlReports
from crawler_cli.technical_audit import TECHNICAL_AUDIT_REPORTS, build_technical_audit
from crawler_cli.technical_audit_evidence import HEADING_LINK_XPATH_PATTERN
from crawler_cli.technical_audit_questions import answer_questions, load_question_registry

SITE = "https://example.com"
REGISTRY = load_question_registry()
PROFILE = {"commercial_hubs": [f"{SITE}/casino/"], "templates": {"priority": {"pattern": "^/reviews/"}}}


def _context(**overrides: object) -> dict[str, object]:
    context: dict[str, object] = {
        "run_status": "complete",
        "completion_state": "complete",
        "snapshot_consistency": "stable",
        "parsed_html_count": 4,
        "html_count": 4,
        "stored_html_count": 4,
        "hashed_count": 4,
        "unparsed_html_count": 0,
        "challenged_count": 0,
        "frontier_pending": 0,
        "rate_limited_count": 0,
        "run_sitemap_source_count": 0,
        "ttfb_sample_count": 100,
        "ttfb_early_median_ms": 100.0,
        "ttfb_late_median_ms": 110.0,
        "seed_hosts": ["example.com"],
        "created_at": "2026-10-01T00:00:00",
    }
    context.update(overrides)
    return context


def _answers(reports: dict[str, list[dict[str, object]]], profile: dict | None = None, **context: object):
    audit = build_technical_audit(crawl_run_id="run-1", reports=reports, run_context=_context(**context))
    return {str(answer["id"]): answer for answer in answer_questions(audit, REGISTRY, profile)}


# --- 392: a gate that could not be fully tested does not downgrade every answer ----


def test_untested_q81_drift_leaves_other_answers_healthy_with_a_note() -> None:
    answers = _answers({"orphans": []}, ttfb_sample_count=3)
    assert answers["Q81"]["status"] == "Needs validation"
    assert answers["Q13"]["status"] == "Healthy"
    assert any("Run gate Q81 is Needs validation" in note for note in answers["Q13"]["notes"])


def test_missing_rate_limit_count_leaves_other_answers_healthy() -> None:
    answers = _answers({"orphans": []}, rate_limited_count=None)
    assert answers["Q81"]["status"] == "Pending"
    assert answers["Q13"]["status"] == "Healthy"


def test_failed_q81_gate_still_downgrades_other_answers() -> None:
    answers = _answers({"orphans": []}, rate_limited_count=5)
    assert (answers["Q81"]["answer"], answers["Q81"]["status"]) == ("Yes", "Issue")
    assert answers["Q13"]["status"] == "Needs validation"


# --- 393: Q15 and Q71 use the indexable-page population ---------------------------


def _profile_pages(indexable: list[bool]) -> list[dict[str, object]]:
    return [
        {"url": f"{SITE}/p{index}", "status": 200, "indexable": flag, "in_sitemap": True, "inlink_count": 1}
        for index, flag in enumerate(indexable)
    ]


def test_q71_and_q15_cannot_pass_when_no_page_is_indexable() -> None:
    reports = {"stored-html": [], "profile-indexability-pages": _profile_pages([False, False])}
    answers = _answers(reports)
    for qid in ("Q15", "Q71"):
        assert answers[qid]["status"] != "Healthy", qid
        assert any("could not be tested" in note for note in answers[qid]["notes"]), qid


def test_q71_and_q15_count_only_indexable_pages() -> None:
    reports = {"stored-html": [], "profile-indexability-pages": _profile_pages([True, True, False, False])}
    answers = _answers(reports)
    for qid in ("Q15", "Q71"):
        assert (answers[qid]["status"], answers[qid]["denominator"]) == ("Healthy", 2), qid


# --- 393 / Q39: the H2/H3 heading-link population is counted ---------------------


def _heading_failure(issue: str = "error_target", xpath: str = "/html/body/h2/a") -> dict[str, object]:
    return {"issue": issue, "source_url": f"{SITE}/a", "target_url": f"{SITE}/x", "xpath": xpath}


def test_q39_is_healthy_over_a_counted_heading_link_population() -> None:
    body_only = [_heading_failure(xpath="/html/body/p/a")]
    answer = _answers({"internal-link-quality": body_only}, heading_link_count=6, heading_link_tested_count=6)["Q39"]
    assert (answer["status"], answer["answer"]) == ("Healthy", "No")
    assert (answer["denominator"], answer["denominator_unit"]) == (6, "heading links")


def test_q39_heading_failures_stay_an_issue_with_a_ticket_over_the_tested_count() -> None:
    reports = {"internal-link-quality": [_heading_failure(), _heading_failure("redirect_target", "/html/body/h3/a")]}
    answer = _answers(reports, heading_link_count=9, heading_link_tested_count=7)["Q39"]
    assert (answer["status"], answer["answer"], answer["ticket"]) == ("Issue", "Yes", True)
    assert (answer["affected_count"], answer["denominator"]) == (2, 7)


def test_q39_untested_heading_links_are_noted_but_do_not_block_healthy() -> None:
    answer = _answers({"internal-link-quality": []}, heading_link_count=10, heading_link_tested_count=8)["Q39"]
    assert (answer["status"], answer["denominator"]) == ("Healthy", 8)
    assert any("2 of 10 heading links" in note and "not tested" in note for note in answer["notes"])


def test_q39_cannot_pass_when_no_heading_link_was_found() -> None:
    for found, tested in ((0, 0), (3, 0)):
        answer = _answers({"internal-link-quality": []}, heading_link_count=found, heading_link_tested_count=tested)
        q39 = answer["Q39"]
        assert q39["status"] != "Healthy", (found, tested)
        assert q39["denominator"] is None
        assert any("could not be tested" in note for note in q39["notes"])


def test_q39_audit_without_heading_link_counts_keeps_the_old_answer() -> None:
    answer = _answers({"internal-link-quality": []})["Q39"]
    assert (answer["status"], answer["answer"], answer["denominator"]) == ("Needs validation", "No (partial)", None)
    assert any("heading-link population is not counted" in note for note in answer["notes"])


class _ContextStore:
    async def get_crawl_run(self, run_id: str) -> dict[str, object]:
        return {"status": "complete", "mode": "crawl", "config": {}, "seed_urls": [f"{SITE}/"]}

    async def frontier_stats(self, *, run_id: str) -> tuple[int, int, int]:
        return (0, 0, 0)


class _ContextReports(CrawlReports):
    def __init__(self, columns: list[str]) -> None:
        super().__init__(_ContextStore())  # type: ignore[arg-type]
        self.columns = columns
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    async def _run_id(self) -> str:
        return "run-1"

    async def _fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        self.queries.append((query, args))
        if "information_schema.columns" in query:
            return [{"column_name": name} for name in self.columns]
        if "heading_links" in query:
            return [{"heading_link_count": 5, "heading_link_tested_count": 4}]
        return []


def test_technical_audit_context_counts_the_heading_link_population() -> None:
    reports = _ContextReports(["content_extracted", "links_json"])
    context = asyncio.run(reports.technical_audit_context())
    assert (context["heading_link_count"], context["heading_link_tested_count"]) == (5, 4)
    query, args = next((query, args) for query, args in reports.queries if "heading_links" in query)
    assert args == ("run-1", HEADING_LINK_XPATH_PATTERN)
    assert "final_status_code IS NOT NULL" in query


def test_technical_audit_context_leaves_heading_counts_unknown_without_links_json() -> None:
    reports = _ContextReports(["content_extracted"])
    context = asyncio.run(reports.technical_audit_context())
    assert (context["heading_link_count"], context["heading_link_tested_count"]) == (None, None)
    assert not any("heading_links" in query for query, _ in reports.queries)


def test_heading_link_pattern_matches_only_h2_and_h3_links() -> None:
    def matches(xpath: str) -> bool:
        return re.search(HEADING_LINK_XPATH_PATTERN, xpath, re.IGNORECASE) is not None

    assert matches("/html/body/h2/a") and matches("/html/body/div[2]/h3[4]/span/a") and matches("/HTML/BODY/H2/A")
    assert not matches("/html/body/h1/a") and not matches("/html/body/h4/a") and not matches("/html/body/p/a")


# --- 395: Q44 only trusts depths that are click depths from a homepage -----------


def _depth_pages(*rows: tuple[str, int]) -> list[dict[str, object]]:
    return [{"url": f"{SITE}{path}", "crawl_depth": depth} for path, depth in rows]


def test_q44_is_not_healthy_when_sitemap_urls_entered_at_depth_zero() -> None:
    reports = {"crawl-depth-pages": _depth_pages(("/", 0), ("/reviews/x", 0), ("/casino/", 0))}
    answers = _answers(reports, PROFILE, run_sitemap_source_count=3)
    assert answers["Q44"]["status"] == "Needs validation"
    assert any("sitemaps" in note for note in answers["Q44"]["notes"])


def test_q44_is_not_healthy_when_a_depth_zero_url_is_not_a_homepage() -> None:
    reports = {"crawl-depth-pages": _depth_pages(("/en/", 0), ("/reviews/x", 1), ("/casino/", 1))}
    answers = _answers(reports, PROFILE)
    assert answers["Q44"]["status"] == "Needs validation"
    assert any("not homepages" in note for note in answers["Q44"]["notes"])


def test_q44_is_healthy_only_for_a_link_crawl_from_the_homepage() -> None:
    reports = {"crawl-depth-pages": _depth_pages(("/", 0), ("/reviews/x", 1), ("/casino/", 2))}
    answers = _answers(reports, PROFILE)
    assert (answers["Q44"]["status"], answers["Q44"]["answer"]) == ("Healthy", "No")


def test_q44_reads_max_depth_from_the_registry_threshold() -> None:
    reports = {"crawl-depth-pages": _depth_pages(("/", 0), ("/casino/", 1), ("/reviews/x", 4))}
    answers = _answers(reports, PROFILE)
    assert (answers["Q44"]["status"], answers["Q44"]["affected_count"]) == ("Issue", 1)


# --- 396 / 397: Q91 is bounded, single-pass and never Healthy from nothing -------


def _anchor_page(path: str, total: int, empty: list[dict[str, object]], truncated: bool = False) -> dict[str, object]:
    return {
        "source_url": f"{SITE}{path}",
        "internal_anchor_count": total,
        "empty_anchors": empty,
        "empty_anchors_truncated": truncated,
    }


def test_q91_stays_pending_without_any_page_rows() -> None:
    assert _answers({"empty-anchor-links": []})["Q91"]["status"] == "Pending"


def test_q91_cannot_pass_when_no_internal_anchor_was_seen() -> None:
    answers = _answers({"empty-anchor-links": [_anchor_page("/a", 0, []) for _ in range(4)]})
    assert answers["Q91"]["status"] != "Healthy"
    assert any("could not be tested" in note for note in answers["Q91"]["notes"])


def test_q91_counts_every_internal_anchor_and_lists_only_confirmed_empty_ones() -> None:
    pages = [
        _anchor_page("/a", 30, [{"target_url": f"{SITE}/x", "anchor_text": "", "linked_image_alt_texts": [None]}]),
        _anchor_page("/b", 20, [{"target_url": f"{SITE}/y", "anchor_text": "", "linked_image_alt_texts": ["Logo"]}]),
        _anchor_page("/c", 10, []),
        _anchor_page("/d", 10, []),
    ]
    answer = _answers({"empty-anchor-links": pages})["Q91"]
    assert (answer["status"], answer["affected_count"], answer["denominator"]) == ("Issue", 1, 70)
    assert answer["rows"][0]["target_url"] == f"{SITE}/x"


def test_q91_is_not_healthy_when_a_page_hit_the_per_page_cap_or_pages_are_missing() -> None:
    capped = [_anchor_page("/a", 500, [], truncated=True)] + [_anchor_page(f"/p{i}", 5, []) for i in range(3)]
    assert _answers({"empty-anchor-links": capped})["Q91"]["status"] == "Needs validation"
    partial = [_anchor_page("/a", 50, [])]
    assert _answers({"empty-anchor-links": partial})["Q91"]["status"] == "Needs validation"


class _Store:
    passes = 0

    def __init__(self, pages: list[tuple[str, str]]) -> None:
        self.pages = pages

    async def iter_run_html(self, *, run_id: str | None = None, batch_size: int = 200):
        _Store.passes += 1
        for page in self.pages:
            yield page


class _Reports(CrawlReports):
    def __init__(self, pages: list[tuple[str, str]]) -> None:
        super().__init__(_Store(pages))  # type: ignore[arg-type]

    async def _run_id(self) -> str:
        return "run-1"

    async def _fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        return []


def test_empty_anchor_rows_come_from_the_shared_stored_html_pass() -> None:
    html = (
        '<html><body><a href="/x"></a><a href="/y">Text</a><a href="https://other.example/"></a>'
        '<a href="/z"><img src="l.png" alt=""></a></body></html>'
    )
    reports = _Reports([(f"{SITE}/a", html)])
    _Store.passes = 0

    async def run() -> list[dict[str, object]]:
        await reports.stored_html_findings()
        return await reports.empty_anchor_links()

    rows = asyncio.run(run())
    assert _Store.passes == 1
    assert rows == [
        {
            "source_url": f"{SITE}/a",
            "internal_anchor_count": 3,
            "empty_anchors": [
                {"target_url": f"{SITE}/x", "anchor_text": None, "linked_image_alt_texts": []},
                {"target_url": f"{SITE}/z", "anchor_text": None, "linked_image_alt_texts": [""]},
            ],
            "empty_anchors_truncated": False,
        }
    ]


def test_stream_a_reports_are_collected_by_the_audit_but_not_by_a_flagless_report_run() -> None:
    new = {"crawl-depth-pages", "performance-pages", "empty-anchor-links"}
    assert new <= set(_REPORT_NAMES) and new <= set(TECHNICAL_AUDIT_REPORTS)
    assert new <= _OPT_IN_REPORTS


# --- 398: Q88 matches its registry entry ------------------------------------------


def _timed_pages(count: int, ttfb: float = 0.1) -> list[dict[str, object]]:
    return [{"url": f"{SITE}/page-{i}", "final_status_code": 200, "ttfb_seconds": ttfb} for i in range(count)]


def test_q88_is_pending_without_a_site_profile_as_the_registry_says() -> None:
    question = next(entry for entry in REGISTRY["questions"] if entry["id"] == "Q88")
    assert question["group"] == "crawl+profile" and "site-profile" in question["requires"]
    assert _answers({"performance-pages": _timed_pages(25)})["Q88"]["status"] == "Pending"


def test_q88_times_pages_outside_every_template_as_one_group() -> None:
    profile = {"templates": {"games": {"pattern": "^/games/"}}}
    answer = _answers({"performance-pages": _timed_pages(25)}, profile)["Q88"]
    assert (answer["status"], answer["answer"], answer["denominator"]) == ("Healthy", "No", 25)
    slow = _answers({"performance-pages": _timed_pages(25, ttfb=2.0)}, profile)["Q88"]
    assert slow["status"] == "Issue" and slow["rows"][0]["template"] == "other"
