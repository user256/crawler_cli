"""Frozen exit-code taxonomy (tickets 092 + 3344).

0 success | 1 crawl/persistence failure | 2 validation/usage error |
3 findings gate (--fail-on) | 130 interrupted. Automation (the portal migration
worker) branches on these exact values.
"""

from __future__ import annotations

import asyncio
import dataclasses

from contract_fixtures import (
    PAIRS_CSV,
    compare_urls_source_results,
    compare_urls_target_results,
    make_result,
    write_artifact,
)

from crawler_cli.__main__ import _build_parser, _dispatch
from crawler_cli.exit_codes import (
    EXIT_FAILURE,
    EXIT_FINDINGS,
    EXIT_INTERRUPTED,
    EXIT_SUCCESS,
    EXIT_VALIDATION,
    resolve_crawl_exit_code,
)
from crawler_cli.models import CrawlJobResult

assert (EXIT_SUCCESS, EXIT_FAILURE, EXIT_VALIDATION, EXIT_FINDINGS, EXIT_INTERRUPTED) == (0, 1, 2, 3, 130)


def _job(**overrides) -> CrawlJobResult:
    kwargs = dict(mode="list", seed_urls=[], results=[make_result("https://old.example/a", "https://old.example/a")])
    kwargs.update(overrides)
    return CrawlJobResult(**kwargs)


def _run(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    return asyncio.run(_dispatch(args))


class TestCrawlExitCodes:
    def test_clean_crawl_is_success(self) -> None:
        assert resolve_crawl_exit_code(_job()) == EXIT_SUCCESS

    def test_persist_errors_fail(self) -> None:
        failed = dataclasses.replace(
            make_result("https://old.example/a", "https://old.example/a"), persist_error="boom"
        )
        job = _job(results=[failed])
        assert resolve_crawl_exit_code(job) == EXIT_FAILURE
        # --allow-persist-failures downgrades ONLY persist errors.
        assert resolve_crawl_exit_code(job, allow_persist_failures=True) == EXIT_SUCCESS

    def test_frontier_incompleteness_fails_even_with_allow_persist_failures(self) -> None:
        job = _job(frontier_mark_done_failed_urls=["https://old.example/a"])
        assert resolve_crawl_exit_code(job) == EXIT_FAILURE
        assert resolve_crawl_exit_code(job, allow_persist_failures=True) == EXIT_FAILURE

    def test_interruption_takes_precedence(self) -> None:
        failed = dataclasses.replace(
            make_result("https://old.example/a", "https://old.example/a"), persist_error="boom"
        )
        job = _job(results=[failed], interrupted=True, frontier_mark_done_failed_urls=["https://old.example/a"])
        assert resolve_crawl_exit_code(job) == EXIT_INTERRUPTED


class TestCompareUrlsExitCodes:
    def _fixture_argv(self, tmp_path, *extra: str) -> list[str]:
        src = tmp_path / "src.json"
        tgt = tmp_path / "tgt.json"
        pairs = tmp_path / "pairs.csv"
        write_artifact(src, compare_urls_source_results())
        write_artifact(tgt, compare_urls_target_results())
        pairs.write_text(PAIRS_CSV, encoding="utf-8")
        return [
            "compare-urls",
            "--pairs",
            str(pairs),
            "--source-artifact",
            str(src),
            "--target-artifact",
            str(tgt),
            *extra,
        ]

    def test_findings_gate_returns_exit_findings(self, tmp_path, capsys) -> None:
        assert _run(self._fixture_argv(tmp_path, "--fail-on", "any")) == EXIT_FINDINGS
        assert _run(self._fixture_argv(tmp_path, "--fail-on", "redirect_mismatch")) == EXIT_FINDINGS
        assert _run(self._fixture_argv(tmp_path, "--fail-on", "content_changed")) == EXIT_FINDINGS

    def test_findings_without_fail_on_still_exit_success(self, tmp_path, capsys) -> None:
        assert _run(self._fixture_argv(tmp_path)) == EXIT_SUCCESS

    def test_clean_mapping_passes_the_gate(self, tmp_path, capsys) -> None:
        src = tmp_path / "src.json"
        tgt = tmp_path / "tgt.json"
        pairs = tmp_path / "pairs.csv"
        write_artifact(
            src,
            [
                make_result(
                    "https://old.example/a",
                    "https://new.example/a",
                    chain=[{"url": "https://old.example/a", "status": 301}],
                )
            ],
        )
        write_artifact(tgt, [make_result("https://new.example/a", "https://new.example/a")])
        pairs.write_text("source_url,target_url\nhttps://old.example/a,https://new.example/a\n", encoding="utf-8")
        argv = [
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
        assert _run(argv) == EXIT_SUCCESS

    def test_missing_pairs_csv_is_validation_error(self, tmp_path, capsys) -> None:
        argv = self._fixture_argv(tmp_path)
        argv[argv.index("--pairs") + 1] = str(tmp_path / "nope.csv")
        assert _run(argv) == EXIT_VALIDATION

    def test_empty_mapping_is_validation_error(self, tmp_path, capsys) -> None:
        argv = self._fixture_argv(tmp_path)
        (tmp_path / "pairs.csv").write_text("source_url,target_url\n", encoding="utf-8")
        assert _run(argv) == EXIT_VALIDATION

    def test_bad_replace_spec_is_validation_error(self, tmp_path, capsys) -> None:
        assert _run(self._fixture_argv(tmp_path, "--replace", "no-equals-sign")) == EXIT_VALIDATION

    def test_unset_store_env_var_is_validation_error(self, tmp_path, capsys, monkeypatch) -> None:
        monkeypatch.delenv("CONTRACT_UNSET_DSN_VAR", raising=False)
        argv = self._fixture_argv(tmp_path, "--source-store-env", "CONTRACT_UNSET_DSN_VAR")
        assert _run(argv) == EXIT_VALIDATION
