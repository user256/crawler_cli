from crawler_cli.comparison import compare
from crawler_cli.models import CrawlJobResult, CrawlResult


def _result(url: str, canonical: str | None, sha: str | None) -> CrawlResult:
    from crawler_cli.models import ExtractedContent, RobotsDirectives

    extracted = ExtractedContent(
        title=None,
        meta_description=None,
        meta_robots=RobotsDirectives(),
        x_robots_tag=RobotsDirectives(),
        canonical=canonical,
        x_canonical=None,
        hreflang_links=[],
        html_lang=None,
        headings={"h1": [], "h2": []},
        text="",
        word_count=0,
        metadata={},
    )
    return CrawlResult(
        requested_url=url,
        final_url=url,
        status=200,
        headers={},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=extracted,
        raw_html="<html></html>",
        content_hash_sha256=sha,
    )


def test_compare_detects_missing_new_and_changed_metadata():
    baseline = CrawlJobResult(
        mode="list",
        seed_urls=[],
        results=[_result("https://example.com/a", "https://example.com/canon-a", "aaa")],
    )
    candidate = CrawlJobResult(
        mode="list",
        seed_urls=[],
        results=[_result("https://example.com/b", "https://example.com/canon-b", "bbb")],
    )

    diff = compare(baseline, candidate)
    assert diff.missing_urls == ["https://example.com/a"]
    assert diff.new_urls == ["https://example.com/b"]

