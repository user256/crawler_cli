"""Unit coverage for the crawler_gui live bridge's pure mapping layer (ticket 125).

These tests exercise the row->page mapping, link-graph folding, overview
aggregation, and helpers without a database. The DB-backed behaviour (runs
listing, run-scoped snapshots, pagination) is covered by the DSN-gated
integration test in ``test_persistence_integration.py``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SERVER_PATH = Path(__file__).resolve().parents[1] / "crawler_gui" / "server.py"
_spec = importlib.util.spec_from_file_location("crawler_gui_server", _SERVER_PATH)
assert _spec and _spec.loader
server = importlib.util.module_from_spec(_spec)
# Register before exec: dataclasses resolve field types via sys.modules.
sys.modules["crawler_gui_server"] = server
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
    assert page["sources"] == []  # attached later from url_sources


def test_page_from_row_snapshot_extracts_external_outlinks_only():
    # Only the external href becomes an outlink here; internal links are added
    # later from internal_links by attach_link_graph.
    page = server.page_from_row(_snapshot_row(), has_snapshots=True)
    assert page["outlinks"] == [
        {"targetUrl": "https://external.example/x", "anchorText": "Out", "external": True, "follow": True}
    ]


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


def test_attach_url_sources_folds_recorded_provenance():
    pages = [server.page_from_row(_snapshot_row(url_id=1), has_snapshots=True)]
    server.attach_url_sources(
        pages,
        {
            1: [
                {"source": "link", "detail": "https://site.example/home"},
                {"source": "backlink", "detail": "https://referrer.example/a"},
                {"source": "backlink", "detail": "https://referrer.example/b"},
            ]
        },
    )
    assert pages[0]["sources"] == ["link", "backlink"]
    assert pages[0]["externalInlinks"] == 2
    assert pages[0]["sourceEvidence"][0]["detail"] == "https://site.example/home"


def test_live_category_tabs_puts_archive_before_external_links():
    tabs = server.live_category_tabs(
        [
            {"id": "internal", "label": "Internal"},
            {"id": "external", "label": "External"},
            {"id": "security", "label": "Security"},
            {"id": "url", "label": "URL"},
        ]
    )
    assert [(tab["id"], tab["label"]) for tab in tabs[:9]] == [
        ("internal", "Internal URLs"),
        ("archive-org", "Archive.org URLs"),
        ("backlinks", "External backlinks"),
        ("custom-checks", "Custom checks"),
        ("host-protocol-checks", "Host & protocol"),
        ("url-variant-checks", "URL variants"),
        ("fictional-url-checks", "Fictional URLs"),
        ("external", "External outlinks"),
        ("security", "Insecure HTTP URLs"),
    ]
    assert tabs[-2]["id"] == "url"
    assert tabs[-1]["id"] == "social"


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


def test_saved_snapshot_populates_report_categories_and_nested_schema_name():
    page = server.page_from_row(
        _snapshot_row(
            h2_tags="First\nSecond",
            images_json=[{"url": "https://site.example/a.png"}],
            hreflang_json=[{"href": "https://site.example/fr", "hreflang": "fr"}],
            schema_json=[
                {"type": "Organization", "parsed_data": json.dumps({"name": "Stored name"}), "is_valid": True}
            ],
            robots_json=["noarchive"],
        ),
        has_snapshots=True,
    )
    assert {"structured-data", "images", "hreflang", "h2", "url", "response-codes"} <= set(page["categoryHints"])
    assert page["structuredData"][0]["name"] == "Stored name"
    assert page["h2Count"] == 2
    assert page["robots"] == "noarchive"


def test_saved_html_evidence_recovers_social_and_links_without_fetching():
    from crawler_cli.compression import compress_html

    result = server.saved_html_evidence(
        {
            "url_id": 1,
            "url": "https://site.example/page",
            "html_compressed": compress_html("""
      <html><head><base href="https://cdn.example/assets/">
      <meta property="og:title" content="A &amp; B"><meta name="twitter:card" content="summary">
      <meta property="og:locale:alternate" content="fr"><meta property="og:locale:alternate" content="de">
      <script src="app.js"></script><script type="application/ld+json">{}</script></head>
      <body><a href="https://other.example/path" rel="nofollow">External</a></body></html>"""),
        }
    )
    assert result["social"][0] == {"property": "og:title", "content": "A & B"}
    assert len(result["social"]) == 4
    assert result["scripts"] == [{"url": "https://cdn.example/assets/app.js", "type": "text/javascript"}]
    assert result["savedOutlinks"][0]["external"] is True
    assert result["savedOutlinks"][0]["follow"] is False
    assert result["evidenceLoaded"] is True


def test_resume_restores_scope_and_refuses_incompatible_backend():
    from crawler_cli.config import CrawlConfig
    from crawler_cli.engine import _crawl_run_config_hash, _crawl_run_config_snapshot
    from crawler_gui.resume import resume_configuration

    config = CrawlConfig(backend="curl_cffi", same_host_only=True, path_exclude=["/private"])
    seeds = ["https://site.example/"]
    saved = _crawl_run_config_snapshot(config, seeds)
    row = {
        "config_json": json.dumps(saved),
        "seed_urls_json": json.dumps(seeds),
        "config_hash": _crawl_run_config_hash(saved),
    }
    restored, restored_seeds = resume_configuration(row)
    assert restored.backend == "curl_cffi"
    assert restored.path_exclude == ["/private"]
    assert restored_seeds == seeds
    with pytest.raises(ValueError, match="cannot be reconstructed"):
        resume_configuration(row, "aiohttp")


@pytest.mark.asyncio
async def test_source_fallback_keeps_run_evidence_and_labels_global_facts():
    from unittest.mock import AsyncMock

    store = server.LiveStore("unused")
    store.has_run_url_sources = store.has_url_sources = True
    conn = AsyncMock()
    conn.fetch.side_effect = [
        [{"url_id": 1, "source": "link", "detail": "parent"}],
        [
            {"url_id": 1, "source": "link", "detail": "parent"},
            {"url_id": 1, "source": "archive_org", "detail": "old import"},
        ],
    ]
    result = await store._url_sources(conn, "selected", [1])
    assert result[1] == [
        {"source": "link", "detail": "parent", "scope": "run"},
        {"source": "archive_org", "detail": "old import", "scope": "database"},
    ]


@pytest.mark.asyncio
async def test_resume_endpoint_does_not_launch_an_exhausted_run():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    launcher = SimpleNamespace(resume=AsyncMock())
    store = SimpleNamespace(resume_plan=AsyncMock(return_value={"canResume": False, "reason": "No queued URLs"}))
    request = SimpleNamespace(
        app={"store": store, "launcher": launcher},
        match_info={"run_id": "complete-run"},
        json=AsyncMock(return_value={}),
    )
    with pytest.raises(server.web.HTTPConflict, match="Conflict"):
        await server.resume_handler(request)
    launcher.resume.assert_not_awaited()


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


# --- ticket 124: crawl submission -------------------------------------------


def test_parse_crawl_spec_defaults_and_run_id():
    spec = server.parse_crawl_spec({"url": "https://site.example"})
    assert spec.target == "https://site.example"
    assert spec.mode == "Spider"
    assert spec.respect_robots is True
    assert spec.run_id.startswith("gui-")  # generated, unique per submission


def test_parse_crawl_spec_rejects_bad_input():
    with pytest.raises(ValueError, match="target is required"):
        server.parse_crawl_spec({"url": "  "})
    with pytest.raises(ValueError, match="http"):
        server.parse_crawl_spec({"url": "ftp://site.example"})
    with pytest.raises(ValueError, match="unknown crawl mode"):
        server.parse_crawl_spec({"url": "https://s.example", "mode": "Sideways"})
    with pytest.raises(ValueError, match="unknown backend"):
        server.parse_crawl_spec({"url": "https://s.example", "backend": "telepathy"})
    with pytest.raises(ValueError, match="whole number"):
        server.parse_crawl_spec({"url": "https://s.example", "maxPages": "lots"})


def test_parse_crawl_spec_list_mode_requires_local_csv(tmp_path):
    with pytest.raises(ValueError, match="local CSV file"):
        server.parse_crawl_spec({"url": "https://site.example/urls.txt", "mode": "List"})
    csv_file = tmp_path / "urls.csv"
    csv_file.write_text("url\nhttps://site.example/a\n", encoding="utf-8")
    spec = server.parse_crawl_spec({"url": str(csv_file), "mode": "List"})
    assert spec.mode == "List"


def test_build_crawl_argv_spider():
    spec = server.parse_crawl_spec(
        {
            "url": "https://site.example",
            "runId": "gui-run-1",
            "maxPages": 200,
            "concurrency": 5,
            "backend": "aiohttp",
            "userAgent": "test-agent",
            "respectRobots": True,
        }
    )
    argv = server.build_crawl_argv(spec, "postgresql://u:p@h/db")
    assert argv[1:4] == ["-m", "crawler_cli", "crawl"]
    assert "https://site.example" in argv
    assert argv[argv.index("--postgres-dsn") + 1] == "postgresql://u:p@h/db"
    assert argv[argv.index("--crawl-run-id") + 1] == "gui-run-1"
    assert argv[argv.index("--max-pages") + 1] == "200"
    assert argv[argv.index("--concurrency") + 1] == "5"
    assert argv[argv.index("--http-backend") + 1] == "aiohttp"
    assert argv[argv.index("--custom-ua") + 1] == "test-agent"
    assert "--ignore-robots" not in argv  # robots respected


def test_build_crawl_argv_ignore_robots_and_js():
    spec = server.parse_crawl_spec({"url": "https://site.example", "respectRobots": False, "backend": "playwright"})
    argv = server.build_crawl_argv(spec, "dsn")
    assert "--ignore-robots" in argv
    assert "--js" in argv  # playwright maps to --js, not --http-backend
    assert "--http-backend" not in argv


def test_build_crawl_argv_list_mode(tmp_path):
    csv_file = tmp_path / "urls.csv"
    csv_file.write_text("url\nhttps://site.example/a\n", encoding="utf-8")
    spec = server.parse_crawl_spec({"url": str(csv_file), "mode": "List"})
    argv = server.build_crawl_argv(spec, "dsn")
    assert argv[argv.index("--csv-file") + 1] == str(csv_file)
    assert argv[argv.index("--csv-column") + 1] == "url"


def test_build_crawl_argv_is_argv_not_shell():
    # Values are passed as argv entries and spawned without a shell, so shell
    # metacharacters in a target cannot inject a second command.
    spec = server.parse_crawl_spec({"url": "https://site.example/a;rm -rf /"})
    argv = server.build_crawl_argv(spec, "dsn")
    assert "https://site.example/a;rm -rf /" in argv
    assert all(isinstance(part, str) for part in argv)


# --- ticket 128: Chrome profile discovery and preflight --------------------


def _write_local_state(root, *, profiles, last_used="Profile 1"):
    state_path = root / "Local State"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    (root / "Profile 1").mkdir(exist_ok=True)
    state_path.write_text(json.dumps({"profile": {"last_used": last_used, "info_cache": profiles}}), encoding="utf-8")


def test_discover_chrome_profiles_reads_labels_without_private_data(tmp_path):
    chrome_root = tmp_path / ".config" / "google-chrome"
    _write_local_state(
        chrome_root,
        profiles={
            "Profile 1": {"name": "Work", "user_name": "work@example.com"},
            "Profile 2": {"gaia_name": "Personal", "user_name": ""},
            "../escape": {"name": "Do not expose"},
        },
    )
    (chrome_root / "Profile 2").mkdir()
    profiles = server.discover_chrome_profiles(home=tmp_path, platform_name="linux", environ={})
    assert [profile["name"] for profile in profiles] == ["Work", "Personal"]
    assert profiles[0]["lastUsed"] is True
    assert profiles[0]["email"] == "work@example.com"
    assert profiles[0]["userDataDir"] == str(chrome_root)
    assert "Cookies" not in json.dumps(profiles)


def test_discover_chrome_profiles_reports_lock_and_default_dir_guidance(tmp_path):
    chrome_root = tmp_path / ".config" / "google-chrome"
    _write_local_state(chrome_root, profiles={"Profile 1": {"name": "Work"}})
    (chrome_root / "SingletonLock").write_text("locked", encoding="utf-8")
    profile = server.discover_chrome_profiles(home=tmp_path, platform_name="linux", environ={})[0]
    assert profile["locked"] is True
    assert profile["requiresDedicatedUserDataDir"] is True
    assert "close Chrome" in profile["warning"]


def test_profile_preflight_rejects_locked_profile_and_warns_on_default_dir(tmp_path):
    root = tmp_path / "User Data"
    (root / "Default").mkdir(parents=True)
    check = server.chrome_profile_preflight(str(root), "Default")
    assert check["locked"] is False
    assert check["requiresDedicatedUserDataDir"] is True
    (root / "SingletonLock").touch()
    assert server.chrome_profile_preflight(str(root), "Default")["locked"] is True
    with pytest.raises(ValueError, match="one Chrome profile"):
        server.chrome_profile_preflight(str(root), "../secrets")


def test_build_crawl_argv_wires_persistent_chrome_profile(tmp_path):
    root = tmp_path / "ChromeProfileRoot"
    (root / "Profile 1").mkdir(parents=True)
    spec = server.parse_crawl_spec(
        {
            "url": "https://site.example",
            "backend": "playwright",
            "browserChannel": "chrome",
            "userDataDir": str(root),
            "profileDirectory": "Profile 1",
            "headed": True,
        }
    )
    argv = server.build_crawl_argv(spec, "dsn")
    assert "--js" in argv
    assert argv[argv.index("--playwright-channel") + 1] == "chrome"
    assert argv[argv.index("--playwright-user-data-dir") + 1] == str(root)
    assert argv[argv.index("--playwright-profile-directory") + 1] == "Profile 1"
    assert "--headed" in argv


def test_profile_launch_is_mutually_exclusive_with_obscura(tmp_path):
    root = tmp_path / "ChromeProfileRoot"
    (root / "Default").mkdir(parents=True)
    with pytest.raises(ValueError, match="Obscura"):
        server.parse_crawl_spec(
            {
                "url": "https://site.example",
                "backend": "obscura",
                "userDataDir": str(root),
                "profileDirectory": "Default",
            }
        )
