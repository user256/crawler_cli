"""Regression tests for the Stream C QA tickets 386-391.

Each observation record here is missing a field the rule depends on, or
carries a value the answerer used to read as something it is not.  The
contract: missing or partial evidence never becomes Healthy, and an Issue
needs evidence that proves the defect.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from crawler_cli.audit_observations import (
    ObservationError,
    attach_observations,
    collection,
    collection_from_render_comparison,
    new_bundle,
)
from crawler_cli.technical_audit import build_technical_audit
from crawler_cli.technical_audit_questions import (
    answer_questions,
    default_site_profile_example_path,
    load_question_registry,
)


SITE = "https://example.com"
REGISTRY = load_question_registry()
PROFILE = json.loads(default_site_profile_example_path().read_text(encoding="utf-8"))
STAGING = PROFILE["nonproduction_hosts"][0]


def _context() -> dict[str, object]:
    return {
        "run_status": "complete",
        "completion_state": "complete",
        "snapshot_consistency": "stable",
        "parsed_html_count": 2,
        "html_count": 2,
        "unparsed_html_count": 0,
        "challenged_count": 0,
        "frontier_pending": 0,
        "rate_limited_count": 0,
        "ttfb_sample_count": 100,
        "ttfb_early_median_ms": 120.0,
        "ttfb_late_median_ms": 130.0,
    }


def _audit() -> dict[str, object]:
    return build_technical_audit(crawl_run_id="run-1", reports={}, run_context=_context())


def _obs(
    kind: str, records: list[dict[str, object]], *, source: str = "fixture", collected_at: str = "2026-10-06T09:00:00Z"
) -> dict[str, object]:
    return collection(
        kind, records, source=source, scope="fixture population", coverage_state="complete", collected_at=collected_at
    )


def _answer(qid: str, collections: list[dict[str, object]], profile: dict[str, object] | None = PROFILE) -> dict:
    audit = attach_observations(_audit(), [new_bundle("run-1", collections)])
    return next(answer for answer in answer_questions(audit, REGISTRY, profile) if answer["id"] == qid)


def _below_healthy(answer: dict) -> None:
    assert answer["status"] in {"Needs validation", "Pending"}, answer["notes"]
    assert answer["ticket"] is False and answer["rows"] == []


# --- ticket 386: a field that was never recorded is untested -----------------


def test_q28_affiliate_link_without_a_rel_field_is_untested() -> None:
    link = {"source_url": f"{SITE}/a", "target_url": "https://partner-casino.example/go", "status": 200}
    answer = _answer("Q28", [_obs("external-link-recheck", [link])])

    _below_healthy(answer)
    assert "1 external-link-recheck records lack the fields this rule needs" in " ".join(answer["notes"])


def test_q28_affiliate_link_with_a_known_defect_is_still_reported() -> None:
    link = {"source_url": f"{SITE}/a", "target_url": "https://partner-casino.example/go", "status": 404}
    answer = _answer("Q28", [_obs("external-link-recheck", [link])])

    assert (answer["status"], answer["answer"]) == ("Issue", "Yes")
    assert answer["rows"][0]["finding"] == "returns 404"


def test_q31_single_known_flag_is_not_a_full_comparison() -> None:
    answer = _answer("Q31", [_obs("verified-google-fetch", [{"url": f"{SITE}/a", "content_differs": False}])])

    _below_healthy(answer)
    assert "1 verified-google-fetch records lack the fields this rule needs" in " ".join(answer["notes"])


def test_q31_known_difference_is_reported_even_when_other_flags_are_unknown() -> None:
    answer = _answer("Q31", [_obs("verified-google-fetch", [{"url": f"{SITE}/a", "content_differs": True}])])

    assert (answer["status"], answer["answer"]) == ("Issue", "Yes")
    assert answer["rows"][0]["finding"] == "content differ from the visitor fetch"


def test_q25_probe_without_location_or_content_fields_is_untested() -> None:
    probe = {"url": f"{SITE}/", "variant": "accept-language:de", "baseline_status": 200, "variant_status": 200}
    answer = _answer("Q25", [_obs("locale-probe", [probe])])

    _below_healthy(answer)
    assert "1 probes lack a baseline or variant status, Location or content comparison" in " ".join(answer["notes"])


def test_q25_probe_with_every_field_recorded_is_healthy() -> None:
    probe = {
        "url": f"{SITE}/",
        "variant": "accept-language:de",
        "baseline_status": 200,
        "variant_status": 200,
        "baseline_location": None,
        "variant_location": None,
        "primary_content_differs": False,
    }
    answer = _answer("Q25", [_obs("locale-probe", [probe])])
    assert (answer["status"], answer["answer"]) == ("Healthy", "No"), answer["notes"]


def test_q25_status_change_is_reported_even_without_the_other_fields() -> None:
    probe = {"url": f"{SITE}/", "variant": "accept-language:de", "baseline_status": 200, "variant_status": 302}
    answer = _answer("Q25", [_obs("locale-probe", [probe])])

    assert (answer["status"], answer["answer"]) == ("Issue", "Yes")
    assert answer["rows"][0]["finding"] == "accept-language:de: status 200->302"


# --- ticket 387: Q102 needs both controls known before it raises ---------------


@pytest.mark.parametrize(
    "fields",
    [
        {"noindex": False},
        {"robots_blocked": False},
        {"noindex": True},
        {"robots_blocked": True},
        {"noindex": False, "robots_blocked": None},
    ],
)
def test_q102_public_utility_path_with_one_unknown_control_is_untested(fields: dict[str, object]) -> None:
    probe = {"url": f"{SITE}/preview/", "path_class": "public-utility", "status": 200, **fields}
    answer = _answer("Q102", [_obs("utility-path-probe", [probe])])

    _below_healthy(answer)
    assert answer["status"] == "Pending"


def test_q102_public_utility_path_with_both_controls_absent_is_an_issue() -> None:
    probe = {"url": f"{SITE}/preview/", "path_class": "public-utility", "status": 200, "noindex": False}
    answer = _answer("Q102", [_obs("utility-path-probe", [{**probe, "robots_blocked": False}])])

    assert (answer["status"], answer["ticket"]) == ("Issue", True)
    assert answer["rows"][0]["finding"] == "public utility URL has no noindex or robots.txt control"


# --- ticket 388: a robots.txt without a readable body is unknown ---------------


@pytest.mark.parametrize("record", [{"status": 301}, {"status": 302, "body": "<html>moved</html>"}, {"status": 403}])
def test_q96_robots_without_a_readable_body_is_unknown(record: dict[str, object]) -> None:
    answer = _answer("Q96", [_obs("robots-txt", [{"host": "example.com", **record}])])

    assert answer["status"] == "Pending", answer["notes"]
    assert "unavailable or unread for: example.com" in " ".join(answer["notes"])


def test_q96_definitive_404_still_means_no_robots_file() -> None:
    answer = _answer("Q96", [_obs("robots-txt", [{"host": "example.com", "status": 404}])])
    assert answer["status"] == "Issue" and answer["rows"][0]["robots_verdict"] == "allow"


# --- ticket 389: the observed answerers import on their own -------------------


def test_observed_answerers_import_in_a_fresh_interpreter() -> None:
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = {**os.environ, "PYTHONPATH": src + os.pathsep + os.environ.get("PYTHONPATH", "")}
    code = "from crawler_cli.technical_audit_observed_answers import OBSERVED_ANSWERERS; print(len(OBSERVED_ANSWERERS))"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120)

    assert result.returncode == 0, result.stderr
    assert int(result.stdout.strip()) > 0


def test_question_runner_registers_the_observed_answerers() -> None:
    from crawler_cli.technical_audit_observed_answers import OBSERVED_ANSWERERS
    from crawler_cli.technical_audit_questions import ANSWERERS

    assert set(OBSERVED_ANSWERERS) <= set(ANSWERERS)


# --- ticket 390: compare-renders output carries no footer fields --------------


def test_q46_stays_pending_on_compare_renders_output_without_footer_fields() -> None:
    payload = {
        "schema_version": "crawler-cli/render-comparison/1",
        "observed_at": "2026-10-06T07:00:00+00:00",
        "input": {
            "input_capped": False,
            "candidate_count": 1,
            "sampling_basis": "strata",
            "source_crawl_run": {"run_id": "run-1"},
        },
        "results": [{"url": f"{SITE}/news/x", "state": "complete", "findings": [], "signals": {}}],
    }
    answer = _answer("Q46", [collection_from_render_comparison(payload, "run-1")])

    assert answer["status"] == "Pending" and answer["rows"] == [] and answer["ticket"] is False
    assert "1 render-parity records lack the fields this rule needs" in " ".join(answer["notes"])


# --- ticket 391: observed-answer edge cases ----------------------------------


def test_q27_host_with_unknown_content_type_is_a_candidate_for_review_not_an_issue() -> None:
    probe = {"host": STAGING, "status": 200, "noindex": False}
    answer = _answer("Q27", [_obs("host-probe", [probe])])

    assert (answer["status"], answer["ticket"]) == ("Needs validation", False)
    assert answer["rows"][0]["finding"] == "200 response without authentication; not read: content_type"


def test_q27_html_host_without_mitigation_is_still_an_issue() -> None:
    hosts = [{"host": host, "status": 401, "auth_required": True} for host in PROFILE["nonproduction_hosts"]]
    hosts[0] = {"host": STAGING, "status": 200, "noindex": False, "content_type": "text/html; charset=utf-8"}
    answer = _answer("Q27", [_obs("host-probe", hosts)])

    assert (answer["status"], answer["ticket"]) == ("Issue", True)


def test_q43_rows_carry_the_provenance_of_the_page_that_links() -> None:
    first = _obs("html-signals", [{"url": f"{SITE}/a", "followed_external_links": []}], source="scan-1")
    second = _obs(
        "html-signals",
        [
            {"url": f"{SITE}/b", "followed_external_links": ["https://network.example/x"]},
            {"url": f"{SITE}/c", "followed_external_links": ["https://network.example/x"]},
        ],
        source="scan-2",
        collected_at="2026-10-06T10:00:00Z",
    )
    answer = _answer("Q43", [first, second])

    assert answer["rows"][0]["target_url"] == "https://network.example/x"
    assert (answer["rows"][0]["observation_source"], answer["rows"][0]["observed_at"]) == (
        "scan-2",
        "2026-10-06T10:00:00Z",
    )


@pytest.mark.parametrize("collections", ["not-a-list", {"kind": "html-signals"}, 7, [1, 2]])
def test_attach_observations_rejects_malformed_prior_collections(collections: object) -> None:
    audit = {**_audit(), "observations": {"crawl_run_id": "run-1", "collections": collections}}
    with pytest.raises(ObservationError, match="collections"):
        attach_observations(audit, [new_bundle("run-1", [])])
