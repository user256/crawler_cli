"""Golden contract: ``compare-urls`` JSON/CSV outputs and stdout summary (ticket 3344).

These tests freeze the ``crawler-cli/compare-urls/1`` schema against checked-in
golden files. The fixture mapping exercises every redirect verdict, missing
pages on either side, near/changed/identical content, the captured redirect-hop
chain, and the signed/unsigned simhash BIGINT mapping.
"""

from __future__ import annotations

import asyncio
import json

from contract_fixtures import (
    PAIRS_CSV,
    assert_matches_golden,
    compare_urls_source_results,
    compare_urls_target_results,
    write_artifact,
)

from crawler_cli.__main__ import COMPARE_URLS_SCHEMA_VERSION, _build_parser, _dispatch


def _run_compare_urls(tmp_path, output_name: str) -> tuple[int, str]:
    src = tmp_path / "src.json"
    tgt = tmp_path / "tgt.json"
    pairs = tmp_path / "pairs.csv"
    out = tmp_path / output_name
    write_artifact(src, compare_urls_source_results())
    write_artifact(tgt, compare_urls_target_results())
    pairs.write_text(PAIRS_CSV, encoding="utf-8")
    args = _build_parser().parse_args(
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
        ]
    )
    code = asyncio.run(_dispatch(args))
    return code, out.read_text(encoding="utf-8")


def test_compare_urls_json_output_matches_golden(tmp_path) -> None:
    code, actual = _run_compare_urls(tmp_path, "out.json")
    assert code == 0  # no --fail-on: findings do not affect the exit code
    payload = json.loads(actual)
    assert payload["schema_version"] == COMPARE_URLS_SCHEMA_VERSION == "crawler-cli/compare-urls/1"
    assert_matches_golden("compare_urls_rows.json", actual)


def test_compare_urls_csv_output_matches_golden(tmp_path) -> None:
    code, actual = _run_compare_urls(tmp_path, "out.csv")
    assert code == 0
    assert_matches_golden("compare_urls_rows.csv", actual)


def test_compare_urls_stdout_summary_matches_golden(tmp_path, capsys) -> None:
    code, _ = _run_compare_urls(tmp_path, "out.json")
    assert code == 0
    stdout = capsys.readouterr().out
    # First line is the "Wrote N rows to <tmp path>" notice; the JSON summary
    # after it is the frozen machine surface.
    summary = stdout.split("\n", 1)[1]
    assert_matches_golden("compare_urls_summary.json", summary)


def test_compare_urls_row_semantics(tmp_path) -> None:
    """Spot-check the semantics the goldens encode, so a golden regeneration
    that silently flips a verdict still fails loudly here."""
    _, actual = _run_compare_urls(tmp_path, "out.json")
    rows = {row["source_url"]: row for row in json.loads(actual)["rows"]}

    assert rows["https://old.example/a"]["redirect_verdict"] == "redirect_ok"
    assert rows["https://old.example/a"]["content_verdict"] == "identical"
    assert rows["https://old.example/a"]["note"] == "homepage"
    assert rows["https://old.example/a"]["redirect_chain"] == [{"url": "https://old.example/a", "status": 301}]

    assert rows["https://old.example/b"]["redirect_verdict"] == "redirect_chain"
    assert rows["https://old.example/b"]["content_verdict"] == "near"
    assert rows["https://old.example/b"]["simhash_distance"] == 1

    assert rows["https://old.example/c"]["redirect_verdict"] == "redirect_temporary"
    assert rows["https://old.example/c"]["content_verdict"] == "changed"

    assert rows["https://old.example/d"]["redirect_verdict"] == "no_redirect"
    assert rows["https://old.example/e"]["redirect_verdict"] == "redirect_wrong_target"
    assert rows["https://old.example/f"]["redirect_verdict"] == "error_status"

    # Missing pages: source never crawled vs target absent.
    assert rows["https://old.example/g"]["redirect_verdict"] == "not_crawled"
    assert rows["https://old.example/g"]["content_verdict"] == "missing"
    assert rows["https://old.example/g"]["source_status"] is None
    assert rows["https://old.example/h"]["redirect_verdict"] == "redirect_ok"
    assert rows["https://old.example/h"]["content_verdict"] == "missing"
    assert rows["https://old.example/h"]["target_status"] is None

    # Signed vs unsigned simhash: same fingerprint in both representations
    # must compare at distance 0 ("near", since the stored sha256s differ).
    assert rows["https://old.example/i"]["simhash_distance"] == 0
    assert rows["https://old.example/i"]["content_verdict"] == "near"
    assert rows["https://old.example/i"]["sha256_equal"] is False
