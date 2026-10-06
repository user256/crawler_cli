from __future__ import annotations

import json

from crawler_cli.transport_security import (
    OcspHandshakeObservation,
    classify_ocsp_stapling,
    hsts_preload_assessment,
    parse_strict_transport_security,
    transport_security_report,
)

FULL = "max-age=63072000; includeSubDomains; preload"


def _page(url: str, hsts: str | None, *, status: int = 200, final_url: str | None = None) -> dict[str, object]:
    headers = {"Content-Type": "text/html"}
    if hsts is not None:
        headers["Strict-Transport-Security"] = hsts
    return {
        "url": url,
        "final_url": final_url,
        "kind": "html",
        "final_status_code": status,
        "headers_json": json.dumps(headers),
    }


def _scheme_probe(host: str, status: int, location: str | None) -> dict[str, object]:
    return {
        "record_type": "candidate",
        "candidate_type": "url_variant_observation",
        "variant_kind": "scheme",
        "variant_url": f"http://{host}/",
        "http_status": status,
        "redirect_location": location,
    }


def test_parser_reads_directives_case_insensitively_and_unquotes_max_age():
    policy = parse_strict_transport_security('MAX-AGE="31536000" ; INCLUDESUBDOMAINS;Preload;unknown=1')

    assert policy.valid is True
    assert policy.max_age == 31536000
    assert policy.include_subdomains is True
    assert policy.preload is True
    assert policy.errors == ()


def test_parser_flags_invalid_headers_without_guessing():
    assert parse_strict_transport_security(None).present is False
    assert parse_strict_transport_security("includeSubDomains").errors == ("max_age_missing",)
    assert parse_strict_transport_security("max-age=abc").errors == ("max_age_not_a_non_negative_integer",)
    duplicate = parse_strict_transport_security("max-age=1; max-age=2")
    assert duplicate.valid is False
    assert duplicate.max_age == 1
    assert "duplicate_directive:max-age" in duplicate.errors


def test_parser_uses_first_of_comma_folded_header_instances():
    policy = parse_strict_transport_security("max-age=300, max-age=63072000; includeSubDomains; preload")

    assert policy.header_instances == 2
    assert policy.max_age == 300
    assert policy.preload is False


def test_full_preload_directives_on_apex_with_same_host_redirect_are_eligible():
    assessment = hsts_preload_assessment("example.com", parse_strict_transport_security(FULL), "same_host_https")

    assert assessment.is_apex is True
    assert assessment.hsts_preload_eligible is True
    assert assessment.warnings == ()


def test_missing_directives_produce_specific_warnings():
    assessment = hsts_preload_assessment(
        "example.com", parse_strict_transport_security("max-age=86400"), "same_host_https"
    )

    assert assessment.hsts_preload_eligible is False
    assert assessment.warnings == (
        "max_age_below_31536000",
        "include_subdomains_missing",
        "preload_token_missing",
    )
    missing = hsts_preload_assessment("example.com", parse_strict_transport_security(None), "not_observed")
    assert missing.warnings == ("hsts_header_missing",)


def test_redirect_evidence_controls_eligibility():
    policy = parse_strict_transport_security(FULL)

    unobserved = hsts_preload_assessment("example.com", policy, "not_observed")
    assert unobserved.hsts_preload_eligible is None
    assert unobserved.eligibility_state == "undetermined_http_redirect_not_observed"

    cross_host = hsts_preload_assessment("example.com", policy, "other_https_host")
    assert cross_host.hsts_preload_eligible is False
    assert "http_redirect_must_reach_https_on_same_host_first" in cross_host.warnings

    plain = hsts_preload_assessment("example.com", policy, "not_redirected")
    assert "http_not_redirected_to_https" in plain.warnings


def test_subdomain_is_not_submittable_but_missing_header_is_still_flagged():
    assessment = hsts_preload_assessment("www.example.co.uk", parse_strict_transport_security(None), "not_observed")

    assert assessment.is_apex is False
    assert assessment.registrable_domain == "example.co.uk"
    assert assessment.hsts_preload_eligible is None
    assert assessment.eligibility_state == "not_applicable_not_registrable_domain"
    assert assessment.warnings == ("hsts_header_missing",)


def test_ocsp_classifier_distinguishes_stapled_not_stapled_and_unsupported():
    stapled = classify_ocsp_stapling(
        OcspHandshakeObservation(
            handshake_completed=True,
            status_request_offered=True,
            stapled_response_present=True,
            ocsp_response_status="SUCCESSFUL",
        )
    )
    assert stapled["ocsp_stapling_state"] == "stapled"
    assert stapled["ocsp_stapled"] is True

    not_stapled = classify_ocsp_stapling(
        OcspHandshakeObservation(handshake_completed=True, status_request_offered=True)
    )
    assert not_stapled["ocsp_stapling_state"] == "not_stapled"
    assert not_stapled["ocsp_stapled"] is False

    unsupported = classify_ocsp_stapling(
        OcspHandshakeObservation(
            handshake_completed=True,
            status_request_offered=True,
            server_acknowledged_status_request=False,
        )
    )
    assert unsupported["ocsp_stapling_state"] == "unsupported"


def test_ocsp_absent_evidence_is_never_reported_as_pass_or_fail():
    for observation in (
        None,
        OcspHandshakeObservation(handshake_completed=False, status_request_offered=True, error="timeout"),
        OcspHandshakeObservation(handshake_completed=True, status_request_offered=False),
    ):
        result = classify_ocsp_stapling(observation)
        assert result["ocsp_stapling_state"] == "not_determinable"
        assert result["ocsp_stapled"] is None
        assert "not_a_ttfb_defect_claim" in str(result["seo_impact"])


def test_report_uses_https_root_response_and_scheme_probes():
    rows = transport_security_report(
        [
            _page("https://example.com/deep", "max-age=60"),
            _page("https://example.com/", FULL),
            _page("http://example.com/insecure", FULL),
            _page("https://www.example.com/", None),
            _page("https://blog.example.com/", FULL, status=500),
        ],
        [
            {"record_type": "coverage"},
            _scheme_probe("example.com", 301, "https://example.com/"),
            _scheme_probe("www.example.com", 301, "https://example.com/"),
        ],
    )

    coverage, *hosts = rows
    by_host = {row["host"]: row for row in hosts}
    assert coverage["https_host_count"] == 2
    assert coverage["http_rows_ignored_for_hsts"] == 1
    assert coverage["unusable_rows"] == 1
    assert coverage["hsts_preload_eligible_count"] == 1
    assert coverage["http_redirect_evidence"] == "scheme_variant_probes"
    assert coverage["ocsp_stapling_state_counts"] == {"not_determinable": 2}

    apex = by_host["example.com"]
    assert apex["record_type"] == "observation"
    assert apex["hsts_preload_eligible"] is True
    assert apex["hsts_preload_list_membership"] == "not_queried"
    assert apex["ocsp_stapled"] is None
    assert apex["ocsp_stapling_state"] == "not_determinable"

    www = by_host["www.example.com"]
    assert www["record_type"] == "candidate"
    assert www["warnings"] == ["hsts_header_missing"]
    assert www["http_redirect_state"] == "other_https_host"


def test_report_attributes_headers_to_the_final_response_host():
    coverage, row = transport_security_report(
        [_page("https://example.com/", None, final_url="https://www.example.com/")]
    )

    assert coverage["https_host_count"] == 1
    assert row["host"] == "www.example.com"
    assert coverage["http_redirect_evidence"] == "unavailable_not_probed"
