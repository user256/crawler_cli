"""Intent-overlap analysis (ticket 079) — the core Intent_Overlap deliverable.

Ports ``analyse()`` (intent_overlap.py:1224) onto crawler_cli's Postgres store:
loads embeddings (ticket 077), partitions by language, computes block-wise
pairwise cosine similarity with hreflang-group suppression (ticket 078),
clusters, scores de-canonicalisation risk, suggests canonicals, calibrates
thresholds, and writes the CSV report set.

Every numeric routine here is a verbatim port of the *fixed* upstream reference
(HEAD 96fce80, v2.1.0): block-wise `similarity_pairs`/`nearest_neighbor_sims`
(no N×N), the `scan_low = min(0.80, threshold)` calibration floor (IO 115),
seeded vectorised `intra_cluster_stats` (IO 110/117), and complete-linkage
membership (IO 110).

**100% crawler-powered.** All inputs come from the crawler's own store. There
is no GSC / external CSV join (dropped per user direction); canonical selection
is word_count → shortest URL only.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from .embeddings import ensure_single_model
from .hreflang_groups import UnionFind, lang_bucket, normalise_url, reciprocity_issues
from .persistence import AnalysisRow, UrlVariantRow

if TYPE_CHECKING:
    from .persistence import AsyncpgStore


class AnalysedRow(AnalysisRow, total=False):
    """A store :class:`AnalysisRow` augmented in-memory with the pairing
    ``excluded`` reason computed by :func:`compute_exclusion` (``None`` == the
    page is eligible for pairing).  ``excluded`` is derived at analysis time,
    never a SELECT column, so it lives here instead of polluting the DB-column
    ``AnalysisRow`` in persistence.py (ticket 085).  ``total=False`` marks only
    this added key optional — and, unlike ``NotRequired``, stays correct at
    runtime under ``from __future__ import annotations``."""

    excluded: str | None


class VariantReportRow(TypedDict):
    """One grouped row of url_variants.csv: a norm_url, its representative, the
    other variants folded into it, and the member count."""

    norm_url: str
    representative: str
    variants: str
    count: int


VERSION = "1.0.0"
CLUSTER_SAMPLE_CAP = 50

DEFAULT_THRESHOLD = 0.85
DEFAULT_DUP_THRESHOLD = 0.92
DIST_LOW = 0.80  # distribution buckets are defined on the 0.80 grid


def _np() -> Any:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - exercised via env without numpy
        raise RuntimeError(
            "numpy is required for intent-overlap analysis. Install the local "
            'embedding extra: pip install "crawler-cli[embeddings-local]"'
        ) from exc
    return np


# --------------------------------------------------------------------------
# Numeric core (verbatim ports)
# --------------------------------------------------------------------------


def similarity_pairs(vecs: Any, threshold: float, block: int = 1000) -> Iterable[tuple[int, int, float]]:
    """Yield (i, j, sim) for i<j with sim >= threshold, block-wise so the full
    NxN matrix never exists at once (intent_overlap.py:1047)."""
    np = _np()
    n = len(vecs)
    for start in range(0, n, block):
        chunk = vecs[start : start + block] @ vecs.T
        for bi, j in np.argwhere(chunk >= threshold):
            i = start + int(bi)
            j = int(j)
            if j > i:
                yield i, j, float(chunk[bi, j])


def ann_similarity_pairs(vecs: Any, threshold: float, k: int = 128) -> Iterable[tuple[int, int, float]]:
    """Approximate pairs via an hnswlib cosine index (recall depends on k/ef).

    Ported from intent_overlap.py:1060 (IO ticket 112). Raises a clear error
    naming the `[ann]` extra when hnswlib is absent.
    """
    try:
        import hnswlib
    except ImportError as exc:
        raise RuntimeError(
            "hnswlib is required for --ann. Install the extra: "
            'pip install "crawler-cli[ann]" (or omit --ann for the exact path).'
        ) from exc
    np = _np()
    n, dim = vecs.shape
    index = hnswlib.Index(space="cosine", dim=dim)
    index.init_index(max_elements=n, ef_construction=200, M=16)
    index.add_items(vecs, np.arange(n))
    index.set_ef(max(50, k))
    best: dict[tuple[int, int], float] = {}
    for i in range(n):
        labels, distances = index.knn_query(vecs[i], k=min(k, n))
        for j, dist in zip(labels[0], distances[0]):
            j = int(j)
            if j == i:
                continue
            lo, hi = min(i, j), max(i, j)
            sim = 1.0 - float(dist)
            best[(lo, hi)] = max(best.get((lo, hi), 0.0), sim)
    for (lo, hi), sim in best.items():
        if sim >= threshold:
            yield lo, hi, sim


def ann_recall_check(vecs: Any, threshold: float, k: int = 128, min_recall: float = 0.99) -> float:
    """Recall of ANN vs brute-force pairs at *threshold* (intent_overlap.py:1086,
    IO ticket 116). Returns 1.0 when there are no brute-force pairs."""
    brute = {(min(i, j), max(i, j)) for i, j, _ in similarity_pairs(vecs, threshold)}
    if not brute:
        return 1.0
    ann = {(min(i, j), max(i, j)) for i, j, _ in ann_similarity_pairs(vecs, threshold, k=k)}
    return len(brute & ann) / len(brute)


def nearest_neighbor_sims(vecs: Any, block: int = 1000) -> Any:
    """Per-page max cosine similarity to any other page, block-wise (no N×N;
    intent_overlap.py:1115)."""
    np = _np()
    n = len(vecs)
    if n < 2:
        return np.array([])
    nn = np.full(n, -1.0, dtype=np.float32)
    for start in range(0, n, block):
        chunk = vecs[start : start + block] @ vecs.T
        for bi in range(chunk.shape[0]):
            i = start + bi
            row = chunk[bi]
            row[i] = -1.0
            nn[i] = max(nn[i], float(row.max()))
    return nn


def percentile_rank(value: float, sample: Any) -> float:
    np = _np()
    if len(sample) == 0:
        return 0.0
    sorted_s = np.sort(sample)
    return float(100.0 * np.searchsorted(sorted_s, value, side="right") / len(sorted_s))


def build_similarity_distribution(
    lang: str, nn: Any, pair_sims: list[float], pages: int | None = None
) -> dict[str, Any]:
    np = _np()
    row: dict[str, Any] = {"language": lang, "pages": pages if pages is not None else len(nn)}
    if len(nn) >= 2:
        pct = np.percentile(nn, [50, 90, 95, 99, 99.9])
        row.update(
            {
                "p50": round(float(pct[0]), 4),
                "p90": round(float(pct[1]), 4),
                "p95": round(float(pct[2]), 4),
                "p99": round(float(pct[3]), 4),
                "p99_9": round(float(pct[4]), 4),
            }
        )
    for t in np.arange(0.80, 0.955, 0.01):
        tr = round(float(t), 2)
        row[f"pairs_at_{tr:.2f}"] = sum(1 for s in pair_sims if s >= tr)
    return row


def _min_pairwise_sim(vecs: Any, member_idxs: list[int], block: int = 512) -> float:
    """Minimum cosine similarity over all member pairs, block-wise; equals the
    naive double-loop min (intent_overlap.py:1156, IO 117)."""
    np = _np()
    members = np.asarray(member_idxs)
    sub = vecs[members]
    m = len(sub)
    min_s = 1.0
    for start in range(0, m, block):
        chunk = sub[start : start + block] @ sub.T
        for bi in range(chunk.shape[0]):
            chunk[bi, start + bi] = np.inf
            min_s = min(min_s, float(chunk[bi].min()))
    return min_s


def intra_cluster_stats(vecs: Any, member_idxs: list[int]) -> tuple[float, float, float, bool]:
    """(min_sim, mean_sim, cohesion, sampled) over member pairs
    (intent_overlap.py:1171; seeded sampling, vectorised true-min)."""
    np = _np()
    if len(member_idxs) < 2:
        return 1.0, 1.0, 1.0, False
    sampled = len(member_idxs) > CLUSTER_SAMPLE_CAP
    min_s = _min_pairwise_sim(vecs, member_idxs)
    if sampled:
        rng = np.random.RandomState(42)
        idxs = sorted(rng.choice(member_idxs, size=CLUSTER_SAMPLE_CAP, replace=False))
    else:
        idxs = member_idxs
    sims = []
    for a in range(len(idxs)):
        for b in range(a + 1, len(idxs)):
            sims.append(float(vecs[idxs[a]] @ vecs[idxs[b]]))
    mean_s = sum(sims) / len(sims)
    cohesion = min_s / mean_s if mean_s > 0 else 0.0
    return min_s, mean_s, cohesion, sampled


def complete_linkage_clusters(edges: list[tuple[int, int, float]], vecs: Any, threshold: float) -> list[set[int]]:
    """Greedy complete-linkage: grow clusters only when the new member ≥
    threshold to ALL current members (intent_overlap.py:1192, IO 110)."""
    clusters: list[set[int]] = []
    node_cluster: dict[int, int] = {}
    for i, j, _s in sorted(edges, key=lambda x: -x[2]):
        ci, cj = node_cluster.get(i), node_cluster.get(j)
        if ci is not None and ci == cj:
            continue
        if ci is not None and cj is not None and ci != cj:
            if all(float(vecs[a] @ vecs[b]) >= threshold for a in clusters[ci] for b in clusters[cj]):
                merged = clusters[ci] | clusters[cj]
                clusters[ci] = merged
                clusters[cj] = set()
                for node in merged:
                    node_cluster[node] = ci
            continue
        if ci is not None:
            if all(float(vecs[j] @ vecs[k]) >= threshold for k in clusters[ci]):
                clusters[ci].add(j)
                node_cluster[j] = ci
        elif cj is not None:
            if all(float(vecs[i] @ vecs[k]) >= threshold for k in clusters[cj]):
                clusters[cj].add(i)
                node_cluster[i] = cj
        else:
            clusters.append({i, j})
            idx = len(clusters) - 1
            node_cluster[i] = node_cluster[j] = idx
    return [c for c in clusters if len(c) > 1]


# --------------------------------------------------------------------------
# Analysis over structured records (no DB, no pandas)
# --------------------------------------------------------------------------


@dataclass(slots=True)
class AnalysisResult:
    pages_rows: list[dict[str, Any]] = field(default_factory=list)
    overlap_pairs: list[dict[str, Any]] = field(default_factory=list)
    cluster_rows: list[dict[str, Any]] = field(default_factory=list)
    distribution_rows: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    suppressed: int = 0
    chained_clusters: int = 0


def _pick_canonical(members: list[dict[str, Any]]) -> str:
    """word_count desc, tie-break shortest URL (intent_overlap.py:1384 without
    the GSC branch — dropped per user direction)."""
    top_wc = max(int(m.get("word_count") or 0) for m in members)
    ties = [m for m in members if int(m.get("word_count") or 0) == top_wc]
    return min((m["url"] for m in ties), key=len)


def analyse_embeddings(
    records: Sequence[dict[str, Any]],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    dup_threshold: float = DEFAULT_DUP_THRESHOLD,
    hreflang_mode: str = "suppress",
    primary_lang: str = "en",
    lang_split: bool = True,
    linkage: str = "single",
    use_ann: bool = False,
    ann_min_pages: int = 10000,
    ann_k: int = 128,
) -> AnalysisResult:
    """Core analysis over embedded, non-excluded page records.

    Each record is a dict with: ``url``, ``vector`` (list[float]), ``group``
    (hreflang group id or None), ``hreflang_code``, ``word_count``,
    ``signal_confidence``.  Ported from ``analyse()`` (intent_overlap.py:1224).
    """
    np = _np()
    result = AnalysisResult()

    emb = [r for r in records if r.get("vector") is not None]
    if not emb:
        return result

    role_map: dict[str, str] = {}
    if hreflang_mode == "primary-only":
        by_group: dict[Any, list[dict[str, Any]]] = {}
        for r in emb:
            by_group.setdefault(r.get("group"), []).append(r)
        keep: list[dict[str, Any]] = []
        for gid, members in by_group.items():
            if gid is None:
                keep.extend(members)
                continue
            ranked = sorted(
                members,
                key=lambda m: (0 if lang_bucket(m.get("hreflang_code")) == primary_lang else 1, len(m["url"])),
            )
            keep.append(ranked[0])
            role_map[ranked[0]["url"]] = f"primary of {gid}"
            for m in ranked[1:]:
                role_map[m["url"]] = f"variant omitted ({gid})"
        emb = keep

    n = len(emb)
    vecs = np.vstack([np.asarray(r["vector"], dtype=np.float32) for r in emb])
    # Defensive L2 normalise so cosine == dot even if a provider returned
    # non-unit vectors (sentence-transformers already normalises).
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vecs = (vecs / norms).astype(np.float32)

    urls = [r["url"] for r in emb]
    groups = [r.get("group") for r in emb]
    conf = [r.get("signal_confidence") for r in emb]
    langs = [lang_bucket(r.get("hreflang_code")) for r in emb]

    known = sum(1 for lang in langs if lang != "unknown") / n if n else 0.0
    if lang_split and known < 0.5:
        lang_split = False
    if lang_split:
        part_map: dict[str, list[int]] = {}
        for i, lang in enumerate(langs):
            part_map.setdefault(lang, []).append(i)
        partitions: list[tuple[str, list[int]]] = list(part_map.items())
    else:
        partitions = [("all", list(range(n)))]

    uf = UnionFind(n)
    max_sim = np.zeros(n)
    nearest: list[str | None] = [None] * n
    partition_edges: list[tuple[str, list[tuple[int, int, float]]]] = []
    suppressed = 0
    all_nn: list[float] = []
    scan_low = min(DIST_LOW, threshold)  # IO ticket 115 floor

    for lang, idx_list in partitions:
        idxs = np.asarray(idx_list)
        sub = vecs[idxs]
        part_n = len(sub)
        nn = nearest_neighbor_sims(sub)
        if len(nn):
            all_nn.extend(nn.tolist())
        part_pair_sims: list[float] = []
        part_edges: list[tuple[int, int, float]] = []
        if use_ann and part_n >= ann_min_pages:
            pair_iter = ann_similarity_pairs(sub, scan_low, k=ann_k)
        else:
            pair_iter = similarity_pairs(sub, scan_low)
        for a, b, s in pair_iter:
            i, j = int(idxs[a]), int(idxs[b])
            if hreflang_mode == "suppress" and groups[i] and groups[i] == groups[j]:
                if s >= threshold:
                    suppressed += 1
                continue
            if s >= DIST_LOW:
                part_pair_sims.append(s)
            if s >= threshold:
                result.overlap_pairs.append(
                    {
                        "url_a": urls[i],
                        "url_b": urls[j],
                        "similarity": round(s, 4),
                        "low_confidence": conf[i] == "low" or conf[j] == "low",
                    }
                )
                part_edges.append((i, j, s))
                uf.union(i, j)
                if s > max_sim[i]:
                    max_sim[i], nearest[i] = s, urls[j]
                if s > max_sim[j]:
                    max_sim[j], nearest[j] = s, urls[i]
        result.distribution_rows.append(build_similarity_distribution(lang, nn, part_pair_sims, pages=part_n))
        if linkage == "complete":
            partition_edges.append((lang, part_edges))

    nn_arr = np.array(all_nn) if all_nn else np.array([])

    # Cluster id assignment
    if linkage == "complete":
        cluster_members: list[set[int]] = []
        for _lang, edges in partition_edges:
            cluster_members += complete_linkage_clusters(edges, vecs, threshold)
        cluster_ids: dict[int, str] = {}
        for k, member_set in enumerate(sorted(cluster_members, key=lambda m: sorted(m)[0])):
            for i in member_set:
                cluster_ids[i] = f"C{k:04d}"
        roots: list[str | None] = [cluster_ids.get(i) for i in range(n)]
    else:
        find_of = [uf.find(i) for i in range(n)]
        counts: dict[int, int] = {}
        for root in find_of:
            counts[root] = counts.get(root, 0) + 1
        multi_roots = {root for root, c in counts.items() if c > 1}
        first_index: dict[int, int] = {}
        for i, root in enumerate(find_of):
            first_index.setdefault(root, i)
        ordered_roots = sorted(multi_roots, key=lambda root: first_index[root])
        root_map = {root: f"C{k:04d}" for k, root in enumerate(ordered_roots)}
        roots = [root_map[find_of[i]] if find_of[i] in multi_roots else None for i in range(n)]

    # Risk + per-page rows
    for i, r in enumerate(emb):
        ms = float(max_sim[i])
        if ms >= dup_threshold:
            risk = "duplicate — decanonicalisation likely"
        elif ms >= threshold:
            risk = "high intent overlap"
        else:
            risk = ""
        r["_cluster_id"] = roots[i]
        r["_max_similarity"] = round(ms, 4)
        r["_nearest_url"] = nearest[i]
        r["_risk"] = risk

    # Clusters
    by_cluster: dict[str, list[int]] = {}
    for i in range(n):
        cid = roots[i]
        if cid is not None:
            by_cluster.setdefault(cid, []).append(i)

    chained_n = 0
    canon_by_cluster: dict[str, str] = {}
    for cid, member_idxs in sorted(by_cluster.items()):
        members = [emb[i] for i in member_idxs]
        min_s, mean_s, cohesion, sampled = intra_cluster_stats(vecs, member_idxs)
        chained = min_s < threshold
        if chained:
            chained_n += 1
            canon = "review — chained cluster"
        else:
            canon = _pick_canonical(members)
        canon_by_cluster[cid] = canon
        note = f"sampled at {CLUSTER_SAMPLE_CAP}" if sampled else ""
        cluster_langs = sorted({lang_bucket(m.get("hreflang_code")) for m in members if m.get("hreflang_code")})
        result.cluster_rows.append(
            {
                "cluster_id": cid,
                "size": len(members),
                "suggested_canonical": canon,
                "languages": ",".join(cluster_langs),
                "urls": " | ".join(m["url"] for m in members),
                "avg_word_count": int(sum(int(m.get("word_count") or 0) for m in members) / len(members)),
                "min_intra_sim": round(min_s, 4),
                "mean_intra_sim": round(mean_s, 4),
                "cohesion": round(cohesion, 4),
                "chained": chained,
                "cohesion_note": note,
            }
        )
    result.cluster_rows.sort(key=lambda c: c["size"], reverse=True)

    # sim_percentile on each pair
    for pair in result.overlap_pairs:
        pair["sim_percentile"] = round(percentile_rank(pair["similarity"], nn_arr), 2) if len(nn_arr) else 0.0
    result.overlap_pairs.sort(key=lambda p: p["similarity"], reverse=True)

    # Per-page report rows (embedded pages)
    for r in emb:
        cid = r.get("_cluster_id")
        result.pages_rows.append(
            {
                "url": r["url"],
                "cluster_id": cid or "",
                "max_similarity": r.get("_max_similarity", 0.0),
                "nearest_url": r.get("_nearest_url") or "",
                "risk": r.get("_risk", ""),
                "suggested_canonical": canon_by_cluster.get(cid, "") if cid else "",
                "hreflang_role": role_map.get(r["url"], ""),
                "hreflang_code": r.get("hreflang_code") or "",
                "word_count": r.get("word_count") or 0,
                "signal_confidence": r.get("signal_confidence") or "",
            }
        )

    dup_n = sum(1 for r in emb if str(r.get("_risk", "")).startswith("duplicate"))
    result.suppressed = suppressed
    result.chained_clusters = chained_n
    result.summary = {
        "embedded": n,
        "overlap_pairs": len(result.overlap_pairs),
        "clusters": len(result.cluster_rows),
        "chained_clusters": chained_n,
        "duplicate_pages": dup_n,
        "suppressed_pairs": suppressed,
        "threshold": threshold,
        "dup_threshold": dup_threshold,
        "threshold_percentile": round(percentile_rank(threshold, nn_arr), 1) if len(nn_arr) else None,
        "dup_threshold_percentile": round(percentile_rank(dup_threshold, nn_arr), 1) if len(nn_arr) else None,
    }
    return result


# --------------------------------------------------------------------------
# Exclusion reasons
# --------------------------------------------------------------------------


def compute_exclusion(row: AnalysisRow) -> str | None:
    """Derive the pairing-exclusion reason for a crawled page (or None if
    eligible).  Mirrors upstream's excluded semantics onto crawler_cli tables.
    """
    if row.get("kind") and row["kind"] != "html":
        return "non-html"
    status = row.get("status")
    if status is not None and int(status) != 200:
        return "non-200"
    if row.get("overall_indexable") is False:
        return "noindex"
    canonical_url = row.get("canonical_url")
    if canonical_url and normalise_url(str(canonical_url)) != normalise_url(str(row["url"])):
        return "canonicalised-elsewhere"
    if row.get("variant_of"):
        return "url-variant"
    return None


# --------------------------------------------------------------------------
# CSV writing
# --------------------------------------------------------------------------

_PAGES_FIELDS = [
    "url",
    "cluster_id",
    "max_similarity",
    "nearest_url",
    "risk",
    "suggested_canonical",
    "hreflang_role",
    "hreflang_code",
    "word_count",
    "signal_confidence",
    "excluded",
]
_PAIRS_FIELDS = ["url_a", "url_b", "similarity", "low_confidence", "sim_percentile"]
_CLUSTER_FIELDS = [
    "cluster_id",
    "size",
    "suggested_canonical",
    "languages",
    "urls",
    "avg_word_count",
    "min_intra_sim",
    "mean_intra_sim",
    "cohesion",
    "chained",
    "cohesion_note",
]
_ISSUE_FIELDS = ["url", "declares_alternate", "hreflang", "issue"]
_VARIANT_FIELDS = ["norm_url", "representative", "variants", "count"]


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _distribution_fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    return seen


def write_reports(
    out_dir: str,
    result: AnalysisResult,
    *,
    excluded_rows: list[AnalysedRow],
    hreflang_issues: list[dict[str, Any]],
    variant_rows: list[VariantReportRow],
    manifest: dict[str, Any] | None = None,
) -> list[str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    pages = list(result.pages_rows) + [
        {
            "url": r["url"],
            "cluster_id": "",
            "max_similarity": "",
            "nearest_url": "",
            "risk": "",
            "suggested_canonical": "",
            "hreflang_role": "",
            "hreflang_code": r.get("hreflang_code") or "",
            "word_count": r.get("word_count") or 0,
            "signal_confidence": r.get("signal_confidence") or "",
            "excluded": r.get("excluded", ""),
        }
        for r in excluded_rows
    ]
    _write_csv(out / "pages.csv", _PAGES_FIELDS, pages)
    _write_csv(out / "overlap_pairs.csv", _PAIRS_FIELDS, result.overlap_pairs)
    _write_csv(out / "clusters.csv", _CLUSTER_FIELDS, result.cluster_rows)
    _write_csv(out / "hreflang_issues.csv", _ISSUE_FIELDS, hreflang_issues)
    _write_csv(out / "url_variants.csv", _VARIANT_FIELDS, variant_rows)

    dist_fields = _distribution_fieldnames(result.distribution_rows) or ["language", "pages"]
    _write_csv(out / "similarity_distribution.csv", dist_fields, result.distribution_rows)

    written = [
        "pages.csv",
        "overlap_pairs.csv",
        "clusters.csv",
        "hreflang_issues.csv",
        "url_variants.csv",
        "similarity_distribution.csv",
    ]
    if manifest is not None:
        (out / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        written.append("run_manifest.json")
    return [str(out / name) for name in written]


def _variant_rows_from_store(raw: list[UrlVariantRow]) -> list[VariantReportRow]:
    """Group store variant rows (url, norm_url, representative) into one row per
    norm_url (representative + variants), for url_variants.csv."""
    by_norm: dict[str, list[UrlVariantRow]] = {}
    for r in raw:
        by_norm.setdefault(r["norm_url"], []).append(r)
    out: list[VariantReportRow] = []
    for norm, members in sorted(by_norm.items()):
        rep = next((m["url"] for m in members if not m.get("representative")), members[0]["url"])
        variants = sorted(m["url"] for m in members if m["url"] != rep)
        out.append(
            {
                "norm_url": norm,
                "representative": rep,
                "variants": " | ".join(variants),
                "count": len(members),
            }
        )
    return out


# --------------------------------------------------------------------------
# Store-driven orchestrator
# --------------------------------------------------------------------------


@dataclass(slots=True)
class IntentOverlapRun:
    result: AnalysisResult
    written: list[str]
    exit_code: int


async def run_intent_overlap(
    store: AsyncpgStore,
    *,
    out_dir: str,
    threshold: float = DEFAULT_THRESHOLD,
    dup_threshold: float = DEFAULT_DUP_THRESHOLD,
    hreflang_mode: str = "suppress",
    primary_lang: str = "en",
    lang_split: bool = True,
    linkage: str = "single",
    fail_on: str | None = None,
    use_ann: bool = False,
    ann_min_pages: int = 10000,
    ann_k: int = 128,
    run_args: dict[str, Any] | None = None,
) -> IntentOverlapRun:
    """Load embeddings + identity from the store, run the analysis, write the
    six CSVs + manifest, and return a run summary (ticket 079)."""
    from datetime import datetime, timezone

    fetched = await store.fetch_analysis_rows()
    rows: list[AnalysedRow] = [{**r, "excluded": compute_exclusion(r)} for r in fetched]
    model = ensure_single_model([r.get("embedding_model") for r in rows if r.get("embedding_model")])

    records = [
        {
            "url": r["url"],
            "vector": r.get("embedding"),
            "group": r.get("hreflang_group"),
            "hreflang_code": r.get("hreflang_code"),
            "word_count": r.get("word_count"),
            "signal_confidence": r.get("signal_confidence"),
        }
        for r in rows
        if r.get("embedding") is not None and r.get("excluded") is None
    ]
    excluded_rows = [r for r in rows if r.get("excluded") is not None]

    result = analyse_embeddings(
        records,
        threshold=threshold,
        dup_threshold=dup_threshold,
        hreflang_mode=hreflang_mode,
        primary_lang=primary_lang,
        lang_split=lang_split,
        linkage=linkage,
        use_ann=use_ann,
        ann_min_pages=ann_min_pages,
        ann_k=ann_k,
    )

    edges = await store.fetch_hreflang_edges()
    issues = reciprocity_issues(edges)
    variant_rows = _variant_rows_from_store(await store.fetch_url_variant_rows())

    summary = dict(result.summary)
    summary.update(
        {
            "pages_total": len(rows),
            "pages_excluded": len(excluded_rows),
            "excluded_by_reason": _count_reasons(excluded_rows),
            "hreflang_issues": len(issues),
            "model": model,
        }
    )
    result.summary = summary

    manifest = None
    if run_args is not None:
        manifest = {
            "version": VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": "intent-overlap",
            "args": run_args,
            "embedding_model": model,
            "summary": summary,
        }

    written = write_reports(
        out_dir,
        result,
        excluded_rows=excluded_rows,
        hreflang_issues=issues,
        variant_rows=variant_rows,
        manifest=manifest,
    )

    exit_code = 0
    if fail_on == "duplicate" and summary.get("duplicate_pages"):
        exit_code = 3
    elif fail_on == "overlap" and summary.get("overlap_pairs"):
        exit_code = 3

    return IntentOverlapRun(result=result, written=written, exit_code=exit_code)


def _count_reasons(excluded_rows: list[AnalysedRow]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in excluded_rows:
        reason = str(r.get("excluded"))
        out[reason] = out.get(reason, 0) + 1
    return out
