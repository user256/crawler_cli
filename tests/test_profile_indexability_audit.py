from __future__ import annotations

import pytest

from crawler_cli.profile_indexability_audit import analyse_profile_indexability


def _profile() -> dict[str, object]:
    return {
        "templates": {
            "article": {"pattern": "^/articles/", "indexable": True},
            "profile": {"pattern": "^/user/[^/]+/?$", "indexable": True},
            "profile_subtab": {"pattern": "^/user/[^/]+/(?:updates|reviews)/?$", "indexable": False},
            "taxonomy": {"pattern": "^/(?:tag|category|author)/", "indexable": True},
        },
        "empty_profile_rule": {"max_main_content_words": 40, "empty_state_selector": "[data-empty-profile]"},
    }


def test_q20_finds_noindex_indexable_template_sitemap_and_navigation_targets() -> None:
    audit = analyse_profile_indexability(
        [
            {
                "url": "https://example.test/articles/a",
                "noindex": True,
                "in_sitemap": False,
                "is_navigation_target": False,
            },
            {"url": "https://example.test/hidden", "noindex": True, "in_sitemap": True, "is_navigation_target": False},
            {"url": "https://example.test/nav", "noindex": True, "in_sitemap": False, "is_navigation_target": True},
        ],
        _profile(),
    )

    assert audit.q20.available is True
    assert audit.q20.complete is True
    assert [fact.url for fact in audit.q20.affected] == [
        "https://example.test/articles/a",
        "https://example.test/hidden",
        "https://example.test/nav",
    ]
    assert audit.q20.affected[0].as_dict()["template_indexable"] is True


def test_q20_retains_observation_but_marks_missing_profile_and_optional_flags_incomplete() -> None:
    audit = analyse_profile_indexability(
        [{"url": "https://example.test/hidden", "noindex": True}],
        None,
    )

    assert audit.q20.available is False
    assert audit.q20.complete is False
    assert audit.q20.facts[0].outcome == "observed"
    assert set(audit.q20.unavailable_reasons) == {
        "missing_in_sitemap_flag",
        "missing_navigation_target_flag",
        "missing_profile_templates",
    }


def test_q36_requires_a_200_indexable_self_canonical_profile_subtab() -> None:
    audit = analyse_profile_indexability(
        [
            {
                "url": "https://example.test/user/ada/updates",
                "status": 200,
                "indexable": True,
                "canonical": "https://example.test/user/ada/updates#section",
            },
            {
                "url": "https://example.test/user/grace/reviews",
                "status": 200,
                "indexable": True,
                "canonical": "https://example.test/user/grace",
            },
        ],
        _profile(),
    )

    assert audit.q36.complete is True
    assert [fact.url for fact in audit.q36.affected] == ["https://example.test/user/ada/updates"]
    assert audit.q36.facts[1].values["self_canonical"] is False


def test_q37_uses_word_count_or_empty_state_and_preserves_missing_sitemap_coverage() -> None:
    audit = analyse_profile_indexability(
        [
            {
                "url": "https://example.test/user/ada",
                "word_count": 9,
                "empty_selector_matched": False,
                "indexable": True,
                "in_sitemap": False,
            },
            {
                "url": "https://example.test/user/grace",
                "word_count": 100,
                "empty_selector_matched": True,
                "indexable": False,
            },
        ],
        _profile(),
    )

    assert [fact.url for fact in audit.q37.affected] == ["https://example.test/user/ada"]
    assert audit.q37.facts[1].outcome == "observed"
    assert audit.q37.complete is False
    assert "missing_in_sitemap_flag" in audit.q37.unavailable_reasons


def test_q78_finds_noindex_taxonomy_hubs_from_percentile_or_profile_hub_fact() -> None:
    audit = analyse_profile_indexability(
        [
            {"url": "https://example.test/tag/seo", "noindex": True, "inlink_percentile": 0.9},
            {"url": "https://example.test/category/news", "noindex": True, "is_profile_hub": True},
            {"url": "https://example.test/author/ada", "noindex": True, "inlink_percentile": 0.89},
        ],
        _profile(),
    )

    assert audit.q78.complete is True
    assert [fact.url for fact in audit.q78.affected] == [
        "https://example.test/tag/seo",
        "https://example.test/category/news",
    ]


def test_missing_policy_is_distinct_from_missing_crawl_facts_and_fact_cap_is_not_healthy() -> None:
    profile = _profile()
    del profile["empty_profile_rule"]
    audit = analyse_profile_indexability(
        [
            {
                "url": "https://example.test/user/ada/updates",
                "status": 200,
                "indexable": True,
                "canonical": "https://example.test/user/ada/updates",
            },
            {
                "url": "https://example.test/user/grace/updates",
                "status": 200,
                "indexable": True,
                "canonical": "https://example.test/user/grace/updates",
            },
        ],
        profile,
        max_facts=1,
    )

    assert audit.q37.available is False
    assert audit.q37.unavailable_reasons == ("missing_profile_empty_rule",)
    assert audit.q36.available is True
    assert audit.q36.facts_truncated is True
    assert audit.q36.complete is False
    with pytest.raises(ValueError, match="at least 1"):
        analyse_profile_indexability([], _profile(), max_facts=0)
