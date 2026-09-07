import asyncio
import csv

import pytest

from crawler_cli import CrawlConfig, CrawlEngine
from crawler_cli.__main__ import (
    _build_parser,
    _collect_seed_urls,
    _render_comparison_payload,
    _render_stratum_coverage,
    _render_url_strata,
    _run_compare_renders,
    _select_run_render_candidates,
    _write_render_comparison_html,
    _write_render_comparison_output,
)
from crawler_cli.compare_renders import (
    RenderParityComparison,
    _cluster_paths,
    compare_rendered_result,
    compare_renders,
)
from crawler_cli.extract import extract_page_data
from crawler_cli.models import CrawlResult, FetchResponse


class StaticBackend:
    def __init__(self, html: str, status: int = 200) -> None:
        self.html = html
        self.status = status

    async def fetch(self, url: str) -> FetchResponse:
        return FetchResponse(
            url=url,
            requested_url=url,
            status=self.status,
            headers={"Content-Type": "text/html; charset=utf-8"},
            body=self.html.encode(),
            text=self.html,
        )


@pytest.mark.asyncio
async def test_compare_renders_static_page_ok(monkeypatch):
    html = "<html><head><title>Hello</title></head><body><a href='/a'>A</a></body></html>"
    config = CrawlConfig(backend="aiohttp")

    async def fake_crawl(self, url: str) -> CrawlResult:
        return CrawlResult(
            requested_url=url,
            final_url=url,
            status=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content_type="text/html; charset=utf-8",
            fetch_backend=self.config.backend,
            extracted=extract_page_data(html, url, {"Content-Type": "text/html; charset=utf-8"}),
            raw_html=html,
        )

    monkeypatch.setattr(CrawlEngine, "crawl", fake_crawl)

    # Both nojs and js use same backend in this test
    result = await compare_renders(
        "https://example.com/",
        nojs_config=config,
        js_config=config,
    )
    assert result.verdict == "ok"
    assert result.title_match is True
    assert result.canonical_match is True


def test_cluster_paths_groups_correctly():
    paths = {"/products/a", "/products/b", "/blog/c", "/about"}
    clusters = _cluster_paths(paths)
    assert clusters["products"] == 2
    assert clusters["blog"] == 1
    assert clusters["about"] == 1


def _same_navigation_result(raw_html: str, rendered_html: str, *, settled: bool | None = True) -> CrawlResult:
    headers = {"Content-Type": "text/html; charset=utf-8"}
    return CrawlResult(
        requested_url="https://example.com/",
        final_url="https://example.com/",
        status=200,
        headers=headers,
        content_type=headers["Content-Type"],
        fetch_backend="playwright",
        extracted=extract_page_data(rendered_html, "https://example.com/", headers),
        raw_html=rendered_html,
        render_raw_html=raw_html,
        render_settled=settled,
    )


def test_same_navigation_comparison_reports_multiple_indexing_findings():
    raw = """<html><head><title>Raw</title><meta name='robots' content='index'>
    <link rel='canonical' href='/raw'></head><body><h1>Raw heading</h1><a href='/old'>Old</a></body></html>"""
    rendered = """<html><head><title>Rendered</title><meta name='robots' content='noindex'>
    <link rel='canonical' href='/rendered'></head><body><h1>Rendered heading</h1><a href='/new'>New</a></body></html>"""

    comparison = compare_rendered_result(_same_navigation_result(raw, rendered))

    assert comparison.state == "complete"
    assert comparison.primary_summary in {"canonical_changed", "indexing_directive_changed"}
    assert {finding.code for finding in comparison.findings} >= {
        "metadata_render_dependency",
        "canonical_changed",
        "indexing_directive_changed",
        "internal_links_added_after_render",
        "internal_links_removed_after_render",
    }
    assert comparison.only_in_rendered == {"https://example.com/new"}
    assert comparison.only_in_raw == {"https://example.com/old"}


def test_same_navigation_missing_baseline_is_inconclusive_not_ok():
    result = _same_navigation_result("<html></html>", "<html><body>Rendered</body></html>")
    result.render_raw_html = None

    comparison = compare_rendered_result(result)

    assert comparison.state == "inconclusive"
    assert comparison.primary_summary == "inconclusive"
    assert comparison.findings[0].code == "render_comparison_incomplete"


def test_same_navigation_truncated_baseline_is_inconclusive_not_ok():
    result = _same_navigation_result("<html></html>", "<html><body>Rendered</body></html>")
    result.render_baseline_truncated = True

    comparison = compare_rendered_result(result)

    assert comparison.state == "inconclusive"
    assert comparison.state_reason == "render_baseline_truncated"


def test_same_navigation_reports_structured_data_changes():
    comparison = compare_rendered_result(
        _same_navigation_result(
            '<html><head><script type=\'application/ld+json\'>{"@context": "https://schema.org", "@type": "Article"}</script></head></html>',
            '<html><head><script type=\'application/ld+json\'>{"@context": "https://schema.org", "@type": "Product"}</script></head></html>',
        )
    )

    finding = next(finding for finding in comparison.findings if finding.code == "structured_data_changed")

    assert finding.field == "structured_data"
    assert finding.raw_value != finding.rendered_value


def test_cluster_paths_parses_absolute_urls_not_schemes():
    clusters = _cluster_paths(
        {
            "https://example.com/products/a",
            "https://example.com/products/b",
            "https://example.com/blog/c",
        }
    )

    assert clusters == {"products": 2, "blog": 1}


def test_render_comparison_outputs_redact_sensitive_url_values(tmp_path):
    comparison = compare_rendered_result(
        _same_navigation_result(
            "<html><body><a href='/old?token=supersecret'>Old</a></body></html>",
            "<html><body><a href='/new?token=supersecret'>New</a></body></html>",
        )
    )
    comparison.url = "https://example.com/?token=supersecret"
    payload = _render_comparison_payload([comparison], selected_urls=[comparison.url], capped=False)
    output = tmp_path / "comparison.json"
    report = tmp_path / "comparison.html"
    _write_render_comparison_output(payload, str(output))
    _write_render_comparison_html(payload, str(report))

    assert "supersecret" not in output.read_text(encoding="utf-8")
    assert "supersecret" not in report.read_text(encoding="utf-8")
    assert "[REDACTED]" in output.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_compare_renders_cli_writes_versioned_output_without_second_fetch(monkeypatch, tmp_path):
    comparison = compare_rendered_result(
        _same_navigation_result("<html><title>Raw</title></html>", "<html><title>Rendered</title></html>")
    )

    async def fake_compare(_engine, urls, *, max_concurrent):
        assert list(urls) == ["https://example.com/"]
        assert max_concurrent == 1
        return [comparison]

    monkeypatch.setattr("crawler_cli.__main__.compare_rendered_sample", fake_compare)
    output = tmp_path / "parity.json"
    args = _build_parser().parse_args(["compare-renders", "https://example.com/", "--output", str(output)])

    assert await _run_compare_renders(args) == 0
    assert '"schema_version": "crawler-cli/render-comparison/1"' in output.read_text(encoding="utf-8")


def test_compare_renders_cli_accepts_multiple_positional_urls():
    args = _build_parser().parse_args(["compare-renders", "https://example.com/", "https://example.com/about/"])

    assert _collect_seed_urls(args) == ["https://example.com/", "https://example.com/about/"]


def test_run_selection_is_deterministic_and_covers_strata_before_duplicates():
    candidates = [
        {"url": "https://example.com/products/a", "html_lang": "en"},
        {"url": "https://example.com/products/b", "html_lang": "en"},
        {"url": "https://example.com/fr/products/a", "html_lang": "fr"},
        {"url": "https://blog.example.com/posts/a", "html_lang": "en"},
    ]

    selected, strata, url_strata, stratum_sources = _select_run_render_candidates(candidates, max_pages=3)

    assert selected == [
        "https://blog.example.com/posts/a",
        "https://example.com/products/a",
        "https://example.com/fr/products/a",
    ]
    assert len(strata) == 3
    assert all(item["selected_count"] == 1 for item in strata)
    assert sum(int(item["candidate_count"]) for item in strata) == len(candidates)
    assert {url_strata[url] for url in selected} == {item["stratum"] for item in strata}
    assert not any("template" in item["stratum"] for item in strata)
    assert _select_run_render_candidates(candidates, max_pages=3)[0] == selected
    assert set(stratum_sources.values()) == {"computed_path_stratum"}


@pytest.mark.asyncio
async def test_compare_renders_cli_selects_a_live_sample_from_one_run_and_persists(monkeypatch, capsys):
    comparison = compare_rendered_result(
        _same_navigation_result("<html><title>Raw</title></html>", "<html><title>Rendered</title></html>")
    )

    class FakeStore:
        closed = False
        persisted: dict[str, object] | None = None

        async def initialize(self) -> None:
            return None

        async def close(self) -> None:
            self.closed = True

        async def get_crawl_run(self, run_id: str):
            assert run_id == "run-1"
            return {"run_id": run_id, "status": "interrupted"}

        async def fetch_render_comparison_candidates(self, *, run_id: str):
            assert run_id == "run-1"
            return [
                {"url": "https://example.com/products/a", "html_lang": "en"},
                {"url": "https://example.com/fr/products/a", "html_lang": "fr"},
            ]

        async def persist_render_comparison_session(self, **kwargs):
            self.persisted = kwargs
            return 44

    store = FakeStore()

    async def fake_compare(_engine, urls, *, max_concurrent):
        assert list(urls) == ["https://example.com/products/a", "https://example.com/fr/products/a"]
        assert max_concurrent == 1
        return [comparison, comparison]

    monkeypatch.setattr("crawler_cli.__main__._store_from_args", lambda _args: store)
    monkeypatch.setattr("crawler_cli.__main__.compare_rendered_sample", fake_compare)
    args = _build_parser().parse_args(["compare-renders", "--crawl-run-id", "run-1", "--persist"])

    assert await _run_compare_renders(args) == 0
    assert store.closed is True
    assert store.persisted is not None
    assert store.persisted["source_crawl_run_id"] == "run-1"
    input_metadata = store.persisted["input_metadata"]
    assert input_metadata["sampling_basis"] == "deterministic_host_locale_path_depth_strata"
    assert input_metadata["source_crawl_run"]["complete"] is False
    assert "Persisted render-comparison session 44" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_compare_renders_cli_rejects_mixed_run_and_exact_inputs(capsys):
    args = _build_parser().parse_args(["compare-renders", "https://example.com/", "--crawl-run-id", "run-1"])

    assert await _run_compare_renders(args) == 2
    assert "cannot be combined" in capsys.readouterr().err


def test_operator_template_labels_win_over_computed_path_strata():
    candidates = [
        {"url": "https://example.com/products/a", "html_lang": "en", "template": "pdp"},
        {"url": "https://example.com/products/b", "html_lang": "en"},
    ]

    url_strata, sources = _render_url_strata(candidates)

    assert url_strata["https://example.com/products/a"] == "template=pdp"
    assert sources["https://example.com/products/a"] == "operator_template_label"
    assert url_strata["https://example.com/products/b"].startswith("host=example.com;")
    assert sources["https://example.com/products/b"] == "computed_path_stratum"


def test_stratum_coverage_reconciles_with_the_selected_urls():
    url_strata = {
        "https://example.com/a": "template=pdp",
        "https://example.com/b": "template=pdp",
        "https://example.com/c": "template=plp",
    }

    coverage = _render_stratum_coverage(url_strata, ["https://example.com/a", "https://example.com/c"])

    assert coverage == [
        {"stratum": "template=pdp", "candidate_count": 2, "selected_count": 1},
        {"stratum": "template=plp", "candidate_count": 1, "selected_count": 1},
    ]
    assert sum(int(item["selected_count"]) for item in coverage) == 2


def test_csv_template_column_labels_the_exact_url_path(tmp_path, monkeypatch, capsys):
    csv_file = tmp_path / "pages.csv"
    csv_file.write_text("url,template\nhttps://example.com/p/1,pdp\nhttps://example.com/c/1,\n", encoding="utf-8")
    comparison = compare_rendered_result(
        _same_navigation_result("<html><title>Raw</title></html>", "<html><title>Rendered</title></html>")
    )

    async def fake_compare(_engine, urls, *, max_concurrent):
        return [
            RenderParityComparison(
                url=url,
                final_url=url,
                status=200,
                state=comparison.state,
                state_reason=comparison.state_reason,
                raw=comparison.raw,
                rendered=comparison.rendered,
                findings=comparison.findings,
                primary_summary=comparison.primary_summary,
            )
            for url in urls
        ]

    monkeypatch.setattr("crawler_cli.__main__.compare_rendered_sample", fake_compare)
    output = tmp_path / "out.csv"
    args = _build_parser().parse_args(["compare-renders", "--csv-file", str(csv_file), "--output", str(output)])

    assert asyncio.run(_run_compare_renders(args)) == 0
    rows = list(csv.DictReader(output.read_text(encoding="utf-8").splitlines()))
    by_url = {row["url"]: row for row in rows}
    assert by_url["https://example.com/p/1"]["stratum"] == "template=pdp"
    assert by_url["https://example.com/p/1"]["stratum_source"] == "operator_template_label"
    assert by_url["https://example.com/c/1"]["stratum_source"] == "computed_path_stratum"
    capsys.readouterr()


def test_html_report_publishes_provenance_strata_and_a_filter(tmp_path):
    comparison = compare_rendered_result(
        _same_navigation_result("<html><title>Raw</title></html>", "<html><title>Rendered</title></html>")
    )
    payload = _render_comparison_payload(
        [comparison],
        selected_urls=[comparison.url],
        capped=False,
        input_metadata={
            "sampling_basis": "deterministic_host_locale_path_depth_strata",
            "source_crawl_run": {"run_id": "run-1", "status": "interrupted", "complete": False},
            "candidate_count": 4,
            "strata": [{"stratum": "template=pdp", "candidate_count": 4, "selected_count": 1}],
        },
        url_strata={comparison.url: "template=pdp"},
        stratum_sources={comparison.url: "operator_template_label"},
    )
    report = tmp_path / "report.html"

    _write_render_comparison_html(payload, str(report))

    document = report.read_text(encoding="utf-8")
    assert "partial or interrupted" in document
    assert "Path strata coverage" in document
    assert 'id="stratum-filter"' in document
    assert "Computed strata are path strata, not inferred templates." in document
