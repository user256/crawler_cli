from __future__ import annotations

import gzip
from types import SimpleNamespace

import pytest

from crawler_cli.current_site_files import build_site_file_scope, collect_current_site_files
from crawler_cli.models import FetchResponse
from crawler_cli.robots import _RobotsRules


BASE = "https://example.com"


class _Robots:
    def __init__(self, rules: _RobotsRules) -> None:
        self.rules = rules

    async def get_rules(self, _url: str) -> _RobotsRules:
        return self.rules

    async def check(self, url: str):
        from urllib.parse import urlsplit

        return self.rules.check(urlsplit(url).path or "/", "crawler_cli/0.1")


class _Engine:
    def __init__(self, responses: dict[str, FetchResponse], rules: _RobotsRules) -> None:
        self.responses = responses
        self.fetched: list[str] = []
        self._robots = _Robots(rules)
        self.config = SimpleNamespace(user_agent_for=lambda _url: "crawler_cli/0.1")

    def _sitemap_url_reject_reason(self, url: str, seeds: list[str], *, check_path: bool = True):
        del check_path
        return None if url.startswith(f"{BASE}/") and seeds == [BASE] else "host_out_of_scope"

    async def _bounded_fetch_response(self, url: str):
        self.fetched.append(url)
        return self.responses.get(url)


def _response(url: str, body: bytes, content_type: str, status: int = 200) -> FetchResponse:
    return FetchResponse(
        url=url,
        requested_url=url,
        status=status,
        headers={"Content-Type": content_type, "ETag": '"fixture"'},
        body=body,
        text=body.decode("utf-8", errors="replace"),
        wire_bytes=len(body),
        decoded_bytes=len(body),
        elapsed_seconds=0.12,
    )


@pytest.mark.asyncio
async def test_collects_nested_sitemaps_and_never_fetches_robots_blocked_documents():
    root = f"{BASE}/sitemap-index.xml"
    child = f"{BASE}/nested.xml.gz"
    blocked = f"{BASE}/private-child.xml"
    root_xml = f"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>{child}</loc></sitemap>
      <sitemap><loc>{blocked}</loc></sitemap>
    </sitemapindex>""".encode()
    child_xml = f"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>{BASE}/en/a</loc><lastmod>2026-01-01</lastmod></url>
      <url><loc>{BASE}/en/a</loc></url>
      <url><loc>{BASE}/fr/b</loc><lastmod>not-a-date</lastmod></url>
    </urlset>""".encode()
    responses = {
        root: _response(root, root_xml, "application/xml"),
        child: _response(child, gzip.compress(child_xml), "application/gzip"),
        f"{BASE}/robots.txt": _response(
            f"{BASE}/robots.txt",
            f"User-agent: *\nDisallow: /private\nSitemap: {root}\n".encode(),
            "text/plain",
        ),
    }
    rules = _RobotsRules(
        "example.com",
        f"User-agent: *\nDisallow: /private\nSitemap: {root}\n",
        status=200,
    )
    engine = _Engine(responses, rules)
    result = await collect_current_site_files(
        engine,  # type: ignore[arg-type]
        seed_origins=[BASE],
        allowed_hosts=set(),
        historical_pages={f"{BASE}/en/a": {"final_status_code": 200, "overall_indexable": True}},
        max_sitemaps=10,
        max_urls=20,
        max_live_samples=0,
    )

    assert root in engine.fetched and child in engine.fetched
    assert blocked not in engine.fetched
    assert any(row.get("state") == "robots_disallowed_not_fetched" for row in result["documents"])
    entries = result["entries"]
    assert len(entries) == 3
    assert entries[0]["historical_crawl"] == "crawled"
    assert entries[2]["historical_crawl"] == "not_crawled_in_selected_run"
    assert result["duplicate_sitemap_url_count"] == 1
    assert any(item["candidate_type"] == "duplicate_sitemap_url" for item in result["validation_candidates"])
    assert any(item["candidate_type"] == "sitemap_lastmod_review" for item in result["validation_candidates"])


@pytest.mark.asyncio
async def test_malformed_declaration_unavailable_child_and_host_boundary_are_retained():
    malformed = f"{BASE}/stray.xml"
    unavailable = f"{BASE}/missing.xml"
    outside = "https://outside.example/sitemap.xml"
    robots_text = f"User-agent: *\n{malformed}\nSitemap: {unavailable}\nSitemap: {outside}\n"
    rules = _RobotsRules("example.com", robots_text, status=200)
    engine = _Engine(
        {
            f"{BASE}/robots.txt": _response(f"{BASE}/robots.txt", robots_text.encode(), "text/plain"),
            malformed: _response(
                malformed,
                b"<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9' />",
                "application/xml",
            ),
            unavailable: _response(unavailable, b"missing", "text/plain", status=503),
        },
        rules,
    )

    result = await collect_current_site_files(
        engine,  # type: ignore[arg-type]
        seed_origins=[BASE],
        allowed_hosts=set(),
        historical_pages={},
        max_sitemaps=10,
        max_urls=20,
        max_live_samples=0,
    )

    assert malformed in engine.fetched
    assert unavailable in engine.fetched
    assert outside not in engine.fetched
    assert any(
        row.get("candidate_type") == "malformed_bare_sitemap_declaration" for row in result["validation_candidates"]
    )
    assert any(row.get("reason") == "host_out_of_scope" for row in result["rejected_sitemaps"])
    assert any(row.get("state") == "http_error" for row in result["documents"])
    assert result["complete"] is False


def test_site_file_scope_blocks_unlisted_origins_and_honours_manifest_delegate():
    scope = build_site_file_scope([BASE], {"www.example.com"})

    assert scope.decide(f"{BASE}/robots.txt").allowed is True
    assert scope.decide("https://www.example.com/sitemap.xml").allowed is True
    assert scope.decide("https://other.example/sitemap.xml").allowed is False
    assert scope.decide("https://user:secret@example.com/sitemap.xml").allowed is False


@pytest.mark.asyncio
async def test_sitemap_fanout_is_bounded_before_unbounded_children_are_queued():
    root = f"{BASE}/sitemap-index.xml"
    xml = f"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>{BASE}/a.xml</loc></sitemap>
      <sitemap><loc>{BASE}/b.xml</loc></sitemap>
      <sitemap><loc>{BASE}/c.xml</loc></sitemap>
    </sitemapindex>""".encode()
    rules = _RobotsRules("example.com", f"User-agent: *\nSitemap: {root}\n", status=200)
    engine = _Engine(
        {
            root: _response(root, xml, "application/xml"),
            f"{BASE}/robots.txt": _response(f"{BASE}/robots.txt", b"", "text/plain"),
        },
        rules,
    )
    result = await collect_current_site_files(
        engine,  # type: ignore[arg-type]
        seed_origins=[BASE],
        allowed_hosts=set(),
        historical_pages={},
        max_sitemaps=2,
        max_urls=20,
        max_live_samples=0,
    )

    assert engine.fetched.count(root) == 1
    assert result["complete"] is False
    assert len(engine.fetched) <= 2
    assert any(row["reason"] == "max_sitemaps_budget" for row in result["rejected_sitemaps"])
