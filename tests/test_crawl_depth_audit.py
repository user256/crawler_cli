from __future__ import annotations

import pytest

from crawler_cli.crawl_depth_audit import analyse_priority_crawl_depth


def _profile() -> dict[str, object]:
    return {
        "templates": {"priority": {"pattern": r"^/(?:reviews|best-[a-z-]+)/?$"}},
        "commercial_hubs": ["https://example.test/casino/"],
    }


def _graph(**overrides: object) -> dict[str, object]:
    return {
        "root_urls": ["https://example.test/"],
        "depths_from_roots": True,
        "coverage_complete": True,
        **overrides,
    }


def test_q44_flags_priority_template_and_hub_beyond_three_clicks() -> None:
    result = analyse_priority_crawl_depth(
        [
            {"url": "https://example.test/", "crawl_depth": 0},
            {"url": "https://example.test/reviews/", "crawl_depth": 4},
            {"url": "https://example.test/casino/", "crawl_depth": 5},
            {"url": "https://example.test/news/a", "crawl_depth": 7},
        ],
        _graph(),
        _profile(),
    )

    assert result.available is True
    assert result.complete is True
    assert result.eligible is True
    assert result.denominator == 2
    assert result.threshold_breached is True
    assert [(fact.url, fact.crawl_depth) for fact in result.affected] == [
        ("https://example.test/reviews", 4),
        ("https://example.test/casino", 5),
    ]
    assert result.affected[1].priority_sources == ("commercial_hubs",)


def test_q44_deduplicates_url_matching_priority_pattern_and_commercial_hub() -> None:
    result = analyse_priority_crawl_depth(
        [
            {"url": "https://example.test/", "depth": 0},
            {"url": "https://example.test/casino", "depth": 3},
        ],
        _graph(),
        {
            "templates": {"priority": {"pattern": r"^/casino/?$"}},
            "commercial_hubs": ["https://example.test/casino/"],
        },
    )

    assert result.complete is True
    assert result.denominator == 1
    assert result.facts[0].priority_sources == ("commercial_hubs", "templates.priority")
    assert result.threshold_breached is False


@pytest.mark.parametrize(
    ("graph", "expected_reason"),
    [
        (_graph(coverage_complete=False), "incomplete_graph_coverage"),
        (_graph(depths_from_roots=False), "depths_not_verified_from_declared_roots"),
        (_graph(root_urls=[]), "missing_graph_root_urls"),
    ],
)
def test_q44_never_calls_unknown_graph_evidence_healthy(graph: dict[str, object], expected_reason: str) -> None:
    result = analyse_priority_crawl_depth(
        [
            {"url": "https://example.test/", "crawl_depth": 0},
            {"url": "https://example.test/reviews/", "crawl_depth": 2},
            {"url": "https://example.test/casino/", "crawl_depth": 2},
        ],
        graph,
        _profile(),
    )

    assert result.complete is False
    assert expected_reason in result.unavailable_reasons
    assert result.threshold_breached is False


def test_q44_retains_unknown_priority_depth_as_unavailable_not_healthy() -> None:
    result = analyse_priority_crawl_depth(
        [
            {"url": "https://example.test/", "crawl_depth": 0},
            {"url": "https://example.test/reviews/"},
            {"url": "https://example.test/casino/", "crawl_depth": 1},
        ],
        _graph(),
        _profile(),
    )

    fact = next(fact for fact in result.facts if fact.url.endswith("/reviews"))
    assert fact.outcome == "unavailable"
    assert fact.crawl_depth is None
    assert result.complete is False
    assert "missing_or_invalid_crawl_depth" in result.unavailable_reasons


def test_q44_requires_every_profile_policy_and_a_verified_root() -> None:
    result = analyse_priority_crawl_depth(
        [{"url": "https://example.test/reviews/", "crawl_depth": 1}],
        _graph(),
        {"templates": {"priority": {"pattern": r"^/reviews/"}}},
    )

    assert result.available is False
    assert result.complete is False
    assert "missing_commercial_hubs" in result.unavailable_reasons
    assert "no_declared_root_verified_at_depth_zero" in result.unavailable_reasons


def test_q44_missing_profile_hub_is_visible_as_unavailable_evidence() -> None:
    result = analyse_priority_crawl_depth(
        [
            {"url": "https://example.test/", "crawl_depth": 0},
            {"url": "https://example.test/reviews/", "crawl_depth": 2},
        ],
        _graph(),
        _profile(),
    )

    hub_fact = next(fact for fact in result.facts if fact.url.endswith("/casino"))
    assert hub_fact.outcome == "unavailable"
    assert "priority_hub_not_observed" in result.unavailable_reasons
    assert result.complete is False


def test_q44_bounds_facts_and_marks_coverage_incomplete() -> None:
    result = analyse_priority_crawl_depth(
        [
            {"url": "https://example.test/", "crawl_depth": 0},
            {"url": "https://example.test/reviews/", "crawl_depth": 2},
            {"url": "https://example.test/best-casino/", "crawl_depth": 4},
            {"url": "https://example.test/casino/", "crawl_depth": 1},
        ],
        _graph(),
        _profile(),
        max_facts=2,
    )

    assert len(result.facts) == 2
    assert result.facts_truncated is True
    assert result.complete is False
    assert "facts_truncated" in result.unavailable_reasons


def test_q44_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="max_depth"):
        analyse_priority_crawl_depth([], _graph(), _profile(), max_depth=-1)
    with pytest.raises(ValueError, match="max_facts"):
        analyse_priority_crawl_depth([], _graph(), _profile(), max_facts=0)
