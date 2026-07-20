"""Golden contract: site-level ``compare`` with host remapping (ticket 3344).

Freezes the ``crawler-cli/compare/1`` row schema and the stdout summary,
including ``--replace`` host remapping, missing/new pages, url moves, title
changes, remap-aware link diffs and the near/changed simhash verdicts.
"""

from __future__ import annotations

import asyncio
import json

from contract_fixtures import (
    assert_matches_golden,
    compare_baseline_results,
    compare_candidate_results,
    write_artifact,
)

from crawler_cli.__main__ import COMPARE_SCHEMA_VERSION, _build_parser, _dispatch


def _run_compare(tmp_path) -> tuple[int, str, str]:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    out = tmp_path / "rows.json"
    write_artifact(baseline, compare_baseline_results())
    write_artifact(candidate, compare_candidate_results())
    args = _build_parser().parse_args(
        [
            "compare",
            str(baseline),
            str(candidate),
            "--compare-links",
            "--replace",
            "old.example=new.example",
            "--output",
            str(out),
        ]
    )
    code = asyncio.run(_dispatch(args))
    return code, out.read_text(encoding="utf-8"), str(out)


def test_compare_rows_match_golden(tmp_path) -> None:
    code, actual, _ = _run_compare(tmp_path)
    assert code == 0
    payload = json.loads(actual)
    assert payload["schema_version"] == COMPARE_SCHEMA_VERSION == "crawler-cli/compare/1"
    assert_matches_golden("compare_rows.json", actual)


def test_compare_stdout_summary_matches_golden(tmp_path, capsys) -> None:
    code, _, _ = _run_compare(tmp_path)
    assert code == 0
    stdout = capsys.readouterr().out
    summary = stdout.split("\n", 1)[1]
    assert_matches_golden("compare_summary.json", summary)


def test_compare_row_semantics(tmp_path) -> None:
    _, actual, _ = _run_compare(tmp_path)
    rows = {row["path"]: row for row in json.loads(actual)["rows"]}

    # Host remapping lines the same logical page up across hosts.
    home = rows["/"]
    assert home["exists_on_baseline"] and home["exists_on_candidate"]
    assert home["content_verdict"] == "near"
    assert home["simhash_distance"] == 1
    # Canonicals differing only by host are NOT a change under --replace.
    assert home["baseline_title"] is None  # no title change recorded

    # Remap-aware link diff: only the genuinely new link appears.
    assert [link["href"] for link in home["links_added"]] == ["https://new.example/fresh"]
    assert home["links_removed"] == []

    about = rows["/about"]
    assert about["baseline_title"] == "About Us"
    assert about["candidate_title"] == "About Us, Rebranded"
    assert about["content_verdict"] == "identical"

    # Missing on candidate vs new on candidate.
    gone = rows["/gone"]
    assert gone["exists_on_baseline"] is True
    assert gone["exists_on_candidate"] is False
    assert gone["content_verdict"] == "missing"
    fresh = rows["/fresh"]
    assert fresh["exists_on_baseline"] is False
    assert fresh["content_verdict"] == "missing"

    # A baseline-side redirect is reported as a url move with its chain.
    moved = rows["/old-path"]
    assert moved["is_moved_content"] is True
    assert moved["moved_from_path"] == "/old-path"
    assert moved["moved_to_path"] == "/new-path"
    assert moved["redirect_chain"] == "/old-path -> /new-path"
    assert rows["/new-path"]["exists_on_candidate"] is True
