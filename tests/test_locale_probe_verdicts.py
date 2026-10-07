"""Q25 from the real Accept-Language collector: failed fetches and non-primary changes (tickets 412, 413)."""

from __future__ import annotations

from itertools import count
from types import SimpleNamespace
from typing import Callable

import pytest

from crawler_cli.accept_language_audit import collect_accept_language_evidence
from crawler_cli.audit_observation_adapters import locale_probe_records
from crawler_cli.audit_observations import attach_observations, collection, new_bundle
from crawler_cli.technical_audit import build_technical_audit
from crawler_cli.technical_audit_questions import answer_questions, load_question_registry

REGISTRY = load_question_registry()
ROOT = "https://one.example/"
# (status, headers, body, skip_reason)
Response = tuple[int, dict[str, str], str | None, str | None]
Handler = Callable[[str, str | None], Response]


def _page(main: str, *, head: str = "", lang: str = "en") -> str:
    return f'<html lang="{lang}"><head><title>Home</title>{head}</head><body><main>{main}</main></body></html>'


_EN_MAIN = "The same primary content. " * 100
_ES_MAIN = "El mismo contenido principal traducido. " * 100


class _Engine:
    """Deterministic engine: one ``crawl`` per hop, exactly like the guarded engine."""

    def __init__(self, handler: Handler) -> None:
        self.config = SimpleNamespace(request_headers={}, follow_redirects=True)
        self.handler = handler

    async def crawl(self, url: str, **kwargs: object) -> SimpleNamespace:
        status, headers, body, skip_reason = self.handler(url, self.config.request_headers.get("Accept-Language"))
        return SimpleNamespace(
            status=status,
            headers=headers,
            skip_reason=skip_reason,
            raw_html=body if status == 200 else None,
            extracted=SimpleNamespace(html_lang="en") if status == 200 else None,
        )


def _spanish(language: str | None) -> bool:
    return bool(language and language.startswith("es"))


def _ok(body: str) -> Response:
    return 200, {}, body, None


async def _run(handler: Handler) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    evidence = await collect_accept_language_evidence(_Engine(handler), [ROOT])
    records = locale_probe_records(evidence)
    audit = build_technical_audit(crawl_run_id="qa", reports={}, run_context={"completion_state": "complete"})
    audit = attach_observations(
        audit,
        [
            new_bundle(
                "qa",
                [collection("locale-probe", records, source="test", scope="1 root", coverage_state="complete")],
            )
        ],
    )
    answer = next(row for row in answer_questions(audit, REGISTRY) if row["id"] == "Q25")
    return evidence, records, answer


def _record(records: list[dict[str, object]], variant: str = "es-ES") -> dict[str, object]:
    return next(row for row in records if row["variant"] == variant)


def _not_confirmed(answer: dict[str, object]) -> None:
    assert answer["status"] not in {"Issue", "Healthy"}, answer
    assert answer["ticket"] is False
    assert not answer["rows"]


# --- ticket 412: a request that was never answered is untested -----------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "skip_reason",
    [
        None,  # transport failure with no recorded reason (the QA reproduction)
        "fetch_error:TimeoutError",  # what the engine records for a timeout
        "robots_txt_disallow",
        "out_of_scope",
    ],
)
async def test_unanswered_variant_is_untested_not_a_status_change(skip_reason: str | None) -> None:
    def handler(url: str, language: str | None) -> Response:
        if _spanish(language):
            return 0, {}, None, skip_reason
        return _ok(_page(_EN_MAIN))

    evidence, records, answer = await _run(handler)

    es = _record(records)
    assert es["baseline_status"] == 200 and es["variant_status"] is None
    assert "baseline_location" not in es and "variant_location" not in es
    assert es["primary_content_differs"] is None
    assert es["variant_failure"] == {
        "outcome": "fetch_error" if skip_reason is None else "not_admitted",
        "skip_reason": skip_reason,
        "hop": 0,
    }
    # The other variants resolved and stay tested, but coverage is not complete.
    assert (answer["status"], answer["answer"], answer["denominator"]) == ("Needs validation", "No (partial)", 1)
    _not_confirmed(answer)
    notes = " ".join(answer["notes"])
    assert "1 probes lack a baseline or variant status" in notes
    assert f"Requests never answered, so not compared: {skip_reason or 'fetch_error'} 1" in notes
    # The collector no longer reports 200->0 as a status change or a missing Vary.
    raw = next(r for r in evidence if r.get("observation_type") == "accept_language_probe" and r["variant"] == "es-ES")
    assert raw["differences_from_no_header"] == []
    assert not [r for r in evidence if r.get("candidate_type") == "missing_vary_header"]


@pytest.mark.asyncio
async def test_every_variant_unanswered_leaves_q25_unanswered() -> None:
    def handler(url: str, language: str | None) -> Response:
        return _ok(_page(_EN_MAIN)) if language is None else (0, {}, None, "fetch_error:ClientConnectorError")

    _, records, answer = await _run(handler)

    assert all(row["variant_status"] is None for row in records)
    assert answer["status"] == "Pending" and answer["ticket"] is False


@pytest.mark.asyncio
async def test_unanswered_baseline_makes_every_comparison_untested() -> None:
    def handler(url: str, language: str | None) -> Response:
        return (0, {}, None, None) if language is None else _ok(_page(_EN_MAIN))

    _, records, answer = await _run(handler)

    assert all(row["baseline_status"] is None and row["baseline_failure"] for row in records)
    assert answer["status"] == "Pending" and answer["ticket"] is False


@pytest.mark.asyncio
async def test_language_redirect_whose_target_fails_keeps_the_observed_redirect() -> None:
    def handler(url: str, language: str | None) -> Response:
        if url == ROOT and _spanish(language):
            return 302, {"Location": "/es/"}, "", None
        if url.endswith("/es/"):
            return 0, {}, None, "robots_txt_disallow"
        return _ok(_page(_EN_MAIN))

    _, records, answer = await _run(handler)

    es = _record(records)
    assert (es["baseline_status"], es["variant_status"]) == (200, 302)
    assert es["variant_location"] == "https://one.example/es/"
    assert es["primary_content_differs"] is None
    assert es["variant_failure"] == {
        "outcome": "redirect_target_not_admitted",
        "skip_reason": "robots_txt_disallow",
        "hop": 1,
    }
    assert (answer["status"], answer["answer"], answer["ticket"]) == ("Issue", "Yes", True)
    assert answer["rows"][0]["finding"] == "es-ES: status 200->302, Location https://one.example/es/"


@pytest.mark.asyncio
async def test_true_http_status_change_is_still_an_issue() -> None:
    def handler(url: str, language: str | None) -> Response:
        if _spanish(language):
            return 404, {}, None, None
        return _ok(_page(_EN_MAIN))

    _, records, answer = await _run(handler)

    assert (_record(records)["baseline_status"], _record(records)["variant_status"]) == (200, 404)
    assert (answer["status"], answer["answer"], answer["ticket"]) == ("Issue", "Yes", True)
    assert answer["rows"][0]["finding"] == "es-ES: status 200->404"


def test_answerer_never_treats_status_zero_as_an_http_status() -> None:
    # Saved bundles written before the fix carry 0 for an unanswered request.
    audit = build_technical_audit(crawl_run_id="qa", reports={}, run_context={"completion_state": "complete"})
    probe = {
        "url": ROOT,
        "variant": "es-ES",
        "baseline_status": 200,
        "variant_status": 0,
        "baseline_location": None,
        "variant_location": None,
        "primary_content_differs": None,
    }
    bundle = new_bundle("qa", [collection("locale-probe", [probe], source="t", scope="1", coverage_state="complete")])
    answer = next(row for row in answer_questions(attach_observations(audit, [bundle]), REGISTRY) if row["id"] == "Q25")
    assert answer["status"] == "Pending" and answer["ticket"] is False


# --- ticket 413: primary content, not raw response bytes ------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "head",
    [
        # A head script's locale (the QA reproduction).
        lambda language: f'<script>window.analyticsLocale="{"es" if _spanish(language) else "en"}";</script>',
        # Inline JSON config.
        lambda language: f'<script type="application/json">{{"locale": "{language or "default"}"}}</script>',
        # A CSP nonce and a style that rotate on every response.
        lambda language, n=count(): f'<script nonce="n{next(n)}">init()</script><style>.x{{--seed:{next(n)}}}</style>',
    ],
    ids=["head-script-locale", "inline-config", "rotating-nonce"],
)
async def test_changes_outside_primary_content_are_not_primary_content_differences(
    head: Callable[[str | None], str],
) -> None:
    def handler(url: str, language: str | None) -> Response:
        return _ok(_page(_EN_MAIN, head=head(language)))

    evidence, records, answer = await _run(handler)

    es = _record(records)
    assert es["raw_body_differs"] is True
    assert es["primary_content_differs"] is False and es["primary_content_basis"] == "main_visible_text"
    assert (answer["status"], answer["answer"], answer["ticket"]) == ("Healthy", "No", False)
    assert "differ only outside the primary content" in " ".join(answer["notes"])
    raw = next(r for r in evidence if r.get("observation_type") == "accept_language_probe" and r["variant"] == "es-ES")
    assert raw["differences_from_no_header"] == []


@pytest.mark.asyncio
async def test_rotating_primary_content_is_unknown_not_an_issue() -> None:
    tick = count()

    def handler(url: str, language: str | None) -> Response:
        n = next(tick)
        return _ok(_page(f"Promo {n} " + f"rotating offer {n * 7919} " * 50))

    _, records, answer = await _run(handler)

    assert all(row["primary_content_differs"] is None for row in records)
    assert answer["status"] == "Pending" and answer["ticket"] is False


@pytest.mark.asyncio
async def test_translated_main_content_is_a_primary_content_difference() -> None:
    def handler(url: str, language: str | None) -> Response:
        if _spanish(language):
            return _ok(_page(_ES_MAIN, lang="es"))
        return _ok(_page(_EN_MAIN))

    _, records, answer = await _run(handler)

    assert _record(records)["primary_content_differs"] is True
    assert _record(records, "de-DE")["primary_content_differs"] is False
    assert (answer["status"], answer["answer"], answer["ticket"]) == ("Issue", "Yes", True)
    assert answer["rows"][0]["finding"] == "es-ES: primary content differs"


@pytest.mark.asyncio
async def test_body_without_main_uses_visible_body_text() -> None:
    def handler(url: str, language: str | None) -> Response:
        locale = "es" if _spanish(language) else "en"
        return _ok(f"<html><head><script>var l='{locale}'</script></head><body><p>{_EN_MAIN}</p></body></html>")

    _, records, answer = await _run(handler)

    assert _record(records)["primary_content_basis"] == "body_visible_text"
    assert _record(records)["primary_content_differs"] is False
    assert answer["status"] == "Healthy"


def test_raw_body_hash_alone_never_claims_primary_content_differs() -> None:
    # Evidence without a primary-content hash (older collector output): raw bytes are review-only.
    def probe(variant: str, sha: str) -> dict[str, object]:
        return {
            "record_type": "observation",
            "observation_type": "accept_language_probe",
            "target_url": ROOT,
            "variant": variant,
            "outcome": "resolved",
            "final_status": 200,
            "body_sha256": sha,
            "redirect_chain": [{"url": ROOT, "status": 200, "location": None}],
            "qualification": "accept_language_probe_observation_requires_intent_and_crawler_access_review",
        }

    records = locale_probe_records([probe("none", "a"), probe("none-repeat", "a"), probe("es-ES", "b")])
    assert records[0]["raw_body_differs"] is True and records[0]["primary_content_differs"] is None
    assert records[0]["collection_qualification"] == (
        "accept_language_probe_observation_requires_intent_and_crawler_access_review"
    )
