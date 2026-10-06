from __future__ import annotations

import json

import pytest

from crawler_cli.technical_audit_inputs import (
    AuditInputError,
    load_inventory_interaction_evidence,
    load_search_evidence,
)


def test_search_evidence_requires_dates_and_classifies_the_three_material_outcomes(tmp_path):
    evidence = tmp_path / "search.json"
    evidence.write_text(
        json.dumps(
            [
                {
                    "url": "https://example.test/fr/game",
                    "source": "url_inspection",
                    "export_date": "2026-09-28",
                    "index_status": "Excluded",
                    "google_canonical": "https://example.test/game",
                    "user_canonical": "https://example.test/fr/game",
                    "priority_url": True,
                    "impressions": 0,
                }
            ]
        )
    )

    [record] = load_search_evidence(evidence)

    assert record["is_issue"] is True
    assert "Excluded" in str(record["issue_reason"])
    assert "canonical differs" in str(record["issue_reason"])
    assert "zero impressions" in str(record["issue_reason"])

    evidence.write_text(json.dumps([{"url": "https://example.test/", "source": "search_console"}]))
    with pytest.raises(AuditInputError, match="export_date"):
        load_search_evidence(evidence)


def test_inventory_interaction_requires_a_before_and_after_count(tmp_path):
    evidence = tmp_path / "interaction.json"
    evidence.write_text(
        json.dumps(
            [
                {
                    "source_url": "https://example.test/games",
                    "action": "Load more",
                    "initial_document_url_count": 24,
                    "post_interaction_document_url_count": 48,
                    "completed": True,
                }
            ]
        )
    )

    [record] = load_inventory_interaction_evidence(evidence)

    assert record["requires_interaction"] is True
    assert record["initial_document_url_count"] == 24

    evidence.write_text(json.dumps([{"source_url": "https://example.test/games", "action": "Load more"}]))
    with pytest.raises(AuditInputError, match="initial_document_url_count"):
        load_inventory_interaction_evidence(evidence)
