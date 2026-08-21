from __future__ import annotations

import pytest

from crawler_cli import CrawlConfig, CrawlEngine
from crawler_cli.__main__ import _build_config, _build_parser
from crawler_cli.css_urls import extract_css_sources, resolve_css_tokens, scan_css_tokens
from crawler_cli.extract import parse_html
from crawler_cli.javascript_urls import resolve_javascript_literals, scan_javascript_literals
from crawler_cli.models import FetchResponse
from crawler_cli.persistence import MemoryStore


class StaticAssetBackend:
    def __init__(self, responses: dict[str, tuple[str, str]]) -> None:
        self.responses = responses
        self.fetch_counts: dict[str, int] = {}

    async def fetch(self, url: str) -> FetchResponse:
        self.fetch_counts[url] = self.fetch_counts.get(url, 0) + 1
        text, content_type = self.responses[url]
        body = text.encode()
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


def test_javascript_scanner_finds_raw_absolute_and_rejects_common_junk() -> None:
    source = r"""
        const mime = "application/json";
        const template = "/products/{slug}";
        const version = "1.2.3";
        const translation = "errors/network.timeout";
        const route = "/products/list.json";
        sourceMappingURL=https://cdn.example/app.js.map
    """
    rejected: dict[str, int] = {}

    literals = scan_javascript_literals(source, rejection_counts=rejected)
    candidates = resolve_javascript_literals(
        literals,
        "https://example.com/catalog/",
        source_kind="inline_script",
        script_source="https://example.com/#inline-script-0",
        script_index=0,
    )

    assert {candidate.url for candidate in candidates} == {
        "https://example.com/products/list.json",
        "https://cdn.example/app.js.map",
    }
    assert rejected["mime_type"] == 1
    assert rejected["unresolved_placeholder"] == 1
    assert rejected["i18n_key"] == 1


def test_dual_javascript_base_mode_is_explicit_and_provenance_rich() -> None:
    literals = scan_javascript_literals('const route = "child/page";')

    candidates = resolve_javascript_literals(
        literals,
        "https://example.com/catalog/index",
        source_kind="external_script",
        script_source="https://cdn.example/assets/app.js",
        script_index=None,
        asset_url="https://cdn.example/assets/app.js",
        relative_base_mode="document-and-asset",
    )

    assert {(candidate.url, candidate.resolution_base) for candidate in candidates} == {
        ("https://example.com/catalog/child/page", "document"),
        ("https://cdn.example/assets/child/page", "asset"),
    }


def test_css_sources_tokens_and_resolution() -> None:
    html = """
    <style>.hero { background: url('/images/hero.webp') }</style>
    <div style="background:url(icons/card.svg)"></div>
    <link rel="stylesheet preload" href="/assets/main.css">
    """
    inline, external = extract_css_sources(
        parse_html(html),
        "https://example.com/catalog/page",
        max_external_stylesheets=5,
        include_style_attributes=True,
    )
    assert external == ["https://example.com/assets/main.css"]
    assert [item.source_kind for item in inline] == ["inline_style", "style_attribute"]

    tokens = scan_css_tokens('@import "theme/base.css"; .x{src:url(../font.woff2)}')
    candidates = resolve_css_tokens(
        tokens,
        "https://cdn.example/css/main.css",
        source_kind="external_stylesheet",
        stylesheet_source="https://cdn.example/css/main.css",
        style_index=None,
    )
    assert {(item.url, item.token_kind, item.classification) for item in candidates} == {
        ("https://cdn.example/css/theme/base.css", "import", "asset"),
        ("https://cdn.example/font.woff2", "url", "asset"),
    }
    assert all(item.resolution_base == "asset" for item in candidates)


@pytest.mark.asyncio
async def test_css_discovery_fetches_bounded_imports_without_following() -> None:
    backend = StaticAssetBackend(
        {
            "https://example.com/": ('<link rel="stylesheet" href="/main.css">', "text/html"),
            "https://example.com/main.css": (
                '@import "nested.css"; .hero{background:url(/images/hero.webp)}',
                "text/css",
            ),
            "https://example.com/nested.css": (".card{background:url(card/page)}", "text/css"),
        }
    )
    engine = CrawlEngine(
        CrawlConfig(
            respect_robots_txt=False,
            discover_css_urls=True,
            max_css_import_depth=1,
        )
    )
    engine.backend = backend

    result = await engine.crawl("https://example.com/")

    assert {candidate.url for candidate in result.css_url_candidates} == {
        "https://example.com/nested.css",
        "https://example.com/images/hero.webp",
        "https://example.com/card/page",
    }
    assert backend.fetch_counts == {
        "https://example.com/": 1,
        "https://example.com/main.css": 1,
        "https://example.com/nested.css": 1,
    }


@pytest.mark.asyncio
async def test_speculative_host_cap_preserves_inventory_and_lower_priority() -> None:
    page = """
    <a href="/normal">Normal</a>
    <style>
      .one { background: url('/one') }
      .two { background: url('/two') }
      .three { background: url('/three') }
    </style>
    """
    backend = StaticAssetBackend(
        {
            "https://example.com/": (page, "text/html"),
            "https://example.com/normal": ("<title>Normal</title>", "text/html"),
            "https://example.com/one": ("<title>One</title>", "text/html"),
            "https://example.com/two": ("<title>Two</title>", "text/html"),
        }
    )
    store = MemoryStore()
    engine = CrawlEngine(
        CrawlConfig(
            respect_robots_txt=False,
            discover_sitemaps=False,
            follow_speculative_urls=True,
            max_outstanding_speculative_per_host=2,
        ),
        store=store,
    )
    engine.backend = backend

    job = await engine.crawl_open(["https://example.com/"], max_urls=10)

    assert job.css_url_candidate_count == 3
    assert job.css_url_enqueued_count == 2
    assert job.speculative_capped_count == 1
    assert "https://example.com/three" not in store.frontiers[job.run_id or ""]
    assert (
        store.frontiers[job.run_id or ""]["https://example.com/normal"]["priority_score"]
        > store.frontiers[job.run_id or ""]["https://example.com/one"]["priority_score"]
    )


def test_cli_exposes_css_and_speculative_bounds() -> None:
    args = _build_parser().parse_args(
        [
            "crawl",
            "https://example.com/",
            "--follow-speculative-urls",
            "--discover-style-attributes",
            "--js-relative-base",
            "document-and-asset",
            "--max-css-files-per-page",
            "7",
            "--max-css-bytes",
            "1234",
            "--max-css-candidates-per-page",
            "88",
            "--max-css-import-depth",
            "2",
            "--max-outstanding-speculative-per-host",
            "9",
        ]
    )
    config = _build_config(args)

    assert config.discover_javascript_urls is True
    assert config.discover_css_urls is True
    assert config.discover_style_attributes is True
    assert config.follow_speculative_urls is True
    assert config.javascript_relative_base == "document-and-asset"
    assert config.max_css_files_per_page == 7
    assert config.max_css_bytes == 1234
    assert config.max_css_candidates_per_page == 88
    assert config.max_css_import_depth == 2
    assert config.max_outstanding_speculative_per_host == 9
