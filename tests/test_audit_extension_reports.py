from __future__ import annotations

import pytest

from crawler_cli.hashing import simhash64, simhash_to_signed
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
async def test_near_duplicates_excludes_exact_hashes_and_sorts_by_distance():
    first = "<main>apple banana cedar ember</main>"
    near = "<main>apple banana cedar ember fig</main>"
    reports = StubReports(
        [
            {
                "url": "https://e.test/a",
                "content_hash_sha256": "a",
                "content_hash_simhash": simhash_to_signed(simhash64(first)),
            },
            {
                "url": "https://e.test/a-copy",
                "content_hash_sha256": "a",
                "content_hash_simhash": simhash_to_signed(simhash64(first)),
            },
            {
                "url": "https://e.test/b",
                "content_hash_sha256": "b",
                "content_hash_simhash": simhash_to_signed(simhash64(near)),
            },
        ]
    )
    rows = await reports.near_duplicates(threshold=64)
    assert all({row["url"], row["near_duplicate_url"]} != {"https://e.test/a", "https://e.test/a-copy"} for row in rows)
    assert any(row["near_duplicate_url"] == "https://e.test/b" for row in rows)


@pytest.mark.asyncio
async def test_internal_authority_rewards_linked_page_and_handles_sink():
    reports = StubReports(
        [
            {"url": "https://e.test/a", "links_json": [{"href": "https://e.test/b"}]},
            {"url": "https://e.test/b", "links_json": []},
        ]
    )
    rows = {row["url"]: row for row in await reports.internal_authority()}
    assert rows["https://e.test/b"]["authority_score"] == 100.0
    assert rows["https://e.test/b"]["unique_inlinks"] == 1
    assert rows["https://e.test/a"]["unique_outlinks"] == 1


@pytest.mark.asyncio
async def test_internal_authority_accepts_asyncpg_json_text():
    reports = StubReports(
        [
            {"url": "https://e.test/a", "links_json": '[{"href":"https://e.test/b"}]'},
            {"url": "https://e.test/b", "links_json": "[]"},
        ]
    )
    rows = {row["url"]: row for row in await reports.internal_authority()}
    assert rows["https://e.test/b"]["unique_inlinks"] == 1
