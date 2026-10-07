"""The re-attached probes (tickets 258-260, 264) feed the question runner as observation kinds."""

from __future__ import annotations

from types import SimpleNamespace

from crawler_cli.__main__ import _build_parser
from crawler_cli.audit_observation_adapters import (
    llms_txt_probe_by_host,
    llms_txt_status_by_host,
    locale_probe_records,
    robots_txt_record,
    tls_probe_records,
)
from crawler_cli.audit_observations import attach_observations, collection, new_bundle
from crawler_cli.technical_audit import build_technical_audit
from crawler_cli.technical_audit_questions import answer_questions, load_question_registry

REGISTRY = load_question_registry()


def _probe(variant: str, status: int, *, location: str | None = None, sha: str | None = "a", final: int = 200):
    return {
        "record_type": "observation",
        "observation_type": "accept_language_probe",
        "target_url": "https://example.com/",
        "variant": variant,
        "outcome": "resolved",
        "final_status": final,
        "html_lang": "en",
        "body_sha256": sha,
        "primary_content_sha256": sha,
        "primary_content_basis": "main_visible_text",
        "redirect_chain": [{"url": "https://example.com/", "status": status, "location": location}],
    }


def test_locale_probe_records_compare_each_variant_with_the_no_header_baseline() -> None:
    evidence = [
        {"record_type": "coverage", "target_count": 1},
        _probe("none", 200),
        _probe("none-repeat", 200),
        _probe("de", 302, location="https://example.com/de/", sha="b"),
        _probe("es", 200, sha="a"),
        {"record_type": "observation", "observation_type": "neutral_access", "target_url": "https://example.com/"},
    ]
    records = locale_probe_records(evidence)
    assert [(row["variant"], row["baseline_status"], row["variant_status"]) for row in records] == [
        ("de", 200, 302),
        ("es", 200, 200),
    ]
    assert records[0]["variant_location"] == "https://example.com/de/" and records[0]["baseline_location"] is None
    assert records[0]["primary_content_differs"] is True and records[1]["primary_content_differs"] is False


def test_locale_probe_content_difference_is_unknown_when_the_control_request_differed() -> None:
    evidence = [_probe("none", 200, sha="a"), _probe("none-repeat", 200, sha="z"), _probe("de", 200, sha="b")]
    assert locale_probe_records(evidence)[0]["primary_content_differs"] is None


def test_robots_txt_record_keeps_the_body_only_for_a_2xx() -> None:
    ok = robots_txt_record("example.com", SimpleNamespace(status=200, text="User-agent: *\nDisallow: /x"), "valid")
    assert ok == {
        "host": "example.com",
        "fetch_outcome": "fetched",
        "status": 200,
        "body": "User-agent: *\nDisallow: /x",
        "llms_txt_status": "valid",
        "llms_txt_outcome": "fetched",
    }
    assert robots_txt_record("example.com", SimpleNamespace(status=301, text="moved"), None)["body"] is None
    # Ticket 410: an unread file is an explicit unknown outcome with a reason.
    assert robots_txt_record("example.com", None, None) == {
        "host": "example.com",
        "fetch_outcome": "unknown",
        "unknown_reason": "no_response",
        "status": None,
        "body": None,
        "llms_txt_status": None,
        "llms_txt_outcome": "unknown",
        "llms_txt_unknown_reason": "not_probed",
    }


def test_llms_status_is_keyed_by_host() -> None:
    collected = {
        "llms_files": [
            {"origin": "https://example.com", "path": "/llms.txt", "state": "valid"},
            {"origin": "https://example.com", "path": "/llms-full.txt", "state": "absent"},
        ]
    }
    assert llms_txt_status_by_host(collected) == {"example.com": "valid"}


def test_llms_probe_carries_outcome_and_reason_and_derives_them_for_old_rows() -> None:
    collected = {
        "llms_files": [
            {"origin": "https://a.example", "path": "/llms.txt", "state": "absent", "fetch_outcome": "fetched"},
            {
                "origin": "https://b.example",
                "path": "/llms.txt",
                "state": "fetch_unavailable",
                "fetch_outcome": "unknown",
                "unknown_reason": "timeout:ReadTimeout",
            },
            # Rows from a collector that predates ticket 423 carry only a state.
            {"origin": "https://c.example", "path": "/llms.txt", "state": "fetch_unavailable"},
            {"origin": "https://d.example", "path": "/llms.txt", "state": "robots_disallowed_not_fetched"},
        ]
    }
    assert llms_txt_probe_by_host(collected) == {
        "a.example": {"status": "absent", "outcome": "fetched", "unknown_reason": None},
        "b.example": {"status": "fetch_unavailable", "outcome": "unknown", "unknown_reason": "timeout:ReadTimeout"},
        "c.example": {"status": "fetch_unavailable", "outcome": "unknown", "unknown_reason": "no_response"},
        "d.example": {
            "status": "robots_disallowed_not_fetched",
            "outcome": "unknown",
            "unknown_reason": "robots_disallowed",
        },
    }


def test_tls_probe_records_never_claim_preload_or_ocsp_that_was_not_observed() -> None:
    rows = [
        {"record_type": "coverage", "https_host_count": 1},
        {
            "record_type": "candidate",
            "host": "example.com",
            "hsts": {"present": True, "raw": "max-age=300", "valid": True},
            "hsts_preload_list_membership": "not_queried",
            "ocsp_stapled": None,
        },
        {"record_type": "observation", "host": "cdn.example.com", "hsts": {"present": False, "raw": None}},
    ]
    assert tls_probe_records(rows) == [
        {"host": "example.com", "hsts_header": "max-age=300", "preload_status": None, "ocsp_stapled": None},
        {"host": "cdn.example.com", "hsts_header": None, "preload_status": None, "ocsp_stapled": None},
    ]


def test_adapted_records_answer_q63_and_q25_without_reaching_healthy_from_partial_evidence() -> None:
    audit = build_technical_audit(crawl_run_id="run-1", reports={}, run_context={"completion_state": "complete"})
    tls = tls_probe_records(
        [{"record_type": "candidate", "host": "example.com", "hsts": {"present": True, "raw": "max-age=300"}}]
    )
    locale = locale_probe_records([_probe("none", 200), _probe("de", 302, location="https://example.com/de/", sha="b")])
    bundle = new_bundle(
        "run-1",
        [
            collection("tls-probe", tls, source="test", scope="1 host", coverage_state="partial"),
            collection("locale-probe", locale, source="test", scope="1 root", coverage_state="complete"),
        ],
    )
    audit = attach_observations(audit, [bundle])
    answers = {row["id"]: row for row in answer_questions(audit, REGISTRY)}
    assert answers["Q63"]["answer"] == "Yes" and answers["Q63"]["status"] != "Healthy"
    assert answers["Q25"]["answer"] == "Yes"


def test_observations_parser_accepts_the_probe_flags() -> None:
    args = _build_parser().parse_args(
        [
            "technical-audit-observations",
            "--crawl-run-id",
            "run-1",
            "--out",
            "o.json",
            "--ai-governance",
            "--probe-accept-language",
            "--tls-probe",
            "--accept-language-max-targets",
            "3",
        ]
    )
    assert args.ai_governance and args.probe_accept_language and args.tls_probe
    assert args.accept_language_max_targets == 3 and args.ai_governance_max_origins == 10
