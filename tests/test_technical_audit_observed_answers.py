from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import pytest

from crawler_cli.__main__ import _run_technical_audit_observations, _run_technical_audit_questions
from crawler_cli.audit_html_signals import HTML_SIGNALS_VERSION, page_html_signals
from crawler_cli.audit_observations import (
    ObservationError,
    attach_observations,
    collection,
    collection_from_exposure_inventory,
    collection_from_html_signals,
    collection_from_render_comparison,
    new_bundle,
    validate_observation_bundle,
)
from crawler_cli.technical_audit import build_technical_audit
from crawler_cli.technical_audit_questions import (
    answer_questions,
    default_site_profile_example_path,
    load_question_registry,
    question_ticket_rows,
)


SITE = "https://example.com"
REGISTRY = load_question_registry()
PROFILE = json.loads(default_site_profile_example_path().read_text(encoding="utf-8"))
HOSTS = PROFILE["nonproduction_hosts"]


def _context(**overrides: object) -> dict[str, object]:
    context: dict[str, object] = {
        "run_status": "complete",
        "completion_state": "complete",
        "snapshot_consistency": "stable",
        "parsed_html_count": 2,
        "html_count": 2,
        "unparsed_html_count": 0,
        "challenged_count": 0,
        "frontier_pending": 0,
    }
    context.update(overrides)
    return context


def _audit(reports: dict[str, list[dict[str, object]]] | None = None, **context: object) -> dict[str, object]:
    return build_technical_audit(crawl_run_id="run-1", reports=reports or {}, run_context=_context(**context))


def _obs(kind: str, records: list[dict[str, object]], coverage: str = "complete") -> dict[str, object]:
    return collection(
        kind,
        records,
        source="fixture",
        scope="fixture population",
        coverage_state=coverage,
        collected_at="2026-10-06T09:00:00Z",
    )


def _answers(
    collections: list[dict[str, object]], profile: dict[str, object] | None = PROFILE, **context: object
) -> dict[str, dict[str, object]]:
    audit = attach_observations(_audit(**context), [new_bundle("run-1", collections)]) if collections else _audit()
    return {str(answer["id"]): answer for answer in answer_questions(audit, REGISTRY, profile)}


def _signals(url: str = f"{SITE}/a", **fields: object) -> dict[str, object]:
    record: dict[str, object] = {
        "url": url,
        "is_https": True,
        "mixed_content": [],
        "insecure_internal_links": [],
        "forms": [],
        "tracking_preloads": [],
        "font_face_rules": 0,
        "font_faces_without_swap": [],
        "font_preloads": 0,
        "head_blocking_stylesheets": [],
        "head_sync_scripts": [],
        "preconnect_origins": [],
        "spam_matches": [],
        "hidden_links": [],
        "hreflang_alternates": [],
        "linked_alternates": [],
        "followed_external_links": [],
        "footer_links": [],
    }
    record.update(fields)
    return record


def _hosts(**staging: object) -> list[dict[str, object]]:
    records: list[dict[str, object]] = [{"host": host, "status": 401, "auth_required": True} for host in HOSTS]
    records[0] = {"host": HOSTS[0], **staging} if staging else records[0]
    return records


FONT = "https://fonts.gstatic.com"
TRACE = {"url": f"{SITE}/reviews/x", "template": "review"}

# question -> (kind, finding records, clean records)
CASES: dict[str, tuple[str, list[dict[str, object]], list[dict[str, object]]]] = {
    "Q5": (
        "html-signals",
        [_signals(mixed_content=[{"tag": "img", "attribute": "src", "url": "http://cdn.example.com/a.png"}])],
        [_signals(), _signals("http://example.com/plain", is_https=False)],
    ),
    "Q92": (
        "html-signals",
        [
            _signals(
                forms=[{"action": "http://example.com/s", "resolved_action": "http://example.com/s", "insecure": True}]
            )
        ],
        [_signals(forms=[{"action": "/s", "resolved_action": f"{SITE}/s", "insecure": False}])],
    ),
    "Q65": (
        "html-signals",
        [_signals(tracking_preloads=["https://www.googletagmanager.com/gtm.js"])],
        [_signals()],
    ),
    "Q67": (
        "html-signals",
        [_signals(font_faces_without_swap=[{"family": "Brand", "font_display": None}])],
        [_signals(font_preloads=2)],
    ),
    "Q86": (
        "html-signals",
        [_signals(head_sync_scripts=["https://example.com/app.js"])],
        [_signals(head_blocking_stylesheets=["a.css", "b.css", "c.css"])],
    ),
    "Q33": ("html-signals", [_signals(spam_matches=[{"category": "pharma", "term": "viagra"}])], [_signals()]),
    "Q45": (
        "html-signals",
        [_signals(hreflang_alternates=[f"{SITE}/de/a"])],
        [_signals(hreflang_alternates=[f"{SITE}/de/a"], linked_alternates=[f"{SITE}/de/a"]), _signals("/b")],
    ),
    "Q43": (
        "html-signals",
        [_signals(f"{SITE}/{name}", followed_external_links=["https://network.example/x"]) for name in "abc"],
        [_signals(followed_external_links=["https://example-group.com/x"]), _signals(f"{SITE}/b")],
    ),
    "Q85": (
        "render-parity",
        [{"url": f"{SITE}/a", "state": "complete", "findings": [{"code": "canonical_changed", "field": "canonical"}]}],
        [
            {
                "url": f"{SITE}/a",
                "state": "complete",
                "findings": [{"code": "metadata_render_dependency", "field": "meta_description"}],
            }
        ],
    ),
    "Q46": (
        "render-parity",
        [
            {
                "url": f"{SITE}/news/x",
                "state": "complete",
                "footer": {"raw_links": [], "rendered_links": [f"{SITE}/about"]},
            }
        ],
        [
            {
                "url": f"{SITE}/news/x",
                "state": "complete",
                "footer": {"raw_links": [f"{SITE}/about/"], "rendered_links": [f"{SITE}/about"]},
            }
        ],
    ),
    "Q38": (
        "listing-controls",
        [{"url": f"{SITE}/casino/slots", "control": "New", "changes_listing": True, "crawlable_href": None}],
        [{"url": f"{SITE}/casino/slots", "control": "New", "changes_listing": True, "crawlable_href": "/casino/new"}],
    ),
    "Q95": (
        "mobile-render",
        [{"url": f"{SITE}/", "overlay_viewport_share": 0.7, "overlay_kind": "promo"}],
        [{"url": f"{SITE}/", "overlay_viewport_share": 0.2, "raw_primary_words": 500, "rendered_primary_words": 480}],
    ),
    "Q35": (
        "render-trace",
        [{**TRACE, "api_request_count": 60}],
        [{**TRACE, "api_request_count": 10, "uncacheable_api_urls": []}],
    ),
    "Q29": (
        "render-trace",
        [{**TRACE, "lcp_ms": 4000, "cls": 0.02, "inp_ms": 100}],
        [{**TRACE, "lcp_ms": 1200, "cls": 0.02, "inp_ms": 100}],
    ),
    "Q64": (
        "render-trace",
        [{**TRACE, "critical_origins": [FONT], "preconnect_origins": []}],
        [{**TRACE, "critical_origins": [FONT, SITE], "preconnect_origins": [FONT]}],
    ),
    "Q68": (
        "render-trace",
        [
            {
                **TRACE,
                "lcp_element": {"type": "image", "loading": "lazy", "fetchpriority": "high", "width": 1, "height": 1},
            }
        ],
        [{**TRACE, "lcp_element": {"type": "image", "fetchpriority": "high", "width": 1, "height": 1}}],
    ),
    "Q69": (
        "render-trace",
        [{**TRACE, "lcp_element": {"type": "image", "is_background": True}}],
        [{**TRACE, "lcp_element": {"type": "text"}}],
    ),
    "Q66": (
        "image-resources",
        [{"image_url": f"{SITE}/a.jpg", "content_type": "image/jpeg", "page_url": f"{SITE}/a"}],
        [
            {"image_url": f"{SITE}/a.webp", "content_type": "image/webp"},
            {"image_url": "x.svg", "content_type": "image/svg+xml"},
        ],
    ),
    "Q25": (
        "locale-probe",
        [{"url": f"{SITE}/", "variant": "accept-language:de", "baseline_status": 200, "variant_status": 302}],
        [{"url": f"{SITE}/", "variant": "accept-language:de", "baseline_status": 200, "variant_status": 200}],
    ),
    "Q27": ("host-probe", _hosts(status=200, noindex=False), _hosts()),
    "Q77": (
        "host-probe",
        _hosts(status=200, noindex=False, canonical_to_main_host=False, robots_blocked=False),
        _hosts(status=200, noindex=False, canonical_to_main_host=True),
    ),
    "Q28": (
        "external-link-recheck",
        [{"source_url": f"{SITE}/a", "target_url": "https://other.example/x", "status": 404}],
        [
            {"source_url": f"{SITE}/a", "target_url": "https://other.example/x", "status": 200},
            {
                "source_url": f"{SITE}/a",
                "target_url": "https://partner-casino.example/go",
                "status": 200,
                "rel": "sponsored",
            },
        ],
    ),
    "Q63": (
        "tls-probe",
        [{"host": "example.com", "hsts_header": "max-age=300", "preload_status": "preloaded", "ocsp_stapled": True}],
        [
            {
                "host": "example.com",
                "hsts_header": "max-age=31536000; includeSubDomains; preload",
                "preload_status": "preloaded",
                "ocsp_stapled": True,
            }
        ],
    ),
    "Q102": (
        "utility-path-probe",
        [{"url": f"{SITE}/wp-admin/", "path_class": "protected", "status": 200, "exposes_content": True}],
        [
            {"url": f"{SITE}/wp-admin/", "path_class": "protected", "status": 302, "exposes_content": False},
            {
                "url": f"{SITE}/preview/",
                "path_class": "public-utility",
                "status": 200,
                "noindex": True,
                "robots_blocked": False,
            },
        ],
    ),
    "Q96": (
        "robots-txt",
        [{"host": "example.com", "status": 200, "body": "User-agent: *\nAllow: /\n"}],
        [{"host": "example.com", "status": 200, "body": "User-agent: CCBot\nDisallow: /\n"}],
    ),
    "Q18": (
        "google-render-inspection",
        [
            {
                "url": f"{SITE}/reviews/x",
                "template": "review",
                "tool": "url-inspection",
                "primary_content_present": False,
            }
        ],
        [{"url": f"{SITE}/reviews/x", "template": "review", "tool": "url-inspection", "primary_content_present": True}],
    ),
    "Q31": (
        "verified-google-fetch",
        [{"url": f"{SITE}/a", "content_differs": True, "google_fetch_method": "url-inspection live test"}],
        [{"url": f"{SITE}/a", "content_differs": False, "links_differ": False, "directives_differ": False}],
    ),
    "Q50": (
        "competitor-topic-gap",
        [{"topic": "RTP explained", "site_covers": False, "competitors_covering": 3}],
        [{"topic": "RTP explained", "site_covers": True, "competitors_covering": 3}],
    ),
}
# Answers that test only part of the question can never be Healthy.
SCOPE_LIMITED = {"Q67"}


def _entry(qid: str) -> dict[str, object]:
    return next(entry for entry in REGISTRY["questions"] if entry["id"] == qid)


def test_every_stream_c_question_has_an_answerer_and_cases() -> None:
    from crawler_cli.technical_audit_questions import ANSWERERS

    stream_c = {
        "Q18", "Q31", "Q38", "Q45", "Q46", "Q95", "Q30", "Q50", "Q85", "Q35", "Q5", "Q25", "Q27", "Q28", "Q33",
        "Q39", "Q43", "Q77", "Q92", "Q102", "Q104", "Q29", "Q63", "Q64", "Q65", "Q66", "Q67", "Q68", "Q69",
        "Q86", "Q96",
    }  # fmt: skip
    assert stream_c - {"Q104"} <= set(ANSWERERS)
    assert stream_c - {"Q30", "Q39", "Q104"} == set(CASES)
    assert {_entry(qid)["group"] for qid in ("Q18", "Q31", "Q50")} == {"supplied-input"}
    assert _entry("Q104")["group"] == "external"


@pytest.mark.parametrize("qid", sorted(CASES))
def test_finding_is_reported_with_provenance(qid: str) -> None:
    kind, finding, _clean = CASES[qid]
    answer = _answers([_obs(kind, finding)])[qid]
    heuristic = _entry(qid)["group"] == "heuristic"

    assert answer["answer"] == "Yes", answer["notes"]
    assert answer["status"] == ("Needs validation" if heuristic else "Issue"), answer["notes"]
    assert answer["ticket"] is (not heuristic)
    row = answer["rows"][0]
    assert (row["observation_source"], row["observed_at"], row["coverage"]) == (
        "fixture",
        "2026-10-06T09:00:00Z",
        "complete",
    )
    assert answer["denominator"] and answer["affected_count"] == len(answer["rows"])
    assert any("Observations: fixture: fixture population" in note for note in answer["notes"])


@pytest.mark.parametrize("qid", sorted(CASES))
def test_clean_complete_population_is_healthy(qid: str) -> None:
    kind, _finding, clean = CASES[qid]
    answer = _answers([_obs(kind, clean)])[qid]

    if qid in SCOPE_LIMITED:
        assert (answer["status"], answer["answer"]) == ("Needs validation", "No (partial)")
    else:
        assert (answer["status"], answer["answer"]) == ("Healthy", "No"), answer["notes"]
    assert answer["rows"] == [] and answer["ticket"] is False


@pytest.mark.parametrize("qid", sorted(CASES))
def test_partial_coverage_is_never_healthy(qid: str) -> None:
    kind, finding, clean = CASES[qid]
    clean_answer = _answers([_obs(kind, clean, coverage="partial")])[qid]
    assert (clean_answer["status"], clean_answer["answer"]) == ("Needs validation", "No (partial)")

    finding_answer = _answers([_obs(kind, finding, coverage="partial")])[qid]
    assert finding_answer["status"] == "Needs validation" and finding_answer["answer"] == "Yes"


@pytest.mark.parametrize("qid", sorted(CASES))
def test_missing_observations_leave_the_question_pending(qid: str) -> None:
    answer = _answers([])[qid]

    assert answer["status"] == "Pending" and answer["answer"] == ""
    assert answer["rows"] == [] and answer["ticket"] is False and answer["affected_count"] is None


# Q50 and Q66 identity fields are everything their rules read.
@pytest.mark.parametrize("qid", sorted(set(CASES) - {"Q50", "Q66"}))
def test_records_without_the_rule_fields_are_untested(qid: str) -> None:
    kind, finding, _clean = CASES[qid]
    from crawler_cli.audit_observations import OBSERVATION_KINDS

    identity = OBSERVATION_KINDS[kind][1]
    bare = [{key: record[key] for key in identity} for record in finding]
    answer = _answers([_obs(kind, bare)])[qid]
    assert answer["status"] == "Pending", answer["notes"]


@pytest.mark.parametrize("qid", ["Q38", "Q43", "Q46", "Q27", "Q77"])
def test_missing_profile_key_leaves_profile_questions_pending(qid: str) -> None:
    kind, finding, _clean = CASES[qid]
    answer = _answers([_obs(kind, finding)], profile=None)[qid]
    assert answer["status"] == "Pending" and "site profile lacks" in " ".join(answer["notes"])


def test_failed_run_gate_downgrades_observed_findings() -> None:
    kind, finding, _clean = CASES["Q85"]
    answer = _answers([_obs(kind, finding)], completion_state="running", frontier_pending=3)["Q85"]
    assert answer["status"] == "Needs validation" and answer["answer"] == "Yes"


def test_heuristic_findings_never_draft_tickets() -> None:
    collections = [_obs(kind, finding) for kind, finding, _clean in CASES.values()]
    audit = attach_observations(_audit(), [new_bundle("run-1", collections)])
    answers = answer_questions(audit, REGISTRY, PROFILE)
    tickets = question_ticket_rows(audit, REGISTRY, answers)
    ticketed = {ticket["question_id"] for ticket in tickets}

    heuristic = {str(entry["id"]) for entry in REGISTRY["questions"] if entry["group"] == "heuristic"}
    assert not ticketed & heuristic
    assert {"Q5", "Q18", "Q85", "Q96"} <= ticketed
    q66 = next(ticket for ticket in tickets if ticket["question_id"] == "Q66")
    assert q66["Ticket Classification"] == "Improvement" and q66["Priority"] == "Low"


def test_template_questions_count_templates_not_pages() -> None:
    finding = [
        {**TRACE, "url": f"{SITE}/reviews/{name}", "lcp_element": {"type": "image", "is_background": True}}
        for name in ("a", "b", "c")
    ]
    clean = {"url": f"{SITE}/news/x", "lcp_element": {"type": "text"}}
    answer = _answers([_obs("render-trace", [*finding, clean])])["Q69"]

    assert (answer["affected_count"], answer["denominator"]) == (1, 2)
    assert answer["rows"][0]["template"] == "review" and answer["rows"][0]["affected_pages"] == 3


def test_q45_share_threshold_uses_pages_with_alternates() -> None:
    linked = _signals(hreflang_alternates=[f"{SITE}/de/"], linked_alternates=[f"{SITE}/de/"])
    pages = [_signals(f"{SITE}/x", hreflang_alternates=[f"{SITE}/de/x"]), *[linked] * 9, _signals(f"{SITE}/y")]
    answer = _answers([_obs("html-signals", pages)])["Q45"]
    # One unlinked page of ten with alternates is 10%, below the 20% threshold.
    assert (answer["status"], answer["affected_count"], answer["denominator"]) == ("Healthy", 1, 10)


def test_q96_without_declared_policy_reports_the_inventory_for_review() -> None:
    profile = {key: value for key, value in PROFILE.items() if key != "ai_crawler_policy"}
    robots = [
        {"host": "example.com", "status": 200, "body": "User-agent: GPTBot\nDisallow: /\n", "llms_txt_status": 404}
    ]
    answer = _answers([_obs("robots-txt", robots)], profile=profile)["Q96"]

    assert (answer["status"], answer["answer"]) == ("Needs validation", "No (partial)")
    notes = " ".join(answer["notes"])
    assert "example.com GPTBot disallow" in notes and "example.com CCBot allow" in notes
    assert "/llms.txt 404 (reported only; not a defect)" in notes


def test_q96_unavailable_robots_allows_everything_and_5xx_is_untested() -> None:
    answer = _answers([_obs("robots-txt", [{"host": "example.com", "status": 404}])])["Q96"]
    assert answer["status"] == "Issue" and answer["rows"][0]["user_agent"] == "CCBot"

    answer = _answers([_obs("robots-txt", [{"host": "example.com", "status": 503}])])["Q96"]
    assert answer["status"] == "Pending" and "unavailable or unread for: example.com" in " ".join(answer["notes"])


def test_q27_unprobed_profile_hosts_block_a_healthy_answer() -> None:
    answer = _answers([_obs("host-probe", _hosts()[:2])])["Q27"]
    assert (answer["status"], answer["answer"]) == ("Needs validation", "No (partial)")
    assert "Profile hosts not probed: preview.example.com, cache.example.com" in " ".join(answer["notes"])


def test_exposure_inventory_reachable_host_is_a_candidate_for_review() -> None:
    artifact = {
        "schema_version": "crawler-cli/exposure-inventory/1",
        "observed_at": "2026-10-06T08:00:00+00:00",
        "candidates": [
            {"hostname": "staging.example.com", "state": "reachable", "http": {"status": 200, "x_robots_tag": None}},
            {"hostname": "dev.example.com", "state": "nxdomain", "http": {"status": None}},
        ],
    }
    host_probe = collection_from_exposure_inventory(artifact)
    assert host_probe["coverage_state"] == "partial" and host_probe["collected_at"] == "2026-10-06T08:00:00+00:00"

    answer = _answers([host_probe])["Q27"]
    assert answer["status"] == "Needs validation" and answer["ticket"] is False
    assert answer["rows"][0]["finding"] == "200 response without authentication; not read: noindex"


def test_q104_stays_pending_even_with_a_review_record() -> None:
    review = {
        "review_type": "gsc-hosts",
        "reviewed_at": "2026-10-06",
        "date_range": "2026-07-01/2026-09-30",
        "permitted_hosts": ["example.com"],
        "unapproved_hosts": ["staging.example.com"],
    }
    collections = [_obs("search-host-review", [review])]
    audit = attach_observations(_audit(), [new_bundle("run-1", collections)])
    answers = answer_questions(audit, REGISTRY, PROFILE)
    answer = next(item for item in answers if item["id"] == "Q104")

    assert answer["status"] == "Pending" and answer["ticket"] is False
    assert answer["notes"] == ["Outside crawler_cli: gsc, external-api"]
    assert "Q104" not in {ticket["question_id"] for ticket in question_ticket_rows(audit, REGISTRY, answers)}


# --- answerers that read audit checks -----------------------------------------


def _search_record(**fields: object) -> dict[str, object]:
    return {"url": f"{SITE}/a", "source": "gsc", "export_date": "2026-10-01", "is_issue": False, **fields}


def test_q30_supplied_search_evidence() -> None:
    def answer(rows: list[dict[str, object]] | None) -> dict[str, object]:
        reports = {"supplied-search-evidence": rows} if rows is not None else {}
        return next(item for item in answer_questions(_audit(reports), REGISTRY) if item["id"] == "Q30")

    finding = answer(
        [_search_record(is_issue=True, issue_reason="Google reports Crawled - not indexed."), _search_record()]
    )
    assert (finding["status"], finding["affected_count"], finding["denominator"], finding["ticket"]) == (
        "Issue",
        1,
        2,
        True,
    )
    assert (answer([_search_record()])["status"], answer([_search_record()])["answer"]) == ("Healthy", "No")
    assert answer(None)["status"] == "Pending" and "supplied-search-evidence not collected" in answer(None)["notes"][1]
    partial = next(
        item
        for item in answer_questions(
            _audit({"supplied-search-evidence": [_search_record()]}, completion_state="partial"), REGISTRY
        )
        if item["id"] == "Q30"
    )
    assert partial["status"] == "Needs validation"


def test_q39_heading_links_scope_is_explicit() -> None:
    def answer(rows: list[dict[str, object]] | None) -> dict[str, object]:
        reports = {"internal-link-quality": rows} if rows is not None else {}
        return next(item for item in answer_questions(_audit(reports), REGISTRY) if item["id"] == "Q39")

    heading = {
        "issue": "error_target",
        "source_url": f"{SITE}/a",
        "target_url": f"{SITE}/x",
        "xpath": "/html/body/h2/a",
    }
    body = {**heading, "xpath": "/html/body/p/a"}
    found = answer([heading, body])
    assert (found["status"], found["affected_count"]) == ("Issue", 1)
    # Redirecting and non-canonical heading targets are not tested yet, so no rows is not Healthy.
    clean = answer([body])
    assert (clean["status"], clean["answer"]) == ("Needs validation", "No (partial)")
    assert answer(None)["status"] == "Pending"


# --- bundle contract and adapters --------------------------------------------


def test_bundle_contract_rejects_missing_provenance_and_identity() -> None:
    bundle = new_bundle("run-1", [_obs("render-trace", [{"url": f"{SITE}/a"}])])
    collection_ = bundle["collections"][0]
    for key, value, message in (
        ("source", "", "source is required"),
        ("collected_at", "yesterday", "collected_at must be an ISO 8601 timestamp"),
        ("coverage_state", "mostly", "coverage_state must be one of"),
        ("records", [{"lcp_ms": 1}], "record 1: missing url"),
        ("kind", "telepathy", "unknown kind 'telepathy'"),
    ):
        broken = {**bundle, "collections": [{**collection_, key: value}]}
        with pytest.raises(ObservationError, match=message):
            validate_observation_bundle(broken)
    with pytest.raises(ObservationError, match="crawl_run_id is required"):
        validate_observation_bundle({**bundle, "crawl_run_id": ""})


def test_bundle_from_another_run_is_refused() -> None:
    with pytest.raises(ObservationError, match="for crawl run 'run-2', the audit is for 'run-1'"):
        attach_observations(_audit(), [new_bundle("run-2", [])])


def _comparison(run_id: str | None = "run-1", *, capped: bool = False, state: str = "complete") -> dict[str, object]:
    source = {"source_crawl_run": {"run_id": run_id}} if run_id else {}
    return {
        "schema_version": "crawler-cli/render-comparison/1",
        "observed_at": "2026-10-06T07:00:00+00:00",
        "input": {"input_capped": capped, "candidate_count": 1, "sampling_basis": "strata", **source},
        "results": [{"url": f"{SITE}/a", "state": state, "findings": []}],
    }


def test_render_comparison_adapter_checks_run_and_coverage() -> None:
    assert collection_from_render_comparison(_comparison(), "run-1")["coverage_state"] == "complete"
    assert collection_from_render_comparison(_comparison(capped=True), "run-1")["coverage_state"] == "partial"
    assert collection_from_render_comparison(_comparison(state="inconclusive"), "run-1")["coverage_state"] == "partial"
    with pytest.raises(ObservationError, match="sampled from crawl run none"):
        collection_from_render_comparison(_comparison(None), "run-1")


def test_html_signals_flow_from_stored_html_to_an_answer() -> None:
    html = '<html><head></head><body><img src="http://cdn.example.com/a.png"><form action="/s"></form></body></html>'
    records = [page_html_signals(f"{SITE}/a", html), page_html_signals(f"{SITE}/b", "<p>ok</p>")]
    complete = collection_from_html_signals(records, run_context=_context(), version=HTML_SIGNALS_VERSION)
    partial = collection_from_html_signals(records[:1], run_context=_context(), version=HTML_SIGNALS_VERSION)
    assert (complete["coverage_state"], partial["coverage_state"]) == ("complete", "partial")

    answers = _answers([complete])
    assert (answers["Q5"]["status"], answers["Q5"]["affected_count"], answers["Q5"]["denominator"]) == ("Issue", 1, 2)
    assert (answers["Q92"]["status"], answers["Q92"]["denominator"]) == ("Healthy", 1)


def _cli_args(tmp_path: Path, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "crawl_run_id": "run-1",
        "out": str(tmp_path / "observations.json"),
        "html_signals": False,
        "site_host": None,
        "render_comparison": None,
        "exposure_inventory": None,
        "robots_txt": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_cli_builds_a_bundle_and_the_question_runner_consumes_it(tmp_path: Path) -> None:
    comparison = tmp_path / "renders.json"
    comparison.write_text(json.dumps(_comparison()), encoding="utf-8")
    robots = tmp_path / "robots.txt"
    robots.write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    args = _cli_args(tmp_path, render_comparison=[str(comparison)], robots_txt=[f"example.com={robots}"])
    assert asyncio.run(_run_technical_audit_observations(args)) == 0

    audit_path = tmp_path / "audit.json"
    audit_path.write_text(json.dumps(_audit()), encoding="utf-8")
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(PROFILE), encoding="utf-8")
    out = tmp_path / "answers.json"
    question_args = argparse.Namespace(
        audit=str(audit_path),
        out=str(out),
        site_profile=str(profile_path),
        questions=None,
        ticket_language=None,
        observations=[args.out],
        google_sheets_template=None,
        google_sheets_title=None,
        google_sheets_folder=None,
        google_sheets_credentials=None,
    )
    assert _run_technical_audit_questions(question_args) == 0
    answers = {item["id"]: item for item in json.loads(out.read_text(encoding="utf-8"))["answers"]}
    assert answers["Q85"]["status"] == "Healthy"
    assert answers["Q96"]["status"] == "Issue" and answers["Q96"]["rows"][0]["user_agent"] == "CCBot"

    other = tmp_path / "other.json"
    other.write_text(json.dumps(new_bundle("run-9", [])), encoding="utf-8")
    question_args.observations = [str(other)]
    assert _run_technical_audit_questions(question_args) != 0


def test_cli_refuses_a_render_comparison_from_another_run(tmp_path: Path) -> None:
    comparison = tmp_path / "renders.json"
    comparison.write_text(json.dumps(_comparison("run-2")), encoding="utf-8")
    assert asyncio.run(_run_technical_audit_observations(_cli_args(tmp_path, render_comparison=[str(comparison)]))) != 0
    assert asyncio.run(_run_technical_audit_observations(_cli_args(tmp_path))) != 0


def test_fallback_template_grouping_ignores_locale_prefixes() -> None:
    pages = [_signals(f"{SITE}/{locale}/casino/live", head_sync_scripts=["app.js"]) for locale in ("ar", "pt-br", "de")]
    answer = _answers([_obs("html-signals", [*pages, _signals(f"{SITE}/casino")])], profile=None)["Q86"]
    assert [row["template"] for row in answer["rows"]] == ["/casino/"]
    assert answer["rows"][0]["affected_pages"] == 3 and answer["denominator"] == 1
