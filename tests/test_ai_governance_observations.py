"""Q96 evidence contract for ``technical-audit-observations --ai-governance``.

Ticket 410: an unread robots.txt is kept as an unknown observation for its host
instead of aborting the bundle. Ticket 411: a capped probe records its
eligible, selected and omitted origins and never reaches Healthy.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from crawler_cli import __main__ as cli
from crawler_cli.audit_observation_adapters import robots_txt_record
from crawler_cli.audit_observations import (
    ObservationError,
    attach_observations,
    collection,
    new_bundle,
    validate_observation_bundle,
)
from crawler_cli.config import CrawlConfig
from crawler_cli.destination_policy import DestinationRejection
from crawler_cli.engine import CrawlEngine
from crawler_cli.models import FetchResponse
from crawler_cli.technical_audit import build_technical_audit
from crawler_cli.technical_audit_observed_answers import AI_CRAWLERS
from crawler_cli.technical_audit_questions import answer_questions, load_question_registry


REGISTRY = load_question_registry()
CONTEXT = {"completion_state": "complete", "snapshot_consistency": "stable", "html_count": 1, "parsed_html_count": 1}
ALLOW_ALL = SimpleNamespace(status=200, text="User-agent: *\nAllow: /")
ALLOW_PROFILE = {"ai_crawler_policy": {agent: "allow" for agent in AI_CRAWLERS}}


def _q96(bundle: dict, profile: dict | None = ALLOW_PROFILE) -> dict:
    audit = attach_observations(build_technical_audit(crawl_run_id="qa", reports={}, run_context=CONTEXT), [bundle])
    return next(row for row in answer_questions(audit, REGISTRY, profile) if row["id"] == "Q96")


async def _run(tmp_path: Path, hosts: list[str], outcomes: dict[str, object], *, cap: int = 10, extra=()):
    """Run the command with a fake guarded fetch.

    ``outcomes`` maps host to a response, or to a skip reason string that the
    fake reports through ``on_skip`` before returning None, as the engine does.
    """

    async def fetch(url: str, on_skip=None):
        host = url.split("/")[2]
        outcome = outcomes[host]
        if isinstance(outcome, str):
            if on_skip is not None:
                on_skip(outcome)
            return None
        return outcome

    store = SimpleNamespace(close=AsyncMock())
    reports = SimpleNamespace(
        _run_id=AsyncMock(return_value="qa"),
        technical_audit_context=AsyncMock(return_value={**CONTEXT, "seed_hosts": hosts}),
        https_response_headers=AsyncMock(return_value=[]),
    )
    engine = SimpleNamespace(_bounded_fetch_response=AsyncMock(side_effect=fetch), close=AsyncMock())
    target = tmp_path / "observations.json"
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
            *extra,
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
    bundle = json.loads(target.read_text()) if target.exists() else None
    return code, stderr.getvalue(), bundle


def _robots(bundle: dict) -> dict:
    return next(item for item in bundle["collections"] if item["kind"] == "robots-txt")


# --- ticket 410: unread robots.txt -------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "timeout:ReadTimeout",
        "destination_denied:private_address",
        "challenge:cloudflare",
        "truncated:max_response_bytes",
        "circuit_breaker_open",
    ],
)
async def test_unread_robots_is_kept_as_unknown_and_other_collections_survive(tmp_path, reason) -> None:
    code, error, bundle = await _run(tmp_path, ["one.example"], {"one.example": reason}, extra=["--tls-probe"])

    assert code == cli.EXIT_SUCCESS, error
    assert {item["kind"] for item in bundle["collections"]} == {"robots-txt", "tls-probe"}
    robots = _robots(bundle)
    assert robots["coverage_state"] == "partial"
    assert robots["records"] == [
        {
            "host": "one.example",
            "fetch_outcome": "unknown",
            "unknown_reason": reason,
            "status": None,
            "body": None,
            "llms_txt_status": None,
        }
    ]
    assert robots["population"]["unread"] == ["one.example"]
    assert reason in robots["scope"]
    answer = _q96(bundle)
    assert answer["status"] == "Pending"
    assert answer["ticket"] is False


@pytest.mark.asyncio
async def test_none_without_a_reported_reason_is_still_unknown(tmp_path) -> None:
    code, _, bundle = await _run(tmp_path, ["one.example"], {"one.example": None})
    assert code == cli.EXIT_SUCCESS
    assert _robots(bundle)["records"][0]["unknown_reason"] == "no_response"


@pytest.mark.asyncio
async def test_mixed_read_and_unread_hosts_keep_both_and_stay_below_healthy(tmp_path) -> None:
    code, error, bundle = await _run(
        tmp_path,
        ["one.example", "two.example"],
        {"one.example": ALLOW_ALL, "two.example": "timeout:TimeoutError"},
    )

    assert code == cli.EXIT_SUCCESS, error
    robots = _robots(bundle)
    assert [(r["host"], r["fetch_outcome"]) for r in robots["records"]] == [
        ("one.example", "fetched"),
        ("two.example", "unknown"),
    ]
    assert robots["coverage_state"] == "partial"
    answer = _q96(bundle)
    assert answer["status"] == "Needs validation"
    assert answer["answer"] == "No (partial)"
    assert answer["denominator"] == len(AI_CRAWLERS)
    assert "two.example (timeout:TimeoutError)" in " ".join(answer["notes"])


# --- ticket 411: capped probes -----------------------------------------------


@pytest.mark.asyncio
async def test_cap_below_population_is_partial_and_never_healthy(tmp_path) -> None:
    code, _, bundle = await _run(
        tmp_path, ["one.example", "two.example"], {"one.example": ALLOW_ALL, "two.example": ALLOW_ALL}, cap=1
    )

    assert code == cli.EXIT_SUCCESS
    robots = _robots(bundle)
    assert robots["coverage_state"] == "partial"
    assert [r["host"] for r in robots["records"]] == ["one.example"]
    population = robots["population"]
    assert population["eligible_count"] == 2 and population["selected_count"] == 1 and population["omitted_count"] == 1
    assert population["eligible"] == ["one.example", "two.example"]
    assert population["selected"] == ["one.example"] and population["omitted"] == ["two.example"]
    assert "1 of 2 eligible" in robots["scope"] and "two.example" in robots["scope"]
    answer = _q96(bundle)
    assert answer["status"] != "Healthy"
    assert answer["status"] == "Needs validation"


@pytest.mark.asyncio
async def test_cap_equal_to_population_can_be_healthy(tmp_path) -> None:
    code, _, bundle = await _run(
        tmp_path, ["one.example", "two.example"], {"one.example": ALLOW_ALL, "two.example": ALLOW_ALL}, cap=2
    )

    assert code == cli.EXIT_SUCCESS
    robots = _robots(bundle)
    assert robots["coverage_state"] == "complete"
    assert robots["population"]["omitted"] == [] and robots["population"]["omitted_count"] == 0
    answer = _q96(bundle)
    assert answer["status"] == "Healthy"
    assert answer["denominator"] == 2 * len(AI_CRAWLERS)


@pytest.mark.asyncio
async def test_duplicate_seed_hosts_count_once(tmp_path) -> None:
    _, _, bundle = await _run(tmp_path, ["one.example", "ONE.example"], {"one.example": ALLOW_ALL}, cap=1)
    robots = _robots(bundle)
    assert robots["population"]["eligible_count"] == 1
    assert robots["coverage_state"] == "complete"


@pytest.mark.asyncio
async def test_cap_with_an_unread_selected_host_stays_pending(tmp_path) -> None:
    _, _, bundle = await _run(
        tmp_path, ["one.example", "two.example"], {"one.example": "challenge:akamai", "two.example": ALLOW_ALL}, cap=1
    )
    robots = _robots(bundle)
    assert robots["coverage_state"] == "partial"
    assert robots["population"]["omitted"] == ["two.example"]
    assert _q96(bundle)["status"] == "Pending"


def test_answerer_honours_population_even_if_a_supplied_bundle_says_complete() -> None:
    # Validation refuses this shape; the answerer is checked on its own here.
    capped = collection(
        "robots-txt",
        [robots_txt_record("one.example", ALLOW_ALL, None)],
        source="test",
        scope="1 of 2",
        coverage_state="partial",
        collected_at="2026-10-06T12:00:00Z",
        population={"eligible_count": 2, "selected_count": 1, "omitted_count": 1, "omitted": ["two.example"]},
    )
    capped["coverage_state"] = "complete"
    audit = build_technical_audit(crawl_run_id="qa", reports={}, run_context=CONTEXT)
    audit["observations"] = {"schema_version": "crawler-cli/audit-observations/1", "crawl_run_id": "qa"}
    audit["observations"]["collections"] = [capped]
    answer = next(row for row in answer_questions(audit, REGISTRY, ALLOW_PROFILE) if row["id"] == "Q96")
    assert answer["status"] == "Needs validation"


# --- bundle validation --------------------------------------------------------


def _bundle(records, **kwargs):
    kwargs.setdefault("coverage_state", "partial")
    return {
        "schema_version": "crawler-cli/audit-observations/1",
        "crawl_run_id": "qa",
        "collections": [
            collection(
                "robots-txt", records, source="test", scope="test", collected_at="2026-10-06T12:00:00Z", **kwargs
            )
        ],
    }


def test_validation_accepts_an_explicit_unknown_robots_record() -> None:
    validate_observation_bundle(_bundle([robots_txt_record("one.example", None, None, unknown_reason="timeout:X")]))


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({"host": "one.example", "status": None}, "missing status"),
        ({"host": "one.example", "fetch_outcome": "unknown"}, "needs an unknown_reason"),
        ({"host": "one.example", "fetch_outcome": "unknown", "unknown_reason": "x", "status": 200}, "must not carry"),
        ({"host": "one.example", "fetch_outcome": "maybe", "status": 200}, "fetch_outcome must be"),
        ({"host": "one.example", "status": "200"}, "must be an integer"),
        ({"status": 200}, "missing host"),
    ],
)
def test_validation_refuses_ambiguous_robots_records(record, message) -> None:
    with pytest.raises(ObservationError, match=message):
        new_bundle("qa", _bundle([record])["collections"])


def test_validation_refuses_complete_coverage_with_omitted_population() -> None:
    population = {"eligible_count": 2, "selected_count": 1, "omitted_count": 1, "omitted": ["two.example"]}
    record = robots_txt_record("one.example", ALLOW_ALL, None)
    with pytest.raises(ObservationError, match="omits eligible items"):
        validate_observation_bundle(_bundle([record], coverage_state="complete", population=population))
    validate_observation_bundle(_bundle([record], coverage_state="partial", population=population))
    with pytest.raises(ObservationError, match="must equal eligible_count"):
        validate_observation_bundle(_bundle([record], population={**population, "eligible_count": 3}))


# --- engine reports why a guarded fetch returned None ---------------------------


def _engine() -> CrawlEngine:
    return CrawlEngine(CrawlConfig(respect_robots_txt=False, discover_sitemaps=False, circuit_breaker_enabled=False))


def _response(**kwargs) -> FetchResponse:
    base = {"url": "https://one.example/robots.txt", "requested_url": "https://one.example/robots.txt"}
    return FetchResponse(**{**base, "status": 200, "headers": {}, "body": b"", "text": "", **kwargs})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fetch", "challenge", "expected"),
    [
        (AsyncMock(side_effect=TimeoutError()), None, "timeout:TimeoutError"),
        (AsyncMock(side_effect=DestinationRejection("private_address")), None, "destination_denied:private_address"),
        (AsyncMock(side_effect=ConnectionError("reset")), None, "fetch_error:ConnectionError"),
        (AsyncMock(return_value=_response()), "cloudflare", "challenge:cloudflare"),
        (
            AsyncMock(return_value=_response(body_truncated=True, body_truncation_reason="max_response_bytes")),
            None,
            "truncated:max_response_bytes",
        ),
    ],
)
async def test_bounded_fetch_reports_the_skip_reason(fetch, challenge, expected) -> None:
    engine = _engine()
    reasons: list[str] = []
    try:
        with (
            patch.object(engine, "_fetch_for_purpose", fetch),
            patch.object(engine, "_handle_challenge", AsyncMock(side_effect=lambda url, r: (r, challenge))),
        ):
            assert (
                await engine._bounded_fetch_response("https://one.example/robots.txt", on_skip=reasons.append) is None
            )
    finally:
        await engine.close()
    assert reasons == [expected]


@pytest.mark.asyncio
async def test_bounded_fetch_reports_nothing_on_success() -> None:
    engine = _engine()
    reasons: list[str] = []
    try:
        with (
            patch.object(engine, "_fetch_for_purpose", AsyncMock(return_value=_response())),
            patch.object(engine, "_handle_challenge", AsyncMock(side_effect=lambda url, r: (r, None))),
        ):
            response = await engine._bounded_fetch_response("https://one.example/robots.txt", on_skip=reasons.append)
    finally:
        await engine.close()
    assert response is not None and reasons == []
