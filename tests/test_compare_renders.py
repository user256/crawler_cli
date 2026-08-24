import pytest

from crawler_cli import CrawlConfig, CrawlEngine
from crawler_cli.__main__ import (
    _build_parser,
    _collect_seed_urls,
    _render_comparison_payload,
    _run_compare_renders,
    _write_render_comparison_html,
    _write_render_comparison_output,
)
from crawler_cli.compare_renders import _cluster_paths, compare_rendered_result, compare_renders
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


def _same_navigation_result(raw_html: str, rendered_html: str, *, settled: bool | None = True) -> CrawlResult:
    headers = {"Content-Type": "text/html; charset=utf-8"}
    return CrawlResult(
        requested_url="https://example.com/",
        final_url="https://example.com/",
        status=200,
        headers=headers,
        content_type=headers["Content-Type"],
        fetch_backend="playwright",
        extracted=extract_page_data(rendered_html, "https://example.com/", headers),
        raw_html=rendered_html,
        render_raw_html=raw_html,
        render_settled=settled,
    )


def test_same_navigation_comparison_reports_multiple_indexing_findings():
    raw = """<html><head><title>Raw</title><meta name='robots' content='index'>
    <link rel='canonical' href='/raw'></head><body><h1>Raw heading</h1><a href='/old'>Old</a></body></html>"""
    rendered = """<html><head><title>Rendered</title><meta name='robots' content='noindex'>
    <link rel='canonical' href='/rendered'></head><body><h1>Rendered heading</h1><a href='/new'>New</a></body></html>"""

    comparison = compare_rendered_result(_same_navigation_result(raw, rendered))

    assert comparison.state == "complete"
    assert comparison.primary_summary in {"canonical_changed", "indexing_directive_changed"}
    assert {finding.code for finding in comparison.findings} >= {
        "metadata_render_dependency",
        "canonical_changed",
        "indexing_directive_changed",
        "internal_links_added_after_render",
        "internal_links_removed_after_render",
    }
    assert comparison.only_in_rendered == {"https://example.com/new"}
    assert comparison.only_in_raw == {"https://example.com/old"}


def test_same_navigation_missing_baseline_is_inconclusive_not_ok():
    result = _same_navigation_result("<html></html>", "<html><body>Rendered</body></html>")
    result.render_raw_html = None

    comparison = compare_rendered_result(result)

    assert comparison.state == "inconclusive"
    assert comparison.primary_summary == "inconclusive"
    assert comparison.findings[0].code == "render_comparison_incomplete"


def test_same_navigation_truncated_baseline_is_inconclusive_not_ok():
    result = _same_navigation_result("<html></html>", "<html><body>Rendered</body></html>")
    result.render_baseline_truncated = True

    comparison = compare_rendered_result(result)

    assert comparison.state == "inconclusive"
    assert comparison.state_reason == "render_baseline_truncated"


def test_same_navigation_reports_structured_data_changes():
    comparison = compare_rendered_result(
        _same_navigation_result(
            '<html><head><script type=\'application/ld+json\'>{"@context": "https://schema.org", "@type": "Article"}</script></head></html>',
            '<html><head><script type=\'application/ld+json\'>{"@context": "https://schema.org", "@type": "Product"}</script></head></html>',
        )
    )

    finding = next(finding for finding in comparison.findings if finding.code == "structured_data_changed")

    assert finding.field == "structured_data"
    assert finding.raw_value != finding.rendered_value


def test_cluster_paths_parses_absolute_urls_not_schemes():
    clusters = _cluster_paths(
        {
            "https://example.com/products/a",
            "https://example.com/products/b",
            "https://example.com/blog/c",
        }
    )

    assert clusters == {"products": 2, "blog": 1}


def test_render_comparison_outputs_redact_sensitive_url_values(tmp_path):
    comparison = compare_rendered_result(
        _same_navigation_result(
            "<html><body><a href='/old?token=supersecret'>Old</a></body></html>",
            "<html><body><a href='/new?token=supersecret'>New</a></body></html>",
        )
    )
    comparison.url = "https://example.com/?token=supersecret"
    payload = _render_comparison_payload([comparison], selected_urls=[comparison.url], capped=False)
    output = tmp_path / "comparison.json"
    report = tmp_path / "comparison.html"
    _write_render_comparison_output(payload, str(output))
    _write_render_comparison_html(payload, str(report))

    assert "supersecret" not in output.read_text(encoding="utf-8")
    assert "supersecret" not in report.read_text(encoding="utf-8")
    assert "[REDACTED]" in output.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_compare_renders_cli_writes_versioned_output_without_second_fetch(monkeypatch, tmp_path):
    comparison = compare_rendered_result(
        _same_navigation_result("<html><title>Raw</title></html>", "<html><title>Rendered</title></html>")
    )

    async def fake_compare(_engine, urls, *, max_concurrent):
        assert list(urls) == ["https://example.com/"]
        assert max_concurrent == 1
        return [comparison]

    monkeypatch.setattr("crawler_cli.__main__.compare_rendered_sample", fake_compare)
    output = tmp_path / "parity.json"
    args = _build_parser().parse_args(["compare-renders", "https://example.com/", "--output", str(output)])

    assert await _run_compare_renders(args) == 0
    assert '"schema_version": "crawler-cli/render-comparison/1"' in output.read_text(encoding="utf-8")


def test_compare_renders_cli_accepts_multiple_positional_urls():
    args = _build_parser().parse_args(["compare-renders", "https://example.com/", "https://example.com/about/"])

    assert _collect_seed_urls(args) == ["https://example.com/", "https://example.com/about/"]
