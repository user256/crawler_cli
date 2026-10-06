"""Regression tests for the Stream B QA tickets 371-385.

Collector fakes return rows the way asyncpg does without a JSON codec: JSONB
columns arrive as strings.  Fixtures built from Python lists hid ticket 371.
"""

from __future__ import annotations

import asyncio
import json

from crawler_cli.html_audit import inspect_stored_html
from crawler_cli.reports import CrawlReports, _is_homepage_variant
from crawler_cli.technical_audit import _link_target_failures, build_technical_audit
from crawler_cli.technical_audit_questions import answer_questions, load_question_registry


SITE = "https://example.com"
REGISTRY = load_question_registry()


class _Store:
    def __init__(self, pages: list[tuple[str, str]]) -> None:
        self.pages = pages

    async def iter_run_html(self, *, run_id: str | None = None, batch_size: int = 200):
        for page in self.pages:
            yield page


class _Reports(CrawlReports):
    """CrawlReports over canned rows; every query returns ``rows``."""

    def __init__(self, rows: list[dict[str, object]], pages: list[tuple[str, str]] | None = None) -> None:
        super().__init__(_Store(pages or []))  # type: ignore[arg-type]
        self.rows = rows

    async def _run_id(self) -> str:
        return "run-1"

    async def _fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        return [dict(row) for row in self.rows]


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
        "ttfb_sample_count": 100,
        "ttfb_early_median_ms": 100.0,
        "ttfb_late_median_ms": 110.0,
    }
    context.update(overrides)
    return context


def _answers(reports: dict[str, list[dict[str, object]]], profile: dict[str, object] | None = None, **context: object):
    audit = build_technical_audit(crawl_run_id="run-1", reports=reports, run_context=_context(**context))
    return {str(answer["id"]): answer for answer in answer_questions(audit, REGISTRY, profile)}, audit


# --- 371 / 375: JSONB arrives as text ---------------------------------------


def test_duplicate_metadata_decodes_canonical_json_text() -> None:
    rows = [
        {"url": f"{SITE}/a", "title": "Same", "h1_tags": "A", "canonical_urls_json": json.dumps([f"{SITE}/a"])},
        {"url": f"{SITE}/b", "title": "Same", "h1_tags": "B", "canonical_urls_json": json.dumps([f"{SITE}/b/"])},
        {"url": f"{SITE}/c", "title": "Same", "h1_tags": "C", "canonical_urls_json": json.dumps([f"{SITE}/a"])},
    ]
    findings = asyncio.run(_Reports(rows).duplicate_metadata())
    assert [(row["field"], row["count"]) for row in findings] == [("title", 2)]


def test_hreflang_validation_decodes_annotation_json_text() -> None:
    rows = [
        {
            "url": f"{SITE}/en/a",
            "hreflang_json": json.dumps([{"hreflang": "fr", "href": f"{SITE}/fr/a", "source": "html_head"}]),
            "canonical_urls_json": json.dumps([f"{SITE}/en/a"]),
            "final_status_code": 200,
            "overall_indexable": True,
            "html_lang": "en",
        },
        {
            "url": f"{SITE}/fr/a",
            "hreflang_json": "[]",
            "canonical_urls_json": json.dumps([f"{SITE}/fr/a"]),
            "final_status_code": 200,
            "overall_indexable": False,
            "html_lang": "fr",
        },
    ]
    kinds = {row["kind"] for row in asyncio.run(_Reports(rows).hreflang_validation())}
    assert {"hreflang-non-reciprocal", "hreflang-target-noindex"} <= kinds


def test_nonhtml_assets_read_header_names_from_json_text() -> None:
    def flagged(headers: dict[str, str]) -> bool:
        row = {"url": f"{SITE}/a.pdf", "final_status_code": 200, "headers_json": json.dumps(headers)}
        return bool(asyncio.run(_Reports([row]).nonhtml_search_assets()))

    assert flagged({"Content-Type": "application/pdf"})
    assert not flagged({"X-Robots-Tag": "noindex"})
    assert not flagged({"Link": f'<{SITE}/doc>; rel="canonical"'})


def test_stored_html_sees_link_header_canonicals_from_json_text() -> None:
    no_html_canonical = "<html lang='en'><head><title>A</title></head><body><h1>A</h1></body></html>"
    other_canonical = f"<html lang='en'><head><title>B</title><link rel='canonical' href='{SITE}/b'></head><body><h1>B</h1></body></html>"
    rows = [
        {
            "url": f"{SITE}/a",
            "headers_json": json.dumps({"link": f'<{SITE}/a>; rel="canonical"'}),
            "final_status_code": 200,
        },
        {
            "url": f"{SITE}/b",
            "headers_json": json.dumps({"Link": f"<{SITE}/other>; rel=canonical"}),
            "final_status_code": 200,
        },
    ]
    pages = [(f"{SITE}/a", no_html_canonical), (f"{SITE}/b", other_canonical)]
    kinds = [(row["url"], row["kind"]) for row in asyncio.run(_Reports(rows, pages).stored_html_findings())]
    # The Link header satisfies Q71 for /a; /b's header and HTML canonicals disagree (Q94).
    assert (f"{SITE}/a", "missing-canonical") not in kinds
    assert (f"{SITE}/b", "html-header-canonical-mismatch") in kinds


# --- 379 / 385: one streamed pass, conservative soft-404s ---------------------


def test_stored_html_reports_share_one_streamed_pass() -> None:
    class _CountingStore(_Store):
        passes = 0

        async def iter_run_html(self, *, run_id: str | None = None, batch_size: int = 200):
            _CountingStore.passes += 1
            for page in self.pages:
                yield page

    reports = _Reports([{"url": f"{SITE}/a", "final_status_code": 200, "title": "Fine"}])
    reports.store = _CountingStore([(f"{SITE}/a", "<html><body><h1>Fine</h1></body></html>")])  # type: ignore[assignment]

    async def run() -> None:
        await reports.stored_html_findings()
        await reports.semantic_html_facts()
        await reports.soft404_error_routes()

    asyncio.run(run())
    assert _CountingStore.passes == 1


def test_soft_404_matches_title_or_h1_not_body_copy() -> None:
    rows = [
        {"url": f"{SITE}/a", "final_status_code": 200, "title": "Page not found"},
        {"url": f"{SITE}/b", "final_status_code": 200, "title": "Pricing"},
        {"url": f"{SITE}/c", "final_status_code": 200, "title": "Help"},
    ]
    pages = [
        (f"{SITE}/a", "<html><body><h1>Oops</h1></body></html>"),
        (
            f"{SITE}/b",
            "<html><body><h1>Plans</h1><p>Error 404 handling, 404 users</p><script>'not found'</script></body></html>",
        ),
        (f"{SITE}/c", "<html><body><h1>Error page</h1></body></html>"),
    ]
    found = asyncio.run(_Reports(rows, pages).soft404_error_routes())
    assert [(row["url"], row["signature_source"]) for row in found] == [(f"{SITE}/a", "title"), (f"{SITE}/c", "h1")]


# --- 372: SVG titles and feed links ------------------------------------------


def test_svg_titles_and_feed_alternates_are_not_head_element_findings() -> None:
    html = (
        f"<html lang='en'><head><title>T</title><link rel='canonical' href='{SITE}/a'></head><body><h1>A</h1>"
        "<svg viewBox='0 0 1 1'><title>Close</title><path d=''/></svg>"
        "<link rel='alternate' type='application/rss+xml' href='/feed'></body></html>"
    )
    assert inspect_stored_html(f"{SITE}/a", html) == []


def test_genuine_head_elements_in_body_are_still_found() -> None:
    html = (
        f"<html lang='en'><head><title>T</title><link rel='canonical' href='{SITE}/a'></head><body><h1>A</h1>"
        "<title>Second</title><link rel='alternate' hreflang='fr' href='/fr/a'></body></html>"
    )
    kinds = {row["kind"] for row in inspect_stored_html(f"{SITE}/a", html)}
    assert {"duplicate-title", "head-only-element-in-body"} <= kinds


# --- 374: homepage variants ---------------------------------------------------


def test_homepage_variants_are_not_canonical_to_homepage_findings() -> None:
    home = f"{SITE}/"
    assert _is_homepage_variant(f"{SITE}/?modal=search", home)
    assert _is_homepage_variant(f"{SITE}/index.html", home)
    assert not _is_homepage_variant(f"{SITE}/casino", home)
    assert not _is_homepage_variant("https://other.example/", home)


# --- 376: zero population ------------------------------------------------------


def test_profile_template_matching_no_page_is_pending_not_healthy() -> None:
    pages = [
        {"url": f"{SITE}/casino", "status": 200, "indexable": True, "noindex": False, "canonical": f"{SITE}/casino"}
    ]
    profile = {"templates": {"profile_subtab": {"pattern": "^/user/[^/]+/tab/?$", "indexable": False}}}
    answers, _audit = _answers({"profile-indexability-pages": pages}, profile)
    assert answers["Q36"]["status"] == "Pending"
    assert "matches the Q36 profile template" in " ".join(answers["Q36"]["notes"])


def test_runner_never_reports_healthy_from_an_empty_population() -> None:
    # No documents were fetched: the Q87 population is empty, so it is untested.
    answers, _audit = _answers({"nonhtml-search-assets": []}, nonhtml_document_count=0)
    assert answers["Q87"]["status"] == "Pending"


# --- 377: locale populations and review qualifications ----------------------


def test_q32_ignores_markup_rows_and_q8_reads_them() -> None:
    stored = [{"url": f"{SITE}/a", "kind": "missing-html-lang", "overall_indexable": True, "final_status_code": 200}]
    answers, audit = _answers({"stored-html": stored})
    assert answers["Q8"]["status"] == "Issue" and answers["Q8"]["affected_count"] == 1
    assert answers["Q32"]["status"] == "Pending"
    checks = {check["id"]: check for check in audit["checks"]}
    assert checks["near-duplicate-content"]["qualification"] == "review_required"
    assert checks["locale-html-lang"]["qualification"] == "review_required"


def test_q41_reads_locale_folder_rows_from_hreflang_validation() -> None:
    rows = [{"url": f"{SITE}/es/x", "kind": "locale-path-language-mismatch", "locale_folder": "es"}]
    answers, _audit = _answers({"hreflang-validation": rows})
    assert (answers["Q41"]["status"], answers["Q41"]["affected_count"]) == ("Issue", 1)


# --- 381: canonical mismatches ------------------------------------------------


def test_header_canonical_mismatch_is_a_canonical_finding_not_a_robots_conflict() -> None:
    stored = [
        {
            "url": f"{SITE}/b",
            "kind": "html-header-canonical-mismatch",
            "header_canonical": f"{SITE}/other",
            "html_canonicals": [f"{SITE}/b"],
        }
    ]
    answers, audit = _answers({"stored-html": stored, "indexability": []})
    assert answers["Q94"]["status"] == "Issue" and answers["Q94"]["affected_count"] == 1
    checks = {check["id"]: check for check in audit["checks"]}
    assert checks["indexability-segmentation"]["affected_count"] == 0
    assert not any(row["Problem"] == "Conflicting indexability directives" for row in audit["audit_log"])


# --- 382: Q54 image identity ----------------------------------------------------


def test_q54_rows_name_each_uncaptioned_image() -> None:
    facts = [
        {
            "url": f"{SITE}/a",
            "main_image_eligible": True,
            "main_image_count": 3,
            "main_images_without_figure_and_figcaption": 2,
            "uncaptioned_main_image_srcs": ["/one.png", "/two.png"],
        }
    ]
    answers, _audit = _answers({"semantic-html": facts})
    assert [row["image_src"] for row in answers["Q54"]["rows"]] == ["/one.png", "/two.png"]
    assert answers["Q54"]["denominator"] == 3


# --- 383: link targets --------------------------------------------------------


def test_link_target_failures_keep_one_row_per_link_with_every_issue() -> None:
    edge = {"source_url": f"{SITE}/a", "target_url": f"{SITE}/x", "xpath": "/html/body/a"}
    rows = [
        {**edge, "issue": "empty_anchor"},
        {**edge, "issue": "non_indexable_target"},
        {**edge, "issue": "redirect_target"},
        {**edge, "target_url": f"{SITE}/y", "issue": "noncanonical_target"},
    ]
    failures = _link_target_failures(rows)
    assert [(row["target_url"], row["issue"], row["issues"]) for row in failures] == [
        (f"{SITE}/x", "redirect_target", ["redirect_target", "non_indexable_target"]),
        (f"{SITE}/y", "noncanonical_target", ["noncanonical_target"]),
    ]


def test_q72_finds_a_trailing_slash_redirect() -> None:
    row = {
        "source_url": f"{SITE}/a",
        "target_url": f"{SITE}/casino",
        "final_url": f"{SITE}/casino/",
        "xpath": "/html/body/a",
        "issue": "redirect_target",
    }
    answers, _audit = _answers({"internal-link-quality": [row]})
    assert (answers["Q72"]["status"], answers["Q72"]["affected_count"]) == ("Issue", 1)
    assert answers["Q22"]["affected_count"] == 1


# --- 384: Q81 gate ----------------------------------------------------------


def test_q81_fails_the_gate_on_response_time_drift() -> None:
    answers, _audit = _answers({}, ttfb_early_median_ms=100.0, ttfb_late_median_ms=180.0)
    assert answers["Q81"]["answer"] == "Yes"
    assert answers["Q81"]["rows"][0]["condition"] == "median TTFB rose over 50% during the run"


def test_q81_is_not_healthy_when_drift_could_not_be_tested() -> None:
    answers, _audit = _answers({}, ttfb_sample_count=5)
    assert (answers["Q81"]["status"], answers["Q81"]["answer"]) == ("Needs validation", "No (partial)")
    assert "Response-time drift not tested" in " ".join(answers["Q81"]["notes"])
    healthy, _audit = _answers({})
    assert healthy["Q81"]["status"] == "Healthy"


# --- 385: discovery provenance --------------------------------------------------


def test_discovery_provenance_is_unavailable_without_run_sitemap_sources() -> None:
    rows = [{"url": f"{SITE}/a", "in_sitemap": False, "internally_linked": True, "issue": "internal_link_only"}]
    answers, _audit = _answers({"discovery-source-provenance": rows}, run_sitemap_source_count=0)
    assert answers["Q82"]["status"] == "Pending"
    answers, _audit = _answers({"discovery-source-provenance": rows}, run_sitemap_source_count=10)
    assert answers["Q82"]["answer"] == "Yes"
