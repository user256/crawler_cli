"""Tickets 414 and 415: TLS/HSTS evidence is attributed to the final response
host, and Q63 judges it with the one shared RFC 6797 parser."""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio

from crawler_cli.audit_observation_adapters import tls_probe_records
from crawler_cli.models import CrawlResult
from crawler_cli.persistence import AsyncpgStore
from crawler_cli.audit_observations import attach_observations, collection, new_bundle
from crawler_cli.reports import CrawlReports
from crawler_cli.technical_audit import build_technical_audit
from crawler_cli.technical_audit_questions import answer_questions, load_question_registry
from crawler_cli.transport_security import parse_strict_transport_security, transport_security_report

REGISTRY = load_question_registry()
CONTEXT = {"completion_state": "complete", "snapshot_consistency": "stable"}
STRONG = "max-age=31536000; includeSubDomains; preload"


class _Reports(CrawlReports):
    def __init__(self, rows: list[dict[str, object]]) -> None:
        super().__init__(None)  # type: ignore[arg-type]
        self.rows = rows
        self.queries: list[str] = []

    async def _run_id(self) -> str:
        return "run-1"

    async def _fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        self.queries.append(" ".join(query.split()))
        return self.rows


def _q63(records: list[dict[str, object]], *, coverage: str = "complete") -> dict[str, object]:
    audit = build_technical_audit(crawl_run_id="run-1", reports={}, run_context=CONTEXT)
    bundle = new_bundle(
        "run-1",
        [collection("tls-probe", records, source="test", scope="fixture", coverage_state=coverage)],
    )
    answers = answer_questions(attach_observations(audit, [bundle]), REGISTRY)
    return next(row for row in answers if row["id"] == "Q63")


# --- ticket 414: response identity -------------------------------------------------


def test_stored_https_headers_query_selects_by_final_response_identity() -> None:
    reports = _Reports([])
    asyncio.run(reports.https_response_headers())

    (query,) = reports.queries
    assert "JOIN urls fu ON fu.id = s.final_url_id" in query
    assert "u.url AS requested_url" in query and "fu.url AS final_url" in query
    # The scheme filter is on the observed final response, not the requested URL.
    assert "lower(fu.url) LIKE 'https://%'" in query
    assert "u.url LIKE" not in query


def test_stored_cross_host_redirect_feeds_q63_the_destination_host_only() -> None:
    rows = [
        {
            "requested_url": "https://old.example/",
            "final_url": "https://new.example/",
            "final_status_code": 200,
            "headers_json": {"strict-transport-security": "max-age=300"},
        }
    ]
    reports = _Reports(rows)
    stored = asyncio.run(reports.https_response_headers())

    records = tls_probe_records(transport_security_report(stored))
    assert records == [
        {"host": "new.example", "hsts_header": "max-age=300", "preload_status": None, "ocsp_stapled": None}
    ]


def test_pre_fix_projection_without_final_url_is_not_attributed_to_the_requested_host() -> None:
    projection = {
        "url": "https://old.example/",
        "final_status_code": 200,
        "headers_json": {"strict-transport-security": "max-age=300"},
    }
    assert tls_probe_records(transport_security_report([projection])) == []


# --- ticket 415: one shared HSTS parser -------------------------------------------

CASES = [
    # (header, valid per shared parser, Q63 finding expected)
    ("max-age=31536000; includeSubDomains; preload", True, False),
    ("max-age = 31536000 ; includeSubDomains ; preload", True, False),
    ('max-age="31536000"; includeSubDomains; preload', True, False),
    ("MAX-AGE=63072000;INCLUDESUBDOMAINS;PRELOAD", True, False),
    ("max-age=31536000; max-age=0; includeSubDomains; preload", False, True),
    ("max-age=abc; includeSubDomains; preload", False, True),
    ("includeSubDomains; preload", False, True),
    ("max-age=31536000; includeSubDomains=1; preload", False, True),
    ("max-age=300; includeSubDomains; preload", True, True),
    ("max-age=31536000; preload", True, True),
    ("max-age=31536000; includeSubDomains", True, True),
]


@pytest.mark.parametrize(("header", "valid", "finding"), CASES)
def test_q63_supplied_observation_agrees_with_shared_parser(header: str, valid: bool, finding: bool) -> None:
    assert parse_strict_transport_security(header).valid is valid
    answer = _q63([{"host": "example.com", "hsts_header": header, "preload_status": "preloaded", "ocsp_stapled": True}])

    assert answer["affected_count"] == (1 if finding else 0)
    assert answer["status"] == ("Healthy" if not finding else "Issue")


@pytest.mark.parametrize(("header", "valid", "finding"), CASES)
def test_q63_stored_observation_agrees_with_shared_parser(header: str, valid: bool, finding: bool) -> None:
    stored = [
        {
            "requested_url": "https://example.com/",
            "final_url": "https://example.com/",
            "final_status_code": 200,
            "headers_json": {"Strict-Transport-Security": header},
        }
    ]
    records = tls_probe_records(transport_security_report(stored))
    assert records[0]["hsts_header"] == header
    answer = _q63(records, coverage="partial")

    assert answer["affected_count"] == (1 if finding else 0)
    # Preload membership and OCSP were never probed on this path: never Healthy.
    assert answer["status"] != "Healthy"
    assert records[0]["preload_status"] is None and records[0]["ocsp_stapled"] is None


def test_q63_duplicate_max_age_names_the_parser_error() -> None:
    answer = _q63(
        [
            {
                "host": "example.com",
                "hsts_header": "max-age=31536000; max-age=0; includeSubDomains; preload",
                "preload_status": "preloaded",
                "ocsp_stapled": True,
            }
        ]
    )
    assert "duplicate_directive:max-age" in str(answer)


def test_q63_keeps_missing_preload_and_ocsp_evidence_unknown() -> None:
    answer = _q63([{"host": "example.com", "hsts_header": STRONG}])

    assert answer["affected_count"] == 0
    assert answer["status"] != "Healthy"


# --- ticket 414: real snapshot SQL (skipped without CRAWLER_CLI_TEST_DSN) ------------

_DSN = os.environ.get("CRAWLER_CLI_TEST_DSN", "")


@pytest_asyncio.fixture
async def store() -> AsyncpgStore:
    if not _DSN:
        pytest.skip("CRAWLER_CLI_TEST_DSN not set")
    s = AsyncpgStore(_DSN)
    await s.initialize()
    yield s
    await s.truncate_crawl_tables()
    await s.close()


def _fetched(requested: str, final: str, hsts: str) -> CrawlResult:
    return CrawlResult(
        requested_url=requested,
        final_url=final,
        status=200,
        headers={"content-type": "text/html", "strict-transport-security": hsts},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=None,
        raw_html=None,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stored_snapshot_headers_are_attributed_to_the_final_response(store: AsyncpgStore) -> None:
    await store.create_crawl_run("tls-414", seed_urls=["https://old.example/"], config_hash="x", config={})
    await store.persist(_fetched("https://old.example/", "https://new.example/", "max-age=300"))
    await store.persist(_fetched("http://plain.example/", "https://plain.example/", STRONG))
    await store.persist(_fetched("https://down.example/", "http://down.example/", STRONG))
    await store.persist(_fetched("https://alias.example/", "https://plain.example/", STRONG))

    rows = await CrawlReports(store, run_id="tls-414").https_response_headers()
    assert sorted((row["requested_url"], row["final_url"]) for row in rows) == [
        ("http://plain.example/", "https://plain.example/"),
        ("https://alias.example/", "https://plain.example/"),
        ("https://old.example/", "https://new.example/"),
    ]
    records = tls_probe_records(transport_security_report(rows))
    assert {record["host"]: record["hsts_header"] for record in records} == {
        "new.example": "max-age=300",
        "plain.example": STRONG,
    }
