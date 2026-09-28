import asyncio

import pytest

from crawler_cli import live_rechecks
from crawler_cli.models import CrawlResult
from crawler_cli.live_rechecks import _aggregate, _observation, candidate_targets
from crawler_cli.technical_audit import TECHNICAL_AUDIT_REPORTS, audit_sheet_tables, build_technical_audit


def test_candidate_targets_are_unique_sorted_and_bounded():
    rows = [
        {"target_url": "https://example.test/z", "target_status": 503},
        {"target_url": "https://example.test/a", "target_status": 404},
        {"target_url": "https://example.test/a", "target_status": 404},
        {"target_url": "https://example.test/ok", "target_status": 200},
    ]
    assert candidate_targets(rows, limit=1) == ["https://example.test/a"]
    with pytest.raises(ValueError, match="recheck limit"):
        candidate_targets(rows, limit=26)


def test_recheck_states_do_not_conflate_access_problems_with_http_failures():
    assert _aggregate([{"state": "http_failure", "status": 503}] * 2) == "persistent_server_error"
    assert _aggregate([{"state": "http_failure", "status": 404}] * 2) == "persistent_http_failure"
    assert _aggregate([{"state": "responsive", "status": 200}] * 2) == "recovered"
    for state in (
        "challenge",
        "robots_disallowed",
        "transport_error",
        "tls_error",
        "dns_error",
        "scope_denied",
        "access_denied",
        "rate_limited",
    ):
        assert _aggregate([{"state": state}] * 2) == state


def test_http_access_and_transport_outcomes_keep_distinct_states():
    def response(status, *, challenge=None, skip_reason=None):
        return CrawlResult(
            requested_url="https://example.test/page",
            final_url="https://example.test/page",
            status=status,
            headers={},
            content_type=None,
            fetch_backend="aiohttp",
            extracted=None,
            raw_html=None,
            challenge=challenge,
            skip_reason=skip_reason,
        )

    assert _observation(response(403))["state"] == "access_denied"
    assert _observation(response(403, challenge="cloudflare"))["state"] == "challenge"
    assert _observation(response(0, skip_reason="robots_txt_disallow"))["state"] == "robots_disallowed"
    assert _observation(response(0, skip_reason="fetch_error:ClientConnectorCertificateError"))["state"] == "tls_error"
    assert _observation(response(0, skip_reason="fetch_error:ClientConnectorDNSError"))["state"] == "dns_error"


def test_collector_uses_probe_scope_robots_and_disabled_browser_escalation(monkeypatch):
    seen = []
    instances = []

    class Scope:
        def decide(self, url, *, purpose):
            assert purpose == "probe"
            return type("Decision", (), {"allowed": True})()

    class Engine:
        def __init__(self, config):
            self.config = config
            instances.append(self)

        async def crawl(self, url, *, purpose):
            seen.append((url, purpose))
            return CrawlResult(
                requested_url=url,
                final_url=url,
                status=503,
                headers={"Content-Type": "text/html", "Set-Cookie": "secret=hidden"},
                content_type="text/html",
                fetch_backend="aiohttp",
                extracted=None,
                raw_html=None,
            )

        async def close(self):
            pass

    monkeypatch.setattr(live_rechecks, "CrawlEngine", Engine)
    evidence = asyncio.run(
        live_rechecks.collect_live_rechecks(
            ["https://example.test/failed"],
            scope_predicate=Scope(),
            allowed_hosts=["example.test"],
            attempts=2,
        )
    )
    config = instances[0].config
    assert config.respect_robots_txt is True
    assert config.challenge_escalate_to_browser is False
    assert seen == [("https://example.test/failed", "probe")] * 2
    assert evidence["https://example.test/failed"]["state"] == "persistent_server_error"
    assert "set-cookie" not in evidence["https://example.test/failed"]["attempts"][0]["headers"]


def _reports():
    return {name: [] for name in TECHNICAL_AUDIT_REPORTS} | {
        "link-graph-metrics": [{"graph_complete": True}],
        "similarity-coverage": [
            {
                "eligible_population": 1,
                "sampled_population": 1,
                "truncated": False,
                "findings_truncated": False,
                "missing_primary_hashes": 0,
            }
        ],
        "authority-coverage": [{"graph_complete": True, "canonical_indexable_population": 1}],
        "internal-link-quality": [
            {
                "source_url": "https://example.test/source",
                "target_url": "https://example.test/failed",
                "target_status": 503,
                "issue": "error_target",
                "anchor_text": "more",
            }
        ],
    }


def _context():
    return {
        "run_status": "complete",
        "completion_state": "complete",
        "parsed_html_count": 1,
        "hashed_count": 1,
        "schema_capabilities": {"indexability_evidence_json": True},
    }


def test_historical_failures_are_candidates_until_rechecked():
    audit = build_technical_audit(crawl_run_id="run-1", reports=_reports(), run_context=_context())
    gate = audit["client_publication_gate"]
    check = next(row for row in audit["checks"] if row["id"] == "internal-link-failures")
    assert gate["ready"] is False
    assert gate["client_actions"] == []
    assert check["status"] == "unavailable"
    assert audit["analyst_evidence"][0]["recheck_state"] == "not_checked"
    assert "Audit Log" not in audit_sheet_tables(audit)


def test_recovered_targets_are_removed_from_client_failures_with_provenance_retained():
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports=_reports(),
        run_context=_context(),
        live_rechecks={"https://example.test/failed": {"state": "recovered", "attempts": [{"status": 200}]}},
    )
    check = next(row for row in audit["checks"] if row["id"] == "internal-link-failures")
    assert check["status"] == "pass"
    assert audit["client_publication_gate"]["client_actions"] == []
    assert audit["analyst_evidence"][0]["recheck_state"] == "recovered"
    assert "Audit Log" not in audit_sheet_tables(audit)


def test_repeated_live_http_failures_are_the_only_link_errors_eligible_for_client_output():
    rechecks = {
        "https://example.test/failed": {
            "state": "persistent_server_error",
            "attempts": [{"status": 503}, {"status": 503}],
        }
    }
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports=_reports(),
        run_context=_context(),
        live_rechecks=rechecks,
    )
    gate = audit["client_publication_gate"]
    assert gate["ready"] is True
    assert gate["eligible_action_count"] == 1
    assert gate["client_actions"][0]["Problem"] == "Internal link targets a repeatedly failing URL"
    tables = audit_sheet_tables(audit)
    assert tables["Audit Log"][1][0] == "Internal link targets a repeatedly failing URL"
    replay = build_technical_audit(
        crawl_run_id="run-1",
        reports=_reports(),
        run_context=_context(),
        live_rechecks=audit["live_rechecks_by_digest"],
    )
    assert replay["client_publication_gate"] == gate


def test_challenge_or_robots_refusal_cannot_be_published_as_target_failure():
    for state in ("challenge", "robots_disallowed", "transport_error"):
        audit = build_technical_audit(
            crawl_run_id="run-1",
            reports=_reports(),
            run_context=_context(),
            live_rechecks={"https://example.test/failed": {"state": state}},
        )
        assert audit["client_publication_gate"]["ready"] is False
        assert audit["client_publication_gate"]["client_actions"] == []


def test_incomplete_run_hides_even_confirmed_actions_behind_closed_gate():
    context = _context() | {"run_status": "interrupted", "completion_state": "partial"}
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports=_reports(),
        run_context=context,
        live_rechecks={
            "https://example.test/failed": {
                "state": "persistent_http_failure",
                "attempts": [{"status": 404}, {"status": 404}],
            }
        },
    )
    gate = audit["client_publication_gate"]
    assert gate["ready"] is False
    assert gate["client_actions"] == []
    assert gate["eligible_action_count"] == 0
