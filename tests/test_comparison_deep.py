from crawler_cli.comparison import compare, compare_deep
from crawler_cli.models import CrawlJobResult, CrawlResult, DiscoveredLink, ExtractedContent, RobotsDirectives


def _result(
    url: str,
    *,
    title: str | None = None,
    h1: list[str] | None = None,
    meta: str | None = None,
    words: int = 0,
    canonical: str | None = None,
    sha: str | None = None,
    requested: str | None = None,
    schema_types: list[str] | None = None,
    links: list[DiscoveredLink] | None = None,
) -> CrawlResult:
    schema_data = [{"type": t, "format": "json-ld", "is_valid": True} for t in (schema_types or [])]
    extracted = ExtractedContent(
        title=title,
        meta_description=meta,
        meta_robots=RobotsDirectives(),
        x_robots_tag=RobotsDirectives(),
        canonical=canonical,
        x_canonical=None,
        hreflang_links=[],
        html_lang=None,
        headings={"h1": h1 or [], "h2": []},
        text="",
        word_count=words,
        metadata={},
        schema_data=schema_data,
    )
    return CrawlResult(
        requested_url=requested or url,
        final_url=url,
        status=200,
        headers={},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=extracted,
        raw_html="<html></html>",
        content_hash_sha256=sha,
        discovered_links=links or [],
    )


def test_compare_deep_detects_metadata_and_schema_and_links():
    baseline = CrawlJobResult(
        mode="list",
        seed_urls=[],
        results=[
            _result(
                "https://example.com/page",
                title="Old",
                h1=["Old H1"],
                meta="Old meta",
                words=100,
                sha="aaa",
                schema_types=["Article"],
                links=[DiscoveredLink("https://example.com/a", "A", "/html/body/a[1]", False)],
            )
        ],
    )
    candidate = CrawlJobResult(
        mode="list",
        seed_urls=[],
        results=[
            _result(
                "https://example.com/page",
                title="New",
                h1=["New H1"],
                meta="New meta",
                words=120,
                sha="bbb",
                schema_types=["Product"],
                links=[DiscoveredLink("https://example.com/b", "B", "/html/body/a[2]", False)],
            ),
            _result("https://example.com/new-page", title="Fresh"),
        ],
    )

    diff = compare_deep(baseline, candidate, compare_links=True)
    assert diff.missing_urls == []
    assert diff.new_urls == ["https://example.com/new-page"]
    assert "/page" in diff.title_changes
    assert "/page" in diff.h1_changes
    assert "/page" in diff.meta_description_changes
    assert diff.word_count_changes["/page"].candidate == 120
    assert diff.schema_changes["/page"] == (["Article"], ["Product"])
    assert "/page" in diff.link_changes


def test_compare_wrapper_still_returns_basic_diff():
    baseline = CrawlJobResult(mode="list", seed_urls=[], results=[_result("https://example.com/a", sha="1")])
    candidate = CrawlJobResult(mode="list", seed_urls=[], results=[_result("https://example.com/b", sha="2")])
    diff = compare(baseline, candidate)
    assert diff.missing_urls == ["https://example.com/a"]
    assert diff.new_urls == ["https://example.com/b"]


def test_compare_deep_detects_url_moves():
    baseline = CrawlJobResult(
        mode="list",
        seed_urls=[],
        results=[
            _result(
                "https://example.com/new-path",
                requested="https://example.com/old-path",
            )
        ],
    )
    candidate = CrawlJobResult(
        mode="list",
        seed_urls=[],
        results=[_result("https://example.com/new-path")],
    )
    diff = compare_deep(baseline, candidate)
    assert len(diff.url_moves) == 1
    assert diff.url_moves[0].from_path == "/old-path"
    assert diff.url_moves[0].to_path == "/new-path"
