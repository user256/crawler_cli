from __future__ import annotations

import pytest

from crawler_cli.orphan_sources import load_known_url_inventory
from crawler_cli.reports import CrawlReports, _build_link_graph
from crawler_cli.technical_audit import build_technical_audit


def test_known_url_inventory_is_validated_deduplicated_and_source_labelled(tmp_path):
    inventory = tmp_path / "known.csv"
    inventory.write_text(
        "url,source\n"
        "https://example.test/landing,analytics\n"
        "https://example.test/landing,search_console\n"
        "https://example.test/landing,analytics\n",
        encoding="utf-8",
    )

    assert load_known_url_inventory(inventory) == [
        {"url": "https://example.test/landing", "source": "analytics"},
        {"url": "https://example.test/landing", "source": "search_console"},
    ]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("url\nhttps://example.test/landing\n", "url and source"),
        ("url,source\nhttps://example.test/landing,unknown\n", "source must"),
        ("url,source\nhttps://user:pass@example.test/landing,analytics\n", "credential-free"),
        ("url,source\nhttps://example.test:invalid/landing,analytics\n", "credential-free"),
        ("url,source\nhttps://example.test/a page,analytics\n", "credential-free"),
        ("url,source\nfile:///tmp/page,analytics\n", "HTTP"),
    ],
)
def test_known_url_inventory_rejects_invalid_rows(tmp_path, body, message):
    inventory = tmp_path / "known.csv"
    inventory.write_text(body, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_known_url_inventory(inventory)


def test_known_url_inventory_preserves_observation_period(tmp_path):
    inventory = tmp_path / "known.csv"
    inventory.write_text(
        "url,source,observed_at\nhttps://example.test/landing,analytics,2026-09\n",
        encoding="utf-8",
    )

    assert load_known_url_inventory(inventory) == [
        {"url": "https://example.test/landing", "source": "analytics", "observed_at": "2026-09"}
    ]


def test_link_graph_counts_same_host_known_urls_but_excludes_other_hosts():
    graph = _build_link_graph(
        [
            {
                "url": "https://example.test/source",
                "content_extracted": True,
                "links_json": [{"href": "https://example.test/known"}],
            }
        ],
        known_urls=[
            {"url": "https://example.test/known", "source": "search_console"},
            {"url": "https://other.test/outside", "source": "analytics"},
        ],
    )

    assert graph["inbound"]["https://example.test/known"] == 1
    assert "https://other.test/outside" not in graph["inbound"]


@pytest.mark.asyncio
async def test_orphan_report_keeps_supplied_urls_as_qualified_candidates():
    class Store:
        async def resolve_reporting_run_id(self, run_id):
            return run_id

        async def get_crawl_run(self, run_id):
            return {"run_id": run_id, "status": "complete", "seed_urls": ["https://example.test/"]}

    reports = CrawlReports(Store(), run_id="run-1")

    async def fetch(query, *args):
        return [
            {
                "url": "https://example.test/",
                "kind": "html",
                "links_json": [{"href": "https://example.test/known"}],
                "content_extracted": True,
                "render_discovery_attempted": False,
                "render_discovery_complete": None,
            }
        ]

    reports._fetch = fetch
    rows = await reports.orphan_pages(
        known_urls=[
            {"url": "https://example.test/known", "source": "search_console"},
            {"url": "https://example.test/unlinked", "source": "analytics"},
            {"url": "https://other.test/outside", "source": "analytics"},
        ]
    )
    by_url = {row["url"]: row for row in rows}

    assert by_url["https://example.test/known"]["candidate_type"] == "source_known_with_observed_inlinks"
    assert by_url["https://example.test/known"]["observed_inlink_count"] == 1
    assert by_url["https://example.test/unlinked"]["candidate_type"] == "source_known_zero_observed_inlinks"
    assert by_url["https://example.test/unlinked"]["live_validation_state"] == "not_requested"
    assert by_url["https://other.test/outside"]["candidate_type"] == "source_inventory_out_of_scope"
    assert by_url["https://other.test/outside"]["observed_inlink_count"] is None


def test_known_inventory_is_not_misreported_as_orphan_or_client_action():
    rows = [
        {
            "url": "https://example.test/linked",
            "candidate_type": "source_known_with_observed_inlinks",
            "source_labels": ["analytics"],
            "source_observations": [{"source": "analytics", "observed_at": "2026-09"}],
            "observed_inlink_count": 2,
        },
        {
            "url": "https://example.test/orphan",
            "candidate_type": "source_known_zero_observed_inlinks",
            "source_labels": ["search_console"],
            "source_observations": [{"source": "search_console"}],
            "observed_inlink_count": 0,
            "live_validation_state": "not_requested",
        },
    ]
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={"orphans": rows, "link-graph-metrics": [{"graph_complete": True}]},
        run_context={"completion_state": "complete", "parsed_html_count": 2},
    )
    orphan_check = next(check for check in audit["checks"] if check["id"] == "orphan-candidates")

    assert [row["url"] for row in orphan_check["evidence"]] == ["https://example.test/orphan"]
    assert audit["known_url_inventory"] == rows
    assert audit["audit_log"] == []
