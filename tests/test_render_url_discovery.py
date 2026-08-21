from __future__ import annotations

import pytest

from crawler_cli import BrowserRequestObservation, CrawlConfig, CrawlEngine
from crawler_cli.__main__ import _build_config, _build_parser
from crawler_cli.models import FetchResponse
from crawler_cli.persistence import MemoryStore


def response(
    url: str,
    html: str,
    *,
    raw_text: str | None = None,
    observed: list[BrowserRequestObservation] | None = None,
) -> FetchResponse:
    body = html.encode()
    return FetchResponse(
        url=url,
        requested_url=url,
        status=200,
        headers={"Content-Type": "text/html"},
        body=body,
        text=html,
        raw_text=raw_text,
        observed_requests=observed or [],
        wire_bytes=len(body),
        decoded_bytes=len(body),
        accounted_bytes=len(body),
    )


class MappingBackend:
    def __init__(self, responses: dict[str, FetchResponse]) -> None:
        self.responses = responses
        self.fetch_counts: dict[str, int] = {}
        self.closed = False

    async def fetch(self, url: str) -> FetchResponse:
        self.fetch_counts[url] = self.fetch_counts.get(url, 0) + 1
        return self.responses[url]

    async def fetch_for_purpose(self, url: str, _purpose: str) -> FetchResponse:
        return await self.fetch(url)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_http_render_gate_skips_link_rich_or_script_light_pages() -> None:
    raw = '<a href="/one">One</a><script></script><script></script>'
    backend = MappingBackend({"https://example.com/": response("https://example.com/", raw)})
    engine = CrawlEngine(CrawlConfig(respect_robots_txt=False, discover_render_urls=True))
    engine.backend = backend

    result = await engine.crawl("https://example.com/")

    assert result.render_discovery_attempted is False
    assert result.render_discovery_skip_reason == "render_gate_too_few_scripts"
    assert result.render_url_candidates == []
    assert engine._render_discovery_backend is None


@pytest.mark.asyncio
async def test_selective_render_records_dom_delta_and_network_without_replay() -> None:
    raw = "<script></script><script></script><script></script>"
    hydrated = raw + '<a href="/hydrated">Hydrated</a>'
    main = MappingBackend({"https://example.com/": response("https://example.com/", raw)})
    rendered = MappingBackend(
        {
            "https://example.com/": response(
                "https://example.com/",
                hydrated,
                raw_text=raw,
                observed=[
                    BrowserRequestObservation(
                        url="https://example.com/api/products",
                        method="GET",
                        resource_type="fetch",
                        outcome="finished",
                        status=200,
                    )
                ],
            )
        }
    )
    engine = CrawlEngine(CrawlConfig(respect_robots_txt=False, discover_render_urls=True))
    engine.backend = main
    engine._render_discovery_backend = rendered  # type: ignore[assignment]

    result = await engine.crawl("https://example.com/")

    by_kind = {candidate.source_kind: candidate for candidate in result.render_url_candidates}
    assert by_kind["render_dom"].url == "https://example.com/hydrated"
    assert by_kind["render_dom"].follow_eligible is True
    assert by_kind["render_network"].url == "https://example.com/api/products"
    assert by_kind["render_network"].classification == "api"
    assert by_kind["render_network"].follow_eligible is False
    assert result.render_discovery_attempted is True
    assert result.render_discovery_complete is True
    assert main.fetch_counts == {"https://example.com/": 1}
    assert rendered.fetch_counts == {"https://example.com/": 1}


@pytest.mark.asyncio
async def test_follow_rendered_links_enqueues_dom_only() -> None:
    raw = "<script></script><script></script><script></script>"
    main = MappingBackend(
        {
            "https://example.com/": response("https://example.com/", raw),
            "https://example.com/hydrated": response(
                "https://example.com/hydrated",
                "<title>Hydrated</title>",
            ),
        }
    )
    rendered = MappingBackend(
        {
            "https://example.com/": response(
                "https://example.com/",
                raw + '<a href="/hydrated">Hydrated</a>',
                raw_text=raw,
                observed=[
                    BrowserRequestObservation(
                        url="https://example.com/api/private",
                        method="POST",
                        resource_type="fetch",
                        outcome="finished",
                        status=204,
                    )
                ],
            )
        }
    )
    store = MemoryStore()
    engine = CrawlEngine(
        CrawlConfig(
            respect_robots_txt=False,
            discover_sitemaps=False,
            follow_rendered_links=True,
        ),
        store=store,
    )
    engine.backend = main
    engine._render_discovery_backend = rendered  # type: ignore[assignment]

    job = await engine.crawl_open(["https://example.com/"], max_urls=5)

    assert job.render_dom_enqueued_count == 1
    assert "https://example.com/hydrated" in store.frontiers[job.run_id or ""]
    assert "https://example.com/api/private" not in store.frontiers[job.run_id or ""]
    assert store.sources["https://example.com/hydrated"] == {("link", "render_dom_candidate")}


@pytest.mark.asyncio
async def test_playwright_mode_reuses_current_render_and_raw_baseline() -> None:
    raw = '<a href="/raw">Raw</a>'
    hydrated = raw + '<a href="/added">Added</a>'
    backend = MappingBackend(
        {
            "https://example.com/": response(
                "https://example.com/",
                hydrated,
                raw_text=raw,
                observed=[
                    BrowserRequestObservation(
                        url="https://cdn.example/app.js",
                        method="GET",
                        resource_type="script",
                        outcome="finished",
                        status=200,
                    )
                ],
            )
        }
    )
    engine = CrawlEngine(
        CrawlConfig(
            backend="playwright",
            respect_robots_txt=False,
            discover_render_urls=True,
        )
    )
    engine.backend = backend

    result = await engine.crawl("https://example.com/")

    assert {(item.source_kind, item.url) for item in result.render_url_candidates} == {
        ("render_dom", "https://example.com/added"),
        ("render_network", "https://cdn.example/app.js"),
    }
    assert backend.fetch_counts == {"https://example.com/": 1}
    assert engine._render_discovery_backend is None


def test_cli_render_flags_and_portal_validation() -> None:
    args = _build_parser().parse_args(
        [
            "crawl",
            "https://example.com/",
            "--follow-rendered-links",
            "--render-discover-max-raw-links",
            "8",
            "--render-discover-min-scripts",
            "2",
            "--max-render-discovery-pages",
            "11",
            "--max-render-discovery-concurrency",
            "2",
            "--max-render-requests-per-page",
            "77",
            "--max-render-links-per-page",
            "66",
        ]
    )
    config = _build_config(args)

    assert config.discover_render_urls is True
    assert config.follow_rendered_links is True
    assert config.render_discovery_max_raw_links == 8
    assert config.render_discovery_min_scripts == 2
    assert config.max_render_discovery_pages == 11
    assert config.max_render_discovery_concurrency == 2
    assert config.max_render_requests_per_page == 77
    assert config.max_render_links_per_page == 66

    with pytest.raises(ValueError, match="browser subrequests are not policy-guarded"):
        CrawlConfig(
            challenge_escalate_to_browser=False,
            portal_connection_policy=object(),  # type: ignore[arg-type]
            discover_render_urls=True,
        )
