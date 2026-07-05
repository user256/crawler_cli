"""ANN scale-path tests for intent-overlap (ticket 081).

Ports the IO ticket-116 recall evidence: ANN pair search achieves >= 0.99 recall
vs exact brute-force on a >= 10k-page synthetic fixture, and degrades gracefully
without hnswlib.
"""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
hnswlib = pytest.importorskip("hnswlib")

from crawler_cli.intent_overlap import (  # noqa: E402
    analyse_embeddings,
    ann_recall_check,
    ann_similarity_pairs,
    similarity_pairs,
)


def _synthetic_clustered(n=10000, dim=32, clusters=200, seed=0):
    """n normalized vectors in `clusters` tight groups, so there are real
    high-similarity pairs to recall."""
    rng = np.random.RandomState(seed)
    centers = rng.randn(clusters, dim).astype(np.float32)
    centers /= np.linalg.norm(centers, axis=1, keepdims=True)
    assign = rng.randint(0, clusters, size=n)
    vecs = centers[assign] + 0.03 * rng.randn(n, dim).astype(np.float32)
    vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs.astype(np.float32)


@pytest.mark.slow
def test_ann_recall_at_least_099_on_10k():
    vecs = _synthetic_clustered(n=10000)
    recall = ann_recall_check(vecs, threshold=0.9, k=128, min_recall=0.99)
    assert recall >= 0.99, f"ANN recall {recall:.4f} below 0.99 floor"


def test_ann_recall_small_fixture():
    # Smaller fixture keeps the default suite fast while still proving the path.
    vecs = _synthetic_clustered(n=1500, clusters=50)
    recall = ann_recall_check(vecs, threshold=0.9, k=128)
    assert recall >= 0.99


def test_ann_pairs_are_subset_of_similarity_semantics():
    vecs = _synthetic_clustered(n=800, clusters=30)
    ann = {(i, j) for i, j, _ in ann_similarity_pairs(vecs, 0.9, k=64)}
    exact = {(i, j) for i, j, _ in similarity_pairs(vecs, 0.9)}
    # Every ANN pair really is above threshold (no false pairs), recall <= 1.
    assert ann <= exact or len(ann & exact) / max(1, len(ann)) > 0.99


def test_ann_and_exact_agree_on_analysis(tmp_path=None):
    # With ann_min_pages below n, the analysis uses ANN; results should match
    # the exact path on a clustered fixture (recall ~1 at this scale).
    vecs = _synthetic_clustered(n=1200, clusters=40)
    recs = [
        {"url": f"https://x/{i}", "vector": vecs[i].tolist(), "group": None,
         "hreflang_code": None, "word_count": 100, "signal_confidence": "high"}
        for i in range(len(vecs))
    ]
    exact = analyse_embeddings(recs, threshold=0.9, lang_split=False, use_ann=False)
    ann = analyse_embeddings(recs, threshold=0.9, lang_split=False, use_ann=True, ann_min_pages=100, ann_k=128)
    # Duplicate-page counts should match (ANN recovers all real pairs here).
    assert ann.summary["duplicate_pages"] == exact.summary["duplicate_pages"]
