from __future__ import annotations

import pytest

from crawler_cli.robots import RobotsPolicyCache, _RobotsRules
from crawler_cli.config import CrawlConfig


# ---------------------------------------------------------------------------
# _RobotsRules unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_returns_matched_disallow_rule():
    rules = _RobotsRules("example.com", "User-agent: *\nDisallow: /wp-admin/\n")
    decision = rules.check("/wp-admin/foo", "*")
    assert decision.allowed is False
    assert decision.matched_rule == "Disallow: /wp-admin/"
    assert decision.matched_user_agent == "*"
    assert decision.source_url == "https://example.com/robots.txt"


@pytest.mark.asyncio
async def test_check_returns_allow_override():
    rules = _RobotsRules("example.com", "User-agent: *\nDisallow: /\nAllow: /public/\n")
    decision = rules.check("/public/page", "*")
    assert decision.allowed is True
    assert decision.matched_rule == "Allow: /public/"


@pytest.mark.asyncio
async def test_check_wildcard_rule():
    rules = _RobotsRules("example.com", "User-agent: *\nDisallow: /*.pdf\n")
    decision = rules.check("/file.pdf", "*")
    assert decision.allowed is False
    assert "*.pdf" in (decision.matched_rule or "")


@pytest.mark.asyncio
async def test_check_no_match_defaults_allowed():
    rules = _RobotsRules("example.com", "User-agent: *\nDisallow: /private/\n")
    decision = rules.check("/public/page", "*")
    assert decision.allowed is True
    assert decision.matched_rule is None


# ---------------------------------------------------------------------------
# Longest-match precedence (RFC 9309 §2.2.2)
# ---------------------------------------------------------------------------

def test_longest_match_wins_over_order():
    """A more-specific (longer) rule wins even if it appears earlier in the file."""
    content = "User-agent: *\nDisallow: /\nAllow: /public/\n"
    rules = _RobotsRules("example.com", content)
    # /public/ (len 8) beats / (len 1) → allowed
    assert rules.check("/public/page", "*").allowed is True
    # /other/ only matches /, no Allow → disallowed
    assert rules.check("/other/page", "*").allowed is False


def test_allow_wins_tie_on_equal_length():
    """Equal-length conflicting rules: Allow beats Disallow (RFC 9309)."""
    content = "User-agent: *\nDisallow: /path\nAllow: /path\n"
    rules = _RobotsRules("example.com", content)
    assert rules.check("/path/sub", "*").allowed is True


def test_disallow_longer_beats_allow_shorter():
    """Longer Disallow beats shorter Allow."""
    content = "User-agent: *\nAllow: /\nDisallow: /private/\n"
    rules = _RobotsRules("example.com", content)
    assert rules.check("/private/doc", "*").allowed is False
    assert rules.check("/public/doc", "*").allowed is True


# ---------------------------------------------------------------------------
# Case-insensitive user-agent matching
# ---------------------------------------------------------------------------

def test_ua_exact_case_insensitive():
    content = "User-agent: MyCrawler\nDisallow: /secret/\nUser-agent: *\nDisallow:\n"
    rules = _RobotsRules("example.com", content)
    # Our UA exactly matches (case-insensitive)
    decision = rules.check("/secret/page", "mycrawler")
    assert decision.allowed is False
    assert decision.matched_user_agent == "MyCrawler"


def test_ua_product_token_match():
    """Group 'crawler_cli' matches UA 'crawler_cli/0.1'."""
    content = "User-agent: crawler_cli\nDisallow: /admin/\nUser-agent: *\nDisallow:\n"
    rules = _RobotsRules("example.com", content)
    decision = rules.check("/admin/page", "crawler_cli/0.1")
    assert decision.allowed is False
    assert decision.matched_user_agent == "crawler_cli"


def test_ua_falls_back_to_wildcard_when_no_group_matches():
    content = "User-agent: googlebot\nDisallow: /\nUser-agent: *\nDisallow: /private/\n"
    rules = _RobotsRules("example.com", content)
    decision = rules.check("/private/x", "crawler_cli/0.1")
    assert decision.allowed is False
    assert decision.matched_user_agent == "*"
    # But we shouldn't hit the googlebot Disallow: /
    decision2 = rules.check("/public/x", "crawler_cli/0.1")
    assert decision2.allowed is True


# ---------------------------------------------------------------------------
# Scheme in source_url
# ---------------------------------------------------------------------------

def test_source_url_uses_provided_scheme():
    rules = _RobotsRules("localhost", "", scheme="http")
    assert rules.source_url == "http://localhost/robots.txt"


def test_source_url_defaults_to_https():
    rules = _RobotsRules("example.com", "")
    assert rules.source_url == "https://example.com/robots.txt"


# ---------------------------------------------------------------------------
# Empty Disallow = allow-all (RFC 9309 §2.2.3)
# ---------------------------------------------------------------------------

def test_empty_disallow_is_allow_all():
    content = "User-agent: *\nDisallow:\n"
    rules = _RobotsRules("example.com", content)
    assert rules.check("/anything", "*").allowed is True


# ---------------------------------------------------------------------------
# RobotsPolicyCache fetch-and-parse: 4xx → allow-all, 5xx → disallow/failed
# ---------------------------------------------------------------------------

class _FakeSession:
    """Minimal aiohttp.ClientSession stand-in."""
    def __init__(self, status: int, body: str = "") -> None:
        self._status = status
        self._body = body

    def get(self, url, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    @property
    def status(self):
        return self._status

    @property
    def headers(self):
        return {}

    async def text(self, **kwargs):
        return self._body


@pytest.mark.asyncio
async def test_404_robots_allows_all(monkeypatch):
    """4xx response → treat as no robots.txt → allow everything."""
    config = CrawlConfig(respect_robots_txt=True)
    cache = RobotsPolicyCache(config)

    async def fake_fetch(url):
        return None, {}, 404

    monkeypatch.setattr(cache, "_fetch_robots_txt", fake_fetch)
    assert await cache.is_allowed("https://example.com/anything") is True


@pytest.mark.asyncio
async def test_5xx_robots_marks_failed_and_allows(monkeypatch):
    """5xx response → mark failed → subsequent checks allow (conservative allow for session)."""
    config = CrawlConfig(respect_robots_txt=True)
    cache = RobotsPolicyCache(config)

    async def fake_fetch(url):
        return None, {}, 503

    monkeypatch.setattr(cache, "_fetch_robots_txt", fake_fetch)
    # First call marks failed
    await cache.is_allowed("https://example.com/page")
    # mark_failed → is_failed → returns True (allow) from check()
    assert cache.cache.is_failed("example.com") is True


@pytest.mark.asyncio
async def test_network_error_marks_failed(monkeypatch):
    config = CrawlConfig(respect_robots_txt=True)
    cache = RobotsPolicyCache(config)

    async def fake_fetch(url):
        return None, {}, 0

    monkeypatch.setattr(cache, "_fetch_robots_txt", fake_fetch)
    await cache.is_allowed("https://example.com/page")
    assert cache.cache.is_failed("example.com") is True


# ---------------------------------------------------------------------------
# Scheme-correct robots fetch URL
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_robots_fetched_with_correct_scheme(monkeypatch):
    """http:// URLs must fetch robots.txt over http://, not https://."""
    config = CrawlConfig(respect_robots_txt=True)
    cache = RobotsPolicyCache(config)

    fetched_urls: list[str] = []

    async def recording_fetch(url):
        fetched_urls.append(url)
        return "", {}, 200

    monkeypatch.setattr(cache, "_fetch_robots_txt", recording_fetch)

    # The URL passed to _fetch_and_parse is the full page URL, so
    # it must derive the robots URL from the correct scheme.
    await cache._fetch_and_parse("http://localhost:8080/page")
    assert fetched_urls[0].startswith("http://"), f"Expected http scheme, got: {fetched_urls[0]}"
