from __future__ import annotations

import pytest

from crawler_cli.robots import RobotsPolicyCache, _RobotsRules, _path_with_query
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


def test_question_mark_is_literal_not_single_char_wildcard():
    """'?' in a robots rule is literal (RFC 9309), not fnmatch's single-char
    wildcard. The common Magento rule "Disallow: /*?" must only block URLs that
    actually contain a query string, not every path."""
    rules = _RobotsRules("example.com", "User-agent: *\nDisallow: /*?\nAllow: /*?p=\n")
    # Paths without a '?' are allowed.
    assert rules.check("/cladding/", "*").allowed is True
    assert rules.check("/cladding/cedar/tgv", "*").allowed is True
    # Paths with a '?' are blocked...
    assert rules.check("/cladding/?foo=1", "*").allowed is False
    # ...unless an Allow override matches (longer rule wins).
    assert rules.check("/cladding/?p=2", "*").allowed is True


def test_dollar_anchors_end_of_path():
    rules = _RobotsRules("example.com", "User-agent: *\nDisallow: /*.php$\n")
    assert rules.check("/index.php", "*").allowed is False
    # The '$' anchors the end, so a trailing query string means no match.
    assert rules.check("/index.php?x=1", "*").allowed is True


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
# Consecutive User-agent lines = one shared group; combine repeated groups
# ---------------------------------------------------------------------------


def test_consecutive_user_agent_lines_share_rules():
    content = "User-agent: a\nUser-agent: b\nDisallow: /private/\nCrawl-delay: 2.5\nUser-agent: *\nDisallow:\n"
    rules = _RobotsRules("example.com", content)
    assert rules.check("/private/x", "a").allowed is False
    assert rules.check("/private/x", "b").allowed is False
    assert rules.check("/public/x", "a").allowed is True
    assert rules.crawl_delay("a") == 2.5
    assert rules.crawl_delay("b") == 2.5
    # Wildcard group is separate and empty Disallow → allow-all
    assert rules.check("/private/x", "otherbot").allowed is True


def test_sitemap_between_user_agents_does_not_split_group():
    content = "User-agent: a\nSitemap: https://example.com/sitemap.xml\nUser-agent: b\nDisallow: /g\n"
    rules = _RobotsRules("example.com", content)
    assert rules.check("/g/page", "a").allowed is False
    assert rules.check("/g/page", "b").allowed is False
    assert rules.sitemaps() == ["https://example.com/sitemap.xml"]


def test_repeated_matching_groups_are_combined():
    content = (
        "User-agent: newsbot\n"
        "Disallow: /fish\n"
        "User-agent: *\n"
        "Disallow: /carrots\n"
        "User-agent: newsbot\n"
        "Disallow: /shrimp\n"
    )
    rules = _RobotsRules("example.com", content)
    assert rules.check("/fish", "newsbot").allowed is False
    assert rules.check("/shrimp", "newsbot").allowed is False
    # Specific groups are not merged with *
    assert rules.check("/carrots", "newsbot").allowed is True


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


def test_path_with_query_helper():
    assert _path_with_query("https://example.com/path") == "/path"
    assert _path_with_query("https://example.com/path?q=1") == "/path?q=1"
    assert _path_with_query("https://example.com") == "/"
    assert _path_with_query("https://example.com/?q=1") == "/?q=1"


# ---------------------------------------------------------------------------
# RobotsPolicyCache fetch-and-parse: 4xx → allow-all, 5xx → disallow
# ---------------------------------------------------------------------------


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
async def test_5xx_robots_marks_failed_and_disallows(monkeypatch):
    """5xx → mark failed → check() disallows (RFC 9309 §2.3.1.4)."""
    config = CrawlConfig(respect_robots_txt=True)
    cache = RobotsPolicyCache(config)

    async def fake_fetch(url):
        return None, {}, 503

    monkeypatch.setattr(cache, "_fetch_robots_txt", fake_fetch)
    decision = await cache.check("https://example.com/page")
    assert cache.cache.is_failed("example.com") is True
    assert decision.allowed is False
    assert decision.matched_rule == "robots.txt unreachable"
    # Subsequent checks stay disallowed without re-fetch.
    assert await cache.is_allowed("https://example.com/other") is False


@pytest.mark.asyncio
async def test_network_error_marks_failed_and_disallows(monkeypatch):
    config = CrawlConfig(respect_robots_txt=True)
    cache = RobotsPolicyCache(config)

    async def fake_fetch(url):
        return None, {}, 0

    monkeypatch.setattr(cache, "_fetch_robots_txt", fake_fetch)
    assert await cache.is_allowed("https://example.com/page") is False
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


# ---------------------------------------------------------------------------
# End-to-end RobotsPolicyCache.check (not only _RobotsRules.check)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_policy_cache_matches_query_rules(monkeypatch):
    """Query-sensitive rules must work through RobotsPolicyCache.check(url)."""
    body = "User-agent: *\nDisallow: /*?\nAllow: /*?p=\n"
    config = CrawlConfig(respect_robots_txt=True, user_agent="crawler_cli/0.1")
    cache = RobotsPolicyCache(config)

    async def fake_fetch(url):
        return body, {}, 200

    monkeypatch.setattr(cache, "_fetch_robots_txt", fake_fetch)

    assert (await cache.check("https://example.com/cladding/")).allowed is True
    assert (await cache.check("https://example.com/cladding/?foo=1")).allowed is False
    assert (await cache.check("https://example.com/cladding/?p=2")).allowed is True


@pytest.mark.asyncio
async def test_policy_cache_consecutive_ua_groups(monkeypatch):
    body = "User-agent: AlphaBot\nUser-agent: BetaBot\nDisallow: /secret/\nUser-agent: *\nDisallow:\n"
    config = CrawlConfig(respect_robots_txt=True, user_agent="AlphaBot/1.0")
    cache = RobotsPolicyCache(config)

    async def fake_fetch(url):
        return body, {}, 200

    monkeypatch.setattr(cache, "_fetch_robots_txt", fake_fetch)

    assert (await cache.check("https://example.com/secret/x")).allowed is False
    # Same cached rules, different UA via ua_map
    cache.config = CrawlConfig(
        respect_robots_txt=True,
        user_agent="other/1.0",
        ua_map={"example.com": "BetaBot/2.0"},
    )
    assert (await cache.check("https://example.com/secret/x")).allowed is False
    cache.config = CrawlConfig(respect_robots_txt=True, user_agent="GammaBot/1.0")
    assert (await cache.check("https://example.com/secret/x")).allowed is True


@pytest.mark.asyncio
async def test_policy_cache_uses_per_url_user_agent(monkeypatch):
    body = "User-agent: SpecialBot\nDisallow: /blocked/\nUser-agent: *\nDisallow:\n"
    config = CrawlConfig(
        respect_robots_txt=True,
        user_agent="DefaultBot/1.0",
        ua_map={"special.example.com": "SpecialBot/9.0"},
    )
    cache = RobotsPolicyCache(config)

    async def fake_fetch(url):
        return body, {}, 200

    monkeypatch.setattr(cache, "_fetch_robots_txt", fake_fetch)

    # Default UA matches * → allowed
    assert (await cache.check("https://example.com/blocked/x")).allowed is True
    # Per-domain UA matches SpecialBot → disallowed
    assert (await cache.check("https://special.example.com/blocked/x")).allowed is False


@pytest.mark.asyncio
async def test_policy_cache_crawl_delay_uses_per_url_ua(monkeypatch):
    body = "User-agent: SpecialBot\nCrawl-delay: 7\nDisallow:\nUser-agent: *\nCrawl-delay: 1\nDisallow:\n"
    config = CrawlConfig(
        respect_robots_txt=True,
        user_agent="DefaultBot/1.0",
        ua_map={"special.example.com": "SpecialBot/9.0"},
    )
    cache = RobotsPolicyCache(config)

    async def fake_fetch(url):
        return body, {}, 200

    monkeypatch.setattr(cache, "_fetch_robots_txt", fake_fetch)

    assert await cache.get_crawl_delay("https://example.com/") == 1.0
    assert await cache.get_crawl_delay("https://special.example.com/") == 7.0


@pytest.mark.asyncio
async def test_fetch_robots_uses_effective_ua_and_proxy(monkeypatch):
    """Robots fetch must use user_agent_for + proxy_auth, not bare config.proxy."""
    config = CrawlConfig(
        respect_robots_txt=True,
        user_agent="DefaultBot/1.0",
        ua_map={"example.com": "MappedBot/2.0"},
        proxy="http://proxy.example:8080",
        proxy_auth="bob:secret",
        request_headers={"Authorization": "Bearer leak-me", "X-Custom": "nope"},
        cookies={"session": "should-not-leak"},
    )
    cache = RobotsPolicyCache(config)

    captured: dict = {}

    class _Resp:
        status = 200
        headers = {}

        async def text(self, **kwargs):
            return "User-agent: *\nDisallow:\n"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class _Session:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def get(self, url, **kwargs):
            captured["url"] = url
            captured["headers"] = dict(kwargs.get("headers") or {})
            captured["proxy"] = kwargs.get("proxy")
            return _Resp()

    monkeypatch.setattr("crawler_cli.robots.aiohttp.ClientSession", _Session)

    content, _headers, status = await cache._fetch_robots_txt("https://example.com/page")
    assert status == 200
    assert content is not None
    assert captured["url"] == "https://example.com/robots.txt"
    assert captured["headers"]["User-Agent"] == "MappedBot/2.0"
    assert "Authorization" not in captured["headers"]
    assert "Cookie" not in captured["headers"]
    assert "X-Custom" not in captured["headers"]
    assert captured["proxy"] == "http://bob:secret@proxy.example:8080"


@pytest.mark.asyncio
async def test_fetch_robots_uses_proxy_pool(monkeypatch):
    config = CrawlConfig(
        respect_robots_txt=True,
        proxies=["http://a.proxy:1", "http://b.proxy:1"],
        proxy_mode="list",
        proxy_rotation="round-robin",
    )
    cache = RobotsPolicyCache(config)
    assert cache._proxy_pool is not None

    captured: list[str | None] = []

    class _Resp:
        status = 404
        headers = {}

        async def text(self, **kwargs):
            return ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class _Session:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def get(self, url, **kwargs):
            captured.append(kwargs.get("proxy"))
            return _Resp()

    monkeypatch.setattr("crawler_cli.robots.aiohttp.ClientSession", _Session)

    await cache._fetch_robots_txt("https://example.com/")
    assert captured[0] in {"http://a.proxy:1", "http://b.proxy:1"}
