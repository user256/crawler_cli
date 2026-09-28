from __future__ import annotations

import pytest

from crawler_cli.technical_audit_contract import (
    CONTROL_DETECTORS,
    CONTROL_EVIDENCE_GAPS,
    CONTROL_EVIDENCE_SCOPES,
    TECHNICAL_AUDIT_CHECK_CONTRACT,
    project_v3_controls,
)
from crawler_cli.technical_audit_tickets import load_ticket_language, ticket_eligibility

_CONTEXT = {"completion_state": "complete", "snapshot_consistency": "stable"}
_ALL_DETECTORS = sorted({detector for detectors in CONTROL_DETECTORS.values() for detector in detectors})


def _detector(identifier: str, status: str = "pass", evidence=None, *, denominator: int = 10, qualification=None):
    rows = list(evidence or [])
    return {
        "id": identifier,
        "status": status,
        "coverage_state": "complete",
        "affected_count": len(rows),
        "tested_count": denominator,
        "denominator": denominator,
        "qualification": qualification,
        "evidence": rows,
    }


def _controls(detectors):
    return {row["id"]: row for row in project_v3_controls(detectors, run_context=_CONTEXT)}


def _eligible_ids(controls):
    language = load_ticket_language()
    entries = language["checks"]
    return [
        identifier
        for identifier, row in controls.items()
        if row["status"] == "finding" and ticket_eligibility(row, entries[identifier], language)[0]
    ]


def test_one_metadata_finding_yields_at_most_one_ticket_eligible_control():
    missing_titles = [
        {"record_type": "candidate", "candidate_type": "missing_title", "url": f"https://example.test/{index}"}
        for index in range(3)
    ]
    controls = _controls([_detector("metadata-and-locale", "finding", missing_titles)])

    findings = [identifier for identifier, row in controls.items() if row["status"] == "finding"]
    assert findings == ["metadata-basics"]
    assert controls["metadata-basics"]["affected_count"] == 3
    for sibling in ("metadata-duplicates-aliases", "locale-html-lang"):
        assert controls[sibling]["status"] == "partial"
        assert controls[sibling]["evidence"] == []
        assert controls[sibling]["affected_count"] == 0
    assert controls["content-quality"]["status"] == "unavailable"
    assert len(_eligible_ids(controls)) <= 1


def test_each_shared_detector_row_is_scoped_to_exactly_one_control():
    shared = {
        "metadata-and-locale": ["missing_html_lang", "duplicate_title_same_locale", "multiple_h1_markup"],
        "url-variants-and-soft-404": ["soft_404_risk_review", "url_variant_observation"],
        "current-robots-and-sitemaps": ["robots_controls_incomplete", "sitemap_lastmod_review"],
        "canonical-consistency": ["missing_canonical", "non_self_canonical_candidate"],
        "hreflang-consistency": ["missing_hreflang_self_reference", "hreflang_target_not_indexable_200"],
    }
    for detector_id, types in shared.items():
        rows = [{"candidate_type": value, "url": f"https://example.test/{value}"} for value in types]
        controls = _controls([_detector(detector_id, "finding", rows)])
        owners = [
            identifier
            for identifier, row in controls.items()
            if row.get("evidence") and all("detector_id" in item for item in row["evidence"])
        ]
        assert sum(len(controls[owner]["evidence"]) for owner in owners) == len(rows), detector_id
        assert len(owners) == len(types), detector_id


def test_unscoped_detector_rows_block_client_tickets_on_every_fed_control():
    rows = [
        {"candidate_type": "missing_title", "url": "https://example.test/a"},
        {"candidate_type": "new_unmapped_type", "url": "https://example.test/b"},
    ]
    controls = _controls([_detector("metadata-and-locale", "finding", rows)])

    assert controls["metadata-basics"]["status"] == "finding"
    assert controls["metadata-basics"]["affected_count"] == 1
    for identifier in ("metadata-basics", "metadata-duplicates-aliases", "locale-html-lang"):
        assert "unscoped_detector_evidence" in controls[identifier]["qualification"]
        assert controls[identifier]["status"] != "pass"
    assert _eligible_ids(controls) == []


def test_every_pass_requires_every_mapped_detector_present_and_passing():
    all_passing = _controls([_detector(identifier) for identifier in _ALL_DETECTORS])
    for identifier, detectors in CONTROL_DETECTORS.items():
        if identifier in CONTROL_EVIDENCE_GAPS:
            continue
        if not all(detector in _ALL_DETECTORS for detector in detectors):
            continue
        assert all_passing[identifier]["status"] == "pass", identifier
        for detector in detectors:
            without = _controls([_detector(other) for other in _ALL_DETECTORS if other != detector])
            assert without[identifier]["status"] in {"partial", "unavailable"}, (identifier, detector)
            not_passing = _controls(
                [_detector(other, "partial" if other == detector else "pass") for other in _ALL_DETECTORS]
            )
            assert not_passing[identifier]["status"] == "partial", (identifier, detector)


def test_missing_required_detector_blocks_a_finding_from_the_present_one():
    rows = [{"candidate_type": "noindex_source_hreflang_guidance", "url": "https://example.test/fr"}]
    controls = _controls([_detector("hreflang-consistency", "finding", rows)])

    noindex = controls["hreflang-noindex"]
    assert noindex["status"] == "finding"
    assert "required_detector_missing:indexability-directive-conflicts" in noindex["qualification"]
    assert "hreflang-noindex" not in _eligible_ids(controls)


@pytest.mark.parametrize("identifier", sorted(CONTROL_EVIDENCE_GAPS))
def test_evidence_gap_controls_never_pass_or_find(identifier):
    row = {"candidate_type": "render_divergence_review", "url": "https://example.test/"}
    for status in ("pass", "finding"):
        evidence = [row] if status == "finding" else []
        detectors = [_detector(detector, status, evidence) for detector in _ALL_DETECTORS]
        control = _controls(detectors)[identifier]
        assert control["status"] == "unavailable"
        assert control["qualification"] == "contract_evidence_not_collected"
        assert control["evidence"] == []


def test_listed_evidence_gap_controls_are_covered():
    assert {
        "locale-redirects",
        "mobile-rendering-parity",
        "crawl-depth-distribution",
    } <= set(CONTROL_EVIDENCE_GAPS)
    assert not set(CONTROL_EVIDENCE_GAPS) & set(CONTROL_EVIDENCE_SCOPES)
    contract_ids = {row["id"] for row in TECHNICAL_AUDIT_CHECK_CONTRACT}
    assert set(CONTROL_EVIDENCE_SCOPES) <= contract_ids
    for identifier, scopes in CONTROL_EVIDENCE_SCOPES.items():
        assert set(scopes) == set(CONTROL_DETECTORS[identifier]), identifier


def test_merged_denominators_are_not_double_counted():
    controls = _controls(
        [
            _detector(
                "tracking-parameter-links", "finding", [{"url": "https://example.test/?utm_source=x"}], denominator=40
            ),
            _detector(
                "parameterized-canonical-links",
                "finding",
                [
                    {
                        "candidate_type": "internally_linked_noncanonical_parameter_url",
                        "url": "https://example.test/?s=1",
                    }
                ],
                denominator=40,
                qualification="analyst_only",
            ),
        ]
    )

    row = controls["parameter-and-faceted-controls"]
    assert row["denominator"] == 40
    assert row["tested_count"] == 40
    assert row["affected_count"] == 2
    assert "combined_v2_detectors" in row["qualification"]
    assert "parameter-and-faceted-controls" not in _eligible_ids(controls)

    hreflang = _controls(
        [
            _detector("hreflang-consistency", denominator=25),
            _detector("indexability-directive-conflicts", denominator=30),
        ]
    )["hreflang-noindex"]
    assert hreflang["status"] == "pass"
    assert hreflang["denominator"] == 30
    assert hreflang["tested_count"] == 30


def test_new_qualification_codes_are_documented_and_blocking():
    language = load_ticket_language()
    blocked = set(language["ticket_eligibility"]["blocked_qualifications"])
    assert {"unscoped_detector_evidence", "required_detector_missing", "combined_v2_detectors"} <= blocked
    for code in (
        "unscoped_detector_evidence",
        "required_detector_missing",
        "detector_finding_outside_control_scope",
        "contract_evidence_not_collected",
    ):
        assert code in language["qualification_text"]


def test_evidence_gap_controls_never_request_client_input():
    language = load_ticket_language()
    rows = project_v3_controls([], run_context={})
    locale = next(row for row in rows if row["id"] == "locale-redirects")
    assert locale["status"] == "unavailable"
    assert language["checks"]["locale-redirects"].get("unavailable_ticket")
    assert ticket_eligibility(locale, language["checks"]["locale-redirects"], language) == (
        False,
        "collector not built",
    )
