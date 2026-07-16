"""Ticket 106: report_data.json export — envelope, projection, labels, size floor."""

from __future__ import annotations

import json

import pytest

np = pytest.importorskip("numpy")

from crawler_cli.intent_overlap import (  # noqa: E402
    analyse_embeddings,
    build_report_data,
    derive_cluster_label,
    longest_common_path_prefix,
    project_embeddings,
    run_intent_overlap,
    write_reports,
)


def _unit(vec):
    v = np.asarray(vec, dtype=np.float32)
    return (v / np.linalg.norm(v)).tolist()


def _rec(url, vec, *, wc=100, sig=None, conf="high"):
    return {
        "url": url,
        "vector": _unit(vec),
        "group": None,
        "hreflang_code": "en",
        "word_count": wc,
        "main_text": "word " * 20 if sig is None else None,
        "signal_confidence": conf,
        "url_class": None,
        "signature_model_input": sig or ("title h1 meta " + "body " * 40),
    }


class FakeAnalysisStore:
    def __init__(self, rows):
        self._rows = rows

    async def fetch_analysis_rows(self):
        return [dict(r) for r in self._rows]

    async def fetch_hreflang_edges(self):
        return []

    async def fetch_url_variant_rows(self):
        return []

    async def classify_amp_variants(self):
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
        "variant_kind": None,
        "hreflang_group": None,
        "hreflang_code": None,
        "word_count": 100,
        "main_text": "hello world " * 30,
        "signal_confidence": "high",
        "signature_model_input": "title compensation claims scotland " + "body " * 50,
        "embedding": _unit(vec),
        "embedding_model": "M",
    }
    row.update(over)
    return row


def test_project_embeddings_pca_fallback_is_deterministic():
    vecs = np.asarray([_unit([1, 0, 0]), _unit([0.9, 0.1, 0]), _unit([0, 1, 0])], dtype=np.float32)
    a, meta_a = project_embeddings(vecs, seed=7)
    b, meta_b = project_embeddings(vecs, seed=7)
    assert meta_a["method"] in {"pca", "umap"}
    assert meta_a == meta_b
    assert a == b
    assert all(len(c) == 2 for c in a)


def test_longest_common_path_prefix_and_cluster_label():
    urls = [
        "https://ex.com/videos/faqs",
        "https://ex.com/videos/client-testimonials",
        "https://ex.com/videos/tv-adverts",
    ]
    assert longest_common_path_prefix(urls) == "/videos"
    label = derive_cluster_label(
        urls,
        [
            "videos faqs personal injury solicitors scotland",
            "videos testimonials client personal injury scotland",
            "videos tv adverts personal injury solicitors",
        ],
    )
    assert label.startswith("/videos")
    assert "personal" in label or "injury" in label or "scotland" in label


def test_build_report_data_envelope_and_exclusion_without_coords(tmp_path):
    recs = [
        _rec("https://a.com/videos/a", [1.0, 0.0, 0.0], sig="videos hub personal injury scotland"),
        _rec("https://a.com/videos/b", [0.99, 0.01, 0.0], sig="videos category personal injury scotland"),
        _rec("https://a.com/other", [0.0, 1.0, 0.0], sig="unrelated employment law guide scotland"),
    ]
    res = analyse_embeddings(recs, lang_split=False, threshold=0.85, dup_threshold=0.92)
    excluded = [
        {
            "url": "https://a.com/amp-page",
            "excluded": "amp-variant",
            "variant_kind": "amp",
            "word_count": 10,
            "main_text": None,
            "signature_model_input": None,
            "signal_confidence": "low",
        }
    ]
    report = build_report_data(
        res,
        excluded_rows=excluded,
        embedding_model="M",
        thresholds={"threshold": 0.85, "dup_threshold": 0.92, "thin_signature_words": 88},
        generated_at="2026-07-15T00:00:00+00:00",
        projection_seed=42,
    )
    assert report["version"] == "1.0.0"
    assert report["generated_at"] == "2026-07-15T00:00:00+00:00"
    assert report["embedding_model"] == "M"
    assert set(report["thresholds"]) >= {"threshold", "dup_threshold", "thin_signature_words"}
    assert report["projection"]["seed"] == 42
    assert report["projection"]["method"] in {"pca", "umap", "trivial"}
    assert "pages" in report and "pairs" in report and "clusters" in report

    embedded = [p for p in report["pages"] if p["excluded"] is None]
    excluded_pages = [p for p in report["pages"] if p["excluded"] is not None]
    assert len(embedded) == 3
    assert all(p["coords"] is not None and len(p["coords"]) == 2 for p in embedded)
    assert all(p["centroid_similarity"] is not None for p in embedded)
    assert "main_text_words" in embedded[0]
    assert "main_text_chars" in embedded[0]
    assert "signature_chars" in embedded[0]
    assert "signature_words" in embedded[0]
    assert excluded_pages and excluded_pages[0]["coords"] is None
    assert excluded_pages[0]["excluded"] == "amp-variant"
    assert excluded_pages[0]["variant_kind"] == "amp"
    assert excluded_pages[0]["main_text_words"] is None  # missing evidence ≠ 0

    # Determinism: same seed → identical JSON payload.
    again = build_report_data(
        res,
        excluded_rows=excluded,
        embedding_model="M",
        thresholds={"threshold": 0.85, "dup_threshold": 0.92, "thin_signature_words": 88},
        generated_at="2026-07-15T00:00:00+00:00",
        projection_seed=42,
    )
    assert json.dumps(report, sort_keys=True) == json.dumps(again, sort_keys=True)

    written = write_reports(
        str(tmp_path),
        res,
        excluded_rows=excluded,
        hreflang_issues=[],
        variant_rows=[],
        json_report=True,
        embedding_model="M",
        projection_seed=42,
    )
    assert any(p.endswith("report_data.json") for p in written)
    disk = json.loads((tmp_path / "report_data.json").read_text())
    assert disk["projection"]["seed"] == 42
    assert len(disk["pages"]) == 4


def test_json_pair_size_floor_filters_low_similarity_pairs():
    recs = [
        _rec("https://a.com/1", [1.0, 0.0, 0.0]),
        _rec("https://a.com/2", [1.0, 0.0, 0.0]),
        _rec("https://a.com/3", [0.9, 0.1, 0.0]),
    ]
    res = analyse_embeddings(recs, lang_split=False, threshold=0.85, dup_threshold=0.99)
    assert res.overlap_pairs  # at least the near-dup pair
    report = build_report_data(
        res,
        excluded_rows=[],
        embedding_model="M",
        thresholds={"threshold": 0.85, "dup_threshold": 0.99, "thin_signature_words": 88},
        json_min_similarity=0.99,
        size_floor_pages=1,  # force floor for this tiny fixture
        generated_at="2026-07-15T00:00:00+00:00",
    )
    assert report["pairs_truncated"] is True
    assert all(float(p["similarity"]) >= 0.99 for p in report["pairs"])


@pytest.mark.asyncio
async def test_run_intent_overlap_json_report_flag(tmp_path):
    rows = [
        _store_row("https://a.com/1", [1.0, 0.0, 0.0]),
        _store_row("https://a.com/2", [0.95, 0.05, 0.0]),
        _store_row(
            "https://a.com/noindex",
            [0.0, 1.0, 0.0],
            overall_indexable=False,
            embedding=None,
        ),
    ]
    store = FakeAnalysisStore(rows)
    run = await run_intent_overlap(
        store,
        out_dir=str(tmp_path),
        lang_split=False,
        json_report=True,
        projection_seed=11,
        run_args={"json_report": True},
    )
    assert (tmp_path / "report_data.json").exists()
    data = json.loads((tmp_path / "report_data.json").read_text())
    assert data["projection"]["seed"] == 11
    assert any(p["excluded"] == "noindex" and p["coords"] is None for p in data["pages"])
    assert any(p["coords"] is not None for p in data["pages"])
    assert "report_data.json" in {p.split("/")[-1] for p in run.written}


def test_cli_json_report_flags():
    from crawler_cli.__main__ import _build_parser

    parser = _build_parser()
    args = parser.parse_args(
        ["intent-overlap", "--json-report", "--json-min-similarity", "0.9", "--projection-seed", "3"]
    )
    assert args.json_report is True
    assert args.json_min_similarity == 0.9
    assert args.projection_seed == 3
