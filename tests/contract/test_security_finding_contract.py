"""Golden contract for the security finding schema (ticket 153).

Freezes ``crawler-cli/security-finding/1``: the field set of a finding, the
report envelope around it, and the CSV column order and hygiene. Tickets 145,
146, 150, 151, 152 and 154 emit this schema and nothing else, so a diff in
these goldens is a contract change for every one of them and must bump the
schema version.

Regenerating: run with ``CONTRACT_GOLDEN_UPDATE=1`` and review the diff.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from contract_fixtures import assert_matches_golden

from crawler_cli.redaction import CorrelationDigest, bounded_snippet
from crawler_cli.security_evidence import (
    FINDING_CSV_COLUMNS,
    SECURITY_FINDING_SCHEMA_VERSION,
    EvidenceSerializer,
    FindingPolicy,
    FindingRule,
    SecurityFact,
)

# A fixed key and fixed timestamps: every value in the golden must be stable
# across runs, platforms and machines.
GOLDEN_DIGEST = CorrelationDigest.from_key(b"crawler-cli-golden-key-0123456789", run_id="run-golden")
GOLDEN_OBSERVED_AT = datetime(2026, 8, 21, 9, 30, 0, tzinfo=timezone.utc)
GOLDEN_GENERATED_AT = datetime(2026, 8, 21, 9, 30, 5, tzinfo=timezone.utc)

COOKIE_RULE = FindingRule(
    rule_id="crawler-cli.cookie.missing-secure",
    title="Session cookie served without Secure",
    category="cookies",
    description="A cookie that looks like a session identifier was set without the Secure attribute.",
    severity="medium",
    confidence="high",
    remediation="Set the Secure attribute on session cookies and serve the site over HTTPS only.",
    references=("https://developer.mozilla.org/docs/Web/HTTP/Headers/Set-Cookie",),
    limitations="Passive observation of response headers only. No session handling was exercised.",
    non_claims=(
        "No attempt was made to hijack, replay, or fixate a session.",
        "The absence of a finding is not evidence that a cookie is safe.",
    ),
)

HEADER_RULE = FindingRule(
    rule_id="crawler-cli.header.sensitive-value-in-url",
    title="Sensitive parameter present in a crawled URL",
    category="urls",
    description="A crawled URL carried a parameter whose name indicates a credential or session value.",
    severity="low",
    confidence="medium",
    remediation="Move credentials out of query strings; they are logged by proxies, CDNs and browsers.",
    limitations="Parameter names are matched by policy; the value was never inspected or validated.",
    non_claims=("No claim is made that the parameter value is currently valid.",),
)


def _findings():
    policy = FindingPolicy([COOKIE_RULE, HEADER_RULE])
    facts = [
        SecurityFact(
            rule_id=COOKIE_RULE.rule_id,
            url="https://example.com/account?session=golden-session-value",
            source="response_header",
            detector="cookie-hygiene",
            detector_version="1.0.0",
            observed_at=GOLDEN_OBSERVED_AT,
            attributes={
                "cookie_name": "SESSIONID",
                "secure": False,
                "http_only": True,
                "same_site": "Lax",
                "value_digest": GOLDEN_DIGEST.digest("golden-session-value", domain="cookie-value"),
            },
            snippets=(bounded_snippet("Set-Cookie: SESSIONID=golden-session-value; Path=/; HttpOnly"),),
        ),
        SecurityFact(
            rule_id=HEADER_RULE.rule_id,
            url="https://alice:hunter2@example.com/reset?token=golden-reset-token&next=/account#frag",
            source="url",
            detector="url-hygiene",
            detector_version="2.1.0",
            observed_at=GOLDEN_OBSERVED_AT,
            attributes={"parameter_names": ["token", "next"], "in_sitemap": True},
            status="unknown",
        ),
    ]
    return policy.evaluate_all(facts)


def _serializer() -> EvidenceSerializer:
    return EvidenceSerializer(run_id="run-golden", digest=GOLDEN_DIGEST)


def test_security_finding_report_matches_golden() -> None:
    payload = _serializer().report_payload(_findings(), generated_at=GOLDEN_GENERATED_AT)
    assert payload["schema_version"] == SECURITY_FINDING_SCHEMA_VERSION == "crawler-cli/security-finding/1"
    assert_matches_golden("security_finding_report.json", json.dumps(payload, indent=2, sort_keys=True) + "\n")


def test_security_finding_csv_matches_golden(tmp_path) -> None:
    path = _serializer().write_csv(tmp_path / "findings.csv", _findings())
    assert_matches_golden("security_findings.csv", path.read_text(encoding="utf-8"))


def test_golden_encodes_the_semantics_it_freezes() -> None:
    """Spot-check the contract the goldens encode, so a regeneration that
    silently changes meaning still fails a named assertion."""
    payload = _serializer().report_payload(_findings(), generated_at=GOLDEN_GENERATED_AT)
    cookie, url = payload["findings"]

    # Every finding carries the schema version, the run, the detector and its
    # version, and a UTC observation time.
    for finding in (cookie, url):
        assert finding["schema_version"] == "crawler-cli/security-finding/1"
        assert finding["run_id"] == "run-golden"
        assert finding["detector_version"]
        assert finding["observed_at"].endswith("Z")

    # The URL is the redacted projection plus a keyed digest, never the raw URL.
    assert "golden-session-value" not in json.dumps(payload)
    assert "golden-reset-token" not in json.dumps(payload)
    assert "hunter2" not in json.dumps(payload)
    assert url["url"] == "https://example.com/reset?token=[REDACTED]&next=/account#[REDACTED]"
    assert url["had_userinfo"] is True
    assert url["had_fragment"] is True
    assert cookie["url_digest"].startswith("hmac-sha256:")

    # Severity is product policy, and passive detectors state their limits.
    assert cookie["severity"] == "medium"
    assert cookie["limitations"]
    assert url["non_claims"]

    # Lifecycle status is a distinct field, not encoded into severity.
    assert cookie["status"] == "observed"
    assert url["status"] == "unknown"

    # The snippet keeps a source hash even though the cookie value is gone.
    assert cookie["snippets"][0]["source_sha256"]
    assert "golden-session-value" not in cookie["snippets"][0]["text"]


def test_csv_columns_are_frozen() -> None:
    assert FINDING_CSV_COLUMNS == (
        "schema_version",
        "run_id",
        "rule_id",
        "title",
        "category",
        "severity",
        "confidence",
        "status",
        "url",
        "url_digest",
        "host",
        "source",
        "detector",
        "detector_version",
        "observed_at",
        "description",
        "remediation",
        "references",
        "limitations",
        "non_claims",
        "evidence",
        "evidence_truncated",
    )
