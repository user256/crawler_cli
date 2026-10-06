from __future__ import annotations

import pytest

from crawler_cli.empty_anchor_audit import evaluate_empty_anchors


def test_reports_only_empty_anchors_without_meaningful_image_alternatives() -> None:
    audit = evaluate_empty_anchors(
        [
            {
                "source_url": "https://example.test/b",
                "target_url": "https://example.test/one",
                "anchor_text": "  ",
                "linked_image_alt_texts": ["", None],
            },
            {
                "source_url": "https://example.test/a",
                "target_url": "https://example.test/two",
                "anchor_text": None,
                "xpath": "/html/body/a[2]",
                "linked_image_alt_texts": [],
            },
            {
                "source_url": "https://example.test/a",
                "target_url": "https://example.test/three",
                "anchor_text": "   ",
                "linked_image_alt_texts": ["Product image"],
            },
            {
                "source_url": "https://example.test/a",
                "target_url": "https://example.test/four",
                "anchor_text": "Read more",
                "linked_image_alt_texts": [],
            },
        ]
    )

    assert [finding.target_url for finding in audit.findings] == [
        "https://example.test/two",
        "https://example.test/one",
    ]
    assert audit.finding_count == 2
    assert audit.coverage.empty_anchor_count == 3
    assert audit.coverage.empty_anchor_with_meaningful_image_alt_count == 1
    assert audit.coverage.empty_anchor_without_meaningful_image_alt_count == 2
    assert audit.coverage.complete is True


def test_missing_image_alt_facts_are_unknown_not_a_healthy_or_failing_row() -> None:
    audit = evaluate_empty_anchors(
        [
            {
                "source_url": "https://example.test/source",
                "target_url": "https://example.test/target",
                "anchor_text": None,
            },
            {
                "source_url": "https://example.test/source",
                "target_url": "https://example.test/known",
                "anchor_text": "",
                "linked_image_alt_texts": None,
            },
        ]
    )

    assert audit.findings == ()
    assert audit.finding_count == 0
    assert audit.coverage.unknown_image_alt_count == 2
    assert audit.coverage.complete is False
    assert audit.as_dict()["coverage"]["complete"] is False


def test_invalid_records_and_truncation_make_coverage_incomplete() -> None:
    records = [
        {
            "source_url": "https://example.test/source",
            "target_url": f"https://example.test/{index}",
            "anchor_text": "\t",
            "linked_image_alt_texts": [],
        }
        for index in range(2)
    ]
    records.append(
        {
            "source_url": "https://example.test/source",
            "target_url": "https://example.test/invalid",
            "anchor_text": "",
            "linked_image_alt_texts": "not-a-list",
        }
    )

    audit = evaluate_empty_anchors(records, max_findings=1)

    assert audit.finding_count == 2
    assert len(audit.findings) == 1
    assert audit.coverage.invalid_record_count == 1
    assert audit.coverage.findings_truncated is True
    assert audit.coverage.complete is False


def test_rejects_non_positive_finding_limit() -> None:
    with pytest.raises(ValueError, match="max_findings"):
        evaluate_empty_anchors([], max_findings=0)
