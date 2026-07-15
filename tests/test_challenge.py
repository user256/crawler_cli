"""Ticket 074/089: bot-challenge detection, escalate-to-browser, hard-stop persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crawler_cli import CrawlConfig, CrawlEngine
from crawler_cli.challenge import detect_challenge
from crawler_cli.models import CrawlJobResult, CrawlResult, ExtractedContent, FetchResponse, RobotsDirectives
from crawler_cli.persistence import MemoryStore
from crawler_cli.serialization import serialize_crawl_job


# Realistic Cloudflare interstitial (the shape seen live on casino.org).
CF_INTERSTITIAL = (
    '<html lang="en-US"><head><title>Just a moment...</title>'
    '<meta http-equiv="content-security-policy" content="...challenges.cloudflare.com...">'
    '</head><body><div id="challenge-error-text"></div>'
    "<script>window._cf_chl_opt={};</script>"
    "<a href='/next'>should not enqueue</a></body></html>"
)

CLEAN_PAGE = "<html><head><title>Real Page</title></head><body><h1>Hello</h1><a href='/next'>n</a></body></html>"


# --- detector ---


def test_detects_cloudflare_interstitial_body():
    assert detect_challenge(403, {}, CF_INTERSTITIAL) == "cloudflare"


def test_detects_cloudflare_via_header():
    assert detect_challenge(503, {"cf-mitigated": "challenge"}, "") == "cloudflare"


def test_clean_page_is_not_a_challenge():
    assert detect_challenge(200, {"content-type": "text/html"}, CLEAN_PAGE) is None


def test_plain_403_without_markers_is_not_a_challenge():
    # A legitimate 403 with no interstitial signature must not false-positive.
    assert detect_challenge(403, {}, "<html><body>Forbidden</body></html>") is None


def test_detects_datadome_cookie():
    assert detect_challenge(403, {"set-cookie": "datadome=abc; Path=/"}, "") == "datadome"


def test_detects_akamai_abck_cookie():
    assert detect_challenge(429, {"set-cookie": "_abck=xyz; Path=/"}, "") == "akamai"


def test_detects_imperva_incap_cookie():
    assert detect_challenge(403, {"set-cookie": "incap_ses_123=v; Path=/"}, "") == "imperva"


def test_cloudflare_marker_without_status_still_detected():
    # __cf_chl_ marker present even on a 200-wrapped challenge.
    body = "<html><head><title>Just a moment...</title></head><body>__cf_chl_opt</body></html>"
    assert detect_challenge(200, {}, body) == "cloudflare"


# --- engine escalation ---


class _ChallengedHTTPBackend:
    """HTTP backend that always returns a Cloudflare interstitial."""

    def __init__(self):
        self.calls = 0

    async def fetch(self, url):
        self.calls += 1
        return FetchResponse(
            url=url,
            requested_url=url,
            status=403,
            headers={"content-type": "text/html"},
            body=CF_INTERSTITIAL.encode(),
            text=CF_INTERSTITIAL,
        )

    async def fetch_resilient(self, url):
        return await self.fetch(url)

    async def close(self):
        return None


class _CleanBrowserBackend:
    """Stands in for the escalation browser backend: returns real content."""

    def __init__(self):
        self.calls = 0

    async def fetch(self, url):
        self.calls += 1
        return FetchResponse(
            url=url,
            requested_url=url,
            status=200,
            headers={"content-type": "text/html"},
            body=CLEAN_PAGE.encode(),
            text=CLEAN_PAGE,
        )

    async def fetch_resilient(self, url):
        return await self.fetch(url)

    async def close(self):
        return None


def _empty_extracted(title: str = "Prior") -> ExtractedContent:
    return ExtractedContent(
        title=title,
        meta_description=None,
        meta_robots=RobotsDirectives(),
        x_robots_tag=RobotsDirectives(),
        canonical=None,
        x_canonical=None,
        hreflang_links=[],
        html_lang=None,
        headings={},
        text="prior content",
        word_count=2,
        metadata={},
    )


@pytest.mark.asyncio
async def test_engine_escalates_challenge_to_browser(monkeypatch):
    engine = CrawlEngine(CrawlConfig(respect_robots_txt=False, detect_challenges=True))
    http_backend = _ChallengedHTTPBackend()
    browser = _CleanBrowserBackend()
    engine.backend = http_backend

    async def _fake_get_browser():
        return browser

    monkeypatch.setattr(engine, "_get_challenge_backend", _fake_get_browser)
    # ensure the escalation isinstance check treats the HTTP backend as non-browser
    monkeypatch.setattr(engine, "_is_browser_backend", lambda b: b is browser)

    result = await engine.crawl("https://hardsite.test/")

    assert browser.calls == 1, "should have escalated to the browser backend"
    assert result.challenge is None, "challenge cleared after escalation"
    assert result.skip_reason is None
    assert result.status == 200
    assert result.extracted is not None and result.extracted.title == "Real Page"
    assert result.discovered_links, "successful escalation still discovers links"


@pytest.mark.asyncio
async def test_engine_records_blocked_when_escalation_still_challenged(monkeypatch):
    engine = CrawlEngine(CrawlConfig(respect_robots_txt=False, detect_challenges=True))
    http_backend = _ChallengedHTTPBackend()
    still_blocked = _ChallengedHTTPBackend()  # browser also gets challenged
    engine.backend = http_backend

    async def _fake_get_browser():
        return still_blocked

    monkeypatch.setattr(engine, "_get_challenge_backend", _fake_get_browser)
    monkeypatch.setattr(engine, "_is_browser_backend", lambda b: b is still_blocked)

    result = await engine.crawl("https://hardsite.test/")

    assert result.challenge == "cloudflare", "still blocked → challenge recorded"
    assert result.skip_reason == "bot_challenge"
    assert result.extracted is None
    assert result.raw_html is None
    assert result.discovered_links == []
    assert result.content_hash_sha256 is None


@pytest.mark.asyncio
async def test_engine_no_escalation_when_disabled(monkeypatch):
    engine = CrawlEngine(
        CrawlConfig(respect_robots_txt=False, detect_challenges=True, challenge_escalate_to_browser=False)
    )
    http_backend = _ChallengedHTTPBackend()
    engine.backend = http_backend

    called = {"browser": False}

    async def _fake_get_browser():
        called["browser"] = True
        return _CleanBrowserBackend()

    monkeypatch.setattr(engine, "_get_challenge_backend", _fake_get_browser)

    result = await engine.crawl("https://hardsite.test/")

    assert called["browser"] is False, "escalation disabled → no browser fetch"
    assert result.challenge == "cloudflare"
    assert result.skip_reason == "bot_challenge"
    assert result.extracted is None
    assert result.raw_html is None
    assert result.discovered_links == []


@pytest.mark.asyncio
async def test_clean_fetch_has_no_challenge():
    engine = CrawlEngine(CrawlConfig(respect_robots_txt=False, detect_challenges=True))
    engine.backend = _CleanBrowserBackend()  # returns clean content
    result = await engine.crawl("https://easysite.test/")
    assert result.challenge is None
    assert result.skip_reason is None
    assert result.status == 200


@pytest.mark.asyncio
async def test_unresolved_challenge_suppresses_hashing_and_custom_extract(monkeypatch):
    from crawler_cli.custom_extract import CustomExtractor, ExtractionRule

    engine = CrawlEngine(
        CrawlConfig(
            respect_robots_txt=False,
            detect_challenges=True,
            challenge_escalate_to_browser=False,
            enable_content_hashing=True,
            extraction_rules=[ExtractionRule(name="title", type="css", selector="title")],
        )
    )
    engine.backend = _ChallengedHTTPBackend()
    # Prove custom extractor would run if hard-stop failed.
    assert engine._custom_extractor is not None
    extract_calls = {"n": 0}
    real_extract = engine._custom_extractor.extract

    def _counting_extract(html: str):
        extract_calls["n"] += 1
        return real_extract(html)

    monkeypatch.setattr(engine._custom_extractor, "extract", _counting_extract)

    result = await engine.crawl("https://hardsite.test/")

    assert result.challenge == "cloudflare"
    assert result.skip_reason == "bot_challenge"
    assert result.content_hash_sha256 is None
    assert result.content_hash_simhash is None
    assert result.custom_data is None
    assert extract_calls["n"] == 0
    assert isinstance(engine._custom_extractor, CustomExtractor)


@pytest.mark.asyncio
async def test_challenge_counts_are_mutually_exclusive():
    blocked = CrawlResult(
        requested_url="https://hardsite.test/",
        final_url="https://hardsite.test/",
        status=403,
        headers={"content-type": "text/html"},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=None,
        raw_html=None,
        skip_reason="bot_challenge",
        challenge="cloudflare",
    )
    ok = CrawlResult(
        requested_url="https://easysite.test/",
        final_url="https://easysite.test/",
        status=200,
        headers={"content-type": "text/html"},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=_empty_extracted("Ok"),
        raw_html=CLEAN_PAGE,
    )
    job = CrawlJobResult(mode="list", seed_urls=[], results=[blocked, ok])
    assert job.crawled_count == 1
    assert job.challenge_blocked_count == 1
    assert job.crawled_count + job.challenge_blocked_count == len(job.results)


@pytest.mark.asyncio
async def test_open_crawl_does_not_enqueue_links_from_challenge(tmp_path: Path):
    store = MemoryStore()
    engine = CrawlEngine(
        CrawlConfig(
            respect_robots_txt=False,
            detect_challenges=True,
            challenge_escalate_to_browser=False,
            same_host_only=True,
            discover_sitemaps=False,
            max_concurrency=1,
            default_open_crawl_limit=10,
        ),
        store=store,
    )
    engine.backend = _ChallengedHTTPBackend()

    save_to = str(tmp_path / "out.jsonl")
    job = await engine.crawl_open(["https://hardsite.test/"], save_to=save_to, max_urls=5)

    assert job.challenge_blocked_count == 1
    assert job.crawled_count == 0
    assert len(job.results) == 1
    assert job.results[0].discovered_links == []
    # Only the seed should have been enqueued; /next must never enter the frontier.
    frontier = store._frontier_for(job.run_id)
    assert set(frontier.keys()) == {"https://hardsite.test/"}
    assert store.saved_metadata["crawl_open"]["challenge_blocked_count"] == 1
    assert store.saved_metadata["crawl_open"]["crawled_count"] == 0

    lines = Path(save_to).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2  # result + summary
    result_line = json.loads(lines[0])
    summary = json.loads(lines[1])
    assert result_line["challenge"] == "cloudflare"
    assert result_line["skip_reason"] == "bot_challenge"
    assert result_line["extracted"] is None
    assert result_line["raw_html"] is None
    assert summary["__type"] == "summary"
    assert summary["challenge_blocked_count"] == 1
    assert summary["crawled_count"] == 0


def test_serialize_crawl_job_includes_challenge_counts():
    blocked = CrawlResult(
        requested_url="https://hardsite.test/",
        final_url="https://hardsite.test/",
        status=403,
        headers={},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=None,
        raw_html=None,
        skip_reason="bot_challenge",
        challenge="cloudflare",
    )
    payload = serialize_crawl_job(CrawlJobResult(mode="list", seed_urls=[], results=[blocked]))
    assert payload["challenge_blocked_count"] == 1
    assert payload["crawled_count"] == 0
    assert payload["persist_error_count"] == 0
