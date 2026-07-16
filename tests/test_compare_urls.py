"""Ticket 122: compare-urls CSV parsing, redirect verdicts, row building."""

import pytest

from crawler_cli.compare_urls import (
    ERROR_STATUS,
    NO_REDIRECT,
    NOT_CRAWLED,
    REDIRECT_CHAIN,
    REDIRECT_OK,
    REDIRECT_TEMPORARY,
    REDIRECT_WRONG_TARGET,
    UrlPair,
    build_pair_row,
    classify_redirect,
    load_url_pairs,
    normalize_url_for_match,
    rows_failing,
)
from crawler_cli.hashing import sha256_hash, simhash64
from crawler_cli.models import CrawlResult, ExtractedContent, RobotsDirectives


def _src(
    requested,
    final,
    *,
    status=200,
    chain=None,
    raw_html="<html><body><h1>H</h1><p>body text</p></body></html>",
    title="T",
):
    extracted = ExtractedContent(
        title=title,
        meta_description=None,
        meta_robots=RobotsDirectives(),
        x_robots_tag=RobotsDirectives(),
        canonical=None,
        x_canonical=None,
        hreflang_links=[],
        html_lang=None,
        headings={"h1": ["H"], "h2": []},
        text="",
        word_count=2,
        metadata={},
    )
    return CrawlResult(
        requested_url=requested,
        final_url=final,
        status=status,
        headers={},
        content_type="text/html",
        fetch_backend="aiohttp",
        extracted=extracted,
        raw_html=raw_html,
        content_hash_sha256=sha256_hash(raw_html),
        content_hash_simhash=simhash64(raw_html),
        redirect_chain=chain or [],
    )


# --- CSV parsing ------------------------------------------------------------


def test_load_pairs_basic(tmp_path):
    csv = tmp_path / "m.csv"
    csv.write_text("source_url,target_url,note\nhttps://a/1,https://b/1,keep\n", encoding="utf-8")
    result = load_url_pairs(csv)
    assert result.pairs == [UrlPair("https://a/1", "https://b/1", "keep")]
    assert result.skipped == 0


def test_load_pairs_skips_empty_and_duplicate_sources(tmp_path):
    csv = tmp_path / "m.csv"
    csv.write_text(
        "source_url,target_url\n"
        "https://a/1,https://b/1\n"
        ",https://b/2\n"  # empty source
        "https://a/3,\n"  # empty target
        "https://a/1,https://b/9\n",  # duplicate source
        encoding="utf-8",
    )
    result = load_url_pairs(csv)
    assert [p.source_url for p in result.pairs] == ["https://a/1"]
    assert result.skipped == 3
    assert len(result.skipped_reasons) == 3


def test_load_pairs_custom_columns(tmp_path):
    csv = tmp_path / "m.csv"
    csv.write_text("from,to\nhttps://a,https://b\n", encoding="utf-8")
    result = load_url_pairs(csv, source_column="from", target_column="to")
    assert result.pairs == [UrlPair("https://a", "https://b", None)]


def test_load_pairs_missing_columns_raises(tmp_path):
    csv = tmp_path / "m.csv"
    csv.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_url_pairs(csv)


# --- URL normalization ------------------------------------------------------


def test_normalize_trailing_slash_and_case():
    assert normalize_url_for_match("https://Example.com/Path/") == normalize_url_for_match("https://example.com/Path")
    assert normalize_url_for_match("HTTPS://HOST") == "https://host"
    assert normalize_url_for_match(None) == ""


# --- redirect verdict matrix ------------------------------------------------


def test_verdict_ok_permanent_single_hop():
    pair = UrlPair("https://old/a", "https://new/a")
    src = _src("https://old/a", "https://new/a", chain=[{"url": "https://old/a", "status": 301}])
    assert classify_redirect(pair, src) == REDIRECT_OK


def test_verdict_wrong_target():
    pair = UrlPair("https://old/a", "https://new/a")
    src = _src("https://old/a", "https://new/elsewhere", chain=[{"url": "https://old/a", "status": 301}])
    assert classify_redirect(pair, src) == REDIRECT_WRONG_TARGET


def test_verdict_temporary():
    pair = UrlPair("https://old/a", "https://new/a")
    src = _src("https://old/a", "https://new/a", chain=[{"url": "https://old/a", "status": 302}])
    assert classify_redirect(pair, src) == REDIRECT_TEMPORARY


def test_verdict_multi_hop_chain():
    pair = UrlPair("https://old/a", "https://new/a")
    src = _src(
        "https://old/a",
        "https://new/a",
        chain=[{"url": "https://old/a", "status": 301}, {"url": "https://mid/a", "status": 301}],
    )
    assert classify_redirect(pair, src) == REDIRECT_CHAIN


def test_verdict_no_redirect():
    pair = UrlPair("https://old/a", "https://new/a")
    src = _src("https://old/a", "https://old/a", chain=[])
    assert classify_redirect(pair, src) == NO_REDIRECT


def test_verdict_error_status():
    pair = UrlPair("https://old/a", "https://new/a")
    src = _src("https://old/a", "https://old/a", status=404, chain=[])
    assert classify_redirect(pair, src) == ERROR_STATUS


def test_verdict_not_crawled_when_source_missing():
    pair = UrlPair("https://old/a", "https://new/a")
    assert classify_redirect(pair, None) == NOT_CRAWLED


def test_verdict_ok_ignores_trailing_slash():
    pair = UrlPair("https://old/a", "https://new/a/")
    src = _src("https://old/a", "https://new/a", chain=[{"url": "https://old/a", "status": 308}])
    assert classify_redirect(pair, src) == REDIRECT_OK


# --- row building + fail-on -------------------------------------------------


def test_build_pair_row_content_and_deltas():
    pair = UrlPair("https://old/a", "https://new/a", note="n")
    src = _src("https://old/a", "https://new/a", chain=[{"url": "https://old/a", "status": 301}], title="Old")
    tgt = _src("https://new/a", "https://new/a", title="New")
    row = build_pair_row(pair, src, tgt)
    assert row["redirect_verdict"] == REDIRECT_OK
    assert row["sha256_equal"] is True
    assert row["content_verdict"] == "identical"
    assert row["field_deltas"]["title"] == {"source": "Old", "target": "New", "changed": True}
    assert row["note"] == "n"


def test_build_pair_row_missing_target():
    pair = UrlPair("https://old/a", "https://new/a")
    src = _src("https://old/a", "https://new/a", chain=[{"url": "https://old/a", "status": 301}])
    row = build_pair_row(pair, src, None)
    assert row["content_verdict"] == "missing"
    assert row["sha256_equal"] is None


def test_rows_failing_modes():
    rows = [
        {"redirect_verdict": REDIRECT_OK, "content_verdict": "identical"},
        {"redirect_verdict": NO_REDIRECT, "content_verdict": "identical"},
        {"redirect_verdict": REDIRECT_OK, "content_verdict": "changed"},
    ]
    assert len(rows_failing(rows, "redirect_mismatch")) == 1
    assert len(rows_failing(rows, "content_changed")) == 1
    assert len(rows_failing(rows, "any")) == 2
    with pytest.raises(ValueError):
        rows_failing(rows, "nonsense")
