"""AMP variant extraction + classification (ticket 103)."""

from __future__ import annotations

import pytest

from crawler_cli.amp import AmpClassification, amp_base_url, classify_amp_variants, is_amp_url_shape
from crawler_cli.extract import extract_page_data


# --------------------------------------------------------------------------
# rel="amphtml" extraction
# --------------------------------------------------------------------------


def test_extract_captures_rel_amphtml():
    html = """
    <html><head>
      <title>Base page</title>
      <link rel="canonical" href="/foo">
      <link rel="amphtml" href="/foo/amp">
    </head><body><p>hello</p></body></html>
    """
    extracted = extract_page_data(html, "https://example.com/foo", {})
    assert extracted.amphtml == "https://example.com/foo/amp"
    # canonical still extracted alongside it.
    assert extracted.canonical == "https://example.com/foo"


def test_extract_amphtml_absent_is_none():
    html = "<html><head><title>x</title></head><body>hi</body></html>"
    extracted = extract_page_data(html, "https://example.com/foo", {})
    assert extracted.amphtml is None


def test_extract_amphtml_absolute_href_preserved():
    html = '<html><head><link rel="amphtml" href="https://cdn.example.com/foo/amp"></head><body>x</body></html>'
    extracted = extract_page_data(html, "https://example.com/foo", {})
    assert extracted.amphtml == "https://cdn.example.com/foo/amp"


# --------------------------------------------------------------------------
# URL-shape detection
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected_base",
    [
        ("https://x.co/foo/amp", "https://x.co/foo"),
        ("https://x.co/foo/bar/amp", "https://x.co/foo/bar"),
        ("https://x.co/foo/amp/", "https://x.co/foo/"),
        ("https://x.co/amp", "https://x.co/"),
        ("https://x.co/foo?amp=1", "https://x.co/foo"),
        ("https://x.co/foo?x=1&amp=1", "https://x.co/foo?x=1"),
        # Negative: a slug that merely ends in "amp" must NOT match.
        ("https://x.co/revamp", None),
        ("https://x.co/foo/revamp", None),
        ("https://x.co/bar", None),
        # Negative: only the amp key is AMP — a value of amp for another key is
        # left to the general parameterised-URL classifier (ticket 102).
        ("https://x.co/foo?type=amp", None),
        ("https://x.co/foo?amp=0", None),
    ],
)
def test_amp_base_url(url, expected_base):
    assert amp_base_url(url) == expected_base
    assert is_amp_url_shape(url) is (expected_base is not None)


# --------------------------------------------------------------------------
# Classification from crawler-captured evidence
# --------------------------------------------------------------------------


def _page(url_id, url, canonical=None, content_hash=None):
    return {"url_id": url_id, "url": url, "canonical_url": canonical, "content_hash": content_hash}


def test_classify_amphtml_target_is_authoritative():
    # /weird is not AMP-shaped, but it is the target of a rel=amphtml edge.
    pages = [_page(1, "https://x.co/base"), _page(2, "https://x.co/weird")]
    amphtml = {2: "https://x.co/base"}
    result = classify_amp_variants(pages, amphtml)
    assert result == [AmpClassification(2, "https://x.co/weird", "https://x.co/base", "amphtml-target")]


def test_classify_url_shape_confirmed_by_base_exists():
    pages = [_page(1, "https://x.co/foo"), _page(2, "https://x.co/foo/amp")]
    result = classify_amp_variants(pages, {})
    assert [c.url_id for c in result] == [2]
    assert result[0].base_url == "https://x.co/foo"
    assert result[0].confirmed_by == "base-exists"


def test_classify_url_shape_confirmed_by_canonical_to_base():
    # Base page not crawled, but the AMP page canonicals to it.
    pages = [_page(2, "https://x.co/foo/amp", canonical="https://x.co/foo")]
    result = classify_amp_variants(pages, {})
    assert [c.url_id for c in result] == [2]
    assert result[0].confirmed_by == "canonical-to-base"


def test_classify_url_shape_confirmed_by_content_hash():
    pages = [
        _page(1, "https://x.co/foo", content_hash="deadbeef"),
        _page(2, "https://x.co/foo/amp", content_hash="deadbeef"),
    ]
    result = classify_amp_variants(pages, {})
    assert [c.url_id for c in result] == [2]
    assert result[0].confirmed_by == "content-hash"


def test_classify_url_shape_unconfirmed_is_not_amp():
    # /amp shape but no base page, no canonical, no matching hash -> not AMP.
    pages = [_page(2, "https://x.co/orphan/amp")]
    result = classify_amp_variants(pages, {})
    assert result == []


def test_classify_revamp_never_matches():
    # A real content page whose slug ends in "amp" must never be classified,
    # even when a plausible "base" (its parent) exists.
    pages = [_page(1, "https://x.co/design"), _page(2, "https://x.co/design/revamp")]
    result = classify_amp_variants(pages, {})
    assert result == []


def test_classify_query_form_confirmed_by_base_exists():
    pages = [_page(1, "https://x.co/team?x=1"), _page(2, "https://x.co/team?x=1&amp=1")]
    result = classify_amp_variants(pages, {})
    assert [c.url_id for c in result] == [2]
    assert result[0].base_url == "https://x.co/team?x=1"


def test_classify_homepage_amp_matches_trailing_slash_base():
    # /amp base is https://x.co ; homepage is crawled as https://x.co/ .
    pages = [_page(1, "https://x.co/"), _page(2, "https://x.co/amp")]
    result = classify_amp_variants(pages, {})
    assert [c.url_id for c in result] == [2]
