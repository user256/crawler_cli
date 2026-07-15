"""Ticket 107: self-contained HTML cluster report from report_data.json."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from crawler_cli.report_html import render_report_html, write_report_html


def _sample_report() -> dict:
    return {
        "version": "1.0.0",
        "generated_at": "2026-07-15T00:00:00+00:00",
        "embedding_model": "M",
        "thresholds": {"threshold": 0.85, "dup_threshold": 0.92, "thin_signature_words": 88},
        "projection": {"method": "pca", "dims": 2, "seed": 42},
        "off_topic": {"percentile": 5.0, "threshold": 0.1},
        "summary": {
            "embedded": 3,
            "overlap_pairs": 1,
            "clusters": 1,
            "duplicate_pages": 0,
            "threshold": 0.85,
        },
        "pages": [
            {
                "url": "https://ex.com/videos",
                "cluster_id": "C0000",
                "coords": [0.1, 0.2],
                "risk": "thin content — add distinguishing content",
                "excluded": None,
                "url_class": None,
                "variant_kind": None,
                "word_count": 900,
                "signature_words": 77,
                "main_text_words": 50,
                "main_text_chars": 200,
                "signature_chars": 400,
                "section": "/videos",
                "signal_confidence": "high",
                "max_similarity": 1.0,
                "nearest_url": "https://ex.com/videos/faqs",
                "suggested_canonical": "review — thin content; add distinguishing content",
                "centroid_similarity": 0.5,
                "off_topic": False,
            },
            {
                "url": "https://ex.com/videos/faqs",
                "cluster_id": "C0000",
                "coords": [0.12, 0.21],
                "risk": "thin content — add distinguishing content",
                "excluded": None,
                "url_class": None,
                "variant_kind": None,
                "word_count": 850,
                "signature_words": 77,
                "main_text_words": 40,
                "main_text_chars": 180,
                "signature_chars": 400,
                "section": "/videos",
                "signal_confidence": "high",
                "max_similarity": 1.0,
                "nearest_url": "https://ex.com/videos",
                "suggested_canonical": "review — thin content; add distinguishing content",
                "centroid_similarity": 0.51,
                "off_topic": False,
            },
            {
                "url": "https://ex.com/the-team?type=x",
                "cluster_id": "C0000",
                "coords": [0.3, 0.4],
                "risk": "",
                "excluded": None,
                "url_class": "parameterised",
                "variant_kind": None,
                "word_count": 100,
                "signature_words": 90,
                "main_text_words": 80,
                "main_text_chars": 400,
                "signature_chars": 500,
                "section": "/the-team",
                "signal_confidence": "high",
                "max_similarity": 0.0,
                "nearest_url": None,
                "suggested_canonical": None,
                "centroid_similarity": 0.4,
                "off_topic": False,
            },
            {
                "url": "https://ex.com/page/amp",
                "cluster_id": None,
                "coords": None,
                "risk": "",
                "excluded": "amp-variant",
                "url_class": None,
                "variant_kind": "amp",
                "word_count": 10,
                "signature_words": None,
                "main_text_words": None,
                "main_text_chars": None,
                "signature_chars": None,
                "section": "/page",
                "signal_confidence": None,
                "max_similarity": None,
                "nearest_url": None,
                "suggested_canonical": None,
                "centroid_similarity": None,
                "off_topic": False,
            },
        ],
        "pairs": [
            {
                "url_a": "https://ex.com/videos",
                "url_b": "https://ex.com/videos/faqs",
                "similarity": 1.0,
                "relation": "parent-child",
                "pair_class": None,
                "thin": "both",
                "sim_percentile": 99.0,
            }
        ],
        "clusters": [
            {
                "id": "C0000",
                "size": 3,
                "urls": [
                    "https://ex.com/videos",
                    "https://ex.com/videos/faqs",
                    "https://ex.com/the-team?type=x",
                ],
                "suggested_canonical": "review — thin content; add distinguishing content",
                "suggested_action": "review — thin content; add distinguishing content",
                "relation": "parent-child",
                "thin": True,
                "time_sequenced": False,
                "label": "/videos: personal, injury",
            }
        ],
    }


def test_render_report_html_embeds_json_and_dom_anchors():
    html = render_report_html(_sample_report())
    assert 'id="report-data"' in html
    assert 'type="application/json"' in html
    assert 'id="map"' in html
    assert 'id="filters"' in html
    assert 'id="summary-card"' in html
    assert "<noscript>" in html
    assert "https://ex.com/videos" in html
    # No CDN / network resource hints in the shell (data URLs in JSON are fine).
    assert "cdn." not in html.lower()
    assert "<script src=" not in html
    assert "<link " not in html
    assert "https://cdn" not in html.lower()


def test_embedded_json_round_trips():
    report = _sample_report()
    html = render_report_html(report)
    match = re.search(
        r'<script type="application/json" id="report-data">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match
    parsed = json.loads(match.group(1))
    assert parsed == report


def test_write_report_html_and_cli(tmp_path):
    data_path = tmp_path / "report_data.json"
    data_path.write_text(json.dumps(_sample_report()), encoding="utf-8")
    out = write_report_html(data_path, tmp_path / "report.html")
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert 'id="report-data"' in text

    from crawler_cli.__main__ import _build_parser, _run_render_report

    parser = _build_parser()
    args = parser.parse_args(["render-report", "--data", str(data_path), "-o", str(tmp_path / "from-cli.html")])
    assert args.command == "render-report"
    assert _run_render_report(args) == 0
    assert (tmp_path / "from-cli.html").exists()


def test_cli_html_report_implies_json_flag_wiring():
    from crawler_cli.__main__ import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["intent-overlap", "--html-report"])
    assert args.html_report is True


@pytest.mark.integration
def test_render_thompsons_report_if_present(tmp_path):
    """Optional integration: render a real thompsons report_data.json when available."""
    candidates = [
        Path("/home/user256/GitRepos/crawler_cli/runs/thompsons-scotland-20260715/report_data.json"),
        Path("runs/thompsons-scotland-20260715/report_data.json"),
    ]
    src = next((p for p in candidates if p.exists()), None)
    if src is None:
        pytest.skip("thompsons report_data.json not present")
    out = write_report_html(src, tmp_path / "thompsons.html")
    html = out.read_text(encoding="utf-8")
    assert 'id="map"' in html
    assert "/videos" in html
    assert out.stat().st_size < 12_000_000
