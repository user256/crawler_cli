from __future__ import annotations

import pytest

from crawler_cli import CrawlConfig, CrawlEngine
from crawler_cli.__main__ import _build_config, _build_parser, _load_saved_crawl
from crawler_cli.extract import parse_html
from crawler_cli.javascript_urls import (
    extract_javascript_sources,
    resolve_javascript_literals,
    scan_javascript_literals,
)
from crawler_cli.models import FetchResponse
from crawler_cli.persistence import MemoryStore


class JavaScriptSiteBackend:
    def __init__(self, responses: dict[str, tuple[str, str]]) -> None:
        self.responses = responses
        self.fetch_counts: dict[str, int] = {}

    async def fetch(self, url: str) -> FetchResponse:
        self.fetch_counts[url] = self.fetch_counts.get(url, 0) + 1
        text, content_type = self.responses[url]
        body = text.encode("utf-8")
        return FetchResponse(
            url=url,
            requested_url=url,
            status=200,
            headers={"Content-Type": content_type},
            body=body,
            text=text,
            wire_bytes=len(body),
            decoded_bytes=len(body),
            accounted_bytes=len(body),
        )

    async def fetch_for_purpose(self, url: str, _purpose: str) -> FetchResponse:
        return await self.fetch(url)


def test_static_literal_scanner_resolves_and_classifies_without_execution() -> None:
    source = r"""
        // "/ignored-comment"
        const page = "\/products\/42?from=js#details";
        const absolute = 'https://OTHER.example:443/sale';
        const protocolRelative = "//cdn.example/image.png";
        const relative = "../offers/today";
        const query = "?view=compact";
        const api = "/api/customer";
        const action = "/account/logout";
        const secret = "/callback?access_token=do-not-store";
        const dynamic = `/products/${productId}`;
        const prose = "See /not-a-url in this sentence";
    """

    literals = scan_javascript_literals(source)
    candidates = resolve_javascript_literals(
        literals,
        "https://shop.example/catalog/item",
        source_kind="inline_script",
        script_source="https://shop.example/catalog/item#inline-script-0",
        script_index=0,
    )
    by_url = {candidate.url: candidate for candidate in candidates}

    assert "https://shop.example/products/42?from=js" in by_url
    assert by_url["https://shop.example/products/42?from=js"].classification == "page"
    assert by_url["https://shop.example/products/42?from=js"].follow_eligible is True
    assert "https://other.example/sale" in by_url
    assert by_url["https://cdn.example/image.png"].classification == "asset"
    assert by_url["https://shop.example/api/customer"].classification == "api"
    assert by_url["https://shop.example/account/logout"].classification == "action"
    assert by_url["https://shop.example/api/customer"].follow_eligible is False
    assert by_url["https://shop.example/account/logout"].follow_eligible is False
    assert all("ignored-comment" not in url for url in by_url)
    assert all("productId" not in url for url in by_url)
    assert all("not-a-url" not in url for url in by_url)
    assert all("do-not-store" not in url for url in by_url)


def test_html_source_extraction_skips_data_scripts_and_bounds_linked_files() -> None:
    html = """
    <script type="application/ld+json">{"url":"/structured-only"}</script>
    <script>const route = "/inline";</script>
    <script src="/one.js"></script>
    <script src="/one.js#duplicate"></script>
    <script type="module" src="https://cdn.example/two.mjs"></script>
    """
    inline, external = extract_javascript_sources(
        parse_html(html),
        "https://example.com/page",
        max_external_scripts=2,
    )

    assert [script.source.strip() for script in inline] == ['const route = "/inline";']
    assert external == ["https://example.com/one.js", "https://cdn.example/two.mjs"]


def test_literal_scan_stops_at_configured_unique_candidate_bound() -> None:
    source = ";".join(f'const route{index} = "/route-{index}"' for index in range(100))

    literals = scan_javascript_literals(source, max_literals=7)

    assert len(literals) == 7
    assert [literal.value for literal in literals] == [f"/route-{index}" for index in range(7)]


@pytest.mark.asyncio
async def test_default_crawl_does_not_fetch_or_scan_linked_javascript() -> None:
    backend = JavaScriptSiteBackend(
        {
            "https://example.com/": (
                '<script>const hidden="/hidden"</script><script src="/missing.js"></script>',
                "text/html",
            )
        }
    )
    engine = CrawlEngine(CrawlConfig(respect_robots_txt=False))
    engine.backend = backend

    result = await engine.crawl("https://example.com/")

    assert result.javascript_url_candidates == []
    assert backend.fetch_counts == {"https://example.com/": 1}


@pytest.mark.asyncio
async def test_shared_bundle_is_scanned_once_and_relative_values_resolve_per_document() -> None:
    backend = JavaScriptSiteBackend(
        {
            "https://example.com/a/index": (
                '<script src="/bundle.js"></script>',
                "text/html",
            ),
            "https://example.com/b/index": (
                '<script src="/bundle.js"></script>',
                "text/html",
            ),
            "https://example.com/bundle.js": (
                'const route = "child/page";',
                "text/javascript",
            ),
        }
    )
    engine = CrawlEngine(CrawlConfig(respect_robots_txt=False, discover_javascript_urls=True))
    engine.backend = backend

    job = await engine.crawl_list(["https://example.com/a/index", "https://example.com/b/index"])

    assert backend.fetch_counts["https://example.com/bundle.js"] == 1
    assert [result.javascript_url_candidates[0].url for result in job.results] == [
        "https://example.com/a/child/page",
        "https://example.com/b/child/page",
    ]


@pytest.mark.asyncio
async def test_portal_policy_scans_inline_only_without_linked_request() -> None:
    backend = JavaScriptSiteBackend(
        {
            "https://example.com/": (
                '<script>const inline="/inline"</script><script src="/guarded.js"></script>',
                "text/html",
            )
        }
    )
    config = CrawlConfig(
        respect_robots_txt=False,
        challenge_escalate_to_browser=False,
        portal_connection_policy=object(),  # type: ignore[arg-type]
        discover_javascript_urls=True,
    )
    engine = CrawlEngine(config)
    engine.backend = backend

    result = await engine.crawl("https://example.com/")

    assert [candidate.url for candidate in result.javascript_url_candidates] == ["https://example.com/inline"]
    assert backend.fetch_counts == {"https://example.com/": 1}


@pytest.mark.asyncio
async def test_discovery_inventories_inline_and_linked_js_without_following() -> None:
    page = """
    <html><body>
      <script>const inlineRoute = "/inline-route";</script>
      <script src="/bundle.js"></script>
    </body></html>
    """
    backend = JavaScriptSiteBackend(
        {
            "https://example.com/": (page, "text/html; charset=utf-8"),
            "https://example.com/bundle.js": (
                'const linkedRoute = "/linked-route"; const asset = "/chunk.js";',
                "application/javascript",
            ),
        }
    )
    store = MemoryStore()
    engine = CrawlEngine(
        CrawlConfig(
            respect_robots_txt=False,
            discover_sitemaps=False,
            discover_javascript_urls=True,
        ),
        store=store,
    )
    engine.backend = backend

    job = await engine.crawl_open(["https://example.com/"], max_urls=10)

    assert len(job.results) == 1
    assert job.javascript_url_candidate_count == 3
    assert job.javascript_url_enqueued_count == 0
    active_frontier = store.frontiers[job.run_id or ""]
    assert set(active_frontier) == {"https://example.com/"}
    persisted = store.javascript_url_candidates[(job.run_id or "", "https://example.com/")]
    assert {candidate.url for candidate in persisted} == {
        "https://example.com/inline-route",
        "https://example.com/linked-route",
        "https://example.com/chunk.js",
    }
    assert backend.fetch_counts["https://example.com/bundle.js"] == 1


@pytest.mark.asyncio
async def test_follow_flag_enqueues_only_strict_page_candidates(tmp_path) -> None:
    page = """
    <script>
      const page = "/hidden-page";
      const api = "/api/users";
      const action = "/account/logout";
      const asset = "/static/app.js";
    </script>
    """
    backend = JavaScriptSiteBackend(
        {
            "https://example.com/": (page, "text/html"),
            "https://example.com/hidden-page": ("<title>Hidden</title>", "text/html"),
        }
    )
    store = MemoryStore()
    config = CrawlConfig(
        respect_robots_txt=False,
        discover_sitemaps=False,
        follow_javascript_urls=True,
    )
    engine = CrawlEngine(config, store=store)
    engine.backend = backend

    artifact = tmp_path / "crawl.jsonl"
    job = await engine.crawl_open(
        ["https://example.com/"],
        max_urls=10,
        save_to=str(artifact),
    )

    assert config.discover_javascript_urls is True
    assert {result.final_url for result in job.results} == {
        "https://example.com/",
        "https://example.com/hidden-page",
    }
    assert job.javascript_url_candidate_count == 4
    assert job.javascript_url_enqueued_count == 1
    active_frontier = store.frontiers[job.run_id or ""]
    assert "https://example.com/api/users" not in active_frontier
    assert "https://example.com/account/logout" not in active_frontier
    assert "https://example.com/static/app.js" not in active_frontier
    assert store.sources["https://example.com/hidden-page"] == {("link", "javascript_candidate")}
    loaded = _load_saved_crawl(artifact)
    assert loaded.javascript_url_candidate_count == 4
    assert loaded.javascript_url_enqueued_count == 1
    assert {candidate.url for candidate in loaded.results[0].javascript_url_candidates} == {
        "https://example.com/hidden-page",
        "https://example.com/api/users",
        "https://example.com/account/logout",
        "https://example.com/static/app.js",
    }


def test_cli_follow_js_urls_implies_discovery_and_exposes_bounds() -> None:
    args = _build_parser().parse_args(
        [
            "crawl",
            "https://example.com/",
            "--follow-js-urls",
            "--max-js-files-per-page",
            "7",
            "--max-js-bytes",
            "12345",
            "--max-js-candidates-per-page",
            "99",
        ]
    )
    config = _build_config(args)

    assert config.discover_javascript_urls is True
    assert config.follow_javascript_urls is True
    assert config.max_javascript_files_per_page == 7
    assert config.max_javascript_bytes == 12345
    assert config.max_javascript_candidates_per_page == 99
