"""Offline post-merge QA. Run with PYTHONPATH=src python tickets/qa-new-audit-2026-10-06/reproduce.py.

Exercises production adapters/answerers and command orchestration. Only I/O
boundaries are substituted; no database, network or Google writes are made.
Prints the current behavior for each ticket key and exits 0; the QA-time
(defective) output is described in the README and each ticket. results.json
is regenerated from this script.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from crawler_cli import __main__ as cli
from crawler_cli.accept_language_audit import collect_accept_language_evidence
from crawler_cli.audit_observation_adapters import locale_probe_records, tls_probe_records
from crawler_cli.audit_observations import attach_observations, collection, new_bundle
from crawler_cli.technical_audit import build_technical_audit
from crawler_cli.technical_audit_observed_answers import AI_CRAWLERS
from crawler_cli.technical_audit_questions import answer_questions, load_question_registry, question_ticket_rows
from crawler_cli.transport_security import parse_strict_transport_security, transport_security_report
from crawler_cli.google_sheets import GoogleSheetsTemplatePublisher, TemplateHeaderError
from crawler_cli.technical_audit_tickets import TICKET_COLUMNS


REGISTRY = load_question_registry()
CONTEXT = {
    "completion_state": "complete",
    "snapshot_consistency": "stable",
    "html_count": 2,
    "parsed_html_count": 2,
    "unparsed_html_count": 0,
    "challenged_count": 0,
    "frontier_pending": 0,
    "rate_limited_count": 0,
    "ttfb_sample_count": 20,
    "ttfb_early_median_ms": 100,
    "ttfb_late_median_ms": 100,
}


def audit_with(kind, records, *, coverage="complete"):
    audit = build_technical_audit(crawl_run_id="qa", reports={}, run_context=CONTEXT)
    return attach_observations(
        audit,
        [
            new_bundle(
                "qa",
                [
                    collection(
                        kind,
                        records,
                        source="post-merge QA fixture",
                        scope="explicit synthetic population",
                        coverage_state=coverage,
                        collected_at="2026-10-06T12:00:00Z",
                    )
                ],
            )
        ],
    )


def answer(audit, qid, profile=None):
    return next(a for a in answer_questions(audit, REGISTRY, profile) if a["id"] == qid)


def brief(value):
    return {k: value[k] for k in ("id", "status", "answer", "affected_count", "denominator", "ticket")}


async def governance_cli(hosts, response, cap):
    store = SimpleNamespace(close=AsyncMock())
    reports = SimpleNamespace(
        _run_id=AsyncMock(return_value="qa"),
        technical_audit_context=AsyncMock(return_value={**CONTEXT, "seed_hosts": hosts}),
    )
    engine = SimpleNamespace(_bounded_fetch_response=AsyncMock(return_value=response), close=AsyncMock())
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "observations.json"
        args = cli._build_parser().parse_args(
            [
                "technical-audit-observations",
                "--crawl-run-id",
                "qa",
                "--out",
                str(target),
                "--ai-governance",
                "--ai-governance-max-origins",
                str(cap),
            ]
        )
        stderr = io.StringIO()
        with (
            patch.object(cli, "_store_from_args", return_value=store),
            patch.object(cli, "CrawlReports", return_value=reports),
            patch.object(cli, "CrawlEngine", return_value=engine),
            patch.object(cli, "collect_ai_governance", AsyncMock(return_value={"llms_files": []})),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(stderr),
        ):
            code = await cli._run_technical_audit_observations(args)
        return code, stderr.getvalue().strip(), json.loads(target.read_text()) if target.exists() else None


class LanguageEngine:
    def __init__(self, mode):
        self.config = SimpleNamespace(request_headers={}, follow_redirects=True)
        self.mode = mode

    async def crawl(self, url, **kwargs):
        spanish = self.config.request_headers.get("Accept-Language", "").startswith("es")
        failure = self.mode == "failure" and spanish
        # Visible content remains identical. Only a head script's locale changes.
        script_locale = "es" if spanish and self.mode == "script" else "en"
        html = (
            f'<html lang="en"><head><script>window.analyticsLocale="{script_locale}";</script></head>'
            "<body><main>" + "The same primary content. " * 100 + "</main></body></html>"
        )
        return SimpleNamespace(
            status=0 if failure else 200,
            headers={},
            skip_reason=None,
            raw_html=None if failure else html,
            extracted=SimpleNamespace(html_lang="en"),
        )


async def main():
    findings = {}
    code, error, bundle = await governance_cli(["one.example"], None, 10)
    findings["410"] = {"exit_code": code, "error": error, "bundle_written": bundle is not None}

    code, error, bundle = await governance_cli(
        ["one.example", "two.example"], SimpleNamespace(status=200, text="User-agent: *\nAllow: /"), 1
    )
    audit = attach_observations(build_technical_audit(crawl_run_id="qa", reports={}, run_context=CONTEXT), [bundle])
    profile = {"ai_crawler_policy": {agent: "allow" for agent in AI_CRAWLERS}}
    findings["411"] = {
        "exit_code": code,
        "coverage_state": bundle["collections"][0]["coverage_state"],
        "hosts_tested": len(bundle["collections"][0]["records"]),
        "hosts_eligible": 2,
        "answer": brief(answer(audit, "Q96", profile)),
    }

    for ticket, mode in (("412", "failure"), ("413", "script")):
        evidence = await collect_accept_language_evidence(LanguageEngine(mode), ["https://one.example/"])
        records = locale_probe_records(evidence)
        result = answer(audit_with("locale-probe", records), "Q25")
        findings[ticket] = {
            "answer": brief(result),
            "finding": result["rows"][0]["finding"] if result["rows"] else None,
            "spanish_raw_observation": next(
                row
                for row in evidence
                if row.get("observation_type") == "accept_language_probe" and row["variant"] == "es-ES"
            ),
        }

    # The production SQL selects requested URL and final headers, omitting final_url.
    redirected = {
        "url": "https://old.example/",
        "final_url": "https://new.example/",
        "final_status_code": 200,
        "headers_json": {"strict-transport-security": "max-age=300"},
    }
    selected_columns = {key: redirected[key] for key in ("url", "final_status_code", "headers_json")}
    findings["414"] = {
        "production_projection": tls_probe_records(transport_security_report([selected_columns])),
        "with_response_identity": tls_probe_records(transport_security_report([redirected])),
    }

    findings["415"] = []
    for header in (
        "max-age = 31536000; includeSubDomains; preload",
        "max-age=31536000; max-age=0; includeSubDomains; preload",
    ):
        parsed = parse_strict_transport_security(header)
        row = {"host": "one.example", "hsts_header": header, "preload_status": "preloaded", "ocsp_stapled": True}
        findings["415"].append(
            {
                "header": header,
                "shared_parser_valid": parsed.valid,
                "shared_parser_errors": parsed.errors,
                "answer": brief(answer(audit_with("tls-probe", [row]), "Q63")),
            }
        )

    weak = audit_with("tls-probe", [{"host": "one.example", "hsts_header": "max-age=300"}])
    result = answer(weak, "Q63")
    draft = question_ticket_rows(weak, REGISTRY, [result])[0]
    findings["416"] = {"answer": brief(result), "ticket_description": draft["Description"]}

    sheets, drive = MagicMock(), MagicMock()
    drive.files.return_value.copy.return_value.execute.return_value = {"id": "qa-copy"}
    sheets.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [{"properties": {"sheetId": 1, "title": "Tickets"}}]
    }
    values = sheets.spreadsheets.return_value.values.return_value
    values.get.return_value.execute.return_value = {
        "values": [["Client title"], ["Existing note"], ["Unrecognised header"]]
    }
    # Only the publisher's public contract is relied on: with no matching
    # Tickets header it raises TemplateHeaderError before any write.
    error = None
    try:
        GoogleSheetsTemplatePublisher(drive, sheets).publish(
            template="template-sheet",
            title="QA",
            tables={"Tickets": [list(TICKET_COLUMNS), ["x"] * 8]},
            locate_ticket_header=True,
        )
    except TemplateHeaderError as exc:
        error = type(exc).__name__
    findings["existing_406"] = {
        "matching_header": False,
        "error": error,
        "write_calls": {
            "values.clear": values.clear.call_count,
            "values.update": values.update.call_count,
            "values.batchUpdate": values.batchUpdate.call_count,
            "spreadsheets.batchUpdate": sheets.spreadsheets.return_value.batchUpdate.call_count,
        },
    }

    empty_links = build_technical_audit(crawl_run_id="qa", reports={"internal-link-quality": []}, run_context=CONTEXT)
    findings["existing_393"] = brief(answer(empty_links, "Q39"))
    print(json.dumps(findings, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
