"""Unit tests for intent-overlap analysis (ticket 079).

Small synthetic vector fixtures — no model, no DB. Covers suppression modes,
both linkages, chained-cluster flagging, singleton partitions, risk levels,
CSV column contracts, --fail-on exit codes, and the ticket-105 time-sequenced
section policy.
"""

from __future__ import annotations

import csv
import json
import math

import pytest

np = pytest.importorskip("numpy")

from crawler_cli.intent_overlap import (  # noqa: E402
    RISK_DUPLICATE,
    RISK_PARENT_CHILD,
    TIME_SEQUENCED_RISK,
    analyse_embeddings,
    classify_and_fold_parameterised,
    classify_url,
    compute_exclusion,
    path_in_section,
    run_intent_overlap,
    similarity_pairs,
    time_sequenced_pair_class,
    write_reports,
)


def _unit(vec):
    v = np.asarray(vec, dtype=np.float32)
    return (v / np.linalg.norm(v)).tolist()


def _rec(url, vec, *, group=None, code=None, wc=100, conf="high", sig=None):
    return {
        "url": url,
        "vector": _unit(vec),
        "group": group,
        "hreflang_code": code,
        "word_count": wc,
        "signal_confidence": conf,
        "signature_model_input": sig,
    }


def _words(n):
    """A signature_model_input string with exactly *n* words."""
    return " ".join(f"w{i}" for i in range(n))


# --------------------------------------------------------------------------
# Numeric core
# --------------------------------------------------------------------------


def test_similarity_pairs_matches_bruteforce():
    rng = np.random.RandomState(0)
    vecs = rng.randn(30, 8).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    threshold = 0.3
    got = {(i, j): s for i, j, s in similarity_pairs(vecs, threshold, block=7)}
    # Brute force upper triangle, same threshold.
    full = vecs @ vecs.T
    expected = {(i, j): float(full[i, j]) for i in range(30) for j in range(i + 1, 30) if full[i, j] >= threshold}
    assert set(got) == set(expected)
    for key, sim in expected.items():
        assert math.isclose(got[key], sim, abs_tol=1e-5)


# --------------------------------------------------------------------------
# Pairing + suppression
# --------------------------------------------------------------------------


def test_two_near_identical_pages_flagged_duplicate():
    recs = [
        _rec("https://a.com/1", [1.0, 0.0, 0.0]),
        _rec("https://a.com/2", [0.999, 0.044, 0.0]),  # cos ~0.999
    ]
    res = analyse_embeddings(recs, lang_split=False)
    assert len(res.overlap_pairs) == 1
    assert res.summary["duplicate_pages"] == 2


def test_hreflang_suppression_skips_same_group_pairs():
    recs = [
        _rec("https://a.com/en", [1.0, 0.0], group="H0001", code="en"),
        _rec("https://a.com/fr", [1.0, 0.0], group="H0001", code="fr"),
    ]
    # lang split off so they would otherwise pair.
    res = analyse_embeddings(recs, hreflang_mode="suppress", lang_split=False)
    assert res.overlap_pairs == []
    assert res.suppressed == 1


def test_hreflang_off_mode_pairs_same_group():
    recs = [
        _rec("https://a.com/en", [1.0, 0.0], group="H0001", code="en"),
        _rec("https://a.com/fr", [1.0, 0.0], group="H0001", code="fr"),
    ]
    res = analyse_embeddings(recs, hreflang_mode="off", lang_split=False)
    assert len(res.overlap_pairs) == 1


def test_primary_only_collapses_group_to_representative():
    recs = [
        _rec("https://a.com/en", [1.0, 0.0], group="H0001", code="en"),
        _rec("https://a.com/fr", [1.0, 0.0], group="H0001", code="fr"),
        _rec("https://a.com/other", [1.0, 0.0], code="en"),
    ]
    res = analyse_embeddings(recs, hreflang_mode="primary-only", primary_lang="en", lang_split=False)
    # en representative kept + the standalone page => they pair; fr omitted.
    urls_in_pairs = {u for p in res.overlap_pairs for u in (p["url_a"], p["url_b"])}
    assert "https://a.com/fr" not in urls_in_pairs
    assert "https://a.com/en" in urls_in_pairs


def test_language_split_prevents_cross_language_pairs():
    recs = [
        _rec("https://a.com/en", [1.0, 0.0], code="en"),
        _rec("https://a.com/de", [1.0, 0.0], code="de"),
    ]
    # Identical vectors but different language buckets -> split keeps them apart.
    res = analyse_embeddings(recs, lang_split=True)
    assert res.overlap_pairs == []


def test_language_split_auto_disabled_when_few_codes():
    recs = [
        _rec("https://a.com/1", [1.0, 0.0], code=None),
        _rec("https://a.com/2", [1.0, 0.0], code=None),
    ]
    # <50% carry a code -> split disabled -> they pair in the "all" partition.
    res = analyse_embeddings(recs, lang_split=True)
    assert len(res.overlap_pairs) == 1


# --------------------------------------------------------------------------
# Clustering + chained flag
# --------------------------------------------------------------------------


def test_single_linkage_clusters_and_singletons_excluded():
    recs = [
        _rec("https://a.com/1", [1.0, 0.0, 0.0]),
        _rec("https://a.com/2", [1.0, 0.0, 0.0]),
        _rec("https://a.com/lonely", [0.0, 0.0, 1.0]),
    ]
    res = analyse_embeddings(recs, lang_split=False)
    assert len(res.cluster_rows) == 1
    assert res.cluster_rows[0]["size"] == 2


def test_chained_cluster_flagged_when_min_intra_below_threshold():
    # A-B similar, B-C similar, A-C far: single-linkage chains them; min intra < threshold.
    a = [1.0, 0.0, 0.0]
    b = [0.75, 0.66, 0.0]
    c = [0.2, 0.98, 0.0]
    recs = [_rec("https://a.com/a", a), _rec("https://a.com/b", b), _rec("https://a.com/c", c)]
    res = analyse_embeddings(recs, threshold=0.6, dup_threshold=0.99, lang_split=False)
    chained = [c for c in res.cluster_rows if c["chained"]]
    assert chained
    assert chained[0]["suggested_canonical"] == "review — chained cluster"


def test_complete_linkage_does_not_chain():
    a = [1.0, 0.0, 0.0]
    b = [0.75, 0.66, 0.0]
    c = [0.2, 0.98, 0.0]
    recs = [_rec("https://a.com/a", a), _rec("https://a.com/b", b), _rec("https://a.com/c", c)]
    res = analyse_embeddings(recs, threshold=0.6, dup_threshold=0.99, lang_split=False, linkage="complete")
    # Complete linkage refuses to merge A and C (below threshold), so no 3-member chain.
    for row in res.cluster_rows:
        assert row["size"] <= 2


def test_pick_canonical_prefers_word_count_then_shortest_url():
    recs = [
        _rec("https://a.com/longer-url-here", [1.0, 0.0], wc=500),
        _rec("https://a.com/x", [1.0, 0.0], wc=900),
    ]
    res = analyse_embeddings(recs, lang_split=False)
    assert res.cluster_rows[0]["suggested_canonical"] == "https://a.com/x"


# --------------------------------------------------------------------------
# Relationship classification (ticket 101)
# --------------------------------------------------------------------------


def test_overlap_pairs_carry_relation_and_sections():
    recs = [
        _rec("https://a.com/videos", [1.0, 0.0, 0.0]),
        _rec("https://a.com/videos/road-safety", [0.999, 0.044, 0.0]),
    ]
    res = analyse_embeddings(recs, lang_split=False)
    assert len(res.overlap_pairs) == 1
    pair = res.overlap_pairs[0]
    assert pair["relation"] == "parent-child"
    assert pair["section_a"] == "videos"
    assert pair["section_b"] == "videos"


def test_parent_child_only_duplicate_gets_distinct_risk_label():
    recs = [
        _rec("https://a.com/videos", [1.0, 0.0, 0.0]),
        _rec("https://a.com/videos/road-safety", [0.999, 0.044, 0.0]),
    ]
    res = analyse_embeddings(recs, lang_split=False)
    by_url = {r["url"]: r for r in res.pages_rows}
    assert by_url["https://a.com/videos"]["risk"] == RISK_PARENT_CHILD
    assert by_url["https://a.com/videos/road-safety"]["risk"] == RISK_PARENT_CHILD
    # duplicate_pages (the --fail-on duplicate gating count) still counts them —
    # ticket 101 must not silently change gating semantics, only the label.
    assert res.summary["duplicate_pages"] == 2
    assert res.summary["duplicate_pages_parent_child_only"] == 2


def test_duplicate_risk_stays_ordinary_when_not_solely_parent_child():
    # hub<->child (parent-child, dup-crossing) and hub<->unrelated
    # (cross-section, dup-crossing), but child<->unrelated stays below
    # dup_threshold. The hub's duplicate risk is driven by *both* a
    # parent-child edge and a cross-section edge, so it keeps the ordinary
    # label; the child's only dup-level edge is the parent-child one, so it
    # gets the distinct label.
    hub = [1.0, 0.0, 0.0, 0.0]
    child = [0.95, (1 - 0.95**2) ** 0.5, 0.0, 0.0]
    unrelated = [0.95, 0.0, (1 - 0.95**2) ** 0.5, 0.0]
    recs = [
        _rec("https://a.com/videos", hub),
        _rec("https://a.com/videos/road-safety", child),
        _rec("https://a.com/news/other", unrelated),
    ]
    res = analyse_embeddings(recs, lang_split=False)
    by_url = {r["url"]: r for r in res.pages_rows}
    assert by_url["https://a.com/videos"]["risk"] == RISK_DUPLICATE
    assert by_url["https://a.com/videos/road-safety"]["risk"] == RISK_PARENT_CHILD
    assert by_url["https://a.com/news/other"]["risk"] == RISK_DUPLICATE


def test_relation_counts_in_summary():
    recs = [
        _rec("https://a.com/videos", [1.0, 0.0, 0.0]),
        _rec("https://a.com/videos/road-safety", [0.999, 0.044, 0.0]),
    ]
    res = analyse_embeddings(recs, lang_split=False)
    assert res.summary["relation_counts"] == {"parent-child": 1}


def test_cluster_relation_field_and_parent_preferred_canonical():
    recs = [
        _rec("https://a.com/videos", [1.0, 0.0, 0.0], wc=50),  # thin hub
        _rec("https://a.com/videos/road-safety", [0.999, 0.044, 0.0], wc=900),  # bigger child
    ]
    res = analyse_embeddings(recs, lang_split=False)
    cluster = res.cluster_rows[0]
    assert cluster["relation"] == "parent-child"
    # Parent (shallower path) preferred over the higher-word-count child.
    assert cluster["suggested_canonical"] == "https://a.com/videos"


def test_cluster_relation_field_mixed_when_not_all_parent_child():
    recs = [
        _rec("https://a.com/longer-url-here", [1.0, 0.0], wc=500),
        _rec("https://a.com/x", [1.0, 0.0], wc=900),
    ]
    res = analyse_embeddings(recs, lang_split=False)
    assert res.cluster_rows[0]["relation"] == "cross-section"
    # Non-parent-child cluster keeps the word-count-based canonical pick.
    assert res.cluster_rows[0]["suggested_canonical"] == "https://a.com/x"


# Ticket 104: thin content vs true duplicate
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sig,words,expected",
    [
        (None, None, False),  # no signature computed at all -> unknown, not thin
        ("", 0, True),
        (_words(49), 49, True),
        (_words(50), 50, False),  # boundary: exactly the threshold is not thin
        (_words(51), 51, False),
    ],
)
def test_is_thin_signature_boundary(sig, words, expected):
    from crawler_cli.intent_signature import is_thin_signature, signature_word_count

    assert is_thin_signature(sig, threshold=50) is expected
    if words is not None:
        assert signature_word_count(sig) == words


def test_both_sides_thin_pair_downgrades_page_risk_to_thin_content():
    # High raw word_count (like the /videos hub+item pages) but a near-empty
    # signature (boilerplate only, no distinguishing copy) on both sides.
    recs = [
        _rec("https://a.com/videos", [1.0, 0.0], wc=900, sig=_words(5)),
        _rec("https://a.com/videos/clip-1", [1.0, 0.0], wc=820, sig=_words(3)),
    ]
    res = analyse_embeddings(recs, lang_split=False)
    assert res.summary["duplicate_pages"] == 0
    assert res.summary["thin_content_pages"] == 2
    assert res.summary["thin_pages"] == 2
    assert res.summary["thin_pairs"] == 1
    risks = {r["url"]: r["risk"] for r in res.pages_rows}
    assert risks["https://a.com/videos"] == "thin content — add distinguishing content"
    assert risks["https://a.com/videos/clip-1"] == "thin content — add distinguishing content"
    pair = res.overlap_pairs[0]
    assert pair["thin"] == "both"
    # signature_words is exposed per page, wc kept for contrast.
    words_by_url = {r["url"]: r["signature_words"] for r in res.pages_rows}
    assert words_by_url["https://a.com/videos"] == 5
    assert words_by_url["https://a.com/videos/clip-1"] == 3


def test_rich_duplicate_pair_keeps_duplicate_label():
    recs = [
        _rec("https://a.com/news/1", [1.0, 0.0], wc=900, sig=_words(300)),
        _rec("https://a.com/news/1-copy", [1.0, 0.0], wc=880, sig=_words(280)),
    ]
    res = analyse_embeddings(recs, lang_split=False)
    assert res.summary["duplicate_pages"] == 2
    assert res.summary["thin_content_pages"] == 0
    risks = {r["url"]: r["risk"] for r in res.pages_rows}
    assert all(r == "duplicate — decanonicalisation likely" for r in risks.values())
    assert res.overlap_pairs[0]["thin"] == ""


def test_mixed_thin_rich_pair_keeps_duplicate_risk_but_flags_asymmetric():
    recs = [
        _rec("https://a.com/rich", [1.0, 0.0], wc=900, sig=_words(300)),
        _rec("https://a.com/thin", [1.0, 0.0], wc=900, sig=_words(5)),
    ]
    res = analyse_embeddings(recs, lang_split=False)
    # Neither side is downgraded: the rich side is a genuine decanonicalisation
    # candidate, so both keep duplicate risk -- but the pair notes the asymmetry.
    assert res.summary["duplicate_pages"] == 2
    assert res.summary["thin_content_pages"] == 0
    risks = {r["url"]: r["risk"] for r in res.pages_rows}
    assert all(r == "duplicate — decanonicalisation likely" for r in risks.values())
    assert res.overlap_pairs[0]["thin"] == "asymmetric"


def test_thin_cluster_carries_thin_label_rich_cluster_does_not():
    recs = [
        _rec("https://a.com/videos", [1.0, 0.0, 0.0], wc=900, sig=_words(5)),
        _rec("https://a.com/videos/clip", [1.0, 0.0, 0.0], wc=820, sig=_words(3)),
        _rec("https://b.com/rich-1", [0.0, 1.0, 0.0], wc=900, sig=_words(300)),
        _rec("https://b.com/rich-2", [0.0, 1.0, 0.0], wc=880, sig=_words(280)),
    ]
    res = analyse_embeddings(recs, lang_split=False)
    by_url_set = {frozenset(c["urls"].split(" | ")): c["thin"] for c in res.cluster_rows}
    thin_cluster = by_url_set[frozenset({"https://a.com/videos", "https://a.com/videos/clip"})]
    rich_cluster = by_url_set[frozenset({"https://b.com/rich-1", "https://b.com/rich-2"})]
    assert thin_cluster is True
    assert rich_cluster is False


def test_thin_signature_words_flag_is_configurable():
    # 45-word signatures: thin at the default 50-word threshold, not thin at 40.
    recs = [
        _rec("https://a.com/1", [1.0, 0.0], sig=_words(45)),
        _rec("https://a.com/2", [1.0, 0.0], sig=_words(45)),
    ]
    default_res = analyse_embeddings(recs, lang_split=False)
    assert default_res.summary["thin_content_pages"] == 2
    lenient_res = analyse_embeddings(recs, lang_split=False, thin_signature_words=40)
    assert lenient_res.summary["thin_content_pages"] == 0
    assert lenient_res.summary["duplicate_pages"] == 2


def test_missing_signature_model_input_defaults_to_not_thin():
    # No signature computed at all (sig=None, the _rec default) -> today's
    # duplicate behaviour is preserved rather than over-flagging as thin.
    recs = [
        _rec("https://a.com/1", [1.0, 0.0]),
        _rec("https://a.com/2", [1.0, 0.0]),
    ]
    res = analyse_embeddings(recs, lang_split=False)
    assert res.summary["duplicate_pages"] == 2
    assert res.summary["thin_content_pages"] == 0


# --------------------------------------------------------------------------
# Exclusion reasons
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "row,expected",
    [
        ({"url": "u", "kind": "image"}, "non-html"),
        ({"url": "u", "kind": "html", "status": 404}, "non-200"),
        ({"url": "u", "kind": "html", "status": 200, "overall_indexable": False}, "noindex"),
        (
            {"url": "https://a.com/p", "kind": "html", "status": 200, "canonical_url": "https://a.com/other"},
            "canonicalised-elsewhere",
        ),
        ({"url": "u", "kind": "html", "status": 200, "variant_of": "https://a.com/rep"}, "url-variant"),
        ({"url": "https://a.com/p", "kind": "html", "status": 200, "canonical_url": "https://a.com/p/"}, None),
        # AMP variant with NO canonical still reports as amp-variant (ticket 103).
        ({"url": "https://a.com/p/amp", "kind": "html", "status": 200, "variant_kind": "amp"}, "amp-variant"),
        # AMP variant that DOES declare a canonical still reports amp-variant,
        # i.e. amp-variant is ranked before canonicalised-elsewhere.
        (
            {
                "url": "https://a.com/p/amp",
                "kind": "html",
                "status": 200,
                "variant_kind": "amp",
                "canonical_url": "https://a.com/p",
            },
            "amp-variant",
        ),
        # non-200 still wins over amp-variant (no content to pair regardless).
        ({"url": "https://a.com/p/amp", "kind": "html", "status": 404, "variant_kind": "amp"}, "non-200"),
    ],
)
def test_compute_exclusion(row, expected):
    assert compute_exclusion(row) == expected


# --------------------------------------------------------------------------
# Parameterised-URL classification + folding (ticket 102)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "row,expected",
    [
        # Real query, no canonical -> parameterised.
        ({"url": "https://a.com/the-team?type=x"}, "parameterised"),
        # Self-canonical that still carries the params -> parameterised.
        (
            {"url": "https://a.com/the-team?type=x", "canonical_url": "https://a.com/the-team?type=x"},
            "parameterised",
        ),
        # No query at all -> not our class.
        ({"url": "https://a.com/the-team"}, None),
        # Only tracking params -> effective query empty -> not parameterised.
        ({"url": "https://a.com/the-team?gclid=1&utm_source=g"}, None),
        # Canonical to a different (clean) URL -> site handled it; caught by
        # compute_exclusion as canonicalised-elsewhere instead.
        (
            {"url": "https://a.com/the-team?type=x", "canonical_url": "https://a.com/the-team"},
            None,
        ),
        # AMP is the more specific structural classification (ticket 103).
        ({"url": "https://a.com/article?amp=1", "variant_kind": "amp"}, None),
    ],
)
def test_classify_url(row, expected):
    assert classify_url(row) == expected


def _prow(url, **over):
    row = {
        "url": url,
        "kind": "html",
        "status": 200,
        "overall_indexable": True,
        "canonical_url": None,
        "variant_of": None,
        "signature_hash": None,
        "excluded": None,
    }
    row.update(over)
    return row


def test_fold_parameterised_folds_on_signature_hash_match():
    rows = [
        _prow("https://a.com/the-team", signature_hash="H1"),
        _prow("https://a.com/the-team?type=lawyers", signature_hash="H1"),
    ]
    classify_and_fold_parameterised(rows)
    base, param = rows
    assert base["url_class"] is None
    assert param["url_class"] == "parameterised"
    # Content-confirmed: excluded from pairing, base suggested as canonical.
    assert param["excluded"] == "parameterised-duplicate"
    assert param["suggested_canonical"] == "https://a.com/the-team"
    # Base stays eligible.
    assert base["excluded"] is None


def test_fold_parameterised_keeps_distinct_content_eligible():
    # Same base path but the signature hashes differ -> a genuine filtered view.
    rows = [
        _prow("https://a.com/the-team", signature_hash="BASE"),
        _prow("https://a.com/the-team?type=lawyers", signature_hash="DIFFERENT"),
    ]
    classify_and_fold_parameterised(rows)
    param = rows[1]
    assert param["url_class"] == "parameterised"
    # Not folded: distinct content stays in the analysis.
    assert param["excluded"] is None
    assert "suggested_canonical" not in param or not param["suggested_canonical"]


def test_fold_parameterised_no_base_crawled_stays_eligible():
    rows = [_prow("https://a.com/the-team?type=lawyers", signature_hash="H1")]
    classify_and_fold_parameterised(rows)
    param = rows[0]
    assert param["url_class"] == "parameterised"
    assert param["excluded"] is None


def test_fold_parameterised_folds_index_document_base():
    # /index.php folds onto / via normalise_url, so a param page whose base is
    # /index.php content-confirms against the crawled home page.
    rows = [
        _prow("https://a.com/", signature_hash="HOME"),
        _prow("https://a.com/index.php?lang=en", signature_hash="HOME"),
    ]
    classify_and_fold_parameterised(rows)
    param = rows[1]
    assert param["excluded"] == "parameterised-duplicate"
    assert param["suggested_canonical"] == "https://a.com/"


# --------------------------------------------------------------------------
# CSV contracts
# --------------------------------------------------------------------------


def test_write_reports_produces_six_csvs_and_manifest(tmp_path):
    recs = [
        _rec("https://a.com/1", [1.0, 0.0]),
        _rec("https://a.com/2", [1.0, 0.0]),
    ]
    res = analyse_embeddings(recs, lang_split=False)
    written = write_reports(
        str(tmp_path),
        res,
        excluded_rows=[{"url": "https://a.com/x", "excluded": "noindex", "word_count": 0}],
        hreflang_issues=[],
        variant_rows=[],
        manifest={"version": "1.0.0"},
    )
    names = {p.split("/")[-1] for p in written}
    assert names == {
        "pages.csv",
        "overlap_pairs.csv",
        "clusters.csv",
        "hreflang_issues.csv",
        "url_variants.csv",
        "amp_issues.csv",
        "similarity_distribution.csv",
        "run_manifest.json",
    }
    # overlap_pairs column contract.
    with open(tmp_path / "overlap_pairs.csv") as fh:
        header = next(csv.reader(fh))
    assert header == [
        "url_a",
        "url_b",
        "similarity",
        "low_confidence",
        "thin",
        "sim_percentile",
        "pair_class",
        "relation",
        "section_a",
        "section_b",
    ]
    # Excluded page appears in pages.csv with its reason.
    with open(tmp_path / "pages.csv") as fh:
        rows = list(csv.DictReader(fh))
    excluded = [r for r in rows if r["url"] == "https://a.com/x"]
    assert excluded and excluded[0]["excluded"] == "noindex"


# --------------------------------------------------------------------------
# Orchestrator + --fail-on against a fake store
# --------------------------------------------------------------------------


class FakeAnalysisStore:
    def __init__(self, rows, amp_hygiene=None):
        self._rows = rows
        self._amp_hygiene = amp_hygiene or []

    async def fetch_analysis_rows(self):
        return [dict(r) for r in self._rows]

    async def fetch_hreflang_edges(self):
        return []

    async def fetch_url_variant_rows(self):
        return []

    async def classify_amp_variants(self):
        return [dict(r) for r in self._amp_hygiene]


def _store_row(url, vec, **over):
    row = {
        "url_id": abs(hash(url)) % 100000,
        "url": url,
        "kind": "html",
        "status": 200,
        "overall_indexable": True,
        "canonical_url": None,
        "variant_of": None,
        "hreflang_group": None,
        "hreflang_code": None,
        "word_count": 100,
        "main_text": None,
        "signal_confidence": "high",
        "signature_model_input": None,
        "embedding": _unit(vec),
        "embedding_model": "M",
    }
    row.update(over)
    return row


@pytest.mark.asyncio
async def test_run_intent_overlap_fail_on_duplicate(tmp_path):
    rows = [
        _store_row("https://a.com/1", [1.0, 0.0, 0.0]),
        _store_row("https://a.com/2", [1.0, 0.0, 0.0]),
    ]
    store = FakeAnalysisStore(rows)
    run = await run_intent_overlap(store, out_dir=str(tmp_path), lang_split=False, fail_on="duplicate")
    assert run.exit_code == 3
    assert run.result.summary["duplicate_pages"] == 2


@pytest.mark.asyncio
async def test_run_intent_overlap_no_fail_when_clean(tmp_path):
    rows = [
        _store_row("https://a.com/1", [1.0, 0.0, 0.0]),
        _store_row("https://a.com/2", [0.0, 1.0, 0.0]),
    ]
    store = FakeAnalysisStore(rows)
    run = await run_intent_overlap(store, out_dir=str(tmp_path), lang_split=False, fail_on="duplicate")
    assert run.exit_code == 0
    assert run.result.summary["overlap_pairs"] == 0


@pytest.mark.asyncio
async def test_run_intent_overlap_excludes_noindex(tmp_path):
    rows = [
        _store_row("https://a.com/1", [1.0, 0.0, 0.0]),
        _store_row("https://a.com/2", [1.0, 0.0, 0.0], overall_indexable=False),
    ]
    store = FakeAnalysisStore(rows)
    run = await run_intent_overlap(store, out_dir=str(tmp_path), lang_split=False)
    # Only one eligible page -> no pairs; the noindex page is excluded.
    assert run.result.summary["overlap_pairs"] == 0
    assert run.result.summary["pages_excluded"] == 1


@pytest.mark.asyncio
async def test_run_intent_overlap_pages_csv_reports_thin_diagnostic_lengths(tmp_path):
    rows = [
        _store_row(
            "https://a.com/videos",
            [1.0, 0.0, 0.0],
            word_count=900,
            main_text="alpha beta gamma",
            signature_model_input="title h1 alpha beta gamma",
        ),
        _store_row(
            "https://a.com/videos/clip",
            [1.0, 0.0, 0.0],
            word_count=820,
            main_text="clip clip",
            signature_model_input="clip clip",
        ),
    ]
    store = FakeAnalysisStore(rows)
    await run_intent_overlap(store, out_dir=str(tmp_path), lang_split=False)

    with open(tmp_path / "pages.csv") as fh:
        by_url = {row["url"]: row for row in csv.DictReader(fh)}

    page = by_url["https://a.com/videos"]
    assert page["word_count"] == "900"
    assert page["main_text_words"] == "3"
    assert page["main_text_chars"] == str(len("alpha beta gamma"))
    assert page["signature_words"] == "5"
    assert page["signature_chars"] == str(len("title h1 alpha beta gamma"))


@pytest.mark.asyncio
async def test_run_intent_overlap_pages_csv_distinguishes_missing_vs_zero_length_evidence(tmp_path):
    rows = [
        _store_row("https://a.com/missing", [1.0, 0.0, 0.0], main_text=None, signature_model_input=None),
        _store_row("https://a.com/empty", [0.0, 1.0, 0.0], main_text="", signature_model_input=""),
    ]
    store = FakeAnalysisStore(rows)
    await run_intent_overlap(store, out_dir=str(tmp_path), lang_split=False)

    with open(tmp_path / "pages.csv") as fh:
        by_url = {row["url"]: row for row in csv.DictReader(fh)}

    missing = by_url["https://a.com/missing"]
    assert missing["main_text_words"] == ""
    assert missing["main_text_chars"] == ""
    assert missing["signature_words"] == ""
    assert missing["signature_chars"] == ""

    empty = by_url["https://a.com/empty"]
    assert empty["main_text_words"] == "0"
    assert empty["main_text_chars"] == "0"
    assert empty["signature_words"] == "0"
    assert empty["signature_chars"] == "0"


@pytest.mark.asyncio
async def test_run_intent_overlap_folds_parameterised_duplicate(tmp_path):
    # Base + a sim-1.0 parameterised variant sharing one signature hash: the
    # variant folds out of pairing and reports a missing-canonical action, so no
    # overlap pair survives (ticket 102).
    rows = [
        _store_row("https://a.com/the-team", [1.0, 0.0, 0.0], signature_hash="TEAM"),
        _store_row("https://a.com/the-team?type=lawyers", [1.0, 0.0, 0.0], signature_hash="TEAM"),
    ]
    store = FakeAnalysisStore(rows)
    run = await run_intent_overlap(store, out_dir=str(tmp_path), lang_split=False)
    s = run.result.summary
    assert s["overlap_pairs"] == 0
    assert s["parameterised_pages"] == 1
    assert s["parameterised_duplicates"] == 1
    assert s["missing_canonical"] == 1
    assert s["excluded_by_reason"].get("parameterised-duplicate") == 1

    with open(tmp_path / "pages.csv") as fh:
        page_rows = list(csv.DictReader(fh))
    assert "url_class" in page_rows[0]
    folded = [r for r in page_rows if r["url"] == "https://a.com/the-team?type=lawyers"][0]
    assert folded["excluded"] == "parameterised-duplicate"
    assert folded["url_class"] == "parameterised"
    assert folded["suggested_canonical"] == "https://a.com/the-team"


@pytest.mark.asyncio
async def test_run_intent_overlap_distinct_parameterised_view_still_pairs(tmp_path):
    # Different signature hashes: the parameterised view keeps its class but is
    # NOT folded, so it stays available to pair as a genuine content finding.
    rows = [
        _store_row("https://a.com/the-team", [1.0, 0.0, 0.0], signature_hash="BASE"),
        _store_row("https://a.com/the-team?type=lawyers", [1.0, 0.0, 0.0], signature_hash="OTHER"),
    ]
    store = FakeAnalysisStore(rows)
    run = await run_intent_overlap(store, out_dir=str(tmp_path), lang_split=False)
    s = run.result.summary
    assert s["overlap_pairs"] == 1
    assert s["parameterised_pages"] == 1
    assert s["parameterised_duplicates"] == 0


@pytest.mark.asyncio
async def test_run_intent_overlap_excludes_amp_and_writes_hygiene(tmp_path):
    # Two identical eligible pages plus an AMP variant with the SAME embedding.
    # Without amp-variant classification the AMP page would pair as a duplicate;
    # with it, it is excluded and never reaches overlap_pairs.csv (ticket 103).
    rows = [
        _store_row("https://a.com/p", [1.0, 0.0, 0.0]),
        _store_row("https://a.com/q", [1.0, 0.0, 0.0]),
        _store_row("https://a.com/p/amp", [1.0, 0.0, 0.0], variant_kind="amp"),
    ]
    amp_hygiene = [
        {
            "url": "https://a.com/p/amp",
            "base_url": "https://a.com/p",
            "variant_kind": "amp",
            "confirmed_by": "base-exists",
            "canonical_url": "",
            "has_canonical": False,
            "issue": "missing-canonical",
        }
    ]
    store = FakeAnalysisStore(rows, amp_hygiene=amp_hygiene)
    run = await run_intent_overlap(store, out_dir=str(tmp_path), lang_split=False)

    assert run.result.summary["amp_variants"] == 1
    assert run.result.summary["amp_missing_canonical"] == 1
    assert run.result.summary["excluded_by_reason"].get("amp-variant") == 1

    # No AMP URL in overlap_pairs.csv.
    with open(tmp_path / "overlap_pairs.csv") as fh:
        pair_rows = list(csv.DictReader(fh))
    assert all("/amp" not in r["url_a"] and "/amp" not in r["url_b"] for r in pair_rows)

    # The missing-canonical AMP page surfaces in amp_issues.csv with its base.
    with open(tmp_path / "amp_issues.csv") as fh:
        amp_rows = list(csv.DictReader(fh))
    assert len(amp_rows) == 1
    assert amp_rows[0]["url"] == "https://a.com/p/amp"
    assert amp_rows[0]["base_url"] == "https://a.com/p"
    assert amp_rows[0]["issue"] == "missing-canonical"


@pytest.mark.asyncio
async def test_run_intent_overlap_fail_on_duplicate_excludes_thin_only_pairs(tmp_path):
    # The thompsons-scotland /videos shape: healthy word_count, near-empty
    # signature on both sides -> should NOT trip --fail-on duplicate, and the
    # thin counters should surface the finding instead of hiding it.
    rows = [
        _store_row("https://a.com/videos", [1.0, 0.0, 0.0], word_count=900, signature_model_input=_words(5)),
        _store_row("https://a.com/videos/clip", [1.0, 0.0, 0.0], word_count=820, signature_model_input=_words(3)),
    ]
    store = FakeAnalysisStore(rows)
    run = await run_intent_overlap(store, out_dir=str(tmp_path), lang_split=False, fail_on="duplicate")
    assert run.exit_code == 0
    assert run.result.summary["duplicate_pages"] == 0
    assert run.result.summary["thin_content_pages"] == 2
    assert run.result.summary["thin_pairs"] == 1


@pytest.mark.asyncio
async def test_run_intent_overlap_rejects_mixed_models(tmp_path):
    from crawler_cli.embeddings import MixedModelError

    rows = [
        _store_row("https://a.com/1", [1.0, 0.0], embedding_model="M1"),
        _store_row("https://a.com/2", [0.0, 1.0], embedding_model="M2"),
    ]
    store = FakeAnalysisStore(rows)
    with pytest.raises(MixedModelError):
        await run_intent_overlap(store, out_dir=str(tmp_path), lang_split=False)


@pytest.mark.asyncio
async def test_run_intent_overlap_fail_on_duplicate_still_counts_parent_child(tmp_path):
    # Ticket 101 constraint: --fail-on duplicate keeps counting parent-child
    # pairs by default — the new label split must not silently change gating.
    rows = [
        _store_row("https://a.com/videos", [1.0, 0.0, 0.0]),
        _store_row("https://a.com/videos/road-safety", [0.999, 0.044, 0.0]),
    ]
    store = FakeAnalysisStore(rows)
    run = await run_intent_overlap(store, out_dir=str(tmp_path), lang_split=False, fail_on="duplicate")
    assert run.exit_code == 3
    assert run.result.summary["duplicate_pages"] == 2
    assert run.result.summary["duplicate_pages_parent_child_only"] == 2


@pytest.mark.asyncio
async def test_run_intent_overlap_manifest_has_relation_counts(tmp_path):
    rows = [
        _store_row("https://a.com/videos", [1.0, 0.0, 0.0]),
        _store_row("https://a.com/videos/road-safety", [0.999, 0.044, 0.0]),
    ]
    store = FakeAnalysisStore(rows)
    run = await run_intent_overlap(store, out_dir=str(tmp_path), lang_split=False, run_args={"threshold": 0.85})
    assert run.result.summary["relation_counts"] == {"parent-child": 1}
    manifest = json.loads((tmp_path / "run_manifest.json").read_text())
    assert manifest["summary"]["relation_counts"] == {"parent-child": 1}


# --------------------------------------------------------------------------
# Ticket 105: time-sequenced sections (news/blog QDF policy)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,prefix,expected",
    [
        ("https://a.com/news", "/news", True),
        ("https://a.com/news/", "/news", True),
        ("https://a.com/news/archived/foo", "/news", True),  # nested path
        ("https://a.com/news/archived/foo/", "/news", True),  # trailing slash on url
        ("https://a.com/news", "/news/", True),  # trailing slash on prefix
        ("https://a.com/newsletter", "/news", False),  # segment-boundary, not substring
        ("https://a.com/newsletter/signup", "/news", False),
        ("https://a.com/blog/post", "/news", False),
        ("https://a.com/NEWS/Archived/Foo", "/news", True),  # case-insensitive
    ],
)
def test_path_in_section_prefix_matching(url, prefix, expected):
    assert path_in_section(url, prefix) is expected


def test_time_sequenced_pair_class_requires_both_sides():
    sections = ["/news"]
    # Both under /news -> time-sequenced.
    assert time_sequenced_pair_class("https://a.com/news/1", "https://a.com/news/2", sections) == "time-sequenced"
    # One in /news, one outside -> cross-section, unaffected.
    assert time_sequenced_pair_class("https://a.com/news/1", "https://a.com/services/x", sections) == ""
    # Neither in /news.
    assert time_sequenced_pair_class("https://a.com/services/x", "https://a.com/services/y", sections) == ""


def test_time_sequenced_pair_class_no_sections_configured():
    # No --time-sequenced-section given -> never classified, existing behaviour untouched.
    assert time_sequenced_pair_class("https://a.com/news/1", "https://a.com/news/2", []) == ""


def test_intra_news_pair_gets_softer_label_and_pair_class():
    recs = [
        _rec("https://a.com/news/archived/frankly-legal-health-and-safety", [1.0, 0.0, 0.0]),
        _rec("https://a.com/news/archived/frankly-legal-how-health-safety-helps-you", [0.999, 0.044, 0.0]),
    ]
    res = analyse_embeddings(recs, lang_split=False, time_sequenced_sections=["/news"])
    assert len(res.overlap_pairs) == 1
    assert res.overlap_pairs[0]["pair_class"] == "time-sequenced"
    assert res.summary["time_sequenced_pairs"] == 1
    assert res.summary["time_sequenced_pages"] == 2
    # Softer label replaces the duplicate label, and duplicate_pages excludes them.
    assert all(row["risk"] == TIME_SEQUENCED_RISK for row in res.pages_rows)
    assert res.summary["duplicate_pages"] == 0
    # Cluster gets the hub/roundup suggestion, not a canonical pick.
    assert len(res.cluster_rows) == 1
    assert "hub/roundup" in res.cluster_rows[0]["suggested_canonical"]
    assert res.cluster_rows[0]["time_sequenced"] is True


def test_thin_content_takes_precedence_over_time_sequenced_policy():
    recs = [
        _rec("https://a.com/news/one", [1.0, 0.0], sig=_words(5)),
        _rec("https://a.com/news/two", [1.0, 0.0], sig=_words(5)),
    ]
    res = analyse_embeddings(recs, lang_split=False, time_sequenced_sections=["/news"])
    assert res.overlap_pairs[0]["pair_class"] == "time-sequenced"
    assert all(row["risk"].startswith("thin content") for row in res.pages_rows)
    assert res.cluster_rows[0]["thin"] is True
    assert "thin content" in res.cluster_rows[0]["suggested_canonical"]
    assert res.summary["duplicate_pages"] == 0
    assert res.summary["time_sequenced_pages"] == 0


def test_cross_section_overlap_is_not_masked_by_closer_time_sequenced_pair():
    recs = [
        _rec("https://a.com/news/one", [1.0, 0.0]),
        _rec("https://a.com/news/two", [1.0, 0.0]),
        _rec("https://a.com/services/topic", [0.9, 0.4358899]),
    ]
    res = analyse_embeddings(recs, lang_split=False, time_sequenced_sections=["/news"])
    news_rows = [row for row in res.pages_rows if "/news/" in row["url"]]
    assert all(row["risk"] == "high intent overlap" for row in news_rows)
    assert res.summary["time_sequenced_pairs"] == 1
    assert res.summary["time_sequenced_pages"] == 0


def test_cross_section_pair_keeps_full_duplicate_treatment():
    # A news page vs. an evergreen service page -> real cannibalisation risk,
    # NOT covered by --time-sequenced-section even with near-identical content.
    recs = [
        _rec("https://a.com/news/archived/foo", [1.0, 0.0, 0.0]),
        _rec("https://a.com/services/health-and-safety", [0.999, 0.044, 0.0]),
    ]
    res = analyse_embeddings(recs, lang_split=False, time_sequenced_sections=["/news"])
    assert res.overlap_pairs[0]["pair_class"] == ""
    assert res.summary["time_sequenced_pairs"] == 0
    assert all(row["risk"] == "duplicate — decanonicalisation likely" for row in res.pages_rows)
    assert res.summary["duplicate_pages"] == 2


def test_non_news_findings_unchanged_when_no_time_sequenced_sections_configured():
    recs = [
        _rec("https://a.com/news/archived/foo", [1.0, 0.0, 0.0]),
        _rec("https://a.com/news/archived/bar", [0.999, 0.044, 0.0]),
    ]
    # No --time-sequenced-section at all -> identical to pre-ticket-105 behaviour.
    res = analyse_embeddings(recs, lang_split=False)
    assert res.overlap_pairs[0]["pair_class"] == ""
    assert all(row["risk"] == "duplicate — decanonicalisation likely" for row in res.pages_rows)
    assert res.summary["time_sequenced_pairs"] == 0
    assert res.summary["time_sequenced_pages"] == 0


def test_chained_cluster_label_wins_over_time_sequenced():
    # Same chained-cluster fixture as test_chained_cluster_flagged_when_min_intra_below_threshold,
    # but all three URLs are under the same time-sequenced section. The graph-quality
    # "chained cluster" review label is existing, more specific precedence and must still win
    # (there is no "thin content" label on current master to defer to instead — see ticket 105's
    # test task note).
    a = [1.0, 0.0, 0.0]
    b = [0.75, 0.66, 0.0]
    c = [0.2, 0.98, 0.0]
    recs = [
        _rec("https://a.com/news/a", a),
        _rec("https://a.com/news/b", b),
        _rec("https://a.com/news/c", c),
    ]
    res = analyse_embeddings(
        recs, threshold=0.6, dup_threshold=0.99, lang_split=False, time_sequenced_sections=["/news"]
    )
    chained = [c for c in res.cluster_rows if c["chained"]]
    assert chained
    assert chained[0]["suggested_canonical"] == "review — chained cluster"
    assert chained[0]["time_sequenced"] is False  # chained precedence, not double-counted


@pytest.mark.asyncio
async def test_run_intent_overlap_fail_on_duplicate_excludes_time_sequenced(tmp_path):
    rows = [
        _store_row("https://a.com/news/1", [1.0, 0.0, 0.0]),
        _store_row("https://a.com/news/2", [1.0, 0.0, 0.0]),
    ]
    store = FakeAnalysisStore(rows)
    run = await run_intent_overlap(
        store,
        out_dir=str(tmp_path),
        lang_split=False,
        fail_on="duplicate",
        time_sequenced_sections=["/news"],
    )
    # Would have failed under plain --fail-on duplicate (see
    # test_run_intent_overlap_fail_on_duplicate); time-sequenced opt-in clears it.
    assert run.exit_code == 0
    assert run.result.summary["duplicate_pages"] == 0
    assert run.result.summary["time_sequenced_pairs"] == 1


@pytest.mark.asyncio
async def test_run_intent_overlap_fail_on_overlap_still_counts_time_sequenced(tmp_path):
    # --fail-on overlap is untouched by ticket 105 — only the duplicate gate is
    # softened, since the ticket scope is decanonicalisation gating specifically.
    rows = [
        _store_row("https://a.com/news/1", [1.0, 0.0, 0.0]),
        _store_row("https://a.com/news/2", [1.0, 0.0, 0.0]),
    ]
    store = FakeAnalysisStore(rows)
    run = await run_intent_overlap(
        store,
        out_dir=str(tmp_path),
        lang_split=False,
        fail_on="overlap",
        time_sequenced_sections=["/news"],
    )
    assert run.exit_code == 3


def test_cli_time_sequenced_section_flag_is_repeatable():
    from crawler_cli.__main__ import _build_parser

    parser = _build_parser()
    args = parser.parse_args(
        [
            "intent-overlap",
            "--time-sequenced-section",
            "/news",
            "--time-sequenced-section",
            "/blog",
        ]
    )
    assert args.time_sequenced_section == ["/news", "/blog"]


def test_cli_time_sequenced_section_defaults_to_none():
    from crawler_cli.__main__ import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["intent-overlap"])
    assert args.time_sequenced_section is None
