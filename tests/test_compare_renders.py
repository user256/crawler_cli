import pytest

from crawler_cli import CrawlConfig, CrawlEngine
from crawler_cli.compare_renders import _cluster_paths, compare_renders
from crawler_cli.extract import extract_page_data
from crawler_cli.models import CrawlResult, FetchResponse


class StaticBackend:
    def __init__(self, html: str, status: int = 200) -> None:
        self.html = html
        self.status = status

    async def fetch(self, url: str) -> FetchResponse:
        return FetchResponse(
            url=url,
            requested_url=url,
            status=self.status,
            headers={"Content-Type": "text/html; charset=utf-8"},
            body=self.html.encode(),
            text=self.html,
        )


@pytest.mark.asyncio
async def test_compare_renders_static_page_ok(monkeypatch):
    html = "<html><head><title>Hello</title></head><body><a href='/a'>A</a></body></html>"
    config = CrawlConfig(backend="aiohttp")

    async def fake_crawl(self, url: str) -> CrawlResult:
        return CrawlResult(
            requested_url=url,
            final_url=url,
            status=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content_type="text/html; charset=utf-8",
            fetch_backend=self.config.backend,
            extracted=extract_page_data(html, url, {"Content-Type": "text/html; charset=utf-8"}),
            raw_html=html,
        )

    monkeypatch.setattr(CrawlEngine, "crawl", fake_crawl)

    # Both nojs and js use same backend in this test
    result = await compare_renders(
        "https://example.com/",
        nojs_config=config,
        js_config=config,
    )
    assert result.verdict == "ok"
    assert result.title_match is True
    assert result.canonical_match is True


def test_cluster_paths_groups_correctly():
    paths = {"/products/a", "/products/b", "/blog/c", "/about"}
    clusters = _cluster_paths(paths)
    assert clusters["products"] == 2
    assert clusters["blog"] == 1
    assert clusters["about"] == 1
