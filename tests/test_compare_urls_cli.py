"""Ticket 122: compare-urls / compare CLI end-to-end (artifact-sourced)."""

import asyncio
import json

from crawler_cli.__main__ import _build_parser, _dispatch
from crawler_cli.hashing import sha256_hash, simhash64
from crawler_cli.serialization import serialize_crawl_result
from crawler_cli.models import CrawlResult, ExtractedContent, RobotsDirectives


def _artifact(path, results):
    payload = {"mode": "list", "seed_urls": [], "results": [serialize_crawl_result(r) for r in results]}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _result(
    requested, final, *, status=200, chain=None, raw_html="<html><body><p>hello world</p></body></html>", title="T"
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


def _run(argv):
    args = _build_parser().parse_args(argv)
    return asyncio.run(_dispatch(args))


def test_compare_urls_fail_on_redirect_mismatch(tmp_path, capsys):
    src = tmp_path / "src.json"
    tgt = tmp_path / "tgt.json"
    pairs = tmp_path / "pairs.csv"
    out = tmp_path / "out.json"

    _artifact(
        src,
        [
            _result("https://old/a", "https://new/a", chain=[{"url": "https://old/a", "status": 301}]),
            _result("https://old/b", "https://old/b", chain=[]),  # no redirect -> mismatch
        ],
    )
    _artifact(tgt, [_result("https://new/a", "https://new/a"), _result("https://new/b", "https://new/b")])
    pairs.write_text(
        "source_url,target_url\nhttps://old/a,https://new/a\nhttps://old/b,https://new/b\n",
        encoding="utf-8",
    )

    code = _run(
        [
            "compare-urls",
            "--pairs",
            str(pairs),
            "--source-artifact",
            str(src),
            "--target-artifact",
            str(tgt),
            "--output",
            str(out),
            "--fail-on",
            "redirect_mismatch",
        ]
    )
    assert code == 3  # findings gate: one pair does not redirect (EXIT_FINDINGS)

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "crawler-cli/compare-urls/1"
    rows = payload["rows"]
    verdicts = {r["source_url"]: r["redirect_verdict"] for r in rows}
    assert verdicts["https://old/a"] == "redirect_ok"
    assert verdicts["https://old/b"] == "no_redirect"


def test_compare_urls_clean_mapping_passes(tmp_path):
    src = tmp_path / "src.json"
    tgt = tmp_path / "tgt.json"
    pairs = tmp_path / "pairs.csv"

    _artifact(src, [_result("https://old/a", "https://new/a", chain=[{"url": "https://old/a", "status": 301}])])
    _artifact(tgt, [_result("https://new/a", "https://new/a")])
    pairs.write_text("source_url,target_url\nhttps://old/a,https://new/a\n", encoding="utf-8")

    code = _run(
        [
            "compare-urls",
            "--pairs",
            str(pairs),
            "--source-artifact",
            str(src),
            "--target-artifact",
            str(tgt),
            "--fail-on",
            "any",
        ]
    )
    assert code == 0


def test_compare_urls_source_resolution_ignores_final_url(tmp_path):
    # Artifact holds A->B then B->C (a chained migration mapping). The pair
    # B->C must resolve to the crawl of B (requested_url), not the A result
    # that merely redirected to B — otherwise B's verdict is computed from
    # A's redirect and reports redirect_wrong_target on a correct mapping.
    src = tmp_path / "src.json"
    tgt = tmp_path / "tgt.json"
    pairs = tmp_path / "pairs.csv"
    out = tmp_path / "out.json"

    _artifact(
        src,
        [
            _result("https://old/a", "https://old/b", chain=[{"url": "https://old/a", "status": 301}]),
            _result("https://old/b", "https://new/c", chain=[{"url": "https://old/b", "status": 301}]),
        ],
    )
    _artifact(tgt, [_result("https://new/c", "https://new/c")])
    pairs.write_text("source_url,target_url\nhttps://old/b,https://new/c\n", encoding="utf-8")

    code = _run(
        [
            "compare-urls",
            "--pairs",
            str(pairs),
            "--source-artifact",
            str(src),
            "--target-artifact",
            str(tgt),
            "--output",
            str(out),
            "--fail-on",
            "redirect_mismatch",
        ]
    )
    assert code == 0

    rows = json.loads(out.read_text(encoding="utf-8"))["rows"]
    assert rows[0]["redirect_verdict"] == "redirect_ok"
    assert rows[0]["source_final_url"] == "https://new/c"


def test_redirect_chain_survives_serialization_round_trip(tmp_path):
    from crawler_cli.__main__ import _load_saved_crawl

    result = _result("https://old/a", "https://new/a", chain=[{"url": "https://old/a", "status": 301}])
    artifact = tmp_path / "one.json"
    _artifact(artifact, [result])
    job = _load_saved_crawl(artifact)
    assert job.results[0].redirect_chain == [{"url": "https://old/a", "status": 301}]


# --- ticket 123: exit code, CSV hops, arg handling -------------------------


def test_fail_on_uses_distinct_exit_code(tmp_path):
    # A tripped CI gate must be distinguishable from a usage error (both were 2).
    from crawler_cli.exit_codes import EXIT_FINDINGS, EXIT_VALIDATION

    src, tgt, pairs = tmp_path / "s.json", tmp_path / "t.json", tmp_path / "p.csv"
    _artifact(src, [_result("https://old/b", "https://old/b", chain=[])])
    _artifact(tgt, [_result("https://new/b", "https://new/b")])
    pairs.write_text("source_url,target_url\nhttps://old/b,https://new/b\n", encoding="utf-8")

    code = _run(
        ["compare-urls", "--pairs", str(pairs), "--source-artifact", str(src),
         "--target-artifact", str(tgt), "--fail-on", "redirect_mismatch"]
    )
    assert code == EXIT_FINDINGS
    assert code != EXIT_VALIDATION


def test_csv_output_has_hops_column_and_clean_final_url(tmp_path):
    import csv as _csv

    src, tgt, pairs, out = tmp_path / "s.json", tmp_path / "t.json", tmp_path / "p.csv", tmp_path / "o.csv"
    _artifact(
        src,
        [_result(
            "https://old/a", "https://new/a",
            chain=[{"url": "https://old/a", "status": 301}, {"url": "https://mid/a", "status": 302}],
        )],
    )
    _artifact(tgt, [_result("https://new/a", "https://new/a")])
    pairs.write_text("source_url,target_url\nhttps://old/a,https://new/a\n", encoding="utf-8")

    assert _run(["compare-urls", "--pairs", str(pairs), "--source-artifact", str(src),
                 "--target-artifact", str(tgt), "--output", str(out)]) == 0

    row = next(iter(_csv.DictReader(out.read_text(encoding="utf-8").splitlines())))
    # source_final_url is a clean URL — no "(N hop)" appended into it.
    assert row["source_final_url"] == "https://new/a"
    # Hops live in their own columns and carry per-hop status.
    assert row["redirect_hops"] == "2"
    assert row["redirect_chain"] == "https://old/a (301) -> https://mid/a (302)"


def test_missing_artifact_reports_clean_error(tmp_path, capsys):
    from crawler_cli.exit_codes import EXIT_VALIDATION

    pairs = tmp_path / "p.csv"
    pairs.write_text("source_url,target_url\nhttps://old/a,https://new/a\n", encoding="utf-8")
    code = _run(["compare-urls", "--pairs", str(pairs), "--source-artifact", str(tmp_path / "nope.json")])
    assert code == EXIT_VALIDATION
    assert "nope.json" in capsys.readouterr().err


def test_compare_rejects_both_json_and_store(tmp_path, capsys):
    from crawler_cli.exit_codes import EXIT_VALIDATION

    a = tmp_path / "a.json"
    _artifact(a, [_result("https://x/1", "https://x/1")])
    code = _run(["compare", str(a), str(a), "--baseline-store", "postgresql://nope/db"])
    assert code == EXIT_VALIDATION
    assert "not both" in capsys.readouterr().err
