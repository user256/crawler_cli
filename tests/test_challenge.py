"""Ticket 074: bot-challenge detection + escalate-to-browser."""

from __future__ import annotations

import pytest

from crawler_cli import CrawlConfig, CrawlEngine
from crawler_cli.challenge import detect_challenge
from crawler_cli.models import FetchResponse


# Realistic Cloudflare interstitial (the shape seen live on casino.org).
CF_INTERSTITIAL = (
    '<html lang="en-US"><head><title>Just a moment...</title>'
    '<meta http-equiv="content-security-policy" content="...challenges.cloudflare.com...">'
    '</head><body><div id="challenge-error-text"></div>'
    '<script>window._cf_chl_opt={};</script></body></html>'
)

CLEAN_PAGE = (
    "<html><head><title>Real Page</title></head>"
    "<body><h1>Hello</h1><a href='/next'>n</a></body></html>"
)


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
            url=url, requested_url=url, status=403,
            headers={"content-type": "text/html"},
            body=CF_INTERSTITIAL.encode(), text=CF_INTERSTITIAL,
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
            url=url, requested_url=url, status=200,
            headers={"content-type": "text/html"},
            body=CLEAN_PAGE.encode(), text=CLEAN_PAGE,
        )

    async def fetch_resilient(self, url):
        return await self.fetch(url)

    async def close(self):
        return None


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
    assert result.status == 200
    assert result.extracted is not None and result.extracted.title == "Real Page"


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


@pytest.mark.asyncio
async def test_engine_no_escalation_when_disabled(monkeypatch):
    engine = CrawlEngine(
        CrawlConfig(respect_robots_txt=False, detect_challenges=True,
                    challenge_escalate_to_browser=False)
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


@pytest.mark.asyncio
async def test_clean_fetch_has_no_challenge():
    engine = CrawlEngine(CrawlConfig(respect_robots_txt=False, detect_challenges=True))
    engine.backend = _CleanBrowserBackend()  # returns clean content
    result = await engine.crawl("https://easysite.test/")
    assert result.challenge is None
    assert result.status == 200
