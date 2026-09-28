"""Ticket 262: multi-source discovery provenance reconciliation.

Pure classification, local file loaders, and CLI wiring with the store and
reports stubbed out. No network and no Postgres; the SQL behind
``CrawlReports.source_reconciliation_inventory`` is covered by the integration
suite.
"""

from __future__ import annotations

import asyncio
import csv
import gzip
import json

import pytest

from crawler_cli.__main__ import _build_parser, _dispatch
from crawler_cli.reports import CrawlReports
from crawler_cli.source_reconciliation import (
    SEGMENTS,
    SourceInput,
    crawl_sitemap_source,
    load_sitemap_files,
    load_url_list,
    reconcile_sources,
)


E = "https://e.test"
COMPLETE = {"run_status": "complete", "frontier_queued": 0, "frontier_pending": 0, "frontier_done": 9}


def _page(path, *, links=(), status=200, initial=None, indexable=True, canonical=None, kind="html"):
    url = f"{E}{path}"
    return {
        "url": url,
        "kind": kind,
        "links_json": [{"href": f"{E}{target}"} for target in links],
        "content_extracted": True,
        "render_discovery_attempted": False,
        "initial_status_code": initial if initial is not None else status,
        "final_status_code": status,
        "overall_indexable": indexable,
        "canonical_urls_json": [canonical or url],
    }


def _source(label, *paths, details=None):
    return SourceInput(
        label=label,
        urls={f"{E}{path}": list(details or []) for path in paths},
        metadata={"label": label},
    )


def _fixture_pages():
    return [
        # Seed: crawled, links out, nothing links to it.
        _page("/", links=("/in-both", "/unmapped", "/redirect", "/linked-404", "/unfetched", "/noindex")),
        _page("/in-both"),
        _page("/unmapped"),
        _page("/redirect", initial=301, status=200),
        _page("/linked-404", status=404, indexable=False),
        _page("/noindex", indexable=False),
        _page("/sitemap-orphan"),
        _page("/dead", status=410, indexable=False),
        _page("/crawled-alone"),
    ]


def _fixture_sources():
    return [
        _source("sitemap_file", "/in-both", "/sitemap-orphan", "/sitemap-only-uncrawled", details=["sitemap.xml"]),
        _source("gsc_export", "/gsc-only", "/unmapped", "/in-both"),
        _source("backlinks_export", "/dead", "/backlink-only", "/linked-404", "/sitemap-orphan"),
        SourceInput(label="gsc_export", urls={"https://other.test/x": []}, metadata={"label": "gsc_other"}),
    ]


def _by_url(result):
    return {row["url"].removeprefix(E): row for row in result["urls"]}


def test_multi_source_fixture_partitions_every_url_into_one_segment():
    result = reconcile_sources(run_id="run-a", context=COMPLETE, pages=_fixture_pages(), sources=_fixture_sources())
    rows = _by_url(result)
    segments = {url: row["segment"] for url, row in rows.items()}
    assert segments == {
        "/in-both": "graph_and_sitemap",
        "/sitemap-orphan": "sitemap_orphan",
        "/sitemap-only-uncrawled": "sitemap_orphan",
        "/unmapped": "unmapped_in_sitemap",
        "/dead": "backlink_dead_end",
        "/backlink-only": "backlink_dead_end",
        "/linked-404": "backlink_dead_end",
        "/gsc-only": "gsc_unlinked",
        "/redirect": "linked_not_in_sitemap_other",
        "/noindex": "linked_not_in_sitemap_other",
        "/": "crawled_unlinked_no_source",
        "/crawled-alone": "crawled_unlinked_no_source",
    }
    # A link target that was neither crawled nor supplied is outside the universe.
    assert "/unfetched" not in rows
    assert set(result["summary"]["segment_counts"]) == set(SEGMENTS)
    assert sum(result["summary"]["segment_counts"].values()) == len(rows) == result["summary"]["total_urls"]
    assert result["summary"]["segment_counts"]["sitemap_orphan"] == 2

    # Precision: the sitemap orphans and unmapped pages are exactly these.
    assert sorted(url for url, row in rows.items() if row["segment"] == "sitemap_orphan") == [
        "/sitemap-only-uncrawled",
        "/sitemap-orphan",
    ]
    assert [url for url, row in rows.items() if row["segment"] == "unmapped_in_sitemap"] == ["/unmapped"]


def test_rows_carry_sources_status_canonical_and_action():
    result = reconcile_sources(run_id="run-a", context=COMPLETE, pages=_fixture_pages(), sources=_fixture_sources())
    rows = _by_url(result)
    both = rows["/in-both"]
    assert both["discovery_sources"] == ["link_graph", "sitemap", "gsc"]
    assert both["source_details"] == {"sitemap_file": ["sitemap.xml"]}
    assert both["http_status"] == 200 and both["canonical_state"] == "declared_self"
    assert both["recommended_action"].startswith("None")
    redirect = rows["/redirect"]
    assert redirect["http_status"] == 301 and redirect["final_status"] == 200
    assert "redirect" in redirect["recommended_action"]
    assert "301-redirect" in rows["/dead"]["recommended_action"]
    uncrawled = rows["/sitemap-only-uncrawled"]
    assert uncrawled["crawled"] is False and uncrawled["http_status"] is None
    assert uncrawled["canonical_state"] == "unknown"
    assert result["summary"]["source_overlap_counts"]["link_graph+sitemap+gsc"] == 1


def test_out_of_scope_urls_are_listed_but_not_joined():
    result = reconcile_sources(run_id="run-a", context=COMPLETE, pages=_fixture_pages(), sources=_fixture_sources())
    assert result["out_of_scope"] == [
        {"url": "https://other.test/x", "source_labels": ["gsc_export"], "reason": "host_not_crawled_in_run"}
    ]
    assert result["summary"]["out_of_scope_count"] == 1
    assert all("other.test" not in row["url"] for row in result["urls"])


def test_complete_coverage_labels_plain_orphans():
    result = reconcile_sources(run_id="run-a", context=COMPLETE, pages=_fixture_pages(), sources=_fixture_sources())
    assert result["coverage"]["complete"] is True
    assert _by_url(result)["/sitemap-orphan"]["linkage"] == "orphan_complete_graph"
    assert "confirm" not in _by_url(result)["/sitemap-orphan"]["recommended_action"]


def test_capped_crawl_qualifies_unlinked_segments_with_unfetched_count():
    context = {"run_status": "complete", "frontier_queued": 7, "frontier_pending": 1, "frontier_done": 9}
    result = reconcile_sources(run_id="run-a", context=context, pages=_fixture_pages(), sources=_fixture_sources())
    coverage = result["coverage"]
    assert coverage["complete"] is False
    assert coverage["discovered_unfetched_count"] == 8
    assert "8 discovered URLs were never fetched" in coverage["statement"]
    assert "not confirmed orphans" in coverage["statement"]
    rows = _by_url(result)
    assert rows["/sitemap-orphan"]["linkage"] == "no_inlinks_from_crawled_pages"
    assert "Crawl coverage is incomplete" in rows["/sitemap-orphan"]["recommended_action"]
    assert rows["/in-both"]["linkage"] == "observed_inlinks"


def test_incomplete_link_extraction_is_not_complete_coverage():
    pages = _fixture_pages()
    pages[1]["content_extracted"] = False
    result = reconcile_sources(run_id="run-a", context=COMPLETE, pages=pages, sources=_fixture_sources())
    assert result["coverage"]["link_graph_complete"] is False
    assert result["coverage"]["complete"] is False


def test_output_is_deterministic_regardless_of_input_order():
    first = reconcile_sources(run_id="run-a", context=COMPLETE, pages=_fixture_pages(), sources=_fixture_sources())
    second = reconcile_sources(
        run_id="run-a",
        context=COMPLETE,
        pages=list(reversed(_fixture_pages())),
        sources=list(reversed(_fixture_sources())),
    )
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    order = [SEGMENTS.index(row["segment"]) for row in first["urls"]]
    assert order == sorted(order)


def test_crawl_sitemap_provenance_counts_as_sitemap_membership():
    source = crawl_sitemap_source(
        [
            {"url": f"{E}/unmapped", "detail": f"{E}/sitemap.xml"},
            {"url": "not a url", "detail": ""},
        ]
    )
    assert list(source.urls) == [f"{E}/unmapped"]
    result = reconcile_sources(run_id="run-a", context=COMPLETE, pages=_fixture_pages(), sources=[source])
    row = _by_url(result)["/unmapped"]
    assert row["segment"] == "graph_and_sitemap"
    assert row["source_labels"] == ["crawl_sitemap"]


def test_load_url_list_matches_gsc_header_ignoring_case_and_bom(tmp_path):
    path = tmp_path / "gsc.csv"
    path.write_text(
        "﻿Top pages,Clicks,Impressions\n"
        "https://e.test/b,3,40\n"
        "https://e.test/a,5,50\n"
        "https://e.test/a,5,50\n"
        "/relative,1,1\n",
        encoding="utf-8",
    )
    loaded = load_url_list(path, label="gsc_export", default_columns=("url", "top pages"))
    assert list(loaded.urls) == ["https://e.test/a", "https://e.test/b"]
    assert loaded.metadata["url_column"] == "Top pages"
    assert loaded.metadata["rejected_count"] == 1
    assert loaded.metadata["rejected_sample"] == ["/relative"]


def test_load_url_list_rejects_header_without_url_column(tmp_path):
    path = tmp_path / "semrush.csv"
    path.write_text("Keyword,Traffic\nfoo,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="headers found: 'Keyword', 'Traffic'"):
        load_url_list(path, label="backlinks_export")


def test_load_url_list_accepts_plain_url_list_and_redacts_credentials(tmp_path):
    path = tmp_path / "urls.txt"
    path.write_text("https://e.test/a\nhttps://user:pw@e.test/b\n\n", encoding="utf-8")
    loaded = load_url_list(path, label="backlinks_export")
    assert list(loaded.urls) == ["https://e.test/a"]
    assert loaded.metadata["url_column"] is None
    assert loaded.metadata["rejected_sample"] == ["[credentials redacted]"]


def test_load_url_list_reports_utf16_exports_clearly(tmp_path):
    path = tmp_path / "ahrefs.csv"
    path.write_bytes("URL\thttps://e.test/a\n".encode("utf-16"))
    with pytest.raises(ValueError, match="not UTF-8"):
        load_url_list(path, label="backlinks_export")


def test_load_sitemap_files_parses_urlsets_and_flags_unresolved_index_children(tmp_path):
    urlset = tmp_path / "pages.xml.gz"
    urlset.write_bytes(
        gzip.compress(
            b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            b"<url><loc>https://e.test/b</loc></url><url><loc>https://e.test/a</loc></url>"
            b"<url><loc>ftp://e.test/x</loc></url></urlset>"
        )
    )
    index = tmp_path / "index.xml"
    index.write_text(
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<sitemap><loc>https://e.test/pages.xml.gz</loc></sitemap></sitemapindex>",
        encoding="utf-8",
    )
    source = load_sitemap_files([index, urlset])
    assert source.urls == {"https://e.test/a": ["pages.xml.gz"], "https://e.test/b": ["pages.xml.gz"]}
    assert source.metadata["rejected_count"] == 1
    assert source.metadata["unresolved_index_child_count"] == 1
    assert source.metadata["complete"] is False


def test_load_sitemap_files_rejects_unparseable_xml(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_text("<urlset>", encoding="utf-8")
    with pytest.raises(ValueError, match="could not parse sitemap"):
        load_sitemap_files([bad])


class _InventoryReports(CrawlReports):
    def __init__(self):
        self.run_id = "run-a"
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    async def _run_id(self) -> str:
        return "run-a"

    async def _fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        self.queries.append((query, args))
        if "url_sources" in query:
            return [{"url": f"{E}/a", "detail": f"{E}/sitemap.xml"}]
        return [{"url": f"{E}/a", "kind": "html"}]


def test_inventory_scopes_crawl_sitemap_provenance_to_the_run_frontier():
    reports = _InventoryReports()
    inventory = asyncio.run(reports.source_reconciliation_inventory())
    assert inventory["crawl_sitemap_urls"] == [{"url": f"{E}/a", "detail": f"{E}/sitemap.xml"}]
    provenance_query, provenance_args = reports.queries[1]
    assert "f.run_id = $1" in provenance_query and provenance_args == ("run-a",)
    assert all(args == ("run-a",) for _query, args in reports.queries)


# --- CLI wiring -------------------------------------------------------------


class _FakeStore:
    closed = False

    async def close(self) -> None:
        _FakeStore.closed = True


class _FakeReports:
    context = COMPLETE

    def __init__(self, store, run_id=None) -> None:
        self.run_id = run_id

    async def _run_id(self):
        return self.run_id or "resolved-run"

    async def technical_audit_context(self):
        return dict(self.context)

    async def source_reconciliation_inventory(self):
        return {
            "pages": _fixture_pages(),
            "crawl_sitemap_urls": [{"url": f"{E}/unmapped", "detail": f"{E}/sitemap.xml"}],
        }


@pytest.fixture
def fake_cli(monkeypatch):
    _FakeStore.closed = False
    _FakeReports.context = COMPLETE
    monkeypatch.setattr("crawler_cli.__main__.CrawlReports", _FakeReports)
    monkeypatch.setattr("crawler_cli.__main__._store_from_args", lambda args: _FakeStore())


def _run(argv: list[str]) -> int:
    return asyncio.run(_dispatch(_build_parser().parse_args(argv)))


def _write_inputs(tmp_path):
    sitemap = tmp_path / "sitemap.xml"
    sitemap.write_text(
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://e.test/in-both</loc></url><url><loc>https://e.test/sitemap-orphan</loc></url>"
        "</urlset>",
        encoding="utf-8",
    )
    gsc = tmp_path / "gsc.csv"
    gsc.write_text("URL\nhttps://e.test/gsc-only\n", encoding="utf-8")
    backlinks = tmp_path / "backlinks.csv"
    backlinks.write_text("Target URL,Domains\nhttps://e.test/dead,12\n", encoding="utf-8")
    return sitemap, gsc, backlinks


def test_cli_writes_deterministic_json_and_csv(fake_cli, tmp_path, capsys):
    sitemap, gsc, backlinks = _write_inputs(tmp_path)
    out = tmp_path / "reconciliation.json"
    csv_out = tmp_path / "reconciliation.csv"
    argv = [
        "reconcile-sources",
        "--crawl-run-id",
        "run-42",
        "--sitemap-file",
        str(sitemap),
        "--gsc-export",
        str(gsc),
        "--backlinks-export",
        str(backlinks),
        "--out",
        str(out),
        "--csv-out",
        str(csv_out),
    ]
    assert _run(argv) == 0
    first = out.read_bytes()
    assert _run(argv) == 0
    assert out.read_bytes() == first
    assert _FakeStore.closed is True

    payload = json.loads(first)
    assert payload["run_id"] == "run-42"
    assert [source["label"] for source in payload["sources"]] == [
        "backlinks_export",
        "crawl_sitemap",
        "gsc_export",
        "sitemap_file",
    ]
    rows = {row["url"]: row for row in payload["urls"]}
    assert rows[f"{E}/unmapped"]["segment"] == "graph_and_sitemap"  # via crawl provenance
    assert rows[f"{E}/sitemap-orphan"]["segment"] == "sitemap_orphan"
    assert rows[f"{E}/gsc-only"]["segment"] == "gsc_unlinked"
    assert rows[f"{E}/dead"]["segment"] == "backlink_dead_end"

    with csv_out.open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == len(payload["urls"])
    assert csv_rows[0]["segment"] == "graph_and_sitemap"
    assert "graph_and_sitemap:" in capsys.readouterr().out


def test_cli_can_exclude_crawl_sitemap_provenance(fake_cli, tmp_path):
    out = tmp_path / "r.json"
    assert _run(["reconcile-sources", "--out", str(out), "--no-crawl-sitemap-provenance"]) == 0
    payload = json.loads(out.read_text())
    assert payload["sources"] == []
    assert {row["url"]: row["segment"] for row in payload["urls"]}[f"{E}/unmapped"] == "unmapped_in_sitemap"


def test_cli_prints_coverage_note_for_incomplete_crawl(fake_cli, tmp_path, capsys):
    _FakeReports.context = {"run_status": "running", "frontier_queued": 3, "frontier_pending": 0}
    out = tmp_path / "r.json"
    assert _run(["reconcile-sources", "--out", str(out)]) == 0
    assert "not confirmed orphans" in capsys.readouterr().err
    assert json.loads(out.read_text())["coverage"]["complete"] is False


def test_cli_rejects_bad_export_before_opening_the_store(fake_cli, tmp_path, capsys):
    bad = tmp_path / "bad.csv"
    bad.write_text("Keyword,Traffic\nfoo,1\n", encoding="utf-8")
    assert _run(["reconcile-sources", "--out", str(tmp_path / "r.json"), "--gsc-export", str(bad)]) == 2
    assert "headers found" in capsys.readouterr().err
    assert _FakeStore.closed is False


def test_cli_scope_manifest_requires_fetch_current_sitemaps(fake_cli, tmp_path, capsys):
    assert _run(["reconcile-sources", "--out", str(tmp_path / "r.json"), "--scope-manifest", "m.json"]) == 2
    assert "--fetch-current-sitemaps" in capsys.readouterr().err


def test_cli_fetch_current_sitemaps_reuses_guarded_collector(fake_cli, tmp_path, monkeypatch):
    seen = []

    async def fake_collect(engine, **kwargs):
        seen.append((engine.config.destination_guard, kwargs["max_live_samples"]))
        return {
            "record_type": "coverage",
            "observed_at": "2026-09-28T00:00:00+00:00",
            "complete": True,
            "sitemap_document_count": 1,
            "_graph_join_urls": [
                {"url": f"{E}/noindex", "source": "sitemap", "source_sitemap": f"{E}/sitemap.xml"},
            ],
        }

    async def join_inventory(self):
        return []

    monkeypatch.setattr("crawler_cli.__main__.collect_current_site_files", fake_collect)
    monkeypatch.setattr(_FakeReports, "current_site_join_inventory", join_inventory, raising=False)
    _FakeReports.context = {**COMPLETE, "seed_origins": [E], "declared_allowed_hosts": ["e.test"]}
    out = tmp_path / "r.json"
    assert _run(["reconcile-sources", "--out", str(out), "--fetch-current-sitemaps"]) == 0
    assert seen == [("pinned", 0)]
    payload = json.loads(out.read_text())
    row = {row["url"]: row for row in payload["urls"]}[f"{E}/noindex"]
    assert row["segment"] == "graph_and_sitemap"
    assert row["source_details"] == {"current_sitemap": [f"{E}/sitemap.xml"]}
    assert "Sitemap lists a non-indexable URL" in row["recommended_action"]
