"""Focused proof for the pure technical-audit hreflang validators."""

from __future__ import annotations

import pytest

from crawler_cli.hreflang_audit import HreflangAnnotation, HreflangPage, hreflang_facts


SITE = "https://example.test"


def _page(path: str, **kwargs: object) -> HreflangPage:
    return HreflangPage(url=f"{SITE}{path}", **kwargs)  # type: ignore[arg-type]


def test_flags_non_reciprocal_and_each_known_bad_target_state() -> None:
    source = _page(
        "/en/page",
        annotations=(HreflangAnnotation("fr", "/fr/page"),),
        status=200,
        indexable=True,
        canonical=f"{SITE}/en/page",
    )
    target = _page(
        "/fr/page",
        annotations=(),
        status=404,
        indexable=False,
        canonical=f"{SITE}/fr/other-page",
    )

    facts = hreflang_facts([source, target])

    assert [fact["kind"] for fact in facts] == [
        "hreflang-non-reciprocal",
        "hreflang-target-noindex",
        "hreflang-target-non-200",
        "hreflang-target-noncanonical",
    ]
    assert {fact["target_url"] for fact in facts} == {f"{SITE}/fr/page"}
    assert next(fact for fact in facts if fact["kind"] == "hreflang-target-non-200")["target_status"] == 404


def test_reciprocal_healthy_target_has_no_q9_facts() -> None:
    en = _page(
        "/en/page",
        annotations=(HreflangAnnotation("fr", "/fr/page"),),
        status=200,
        indexable=True,
        canonical=f"{SITE}/en/page",
    )
    fr = _page(
        "/fr/page",
        annotations=(HreflangAnnotation("en", "/en/page"),),
        status=200,
        indexable=True,
        canonical=f"{SITE}/fr/page",
    )

    assert hreflang_facts([en, fr]) == []


def test_uncrawled_target_does_not_claim_a_non_reciprocal_finding() -> None:
    source = _page("/en/page", annotations=(HreflangAnnotation("fr", "https://fr.example.test/page"),))

    assert hreflang_facts([source]) == []


def test_locale_folder_compares_primary_language_for_html_lang_and_self_hreflang() -> None:
    page = _page(
        "/en-gb/page",
        html_lang="fr-FR",
        annotations=(HreflangAnnotation("de-DE", "/en-gb/page"),),
    )

    facts = hreflang_facts([page])

    assert [fact["kind"] for fact in facts] == [
        "locale-path-language-mismatch",
        "locale-path-language-mismatch",
    ]
    assert {(fact["declared_from"], fact["locale_folder"]) for fact in facts} == {
        ("html_lang", "en"),
        ("self_hreflang", "en"),
    }


def test_root_level_default_language_is_not_inferred_to_be_a_locale_failure() -> None:
    page = _page("/products/widget", html_lang="en")

    assert hreflang_facts([page]) == []


def test_q83_flags_only_more_than_twenty_html_annotations_without_sitemap_evidence() -> None:
    annotations = tuple(HreflangAnnotation(f"l{index:02d}", f"/locale-{index}") for index in range(21))
    page = _page("/en/page", annotations=annotations)

    facts = hreflang_facts([page], sitemap_hreflang_present=False)

    assert facts == [
        {
            "kind": "hreflang-html-bloat-without-sitemap",
            "url": f"{SITE}/en/page",
            "html_hreflang_count": 21,
            "max_html_hreflangs": 20,
        }
    ]
    assert hreflang_facts([page], sitemap_hreflang_present=True) == []
    assert hreflang_facts([_page("/en/page", annotations=annotations[:20])], sitemap_hreflang_present=False) == []


def test_snapshot_shaped_records_are_accepted_and_sitemap_source_is_derived() -> None:
    records = [
        {
            "url": f"{SITE}/en/page",
            "final_status_code": 200,
            "overall_indexable": True,
            "canonical_urls_json": [f"{SITE}/en/page"],
            "hreflang_json": [
                {"hreflang": "fr", "href": f"{SITE}/fr/page", "source": "html_head"},
                {"hreflang": "de", "href": f"{SITE}/de/page", "source": "sitemap"},
            ],
        },
        {
            "url": f"{SITE}/fr/page",
            "final_status_code": 200,
            "overall_indexable": True,
            "canonical_urls_json": [f"{SITE}/fr/page"],
            "hreflang_json": [{"hreflang": "en", "href": f"{SITE}/en/page", "source": "html_head"}],
        },
    ]

    assert hreflang_facts(records) == []


def test_invalid_bloat_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        hreflang_facts([], max_html_hreflangs=-1)
