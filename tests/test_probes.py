"""Soft-404 probe contract (ticket 146).

The probe borrows the live engine to make one request. The property that
matters is that it gives the engine back unchanged: it previously assigned
``engine.config`` to a local name and set ``follow_redirects = False`` on it,
which is the same object, so one probe silently disabled redirect following for
every subsequent fetch in the crawl.
"""

from __future__ import annotations

import pytest

from crawler_cli import CrawlConfig
from crawler_cli.models import CrawlResult, ExtractedContent, RobotsDirectives
from crawler_cli.probes import soft_404_fingerprint


def _extracted(title: str) -> ExtractedContent:
    return ExtractedContent(
        title=title,
        meta_description=None,
        meta_robots=RobotsDirectives(),
        x_robots_tag=RobotsDirectives(),
        canonical=None,
        x_canonical=None,
        hreflang_links=[],
        html_lang="en",
        headings={"h1": [], "h2": []},
        text="",
        word_count=0,
        metadata={},
    )


class _RecordingEngine:
    """Engine stand-in that records what the probe asked of it."""

    def __init__(self, *, status: int = 404, html: str = "<html><title>Not found</title></html>") -> None:
        self.config = CrawlConfig()
        self.status = status
        self.html = html
        self.crawled: list[str] = []
        self.follow_redirects_during_crawl: list[bool] = []

    async def crawl(self, url: str) -> CrawlResult:
        self.crawled.append(url)
        self.follow_redirects_during_crawl.append(self.config.follow_redirects)
        return CrawlResult(
            requested_url=url,
            final_url=url,
            status=self.status,
            headers={"Content-Type": "text/html"},
            content_type="text/html",
            fetch_backend="aiohttp",
            extracted=_extracted("Not found"),
            raw_html=self.html,
        )


@pytest.mark.asyncio
async def test_probe_restores_follow_redirects_on_the_live_config():
    """The regression this test exists for: the setting used to leak."""
    engine = _RecordingEngine()
    assert engine.config.follow_redirects is True

    await soft_404_fingerprint(engine, "https://example.com")

    assert engine.config.follow_redirects is True, "probe leaked follow_redirects into the live config"


@pytest.mark.asyncio
async def test_probe_disables_redirects_only_for_its_own_request():
    """It still needs the raw status, so the setting must apply during the fetch."""
    engine = _RecordingEngine()

    await soft_404_fingerprint(engine, "https://example.com")

    assert engine.follow_redirects_during_crawl == [False]


@pytest.mark.asyncio
async def test_probe_restores_the_setting_even_when_the_fetch_fails():
    class _FailingEngine(_RecordingEngine):
        async def crawl(self, url: str) -> CrawlResult:
            raise RuntimeError("network down")

    engine = _FailingEngine()
    with pytest.raises(RuntimeError):
        await soft_404_fingerprint(engine, "https://example.com")

    assert engine.config.follow_redirects is True


@pytest.mark.asyncio
async def test_probe_preserves_a_caller_who_already_disabled_redirects():
    engine = _RecordingEngine()
    engine.config.follow_redirects = False

    await soft_404_fingerprint(engine, "https://example.com")

    assert engine.config.follow_redirects is False


@pytest.mark.asyncio
async def test_probe_spends_exactly_one_request_on_one_invented_path():
    """Ticket 146: one bounded request, never a retry with more invented paths."""
    engine = _RecordingEngine()

    result = await soft_404_fingerprint(engine, "https://example.com")

    assert len(engine.crawled) == 1
    # The invented path is recorded explicitly so the operator can see exactly
    # what was requested on their site.
    assert result.tested_url == engine.crawled[0]
    assert result.tested_url.startswith("https://example.com/__crawler-cli-404-")


@pytest.mark.asyncio
async def test_probe_does_not_double_the_base_url_separator():
    engine = _RecordingEngine()

    result = await soft_404_fingerprint(engine, "https://example.com/")

    assert "//__crawler-cli-404-" not in result.tested_url


@pytest.mark.asyncio
async def test_probe_captures_the_error_page_fingerprint():
    engine = _RecordingEngine(status=200, html="<html><title>Not found</title>body</html>")

    result = await soft_404_fingerprint(engine, "https://example.com")

    assert result.status == 200
    assert result.title == "Not found"
    assert result.body_len == len(engine.html)
    assert result.simhash is not None


@pytest.mark.asyncio
async def test_probe_reports_no_simhash_without_a_body():
    engine = _RecordingEngine(html="")

    result = await soft_404_fingerprint(engine, "https://example.com")

    assert result.simhash is None
    assert result.body_len == 0
