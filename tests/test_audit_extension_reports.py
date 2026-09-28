from __future__ import annotations

import pytest

from crawler_cli.compression import compress_html
from crawler_cli.reports import CrawlReports


class StubReports(CrawlReports):
    def __init__(self, rows):
        self.rows = rows
        self.store = None  # type: ignore[assignment]
        self.run_id = "run-a"

    async def _run_id(self) -> str:
        return "run-a"

    async def _fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        return self.rows


class GraphStore:
    async def get_crawl_run(self, _run_id):
        return {"status": "complete", "seed_urls": ["https://e.test/seed"]}


class GraphReports(StubReports):
    def __init__(self, pages):
        super().__init__(pages)
        self.store = GraphStore()


@pytest.mark.asyncio
async def test_orphans_uses_same_run_snapshot_inlinks_not_frontier_seed_provenance():
    reports = GraphReports(
        [
            {
                "url": "https://e.test/seed",
                "kind": "html",
                "links_json": [{"href": "https://e.test/target"}],
                "content_extracted": True,
                "render_discovery_attempted": False,
            },
            {
                "url": "https://e.test/target",
                "kind": "html",
                "links_json": [{"href": "https://e.test/seed"}],
                "content_extracted": True,
                "render_discovery_attempted": False,
            },
            {
                "url": "https://e.test/orphan",
                "kind": "html",
                "links_json": [],
                "content_extracted": True,
                "render_discovery_attempted": False,
            },
        ]
    )
    findings = await reports.orphan_pages()
    assert [row["url"] for row in findings] == ["https://e.test/orphan"]
    assert findings[0]["graph_complete"] is True


@pytest.mark.asyncio
async def test_incomplete_render_graph_does_not_claim_complete_orphan_coverage():
    reports = GraphReports(
        [
            {
                "url": "https://e.test/a",
                "kind": "html",
                "links_json": [],
                "content_extracted": True,
                "render_discovery_attempted": True,
                "render_discovery_complete": False,
            }
        ]
    )
    assert (await reports.orphan_pages())[0]["graph_complete"] is False


@pytest.mark.asyncio
async def test_sitemap_known_urls_join_same_run_graph_with_source_and_history_state():
    reports = GraphReports(
        [
            {
                "url": "https://e.test/seed",
                "kind": "html",
                "links_json": [{"href": "https://e.test/linked"}],
                "content_extracted": True,
                "render_discovery_attempted": False,
                "final_status_code": 200,
                "overall_indexable": True,
                "canonical_urls_json": ["https://e.test/seed"],
            },
            {
                "url": "https://e.test/linked",
                "kind": "html",
                "links_json": [],
                "content_extracted": True,
                "render_discovery_attempted": False,
                "final_status_code": 200,
                "overall_indexable": True,
                "canonical_urls_json": ["https://e.test/linked"],
            },
        ]
    )
    findings = await reports.orphan_pages(
        known_urls=[
            {
                "url": "https://e.test/linked",
                "source": "sitemap",
                "observed_at": "2026-09-25T12:00:00+00:00",
                "source_sitemap": "https://e.test/sitemap.xml",
                "historical_status": "200",
                "historical_indexable": "True",
                "historical_canonical_state": "declared_self",
            },
            {
                "url": "https://e.test/sitemap-only",
                "source": "sitemap",
                "observed_at": "2026-09-25T12:00:00+00:00",
                "source_sitemap": "https://e.test/sitemap.xml",
            },
            {"url": "https://outside.test/unjoined", "source": "sitemap"},
        ]
    )
    by_url = {row["url"]: row for row in findings}
    linked = by_url["https://e.test/linked"]
    assert linked["candidate_type"] == "source_known_with_observed_inlinks"
    assert linked["source_labels"] == ["sitemap"]
    assert linked["http_status"] == 200
    assert linked["overall_indexable"] is True
    assert linked["canonical_state"] == "declared_self"
    sitemap_only = by_url["https://e.test/sitemap-only"]
    assert sitemap_only["candidate_type"] == "source_known_zero_observed_inlinks"
    assert sitemap_only["source_sitemaps"] == ["https://e.test/sitemap.xml"]
    assert sitemap_only["graph_complete"] is True
    assert by_url["https://outside.test/unjoined"]["candidate_type"] == "source_inventory_out_of_scope"


@pytest.mark.asyncio
async def test_link_graph_reports_unique_nodes_and_instances_separately():
    reports = GraphReports(
        [
            {
                "url": "https://e.test/seed",
                "kind": "html",
                "links_json": [
                    {"href": "https://e.test/child"},
                    {"href": "https://e.test/child"},
                ],
                "content_extracted": True,
                "render_discovery_attempted": False,
            },
            {
                "url": "https://e.test/child",
                "kind": "html",
                "links_json": [],
                "content_extracted": True,
                "render_discovery_attempted": False,
            },
        ]
    )
    metrics = (await reports.link_graph_metrics())[0]
    assert metrics["unique_sources"] == 1
    assert metrics["unique_targets"] == 1
    assert metrics["link_instances"] == 2
    assert metrics["max_depth"] == 1


@pytest.mark.asyncio
async def test_internal_link_quality_retains_multiple_issues_and_redirect_identity():
    reports = StubReports(
        [
            {
                "source_url": "https://e.test/source",
                "source_indexable": True,
                "link_evidence": {
                    "href": "https://e.test/broken?ref=x",
                    "anchor_text": "",
                    "xpath": "/html/body/a[1]",
                    "original_href": "/broken?ref=x",
                    "discovery_source": "html_anchor",
                },
                "target_initial_status": 404,
                "target_status": 404,
                "target_final_url_id": 2,
                "target_url_id": 2,
                "target_indexable": False,
                "html_meta_allows": False,
                "http_header_allows": True,
                "canonical_urls_json": [],
            },
            {
                "source_url": "https://e.test/source",
                "source_indexable": True,
                "link_evidence": {"href": "https://e.test/old", "anchor_text": "Moved", "xpath": "/a[2]"},
                "target_initial_status": 301,
                "target_status": 200,
                "target_final_url_id": 4,
                "target_url_id": 3,
                "target_indexable": True,
                "html_meta_allows": True,
                "http_header_allows": True,
                "canonical_urls_json": ["https://e.test/new"],
            },
        ]
    )
    rows = await reports.internal_link_quality()
    assert rows[0]["issues"] == [
        "empty_anchor",
        "error_target",
        "noindex_target",
        "non_indexable_target",
        "parameter_target",
    ]
    assert rows[0]["issue"] == "error_target"
    assert rows[0]["source_indexable"] is True
    assert rows[0]["xpath"] == "/html/body/a[1]"
    assert rows[1]["issues"] == ["redirect_target", "noncanonical_target"]


@pytest.mark.asyncio
async def test_tracking_parameter_links_only_returns_known_tracking_keys():
    reports = StubReports(
        [
            {"source_url": "https://e.test/", "target_url": "https://e.test/a?utm_source=nav&page=2"},
            {"source_url": "https://e.test/", "target_url": "https://e.test/b?page=2"},
        ]
    )
    assert await reports.tracking_parameter_links() == [
        {
            "source_url": "https://e.test/",
            "target_url": "https://e.test/a?utm_source=nav&page=2",
            "tracking_parameters": "utm_source",
        }
    ]


@pytest.mark.asyncio
async def test_tracking_parameter_links_excludes_external_links():
    reports = StubReports(
        [
            {"source_url": "https://e.test/", "target_url": "https://other.test/a?utm_source=nav"},
        ]
    )
    assert await reports.tracking_parameter_links() == []


@pytest.mark.asyncio
async def test_similarity_uses_main_content_and_separates_exact_from_near():
    shared = "<nav>same large shared navigation boilerplate</nav>"
    first = f"<html>{shared}<main>apple banana cedar ember market analysis topic A</main></html>"
    different = f"<html>{shared}<main>ocean mountain river valley forest climate research topic B</main></html>"
    reports = StubReports(
        [
            {"url": "https://e.test/a", "html_compressed": compress_html(first), "eligible_population": 3},
            {"url": "https://e.test/a-copy", "html_compressed": compress_html(first), "eligible_population": 3},
            {"url": "https://e.test/b", "html_compressed": compress_html(different), "eligible_population": 3},
        ]
    )
    rows = await reports.near_duplicates(threshold=0)
    exact_pairs = [row for row in rows if row["match_kind"] == "exact_primary_content"]
    assert [{row["url"], row["near_duplicate_url"]} for row in exact_pairs] == [
        {"https://e.test/a", "https://e.test/a-copy"}
    ]
    assert all(row["match_kind"] != "exact_primary_content" for row in rows if row["url"] == "https://e.test/b")
    coverage = (await reports.similarity_coverage())[0]
    assert coverage["eligible_population"] == 3
    assert coverage["sampled_population"] == 3
    assert coverage["missing_primary_hashes"] == 0


@pytest.mark.asyncio
async def test_similarity_reports_missing_hashes_instead_of_claiming_a_pass():
    reports = StubReports([{"url": "https://e.test/no-html", "html_compressed": None, "eligible_population": 1}])
    assert await reports.near_duplicates() == []
    coverage = (await reports.similarity_coverage())[0]
    assert coverage["missing_primary_hashes"] == 1
    assert coverage["truncated"] is False


@pytest.mark.asyncio
async def test_similarity_limit_is_hard_bounded_and_population_truncation_is_explicit():
    class CappedReports(StubReports):
        def __init__(self):
            super().__init__(
                [
                    {
                        "url": "https://e.test/a",
                        "html_compressed": compress_html("<main>one</main>"),
                        "eligible_population": 6001,
                    }
                ]
            )
            self.fetch_args = ()

        async def _fetch(self, query: str, *args: object) -> list[dict[str, object]]:
            self.fetch_args = args
            return self.rows

    reports = CappedReports()
    await reports.near_duplicates(limit=6001)
    assert reports.fetch_args[-1] == 5000
    coverage = (await reports.similarity_coverage())[0]
    assert coverage["sample_limit"] == 5000
    assert coverage["truncated"] is True


@pytest.mark.asyncio
async def test_internal_authority_rewards_linked_page_and_handles_sink():
    reports = GraphReports(
        [
            {
                "url": "https://e.test/a",
                "kind": "html",
                "overall_indexable": True,
                "canonical_urls_json": [],
                "content_extracted": True,
                "render_discovery_attempted": False,
                "links_json": [{"href": "https://e.test/b"}],
            },
            {
                "url": "https://e.test/b",
                "kind": "html",
                "overall_indexable": True,
                "canonical_urls_json": [],
                "content_extracted": True,
                "render_discovery_attempted": False,
                "links_json": [],
            },
            {
                "url": "https://e.test/alias",
                "kind": "html",
                "overall_indexable": True,
                "canonical_urls_json": ["https://e.test/a"],
                "content_extracted": True,
                "render_discovery_attempted": False,
                "links_json": [{"href": "https://e.test/b"}],
            },
            {
                "url": "https://e.test/file.pdf",
                "kind": "asset",
                "overall_indexable": True,
                "canonical_urls_json": [],
                "content_extracted": True,
                "render_discovery_attempted": False,
                "links_json": [],
            },
        ]
    )
    first = await reports.internal_authority()
    assert first == await reports.internal_authority()
    rows = {row["url"]: row for row in first}
    assert "https://e.test/alias" not in rows
    assert "https://e.test/file.pdf" not in rows
    assert rows["https://e.test/b"]["authority_score"] == 100.0
    assert rows["https://e.test/b"]["unique_inlinks"] == 1
    assert rows["https://e.test/a"]["unique_outlinks"] == 1
    assert rows["https://e.test/b"]["graph_complete"] is True


@pytest.mark.asyncio
async def test_internal_authority_accepts_asyncpg_json_text():
    reports = GraphReports(
        [
            {
                "url": "https://e.test/a",
                "kind": "html",
                "overall_indexable": True,
                "canonical_urls_json": [],
                "content_extracted": True,
                "render_discovery_attempted": False,
                "links_json": '[{"href":"https://e.test/b"}]',
            },
            {
                "url": "https://e.test/b",
                "kind": "html",
                "overall_indexable": True,
                "canonical_urls_json": [],
                "content_extracted": True,
                "render_discovery_attempted": False,
                "links_json": "[]",
            },
        ]
    )
    rows = {row["url"]: row for row in await reports.internal_authority()}
    assert rows["https://e.test/b"]["unique_inlinks"] == 1


@pytest.mark.asyncio
async def test_incomplete_authority_graph_withholds_relative_scores():
    reports = GraphReports(
        [
            {
                "url": "https://e.test/a",
                "kind": "html",
                "overall_indexable": True,
                "canonical_urls_json": [],
                "content_extracted": None,
                "render_discovery_attempted": False,
                "links_json": [],
            },
        ]
    )
    row = (await reports.internal_authority())[0]
    assert row["authority_score"] is None
    assert row["relative_rank"] is None
