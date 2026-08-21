"""Unit tests for the security finding contract (ticket 153).

Covers the fact/policy/serializer separation, the evidence budget, the raw
sensitive-evidence override, and the GUI/API projection. The frozen schema
itself is asserted in ``tests/contract/test_security_finding_contract.py``.
"""

from __future__ import annotations

import argparse
import json
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from crawler_cli.redaction import REDACTED, CorrelationDigest, bounded_snippet
from crawler_cli.security_evidence import (
    FINDING_CSV_COLUMNS,
    SECURITY_FINDING_SCHEMA_VERSION,
    EvidenceBudget,
    EvidenceSerializer,
    FindingPolicy,
    FindingRule,
    RawEvidencePolicy,
    SecurityEvidenceCollector,
    SecurityFact,
    add_raw_evidence_arguments,
    raw_evidence_policy_from_args,
    redacted_projection,
    write_raw_evidence,
)

OBSERVED_AT = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
DIGEST = CorrelationDigest.from_key(b"deterministic-test-key-0123456789", run_id="run-153")

COOKIE_RULE = FindingRule(
    rule_id="crawler-cli.cookie.missing-secure",
    title="Session cookie served without Secure",
    category="cookies",
    description="A cookie that looks like a session identifier was set without the Secure attribute.",
    severity="medium",
    confidence="high",
    remediation="Set the Secure attribute on session cookies and serve them only over HTTPS.",
    references=("https://developer.mozilla.org/docs/Web/HTTP/Headers/Set-Cookie",),
    limitations="Passive observation of response headers only; no session handling was tested.",
    non_claims=("No attempt was made to hijack or replay a session.",),
)


def _serializer(**kwargs) -> EvidenceSerializer:
    return EvidenceSerializer(run_id="run-153", digest=DIGEST, **kwargs)


def _fact(**overrides) -> SecurityFact:
    defaults = dict(
        rule_id=COOKIE_RULE.rule_id,
        url="https://example.com/account?session=live-session-value",
        source="response_header",
        detector="cookie-hygiene",
        detector_version="1.0.0",
        observed_at=OBSERVED_AT,
        attributes={"cookie_name": "SESSIONID", "secure": False},
    )
    defaults.update(overrides)
    return SecurityFact(**defaults)


# --- facts and policy -------------------------------------------------------------


def test_fact_requires_a_detector_version() -> None:
    with pytest.raises(ValueError, match="detector_version"):
        _fact(detector_version="")


def test_fact_repr_does_not_leak_the_raw_url() -> None:
    assert "live-session-value" not in repr(_fact())


def test_policy_refuses_an_unregistered_rule() -> None:
    with pytest.raises(KeyError, match="no FindingRule registered"):
        FindingPolicy([]).evaluate(_fact())


def test_policy_refuses_to_silently_replace_a_rule() -> None:
    policy = FindingPolicy([COOKIE_RULE])
    conflicting = FindingRule(
        rule_id=COOKIE_RULE.rule_id,
        title="Different",
        category="cookies",
        description="",
        severity="low",
    )
    with pytest.raises(ValueError, match="already registered"):
        policy.register(conflicting)


def test_unknown_severity_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown severity"):
        FindingRule(rule_id="x", title="t", category="c", description="d", severity="catastrophic")


def test_severity_override_is_applied_by_policy_not_by_the_detector() -> None:
    policy = FindingPolicy([COOKIE_RULE], severity_overrides={COOKIE_RULE.rule_id: "low"})
    finding = policy.evaluate(_fact())
    assert finding.severity == "low"
    assert finding.rule.severity == "medium"


def test_lifecycle_status_travels_with_the_fact() -> None:
    finding = FindingPolicy([COOKIE_RULE]).evaluate(_fact(status="resolved"))
    assert finding.status == "resolved"


# --- serialization ----------------------------------------------------------------


def test_finding_payload_carries_the_schema_version_and_redacted_url() -> None:
    finding = FindingPolicy([COOKIE_RULE]).evaluate(_fact())
    payload = _serializer().finding_payload(finding)
    assert payload["schema_version"] == SECURITY_FINDING_SCHEMA_VERSION == "crawler-cli/security-finding/1"
    assert payload["url"] == f"https://example.com/account?session={REDACTED}"
    assert payload["url_digest"].startswith("hmac-sha256:")
    assert "live-session-value" not in json.dumps(payload)


def test_finding_payload_reports_the_detector_and_its_version() -> None:
    finding = FindingPolicy([COOKIE_RULE]).evaluate(_fact())
    payload = _serializer().finding_payload(finding)
    assert payload["detector"] == "cookie-hygiene"
    assert payload["detector_version"] == "1.0.0"
    assert payload["observed_at"] == "2026-08-21T12:00:00Z"


def test_finding_payload_keeps_limitations_and_non_claims() -> None:
    finding = FindingPolicy([COOKIE_RULE]).evaluate(_fact())
    payload = _serializer().finding_payload(finding)
    assert "no session handling was tested" in payload["limitations"].lower()
    assert payload["non_claims"] == list(COOKIE_RULE.non_claims)


def test_evidence_is_redacted_recursively() -> None:
    finding = FindingPolicy([COOKIE_RULE]).evaluate(
        _fact(attributes={"headers": {"Set-Cookie": "sid=leaky-cookie-value"}, "note": "token=leaky-token-value"})
    )
    rendered = json.dumps(_serializer().finding_payload(finding))
    assert "leaky-cookie-value" not in rendered
    assert "leaky-token-value" not in rendered


def test_evidence_budget_caps_keys_values_and_lists() -> None:
    attributes = {f"key_{index}": "value" for index in range(30)}
    attributes["long"] = "x" * 1000
    attributes["many"] = list(range(50))
    finding = FindingPolicy([COOKIE_RULE]).evaluate(_fact(attributes=attributes))
    payload = _serializer(budget=EvidenceBudget(max_keys=5, max_value_chars=20, max_list_items=3)).finding_payload(
        finding
    )
    assert len(payload["evidence"]) == 5
    assert payload["evidence_truncated"] is True
    assert payload["evidence_dropped_keys"]


def test_evidence_budget_caps_snippet_count() -> None:
    snippets = [bounded_snippet(f"line {index}") for index in range(10)]
    finding = FindingPolicy([COOKIE_RULE]).evaluate(_fact(snippets=snippets))
    payload = _serializer(budget=EvidenceBudget(max_snippets=2)).finding_payload(finding)
    assert len(payload["snippets"]) == 2
    assert payload["evidence_truncated"] is True


def test_report_payload_counts_severities_and_detector_versions() -> None:
    findings = FindingPolicy([COOKIE_RULE]).evaluate_all([_fact(), _fact()])
    payload = _serializer().report_payload(findings, generated_at=OBSERVED_AT)
    assert payload["finding_count"] == 2
    assert payload["severity_counts"]["medium"] == 2
    assert payload["detector_versions"] == {"cookie-hygiene": "1.0.0"}


def test_jsonl_output_is_one_object_per_finding(tmp_path: Path) -> None:
    findings = FindingPolicy([COOKIE_RULE]).evaluate_all([_fact(), _fact()])
    path = _serializer().write_jsonl(tmp_path / "findings.jsonl", findings)
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["schema_version"] == SECURITY_FINDING_SCHEMA_VERSION


def test_csv_output_uses_the_frozen_column_order(tmp_path: Path) -> None:
    findings = FindingPolicy([COOKIE_RULE]).evaluate_all([_fact()])
    path = _serializer().write_csv(tmp_path / "findings.csv", findings)
    header = path.read_text(encoding="utf-8").split("\n")[0]
    assert header.strip() == ",".join(FINDING_CSV_COLUMNS)


def test_csv_output_neutralises_formula_injection_from_evidence(tmp_path: Path) -> None:
    """A crawled page can name a field ``=cmd|'/c calc'!A1``; the CSV must not."""
    hostile = FindingRule(
        rule_id="crawler-cli.test.hostile",
        title='=HYPERLINK("http://evil","click")',
        category="test",
        description="-2+3+cmd|' /c calc'!A0",
        severity="info",
    )
    findings = FindingPolicy([hostile]).evaluate_all([_fact(rule_id=hostile.rule_id, attributes={"@sum": "=1+1"})])
    serializer = _serializer()
    rows = serializer.csv_rows(findings)
    assert rows[0]["title"].startswith("'=HYPERLINK")
    assert rows[0]["description"].startswith("'-2+3")
    path = serializer.write_csv(tmp_path / "hostile.csv", findings)
    for line in path.read_text(encoding="utf-8").split("\n")[1:]:
        for cell in line.split(","):
            assert not cell.lstrip('"').startswith(("=", "+", "@"))


def test_html_output_escapes_every_value(tmp_path: Path) -> None:
    injected = FindingRule(
        rule_id="crawler-cli.test.html",
        title="<script>alert(1)</script>",
        category="test",
        description="",
        severity="info",
    )
    findings = FindingPolicy([injected]).evaluate_all([_fact(rule_id=injected.rule_id)])
    rendered = _serializer().render_html(findings)
    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;" in rendered


# --- detector helper ---------------------------------------------------------------


def test_collector_refuses_a_fact_whose_rule_is_not_registered() -> None:
    collector = SecurityEvidenceCollector(policy=FindingPolicy([]), serializer=_serializer())
    with pytest.raises(KeyError):
        collector.record(_fact())


def test_collector_produces_a_serialized_report() -> None:
    collector = SecurityEvidenceCollector(policy=FindingPolicy([COOKIE_RULE]), serializer=_serializer())
    collector.record(_fact())
    collector.record_status(_fact(), "resolved")
    payload = collector.report_payload(generated_at=OBSERVED_AT)
    assert payload["finding_count"] == 2
    assert [finding["status"] for finding in payload["findings"]] == ["observed", "resolved"]


# --- raw evidence override -----------------------------------------------------------


def _raw_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    add_raw_evidence_arguments(parser)
    return parser


def test_raw_evidence_is_off_by_default() -> None:
    policy = raw_evidence_policy_from_args(_raw_parser().parse_args([]))
    assert policy.any_enabled is False


def test_raw_evidence_file_requires_confirmation() -> None:
    args = _raw_parser().parse_args(["--retain-raw-evidence-dir", "/tmp/evidence"])
    with pytest.raises(ValueError, match="explicit confirmation"):
        raw_evidence_policy_from_args(args)


def test_raw_evidence_file_requires_a_directory() -> None:
    with pytest.raises(ValueError, match="explicit output directory"):
        RawEvidencePolicy(file_enabled=True, confirmed=True).validate()


def test_enabling_a_raw_evidence_file_does_not_enable_database_retention(tmp_path: Path) -> None:
    """The two destinations are separate explicit choices, never one flag."""
    args = _raw_parser().parse_args(
        ["--retain-raw-evidence-dir", str(tmp_path), "--i-understand-raw-evidence-is-sensitive"]
    )
    policy = raw_evidence_policy_from_args(args)
    assert policy.file_enabled is True
    assert policy.database_enabled is False


def test_database_retention_is_its_own_flag_and_still_needs_confirmation() -> None:
    args = _raw_parser().parse_args(["--retain-raw-evidence-in-database"])
    with pytest.raises(ValueError, match="separate choice"):
        raw_evidence_policy_from_args(args)
    confirmed = _raw_parser().parse_args(
        ["--retain-raw-evidence-in-database", "--i-understand-raw-evidence-is-sensitive"]
    )
    policy = raw_evidence_policy_from_args(confirmed)
    assert policy.database_enabled is True
    assert policy.file_enabled is False


def test_raw_evidence_file_is_owner_only_and_carries_a_warning(tmp_path: Path) -> None:
    directory = tmp_path / "evidence"
    policy = RawEvidencePolicy(file_enabled=True, directory=directory, confirmed=True)
    path = write_raw_evidence(policy, "case-1.txt", "raw material")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert path.read_text(encoding="utf-8").startswith("WARNING:")


def test_write_raw_evidence_refuses_when_retention_is_off() -> None:
    with pytest.raises(ValueError, match="not enabled"):
        write_raw_evidence(RawEvidencePolicy(), "case", "raw")


# --- GUI / API projection ---------------------------------------------------------------


def test_gui_projection_scrubs_and_strips_raw_keys() -> None:
    projected = redacted_projection(
        {
            "rule_id": "x",
            "raw_url": "https://example.com/?token=live",
            "headers": {"Cookie": "sid=live-cookie"},
            "note": "password=hunter9999",
        }
    )
    assert projected["raw_url"] == REDACTED
    assert projected["headers"]["Cookie"] == REDACTED
    assert "hunter9999" not in projected["note"]
