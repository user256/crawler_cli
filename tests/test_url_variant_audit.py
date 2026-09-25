from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from crawler_cli.models import CrawlResult, ExtractedContent, RobotsDirectives
from crawler_cli.technical_audit import parameterized_canonical_link_inventory
from crawler_cli.url_variant_audit import collect_url_variant_evidence


def _extracted(url: str, *, title: str = "A useful page") -> ExtractedContent:
    return ExtractedContent(
        title=title,
        meta_description=None,
        meta_robots=RobotsDirectives(),
        x_robots_tag=RobotsDirectives(),
        canonical=url,
        x_canonical=None,
        hreflang_links=[],
        html_lang="en",
        headings={"h1": [], "h2": []},
        text="useful page content",
        word_count=3,
        metadata={},
    )


class _ProbeEngine:
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            follow_redirects=True,
            url_admission_reason=self._admission_reason,
        )
        self.requested: list[str] = []

    @staticmethod
    def _admission_reason(url: str, *, purpose: str) -> str | None:
        assert purpose == "probe"
        return "host_out_of_scope" if urlsplit(url).hostname != "example.com" else None

    async def crawl(self, url: str) -> CrawlResult:
        self.requested.append(url)
        if "__crawler-cli-404-" in url:
            raw_html = "<html><title>Not found</title><body>Not found</body></html>"
            return CrawlResult(
                requested_url=url,
                final_url=url,
                status=200,
                headers={"Content-Type": "text/html"},
                content_type="text/html",
                fetch_backend="aiohttp",
                extracted=_extracted(url, title="Not found"),
                raw_html=raw_html,
            )
        return CrawlResult(
            requested_url=url,
            final_url=url,
            status=200,
            headers={"Content-Type": "text/html", "ETag": '"fixture"'},
            content_type="text/html",
            fetch_backend="aiohttp",
            extracted=_extracted(url),
            raw_html="<html><title>A useful page</title><body>Useful content</body></html>",
        )


@pytest.mark.asyncio
async def test_variant_probes_are_bounded_scoped_and_synthetic_only_findings():
    engine = _ProbeEngine()
    evidence = await collect_url_variant_evidence(
        engine,
        [
            {
                "url": "https://example.com/en/about",
                "kind": "html",
                "final_status_code": 200,
                "overall_indexable": True,
                "canonical_urls_json": ["https://example.com/en/about"],
                "html_lang": "en",
                "template": "article",
                "links_json": [],
            }
        ],
        max_control_pages=1,
        max_variant_probes=3,
        max_soft404_hosts=1,
    )

    assert evidence["variant_probe_count"] <= 3
    assert all("www.example.com" not in url for url in engine.requested)
    assert any(row["candidate_type"] == "soft_404_risk_review" for row in evidence["soft404_candidates"])
    assert all(
        row.get("qualification", "").endswith("review")
        or row.get("qualification", "").endswith("confirmation")
        for row in evidence["variant_candidates"]
    )
    assert all(engine.config.follow_redirects is True for _ in engine.requested)


def test_parameter_family_inventory_reconciles_instances_targets_and_sources():
    rows = [
        {
            "issues": ["parameter_target", "noncanonical_target"],
            "source_url": "https://example.com/a",
            "source_indexable": True,
            "target_url": "https://example.com/list?sort=",
            "target_canonical_url": "https://example.com/list",
            "anchor_text": "Sort",
            "xpath": "/html/body/a[1]",
        },
        {
            "issues": ["parameter_target", "noncanonical_target"],
            "source_url": "https://example.com/b",
            "source_indexable": True,
            "target_url": "https://example.com/list?sort=",
            "target_canonical_url": "https://example.com/list",
            "anchor_text": "Sort",
            "xpath": "/html/body/a[2]",
        },
        {
            "issues": ["parameter_target"],
            "source_url": "https://example.com/c",
            "target_url": "https://example.com/list?page=2",
        },
    ]

    inventory = parameterized_canonical_link_inventory(rows)
    coverage = inventory[0]

    assert coverage["parameter_family"] == "ui_state_or_search_review"
    assert coverage["link_instances"] == 2
    assert coverage["unique_targets"] == 1
    assert coverage["unique_sources"] == 2
    assert inventory[1]["parameter_keys"] == ["sort"]
    assert "https://example.com/list?page=2" not in {row.get("target_url") for row in inventory[1:]}
