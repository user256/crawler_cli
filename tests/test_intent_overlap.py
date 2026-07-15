"""Unit tests for intent-overlap analysis (ticket 079).

Small synthetic vector fixtures — no model, no DB. Covers suppression modes,
both linkages, chained-cluster flagging, singleton partitions, risk levels,
CSV column contracts, and --fail-on exit codes.
"""

from __future__ import annotations

import csv
import math

import pytest

np = pytest.importorskip("numpy")

from crawler_cli.intent_overlap import (  # noqa: E402
    analyse_embeddings,
    classify_and_fold_parameterised,
    classify_url,
    compute_exclusion,
    run_intent_overlap,
    similarity_pairs,
    write_reports,
)


def _unit(vec):
    v = np.asarray(vec, dtype=np.float32)
    return (v / np.linalg.norm(v)).tolist()


def _rec(url, vec, *, group=None, code=None, wc=100, conf="high"):
    return {
        "url": url,
        "vector": _unit(vec),
        "group": group,
        "hreflang_code": code,
        "word_count": wc,
        "signal_confidence": conf,
    }


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
    ],
)
def test_classify_url(row, expected):
    assert classify_url(row) == expected


def _prow(url, **over):
    row = {"url": url, "kind": "html", "status": 200, "overall_indexable": True, "canonical_url": None,
           "variant_of": None, "signature_hash": None, "excluded": None}
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
        "similarity_distribution.csv",
        "run_manifest.json",
    }
    # overlap_pairs column contract.
    with open(tmp_path / "overlap_pairs.csv") as fh:
        header = next(csv.reader(fh))
    assert header == ["url_a", "url_b", "similarity", "low_confidence", "sim_percentile"]
    # Excluded page appears in pages.csv with its reason.
    with open(tmp_path / "pages.csv") as fh:
        rows = list(csv.DictReader(fh))
    excluded = [r for r in rows if r["url"] == "https://a.com/x"]
    assert excluded and excluded[0]["excluded"] == "noindex"


# --------------------------------------------------------------------------
# Orchestrator + --fail-on against a fake store
# --------------------------------------------------------------------------


class FakeAnalysisStore:
    def __init__(self, rows):
        self._rows = rows

    async def fetch_analysis_rows(self):
        return [dict(r) for r in self._rows]

    async def fetch_hreflang_edges(self):
        return []

    async def fetch_url_variant_rows(self):
        return []


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
        "signal_confidence": "high",
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
async def test_run_intent_overlap_rejects_mixed_models(tmp_path):
    from crawler_cli.embeddings import MixedModelError

    rows = [
        _store_row("https://a.com/1", [1.0, 0.0], embedding_model="M1"),
        _store_row("https://a.com/2", [0.0, 1.0], embedding_model="M2"),
    ]
    store = FakeAnalysisStore(rows)
    with pytest.raises(MixedModelError):
        await run_intent_overlap(store, out_dir=str(tmp_path), lang_split=False)
