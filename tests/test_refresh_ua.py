"""Tests for crawl parity: --refresh-days staleness + --ua per-domain UA (ticket 080)."""

from __future__ import annotations

import pytest

from crawler_cli.backends import _request_headers
from crawler_cli.config import CrawlConfig, parse_ua_map


# --------------------------------------------------------------------------
# UA map parsing + resolution precedence
# --------------------------------------------------------------------------


def test_parse_ua_map_basic():
    m = parse_ua_map(["casino.org=Screaming Frog/1.0", "example.com=Bot/2"])
    assert m == {"casino.org": "Screaming Frog/1.0", "example.com": "Bot/2"}


def test_parse_ua_map_rejects_malformed():
    with pytest.raises(ValueError, match="--ua expects"):
        parse_ua_map(["no-equals-sign"])
    with pytest.raises(ValueError):
        parse_ua_map(["=only-ua"])


def test_user_agent_for_exact_and_subdomain_and_fallback():
    cfg = CrawlConfig(user_agent="default-UA", ua_map={"casino.org": "SF/1.0"})
    assert cfg.user_agent_for("https://casino.org/x") == "SF/1.0"
    assert cfg.user_agent_for("https://www.casino.org/x") == "SF/1.0"  # subdomain
    assert cfg.user_agent_for("https://de.casino.org/y") == "SF/1.0"
    assert cfg.user_agent_for("https://othersite.com/x") == "default-UA"  # fallback
    # Not a subdomain: casino.org.evil.com must NOT match casino.org.
    assert cfg.user_agent_for("https://casino.org.evil.com/x") == "default-UA"
    # An explicit port in the URL must not defeat the match (hostname, not netloc).
    assert cfg.user_agent_for("http://casino.org:8080/x") == "SF/1.0"


def test_user_agent_for_no_map_uses_default():
    cfg = CrawlConfig(user_agent="only-UA")
    assert cfg.user_agent_for("https://anything.com") == "only-UA"


# --------------------------------------------------------------------------
# Backend header pass-through (aiohttp / curl_cffi share _request_headers)
# --------------------------------------------------------------------------


def test_request_headers_uses_per_domain_ua():
    cfg = CrawlConfig(user_agent="default-UA", ua_map={"casino.org": "SF/1.0"})
    h1 = _request_headers(cfg, "https://www.casino.org/page")
    assert h1["User-Agent"] == "SF/1.0"
    h2 = _request_headers(cfg, "https://elsewhere.com/page")
    assert h2["User-Agent"] == "default-UA"


def test_obscura_argv_uses_per_domain_ua():
    from crawler_cli.backends import ObscuraFetchBackend

    cfg = CrawlConfig(backend="playwright", user_agent="default-UA", ua_map={"casino.org": "SF/1.0"})
    backend = ObscuraFetchBackend.__new__(ObscuraFetchBackend)
    backend.config = cfg
    backend._binary = "/usr/bin/obscura"
    backend._stealth = False
    backend._proxy_pool = None
    argv = backend._build_argv("https://sub.casino.org/x", raw=False)
    assert "--user-agent" in argv
    assert argv[argv.index("--user-agent") + 1] == "SF/1.0"
    argv2 = backend._build_argv("https://other.com/x", raw=False)
    assert argv2[argv2.index("--user-agent") + 1] == "default-UA"


# --------------------------------------------------------------------------
# --refresh-days staleness filtering in the engine
# --------------------------------------------------------------------------


class FakeRefreshStore:
    """Records enqueue calls and answers the staleness query from a fixed set."""

    def __init__(self, fresh_urls):
        self._fresh = set(fresh_urls)
        self.enqueued: list = []

    async def urls_fetched_since(self, urls, cutoff_epoch):
        return {u for u in urls if u in self._fresh}

    async def enqueue_frontier(self, frontier_data, *, source=None, source_detail=None):
        self.enqueued.extend(frontier_data)
        return len(frontier_data)


@pytest.mark.asyncio
async def test_enqueue_frontier_skips_fresh_urls():
    from crawler_cli.engine import CrawlEngine

    cfg = CrawlConfig(refresh_days=30)
    store = FakeRefreshStore(fresh_urls={"https://a.com/fresh"})
    engine = CrawlEngine(cfg, store=store)

    frontier = [
        ("https://a.com/fresh", 0, None, 0.0),  # fetched recently -> skipped
        ("https://a.com/stale", 0, None, 0.0),  # aged out -> enqueued
        ("https://a.com/new", 0, None, 0.0),  # never fetched -> enqueued
    ]
    inserted = await engine._enqueue_frontier(frontier, source="seed")
    enqueued_urls = {item[0] for item in store.enqueued}
    assert enqueued_urls == {"https://a.com/stale", "https://a.com/new"}
    assert engine._refresh_skipped == 1
    assert inserted == 2
    await engine.close()


@pytest.mark.asyncio
async def test_enqueue_frontier_no_refresh_enqueues_all():
    from crawler_cli.engine import CrawlEngine

    cfg = CrawlConfig(refresh_days=0)  # disabled -> refetch everything
    store = FakeRefreshStore(fresh_urls={"https://a.com/fresh"})
    engine = CrawlEngine(cfg, store=store)
    frontier = [("https://a.com/fresh", 0, None, 0.0), ("https://a.com/x", 0, None, 0.0)]
    await engine._enqueue_frontier(frontier, source="seed")
    assert len(store.enqueued) == 2
    assert engine._refresh_skipped == 0
    await engine.close()
