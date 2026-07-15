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
    compute_exclusion,
    run_intent_overlap,
    similarity_pairs,
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
    ],
)
def test_compute_exclusion(row, expected):
    assert compute_exclusion(row) == expected


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
    assert header == ["url_a", "url_b", "similarity", "low_confidence", "thin", "sim_percentile"]
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
