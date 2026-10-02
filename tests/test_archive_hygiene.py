import pytest

from crawler_cli.archive import _clean_url, _normalize_url, discover_historical_urls
from crawler_cli.config import CrawlConfig


def test_normalize_url_strips_double_prefix():
    result = _normalize_url("https://example.com/https://other.com/page")
    assert result == "https://other.com/page"


def test_normalize_url_returns_none_for_empty():
    assert _normalize_url("   ") is None
    assert _normalize_url("") is None


def test_clean_url_drops_mailto():
    assert _clean_url("mailto:foo@example.com") is None


def test_clean_url_drops_asset_extensions():
    assert _clean_url("https://example.com/style.css") is None
    assert _clean_url("https://example.com/image.jpg") is None
    assert _clean_url("https://example.com/font.woff2") is None


def test_clean_url_drops_well_known():
    assert _clean_url("https://example.com/.well-known/security.txt") is None


def test_clean_url_keeps_html():
    result = _clean_url("https://example.com/page.html")
    assert result == "https://example.com/page.html"


def test_clean_url_strips_port():
    result = _clean_url("https://example.com:8080/page")
    assert result == "https://example.com/page"


def test_clean_url_force_https():
    result = _clean_url("http://example.com/page", force_https=True)
    assert result == "https://example.com/page"


def test_clean_url_force_www():
    result = _clean_url("https://example.com/page", force_www=True)
    assert result == "https://www.example.com/page"


def test_archive_timeout_allows_a_slow_healthy_cdx_response():
    assert CrawlConfig().archive_timeout_seconds == 60.0


@pytest.mark.asyncio
async def test_archive_discovery_uses_paginated_cdx_when_unpaged_request_fails(monkeypatch):
    requests: list[str] = []
    responses = iter(
        [
            None,
            ["https://example.com/asset.css", "https://example.com/first"],
            ["https://example.com/second"],
        ]
    )

    async def fake_fetch(endpoint, config, headers):
        requests.append(endpoint)
        return next(responses)

    monkeypatch.setattr("crawler_cli.archive._fetch_cdx_urls", fake_fetch)

    urls = await discover_historical_urls(
        "https://example.com/",
        CrawlConfig(archive_max_urls=2),
    )

    assert urls == ["https://example.com/first", "https://example.com/second"]
    assert "page=" not in requests[0]
    assert "page=0&pageSize=1" in requests[1]
    assert "page=1&pageSize=1" in requests[2]
