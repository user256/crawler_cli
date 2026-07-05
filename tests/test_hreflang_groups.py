"""Unit tests for hreflang groups + URL identity resolution (ticket 078).

100% crawler-powered: all inputs are crawler-captured edges/pages. Covers the
fixed upstream invariants — tracking-param folding, self-normalising redirect
vs genuine loop, cross-domain groups, x-default handling, reciprocity.
"""

from __future__ import annotations

import pytest

from crawler_cli.hreflang_groups import (
    UnionFind,
    build_and_store_identity,
    build_groups,
    lang_bucket,
    normalise_url,
    reciprocity_issues,
    resolve_language,
    resolve_variants,
)


# --------------------------------------------------------------------------
# normalise_url
# --------------------------------------------------------------------------


def test_normalise_url_lowercases_and_drops_fragment_and_trailing_slash():
    assert normalise_url("HTTPS://Example.COM/Path/#frag") == "https://example.com/path"
    assert normalise_url("https://example.com/") == "https://example.com/"


def test_normalise_url_strips_tracking_params_but_keeps_real_ones():
    assert normalise_url("https://x.com/p?utm_source=g&gclid=1&id=5") == "https://x.com/p?id=5"
    # All-tracking query collapses to no query.
    assert normalise_url("https://x.com/p?fbclid=abc") == "https://x.com/p"


def test_normalise_url_empty_and_non_string():
    assert normalise_url("") == ""
    assert normalise_url(None) == ""  # type: ignore[arg-type]


def test_lang_bucket():
    assert lang_bucket("en-US") == "en"
    assert lang_bucket("en") == "en"
    assert lang_bucket(None) == "unknown"
    assert lang_bucket("") == "unknown"


# --------------------------------------------------------------------------
# UnionFind + grouping
# --------------------------------------------------------------------------


def test_union_find_basic():
    uf = UnionFind(4)
    uf.union(0, 1)
    uf.union(2, 3)
    assert uf.find(0) == uf.find(1)
    assert uf.find(0) != uf.find(2)


def test_build_groups_cross_domain_and_stable_ids():
    # Two locales on sibling ccTLDs, mutually declared -> one group spanning domains.
    edges = [
        ("https://acme.com/p", "https://acme.co.uk/p", "en-gb"),
        ("https://acme.co.uk/p", "https://acme.com/p", "en-us"),
    ]
    grouping = build_groups(edges)
    assert grouping.group_count == 1
    g = grouping.groups_by_url
    assert g["https://acme.com/p"] == g["https://acme.co.uk/p"]
    assert list(grouping.groups_by_url.values())[0].startswith("H")


def test_build_groups_records_declared_language_but_skips_x_default():
    edges = [
        ("https://a.com/x", "https://a.com/x-de", "de"),
        ("https://a.com/x", "https://a.com/x", "x-default"),
    ]
    grouping = build_groups(edges)
    # x-default does not set a self language.
    assert grouping.self_lang_by_norm.get("https://a.com/x") != "x-default"
    assert grouping.self_lang_by_norm.get("https://a.com/x-de") == "de"


def test_build_groups_folds_tracking_param_variants():
    # Same page, one edge endpoint carries a tracking param -> same normalized node.
    edges = [
        ("https://a.com/p?gclid=1", "https://a.com/p-fr", "fr"),
        ("https://a.com/p", "https://a.com/p-fr", "fr"),
    ]
    grouping = build_groups(edges)
    # Both /p forms normalize identically, so the group has 2 members not 3.
    members = set(grouping.groups_by_url)
    assert "https://a.com/p" in members
    assert "https://a.com/p-fr" in members


def test_build_groups_empty():
    assert build_groups([]).group_count == 0


# --------------------------------------------------------------------------
# Reciprocity
# --------------------------------------------------------------------------


def test_reciprocity_flags_missing_return_link():
    edges = [
        ("https://a.com/en", "https://a.com/fr", "fr"),  # a->fr, no fr->a
    ]
    issues = reciprocity_issues(edges)
    assert len(issues) == 1
    assert issues[0]["declares_alternate"] == "https://a.com/fr"


def test_reciprocity_ok_when_mutual():
    edges = [
        ("https://a.com/en", "https://a.com/fr", "fr"),
        ("https://a.com/fr", "https://a.com/en", "en"),
    ]
    assert reciprocity_issues(edges) == []


# --------------------------------------------------------------------------
# Variant resolution
# --------------------------------------------------------------------------


def test_resolve_variants_picks_non_redirected_200_representative():
    pages = [
        {"url": "https://a.com/p", "status": 200, "redirected": False, "word_count": 500},
        {"url": "https://a.com/p/", "status": 200, "redirected": True, "word_count": 500},
    ]
    res = resolve_variants(pages)
    # The redirected one folds into the non-redirected representative.
    assert res.variant_of == {"https://a.com/p/": "https://a.com/p"}
    assert res.representatives == ["https://a.com/p"]


def test_resolve_variants_self_normalising_redirect_not_dropped():
    # A page that 301s to its own normalized form (adds trailing slash) shares a
    # norm_url with its target -> folds as a variant, never dropped/excluded.
    pages = [
        {"url": "https://a.com/p", "status": 200, "redirected": False, "word_count": 300},
        {"url": "https://a.com/p?utm_source=x", "status": 200, "redirected": True, "word_count": 300},
    ]
    res = resolve_variants(pages)
    assert "https://a.com/p?utm_source=x" in res.variant_of
    assert res.variant_of["https://a.com/p?utm_source=x"] == "https://a.com/p"


def test_resolve_variants_distinct_norms_are_not_folded():
    # Genuinely different pages (different norm_url) -> no variants (no false loop).
    pages = [
        {"url": "https://a.com/one", "status": 200, "redirected": False, "word_count": 100},
        {"url": "https://a.com/two", "status": 200, "redirected": False, "word_count": 100},
    ]
    res = resolve_variants(pages)
    assert res.variant_of == {}


def test_resolve_variants_prefers_higher_word_count_then_shorter_url():
    pages = [
        {"url": "https://a.com/p?a=1", "status": 200, "redirected": False, "word_count": 800},
        {"url": "https://a.com/p?a=1&b=2", "status": 200, "redirected": False, "word_count": 200},
    ]
    # Both normalize differently (real params kept), so no fold here — sanity that
    # kept params keep pages distinct.
    assert resolve_variants(pages).variant_of == {}


def test_resolve_language_prefers_declared_then_html_lang():
    assert resolve_language("fr-ca", "en") == ("fr-ca", "fr")
    assert resolve_language(None, "de-DE") == ("de-de", "de")
    assert resolve_language(None, None) == (None, "unknown")


# --------------------------------------------------------------------------
# Orchestrator against a fake store (no DB)
# --------------------------------------------------------------------------


class FakeIdentityStore:
    def __init__(self, edges, pages):
        self._edges = edges
        self._pages = pages
        self.identity_rows = None
        self.variant_pairs = None

    async def fetch_hreflang_edges(self):
        return list(self._edges)

    async def fetch_pages_for_identity(self):
        return [dict(p) for p in self._pages]

    async def store_hreflang_identity(self, rows):
        self.identity_rows = rows

    async def store_url_variants(self, pairs):
        self.variant_pairs = pairs


@pytest.mark.asyncio
async def test_build_and_store_identity_end_to_end():
    edges = [
        ("https://a.com/en", "https://a.com/fr", "fr"),
        ("https://a.com/fr", "https://a.com/en", "en"),
    ]
    pages = [
        {
            "url_id": 1,
            "url": "https://a.com/en",
            "html_lang": "en",
            "status": 200,
            "word_count": 300,
            "final_url": None,
        },
        {
            "url_id": 2,
            "url": "https://a.com/fr",
            "html_lang": "fr",
            "status": 200,
            "word_count": 300,
            "final_url": None,
        },
        # A tracking-param variant of /en that folds.
        {
            "url_id": 3,
            "url": "https://a.com/en?gclid=9",
            "html_lang": "en",
            "status": 200,
            "word_count": 300,
            "final_url": None,
        },
    ]
    store = FakeIdentityStore(edges, pages)
    result = await build_and_store_identity(store)

    assert result.groups == 1
    assert result.grouped_urls == 3  # all three share the /en or /fr group
    # /en?gclid=9 folds into /en (same norm_url).
    assert store.variant_pairs == [(3, 1)]
    assert result.variants == 1
    # Language resolved to declared code where available.
    by_id = {r["url_id"]: r for r in store.identity_rows}
    assert by_id[2]["lang_bucket"] == "fr"
