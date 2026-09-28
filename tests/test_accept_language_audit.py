from __future__ import annotations

from types import SimpleNamespace
from typing import Callable

from aiohttp import web
import pytest

from crawler_cli.accept_language_audit import (
    ACCEPT_LANGUAGE_VARIANTS,
    collect_accept_language_evidence,
    select_accept_language_targets,
)
from crawler_cli.config import CrawlConfig
from crawler_cli.engine import CrawlEngine
from crawler_cli.models import CrawlResult, ExtractedContent, RobotsDirectives
from crawler_cli.technical_audit import TECHNICAL_AUDIT_REPORTS, audit_sheet_tables, build_technical_audit

Response = tuple[int, dict[str, str], str]
Handler = Callable[[str, str | None], Response]

_EN = "<html lang='en'><title>Home</title><body>" + "Welcome to the default home page. " * 20 + "</body></html>"
_ES = (
    "<html lang='es'><title>Inicio</title><body>"
    + "Bienvenido a la pagina principal en espanol. " * 20
    + "</body></html>"
)


def _extracted(lang: str | None) -> ExtractedContent:
    return ExtractedContent(
        title="t",
        meta_description=None,
        meta_robots=RobotsDirectives(),
        x_robots_tag=RobotsDirectives(),
        canonical=None,
        x_canonical=None,
        hreflang_links=[],
        html_lang=lang,
        headings={"h1": [], "h2": []},
        text="",
        word_count=0,
        metadata={},
    )


class _FakeEngine:
    """Records exact request headers and per-hop purposes; never touches the network."""

    def __init__(self, handler: Handler, *, blocked: set[str] | None = None) -> None:
        self.config = SimpleNamespace(follow_redirects=True, request_headers={"X-Existing": "kept"})
        self.handler = handler
        self.blocked = blocked or set()
        self.requests: list[tuple[str, str, str | None, bool]] = []

    async def crawl(self, url: str, *, purpose: str = "discovered") -> CrawlResult:
        language = self.config.request_headers.get("Accept-Language")
        assert self.config.request_headers.get("X-Existing") == "kept"
        self.requests.append((url, purpose, language, self.config.follow_redirects))
        if url in self.blocked:
            return CrawlResult(
                requested_url=url,
                final_url=url,
                status=0,
                headers={},
                content_type=None,
                fetch_backend="aiohttp",
                extracted=None,
                raw_html=None,
                skip_reason="robots_txt_disallow",
            )
        status, headers, body = self.handler(url, language)
        lang = "es" if "lang='es'" in body else ("en" if "lang='en'" in body else None)
        return CrawlResult(
            requested_url=url,
            final_url=url,
            status=status,
            headers=headers,
            content_type="text/html",
            fetch_backend="aiohttp",
            extracted=_extracted(lang) if status == 200 else None,
            raw_html=body if status == 200 else None,
        )


def _by_type(rows: list[dict[str, object]], candidate_type: str) -> list[dict[str, object]]:
    return [row for row in rows if row.get("candidate_type") == candidate_type]


@pytest.mark.asyncio
async def test_spanish_header_redirect_is_language_redirect_with_exact_request_evidence():
    def handler(url: str, language: str | None) -> Response:
        if url == "https://example.com/" and language and language.startswith("es"):
            return 302, {"Location": "/es/", "Vary": "Accept-Language"}, ""
        if url.endswith("/es/"):
            return 200, {"Vary": "Accept-Language"}, _ES
        return 200, {"Vary": "Accept-Encoding, Accept-Language"}, _EN

    engine = _FakeEngine(handler)
    rows = await collect_accept_language_evidence(engine, ["https://example.com/"])

    coverage = rows[0]
    assert coverage["record_type"] == "coverage"
    assert coverage["probe_count"] == len(ACCEPT_LANGUAGE_VARIANTS) + 1
    assert coverage["complete"] is True
    redirects = _by_type(rows, "language_redirect_detected")
    assert len(redirects) == 1
    assert redirects[0]["ticket_flag"] == "forced_language_redirect"
    assert redirects[0]["redirect_statuses"] == [302]
    assert redirects[0]["redirect_targets"] == {"es-ES": "https://example.com/es/"}
    assert not _by_type(rows, "missing_vary_header")
    assert not _by_type(rows, "bot_trap")

    es_probe = next(
        row for row in rows if row.get("observation_type") == "accept_language_probe" and row["variant"] == "es-ES"
    )
    assert es_probe["request_headers"] == {"Accept-Language": "es-ES,es;q=0.9"}
    assert es_probe["final_url"] == "https://example.com/es/"
    assert [hop["status"] for hop in es_probe["redirect_chain"]] == [302, 200]
    assert "redirect_target_changed" in es_probe["differences_from_no_header"]
    none_probe = next(
        row for row in rows if row.get("observation_type") == "accept_language_probe" and row["variant"] == "none"
    )
    assert none_probe["request_headers"] == {}

    # Redirects are followed by hand: every request disables engine following,
    # and follow-on hops are admitted as redirects rather than probes.
    assert all(follow is False for *_, follow in engine.requests)
    assert ("https://example.com/es/", "redirect", "es-ES,es;q=0.9", False) in engine.requests
    assert engine.config.follow_redirects is True
    assert engine.config.request_headers == {"X-Existing": "kept"}
    sent = {language for _, purpose, language, _ in engine.requests if purpose == "probe"}
    assert sent == {value for _, value in ACCEPT_LANGUAGE_VARIANTS}


@pytest.mark.asyncio
async def test_language_content_without_vary_is_flagged_and_neutral_access_is_clean():
    def handler(url: str, language: str | None) -> Response:
        body = _ES if language and language.startswith("es") else _EN
        return 200, {"Content-Type": "text/html"}, body

    rows = await collect_accept_language_evidence(_FakeEngine(handler), ["https://example.com/"])

    missing = _by_type(rows, "missing_vary_header")
    assert len(missing) == 1
    assert set(missing[0]["variants_missing_vary"]) == {"none", "es-ES"}
    assert set(missing[0]["differences"]["es-ES"]) >= {"html_lang_changed", "content_changed"}
    assert not _by_type(rows, "language_redirect_detected")
    neutral = next(row for row in rows if row.get("observation_type") == "neutral_access")
    assert neutral["neutral_access_state"] == "clean"
    assert neutral["content_stable_across_repeat"] is True


@pytest.mark.asyncio
async def test_identical_responses_produce_no_candidates():
    rows = await collect_accept_language_evidence(
        _FakeEngine(lambda url, language: (200, {}, _EN)), ["https://example.com/"]
    )
    assert [row for row in rows if row["record_type"] == "candidate"] == []
    assert rows[0]["candidate_counts"] == {"language_redirect_detected": 0, "missing_vary_header": 0, "bot_trap": 0}


@pytest.mark.asyncio
async def test_volatile_pages_do_not_become_content_variation():
    counter = iter(range(1000))

    def handler(url: str, language: str | None) -> Response:
        # Each response is entirely different, regardless of language.
        n = next(counter)
        return 200, {}, f"<html lang='en'><body>{'token%d ' % n * 50}{n * 7919}</body></html>"

    rows = await collect_accept_language_evidence(_FakeEngine(handler), ["https://example.com/"])
    neutral = next(row for row in rows if row.get("observation_type") == "neutral_access")
    assert neutral["content_stable_across_repeat"] is False
    assert not _by_type(rows, "missing_vary_header")


@pytest.mark.asyncio
async def test_headerless_redirect_loop_is_bot_trap():
    def handler(url: str, language: str | None) -> Response:
        if language is None or language == "*":
            target = "/en/" if url.endswith("example.com/") else "/"
            return 302, {"Location": target}, ""
        return 200, {"Vary": "Accept-Language"}, _EN

    rows = await collect_accept_language_evidence(_FakeEngine(handler), ["https://example.com/"])
    traps = _by_type(rows, "bot_trap")
    assert {row["trap_reason"] for row in traps} == {"redirect_loop"}
    assert {row["probes"][0]["variant"] for row in traps} == {"none", "wildcard"}
    neutral = next(row for row in rows if row.get("observation_type") == "neutral_access")
    assert neutral["neutral_access_state"] == "trap:redirect_loop"


@pytest.mark.asyncio
async def test_redirect_chain_is_bounded_by_hop_limit():
    def handler(url: str, language: str | None) -> Response:
        n = int(url.rsplit("/", 1)[-1] or 0)
        return 301, {"Location": f"/{n + 1}"}, ""

    engine = _FakeEngine(handler)
    rows = await collect_accept_language_evidence(engine, ["https://example.com/0"], max_redirect_hops=2)
    assert {row["trap_reason"] for row in _by_type(rows, "bot_trap")} == {"redirect_limit_exceeded"}
    assert len(engine.requests) == (len(ACCEPT_LANGUAGE_VARIANTS) + 1) * 3
    with pytest.raises(ValueError):
        await collect_accept_language_evidence(engine, ["https://example.com/"], max_redirect_hops=11)


@pytest.mark.asyncio
async def test_off_site_headerless_redirect_is_trap_but_www_alias_is_not():
    def handler(url: str, language: str | None) -> Response:
        if url == "https://example.com/":
            return 301, {"Location": "https://www.example.com/"}, ""
        if url == "https://shop.example.com/":
            return 302, {"Location": "https://geo.example.net/"}, ""
        return 200, {}, _EN

    rows = await collect_accept_language_evidence(
        _FakeEngine(handler, blocked={"https://geo.example.net/"}),
        ["https://example.com/", "https://shop.example.com/"],
    )
    traps = _by_type(rows, "bot_trap")
    assert {row["target_url"] for row in traps} == {"https://shop.example.com/"}
    assert {row["trap_reason"] for row in traps} == {"left_primary_host"}
    states = {
        row["target_url"]: row["neutral_access_state"]
        for row in rows
        if row.get("observation_type") == "neutral_access"
    }
    assert states["https://example.com/"] == "reached_after_redirects"


@pytest.mark.asyncio
async def test_robots_blocked_target_is_not_admitted_not_trap():
    rows = await collect_accept_language_evidence(
        _FakeEngine(lambda url, language: (200, {}, _EN), blocked={"https://example.com/"}),
        ["https://example.com/"],
    )
    assert not [row for row in rows if row["record_type"] == "candidate"]
    neutral = next(row for row in rows if row.get("observation_type") == "neutral_access")
    assert neutral["neutral_access_state"] == "not_admitted"
    probe = next(row for row in rows if row.get("observation_type") == "accept_language_probe")
    assert probe["redirect_chain"][0]["skip_reason"] == "robots_txt_disallow"


@pytest.mark.asyncio
async def test_set_cookie_values_are_not_recorded():
    def handler(url: str, language: str | None) -> Response:
        return 200, {"Set-Cookie": "session=SECRET; Path=/; HttpOnly, site_lang=es; Max-Age=60"}, _EN

    rows = await collect_accept_language_evidence(_FakeEngine(handler), ["https://example.com/"])
    probe = next(row for row in rows if row.get("observation_type") == "accept_language_probe")
    cookies = probe["redirect_chain"][0]["set_cookies"]
    assert cookies == [
        {"name": "session", "attributes": ["httponly", "path"], "language_cookie_name_candidate": False},
        {"name": "site_lang", "attributes": ["max-age"], "language_cookie_name_candidate": True},
    ]
    assert "SECRET" not in repr(rows)


def test_target_selection_is_bounded_roots_first_then_locale_roots():
    rows = [
        {"url": "https://example.com/de/", "kind": "html", "final_status_code": 200},
        {"url": "https://example.com/es/", "kind": "html", "final_status_code": 200},
        {"url": "https://example.com/pt-br", "kind": "html", "final_status_code": 200},
        {"url": "https://example.com/es/product", "kind": "html", "final_status_code": 200},
        {"url": "https://example.com/fr/", "kind": "html", "final_status_code": 404},
        {"url": "https://example.com/it/?x=1", "kind": "html", "final_status_code": 200},
        {"url": "https://other.test/es/", "kind": "html", "final_status_code": 200},
    ]
    targets, population = select_accept_language_targets(["https://example.com/start"], rows, max_targets=3)
    assert targets == ["https://example.com/", "https://example.com/de/", "https://example.com/es/"]
    assert population == 4
    with pytest.raises(ValueError):
        select_accept_language_targets(["https://example.com"], rows, max_targets=21)


@pytest.mark.asyncio
async def test_real_engine_sends_each_accept_language_over_loopback():
    seen: list[str | None] = []

    async def root(request: web.Request) -> web.StreamResponse:
        language = request.headers.get("Accept-Language")
        seen.append(language)
        if language and language.startswith("es"):
            raise web.HTTPFound("/es/")
        return web.Response(text=_EN, content_type="text/html")

    async def spanish(request: web.Request) -> web.Response:
        return web.Response(text=_ES, content_type="text/html")

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_get("/es/", spanish)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    # Loopback fixture server: the destination guard is off so this test
    # proves header variation and manual redirects, not address policy.
    engine = CrawlEngine(
        CrawlConfig(
            respect_robots_txt=False,
            destination_guard="off",
            max_concurrency=1,
            challenge_escalate_to_browser=False,
        )
    )
    try:
        rows = await collect_accept_language_evidence(engine, [f"http://127.0.0.1:{port}/"])
    finally:
        await engine.close()
        await runner.cleanup()

    assert seen == [value for _, value in ACCEPT_LANGUAGE_VARIANTS] + [None]
    redirects = _by_type(rows, "language_redirect_detected")
    assert len(redirects) == 1
    assert redirects[0]["redirect_targets"] == {"es-ES": f"http://127.0.0.1:{port}/es/"}
    assert _by_type(rows, "missing_vary_header")[0]["variants_missing_vary"] == ["none", "es-ES"]
    assert engine.config.follow_redirects is True


def _audit(reports: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    return build_technical_audit(
        crawl_run_id="run-1",
        reports={name: [] for name in TECHNICAL_AUDIT_REPORTS if name != "accept-language-probes"} | reports,
        run_context={"completion_state": "complete", "parsed_html_count": 1},
    )


@pytest.mark.asyncio
async def test_audit_surfaces_accept_language_check_as_analyst_evidence():
    audit = _audit({})
    check = next(item for item in audit["checks"] if item["id"] == "accept-language-variation")
    assert check["status"] == "unavailable"
    assert check["qualification"] == "requires_explicit_accept_language_probe"
    # Not requested stays visible without gating publication; the ready-gate
    # fixture in tests/test_live_rechecks.py covers the non-blocking path.

    def handler(url: str, language: str | None) -> Response:
        if language and language.startswith("es"):
            return 302, {"Location": "/es/"}, ""
        return 200, {}, _EN

    rows = await collect_accept_language_evidence(_FakeEngine(handler), ["https://example.com/"])
    audit = _audit({"accept-language-probes": rows})
    check = next(item for item in audit["checks"] if item["id"] == "accept-language-variation")
    assert check["status"] == "finding"
    assert check["denominator"] == 1
    assert {row["candidate_type"] for row in check["evidence"]} == {
        "language_redirect_detected",
        "missing_vary_header",
    }
    assert all(row["qualification"] == "analyst_only" for row in check["evidence"])
    overview = dict((row[0], row[1]) for row in audit_sheet_tables(audit)["Overview"])
    assert overview["Language redirects detected"] == 1
    assert overview["Accept-Language probe coverage complete"] is True
