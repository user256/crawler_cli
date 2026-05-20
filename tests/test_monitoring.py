from __future__ import annotations

import pytest

from crawler_cli.models import FetchResponse
from crawler_cli.monitoring import extract_page, fetch_page


class StubBackend:
    def __init__(self) -> None:
        self.closed = False
        self.calls: list[str] = []

    async def fetch(self, url: str) -> FetchResponse:
        self.calls.append(url)
        return FetchResponse(
            url=url,
            requested_url=url,
            status=200,
            headers={"Content-Type": "text/html; charset=utf-8", "X-Test": "ok"},
            body=b"<html><head><title>Fetched</title></head><body>Hello</body></html>",
            text="<html><head><title>Fetched</title></head><body>Hello</body></html>",
        )

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_fetch_page_uses_backend_and_closes_it(monkeypatch):
    stub = StubBackend()

    def fake_build_backend(config):
        assert config.backend == "aiohttp"
        assert config.user_agent == "GuardGeeseBot/1.0"
        assert config.timeout_seconds == 12.5
        assert config.follow_redirects is False
        assert config.request_headers == {"X-Monitor": "1"}
        return stub

    monkeypatch.setattr("crawler_cli.monitoring.build_backend", fake_build_backend)

    result = await fetch_page(
        "https://example.com/check",
        user_agent="GuardGeeseBot/1.0",
        headers={"X-Monitor": "1"},
        timeout_seconds=12.5,
        follow_redirects=False,
    )

    assert result.status == 200
    assert stub.calls == ["https://example.com/check"]
    assert stub.closed is True


def test_extract_page_reuses_core_extraction():
    extracted = extract_page(
        """
        <html lang="en">
          <head>
            <title>GuardGeese Check</title>
            <meta name="description" content="Monitor me">
            <meta name="robots" content="noindex">
            <link rel="canonical" href="/canonical">
            <link rel="alternate" hreflang="en-gb" href="/uk">
          </head>
          <body><h1>Status</h1></body>
        </html>
        """,
        {
            "X-Robots-Tag": "nofollow",
            "Link": '<https://example.com/us>; rel="alternate"; hreflang="en-us"',
        },
        "https://example.com/check",
    )

    assert extracted.title == "GuardGeese Check"
    assert extracted.meta_description == "Monitor me"
    assert extracted.meta_robots.noindex is True
    assert extracted.x_robots_tag.nofollow is True
    assert extracted.canonical == "https://example.com/canonical"
    assert {item.hreflang for item in extracted.hreflang_links} == {"en-gb", "en-us"}
