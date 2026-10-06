from __future__ import annotations

import pytest

from crawler_cli.performance_distribution import analyse_performance_distribution


def _pages(template: str, timings_ms: list[float]) -> list[dict[str, object]]:
    return [
        {
            "url": f"https://example.test/{template}/{index}",
            "template": template,
            "status": 200,
            "ttfb_seconds": timing / 1_000,
        }
        for index, timing in enumerate(timings_ms)
    ]


def test_q88_reports_per_template_percentiles_and_threshold_breach_evidence() -> None:
    pages = _pages("article", [100] * 17 + [650, 1_600, 2_000])
    pages += _pages("listing", [600] * 20)

    audit = analyse_performance_distribution(pages)

    assert audit.available is True
    assert audit.complete is True
    assert audit.eligible_record_count == 40
    assert [fact.template for fact in audit.facts] == ["article", "listing"]
    article, listing = audit.facts
    assert article.outcome == "finding"
    assert article.p90_ms == 745.0
    assert article.p99_ms == 1_924.0
    assert article.p90_breach is True
    assert article.p99_breach is True
    assert article.slowest_urls[0].endswith("/19")
    assert listing.outcome == "observed"
    assert listing.p90_ms == 600.0  # Threshold comparison is strictly greater-than.
    assert listing.p90_breach is False
    assert audit.affected == (article,)


def test_q88_keeps_insufficient_template_samples_incomplete_not_healthy() -> None:
    audit = analyse_performance_distribution(_pages("article", [100] * 19))

    assert audit.available is True
    assert audit.complete is False
    assert audit.unavailable_reasons == ("insufficient_template_samples",)
    fact = audit.facts[0]
    assert fact.outcome == "unavailable"
    assert fact.sample_count == 19
    assert fact.p90_ms is None
    assert fact.p90_breach is None


def test_missing_or_malformed_saved_facts_are_incomplete_instead_of_silently_excluded() -> None:
    pages = _pages("article", [100] * 20)
    pages.extend(
        [
            {"url": "https://example.test/unclassified", "ttfb_ms": 100},
            {"url": "https://example.test/no-timing", "template": "article"},
            {"url": "https://example.test/bad-status", "template": "article", "status": "bad", "ttfb_ms": 100},
            {"url": "https://example.test/failed", "template": "article", "status": 503, "ttfb_ms": 5_000},
        ]
    )

    audit = analyse_performance_distribution(pages)

    assert audit.available is True
    assert audit.complete is False
    assert audit.excluded_record_count == 1
    assert set(audit.unavailable_reasons) == {
        "invalid_response_status",
        "missing_or_invalid_ttfb",
        "missing_template_identity",
    }
    assert audit.facts[0].outcome == "observed"


def test_template_aliases_timing_units_ordering_and_output_bounds_are_deterministic() -> None:
    pages: list[dict[str, object]] = [
        {"url": "https://example.test/z", "template_pattern": "listing", "response_time_ms": 900},
        {"url": "https://example.test/a", "template_id": "listing", "ttfb_ms": 900},
    ] + _pages("listing", [100] * 18)

    audit = analyse_performance_distribution(pages, max_example_urls=1)

    assert audit.complete is True
    assert audit.facts[0].sample_count == 20
    assert audit.facts[0].slowest_urls == ("https://example.test/a",)
    assert audit.facts[0].as_dict()["slowest_urls"] == ["https://example.test/a"]


def test_empty_input_and_invalid_options_do_not_produce_a_clean_result() -> None:
    audit = analyse_performance_distribution([])

    assert audit.available is False
    assert audit.complete is False
    assert audit.unavailable_reasons == ("no_eligible_ttfb_samples",)
    with pytest.raises(ValueError, match="min_samples"):
        analyse_performance_distribution([], min_samples=0)
    with pytest.raises(ValueError, match="thresholds"):
        analyse_performance_distribution([], p90_threshold_ms=0)
