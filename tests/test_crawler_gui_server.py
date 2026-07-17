"""Unit coverage for the crawler_gui live bridge's pure mapping layer (ticket 125).

These tests exercise the row->page mapping, link-graph folding, overview
aggregation, and helpers without a database. The DB-backed behaviour (runs
listing, run-scoped snapshots, pagination) is covered by the DSN-gated
integration test in ``test_persistence_integration.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SERVER_PATH = Path(__file__).resolve().parents[1] / "crawler_gui" / "server.py"
_spec = importlib.util.spec_from_file_location("crawler_gui_server", _SERVER_PATH)
assert _spec and _spec.loader
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


def _snapshot_row(**overrides):
    row = {
        "url_id": 1,
        "url": "https://site.example/page",
        "kind": "html",
        "final_status_code": 200,
        "headers_json": {"content-type": "text/html; charset=utf-8"},
        "title": "Page Title",
        "meta_description": "A description here.",
        "h1_tags": "Main Heading",
        "word_count": 512,
        "overall_indexable": True,
        "total_duration_seconds": 0.25,
        "canonical_urls_json": ["https://site.example/page"],
        "schema_json": [{"@type": "Article", "headline": "News"}],
        "links_json": [
            {"href": "https://site.example/other", "anchor_text": "Internal"},
            {"href": "https://external.example/x", "anchor_text": "Out"},
        ],
        "redirect_url": None,
    }
    row.update(overrides)
    return row


def test_is_external():
    assert server.is_external("https://other.example/a", "site.example") is True
    assert server.is_external("https://site.example/a", "site.example") is False
    assert server.is_external("/relative/path", "site.example") is False
    assert server.is_external("", "site.example") is False


def test_page_from_row_snapshot_maps_core_fields():
    page = server.page_from_row(_snapshot_row(), has_snapshots=True)
    assert page["id"] == 1
    assert page["address"] == "https://site.example/page"
    assert page["statusCode"] == 200
    assert page["status"] == "OK"
    assert page["indexability"] == "Indexable"
    assert page["title"] == "Page Title"
    assert page["canonical"] == "https://site.example/page"
    assert page["responseTimeMs"] == 250  # 0.25s -> ms
    assert page["wordCount"] == 512
    assert page["structuredData"] == [{"type": "Article", "name": "News"}]
    # Charset param is stripped so exact content-type matching works downstream.
    assert page["contentType"] == "text/html"
    assert "page-titles" in page["categoryHints"]


def test_page_from_row_snapshot_extracts_external_outlinks_only():
    # Only the external href becomes an outlink here; internal links are added
    # later from internal_links by attach_link_graph.
    page = server.page_from_row(_snapshot_row(), has_snapshots=True)
    assert page["outlinks"] == [{"targetUrl": "https://external.example/x", "anchorText": "Out", "external": True}]


def test_page_from_row_missing_response_time_is_none():
    page = server.page_from_row(_snapshot_row(total_duration_seconds=None), has_snapshots=True)
    assert page["responseTimeMs"] is None


def test_page_from_row_legacy_uses_scalar_canonical():
    row = {
        "url_id": 7,
        "url": "https://legacy.example/",
        "kind": "html",
        "final_status_code": 301,
        "headers_json": None,
        "title": "",
        "meta_description": None,
        "h1_tags": "",
        "word_count": 0,
        "overall_indexable": False,
        "total_duration_seconds": 1.5,
        "canonical_url": "https://legacy.example/canonical",
        "redirect_url": "https://legacy.example/moved",
    }
    page = server.page_from_row(row, has_snapshots=False)
    assert page["canonical"] == "https://legacy.example/canonical"
    assert page["indexability"] == "Non-Indexable"
    assert page["status"] == "Moved Permanently"
    assert page["responseTimeMs"] == 1500
    assert page["structuredData"] == []
    assert page["outlinks"] == []  # no links_json on the legacy schema


def test_attach_link_graph_folds_counts_and_lists():
    pages = [server.page_from_row(_snapshot_row(url_id=1), has_snapshots=True)]
    inlinks = {1: [{"sourceUrl": "https://site.example/a", "anchorText": "home", "follow": True}]}
    outlinks = {1: [{"targetUrl": "https://site.example/other", "anchorText": "Internal", "external": False}]}
    server.attach_link_graph(pages, inlinks, outlinks)
    page = pages[0]
    assert page["internalInlinks"] == 1
    assert page["externalInlinks"] == 0
    assert page["inlinks"] == inlinks[1]
    # Internal outlink is prepended; the external one from links_json is kept.
    assert page["outlinks"][0]["targetUrl"] == "https://site.example/other"
    assert page["outlinks"][-1]["external"] is True


def test_overview_from_counts_reports_whole_run_aggregates():
    # Counts come from the run-wide SQL aggregate, not the page window, so a
    # 2-page window over a 100-page run still describes all 100.
    ov = server.overview_from_counts(
        {
            "total": 100,
            "indexable": 60,
            "https": 100,
            "c2xx": 80,
            "c3xx": 5,
            "c4xx": 10,
            "c5xx": 5,
            "html": 90,
            "missing_title": 3,
            "missing_meta": 7,
            "missing_h1": 2,
        }
    )
    summary = {row["label"]: row["count"] for row in ov["summary"]}
    assert summary["Total URLs Crawled"] == 100
    assert summary["Indexable"] == 60
    assert summary["Non-Indexable"] == 40
    codes = {row["label"]: (row["count"], row["pct"]) for row in ov["responseCodes"]}
    assert codes["2xx OK"] == (80, 80.0)
    assert codes["4xx Client Error"] == (10, 10.0)
    content = {row["label"]: row["count"] for row in ov["content"]}
    assert content["HTML"] == 90
    assert content["Missing Title"] == 3


def test_overview_from_counts_empty_run_does_not_divide_by_zero():
    ov = server.overview_from_counts({})
    assert all(row["pct"] == 0.0 for row in ov["responseCodes"])
    assert ov["summary"][0]["count"] == 0


def test_structured_data_of_handles_strings_and_dicts():
    assert server.structured_data_of(["Organization"]) == [{"type": "Organization", "name": ""}]
    assert server.structured_data_of([{"type": "Product", "name": "Widget"}]) == [{"type": "Product", "name": "Widget"}]
    assert server.structured_data_of(None) == []


def test_as_list_coerces_jsonb_forms():
    assert server.as_list('["a", "b"]') == ["a", "b"]
    assert server.as_list(["a"]) == ["a"]
    assert server.as_list("not json") == []
    assert server.as_list(None) == []


def test_parse_int_clamps_and_rejects():
    assert server._parse_int("5", minimum=1, maximum=10, name="limit") == 5
    assert server._parse_int("0", minimum=1, maximum=10, name="limit") == 1  # clamped up
    assert server._parse_int("99", minimum=1, maximum=10, name="limit") == 10  # clamped down
    with pytest.raises(server.web.HTTPBadRequest):
        server._parse_int("abc", minimum=1, maximum=10, name="limit")
