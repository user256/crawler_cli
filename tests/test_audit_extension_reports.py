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
