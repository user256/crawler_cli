from __future__ import annotations

from crawler_cli.technical_audit import (
    audit_sheet_tables,
    build_technical_audit,
    canonical_hreflang_report,
    metadata_locale_report,
)


def test_metadata_inventory_excludes_ineligible_pages_and_keeps_denominators():
    rows = metadata_locale_report(
        [
            {
                "url": "https://e.test/a",
                "kind": "html",
                "final_status_code": 200,
                "content_extracted": True,
                "overall_indexable": True,
                "challenge": None,
                "title": "",
                "meta_description": "d",
                "h1_tags": "",
                "html_lang": "en",
                "template": "product",
                "canonical_urls_json": [],
                "variant_kind": None,
            },
            {
                "url": "https://e.test/challenge",
                "kind": "html",
                "final_status_code": 200,
                "content_extracted": True,
                "overall_indexable": True,
                "challenge": "captcha",
            },
            {
                "url": "https://e.test/file.pdf",
                "kind": "pdf",
                "final_status_code": 200,
                "content_extracted": True,
                "overall_indexable": True,
            },
            {
                "url": "https://e.test/unknown",
                "kind": "html",
                "final_status_code": 200,
                "content_extracted": True,
                "overall_indexable": None,
            },
        ]
    )
    coverage = rows[0]
    assert coverage["eligible_indexable_count"] == 1
    assert coverage["excluded_by_reason"] == {
        "challenged": 1,
        "non_html": 1,
        "indexability_unknown": 1,
    }
    assert coverage["inventory_complete"] is True
    candidates = rows[1:]
    assert [row["candidate_type"] for row in candidates] == ["missing_title", "missing_h1"]
    assert candidates[1]["visible_content_state"] == "unknown_without_rendered_confirmation"
    assert candidates[0]["sitemap_inclusion"] == "unavailable_not_run_scoped"


def test_metadata_duplicates_are_locale_scoped_and_keep_all_affected_urls():
    def page(url, locale, title):
        return {
            "url": url,
            "kind": "html",
            "final_status_code": 200,
            "content_extracted": True,
            "overall_indexable": True,
            "challenge": None,
            "title": title,
            "meta_description": "same",
            "h1_tags": "Heading",
            "html_lang": locale,
            "canonical_urls_json": [],
            "variant_kind": None,
        }

    result = metadata_locale_report(
        [
            page("https://e.test/en/a?utm_source=secret", "en", "Shared title"),
            page("https://e.test/en/b", "en", " shared   TITLE "),
            page("https://e.test/fr/a", "fr", "Shared title"),
            page("https://e.test/no-locale", None, "Shared title"),
        ]
    )
    duplicates = [row for row in result[1:] if row["candidate_type"].startswith("duplicate_")]
    titles = [row for row in duplicates if row["candidate_type"] == "duplicate_title_same_locale"]
    descriptions = [row for row in duplicates if row["candidate_type"] == "duplicate_description_same_locale"]
    assert len(titles) == 2
    assert {row["url"] for row in titles} == {
        "https://e.test/en/a?utm_source",
        "https://e.test/en/b",
    }
    assert len(descriptions) == 2
    assert all(row["locale"] in {"en", "fr"} for row in duplicates)
    assert titles[0]["query_parameter_names"] == ["utm_source"]
    assert "secret" not in titles[0]["url"]
    assert titles[0]["pagination_parameter_candidates"] == []


def test_complete_metadata_inventory_reports_zero_findings_and_keeps_sheet_denominator():
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={
            "metadata-locale-inventory": [
                {
                    "record_type": "coverage",
                    "inventory_complete": True,
                    "eligible_indexable_count": 12,
                    "eligible_noindex_count": 3,
                    "excluded_count": 2,
                    "excluded_by_reason": {"challenged": 2},
                    "segments": {"True|en|product|clean|declared_self|sitemap_unavailable": 12},
                }
            ]
        },
        run_context={"completion_state": "complete"},
    )
    check = next(row for row in audit["checks"] if row["id"] == "metadata-and-locale")
    assert check["status"] == "pass"
    assert check["eligible_count"] == 12
    assert check["affected_count"] == 0
    coverage_tab = audit_sheet_tables(audit)["Metadata Coverage"]
    assert ["eligible_indexable_count", 12] in coverage_tab
    assert ["excluded_by_reason", '{"challenged": 2}'] in coverage_tab


def test_canonical_report_preserves_channels_and_keeps_uncrawled_target_unknown():
    rows = canonical_hreflang_report(
        [
            {
                "url": "https://e.test/en/page",
                "kind": "html",
                "final_status_code": 200,
                "content_extracted": True,
                "overall_indexable": True,
                "canonical_evidence_json": [
                    {"href": "https://e.test/en/page", "source": "html_head", "well_formed_http_url": True},
                    {"href": "https://other.test/page", "source": "http_header_link", "well_formed_http_url": True},
                ],
                "canonical_urls_json": [],
                "hreflang_json": [
                    {"href": "https://e.test/en/page", "hreflang": "en", "source": "html_head"},
                    {"href": "https://e.test/fr/page?user=private", "hreflang": "fr", "source": "html_head"},
                ],
                "html_lang": "en",
            }
        ]
    )
    types = {row.get("candidate_type") for row in rows[1:]}
    assert "canonical_channel_disagreement" in types
    assert "non_self_canonical_candidate" in types
    assert "hreflang_target_unknown_not_crawled" in types
    unknown = next(row for row in rows if row.get("candidate_type") == "hreflang_target_unknown_not_crawled")
    assert unknown["qualification"] == "not_a_confirmed_defect"
    assert "private" not in unknown["alternate_url"]
    assert rows[0]["sitemap_channel"] == "unavailable_not_in_run_snapshot"


def test_canonical_targets_distinguish_http_error_noindex_and_canonical_chain():
    def page(url, *, status=200, indexable=True, canonicals=None):
        return {
            "url": url,
            "kind": "html",
            "final_status_code": status,
            "content_extracted": status == 200,
            "overall_indexable": indexable,
            "canonical_evidence_json": canonicals or [],
            "canonical_urls_json": [],
            "hreflang_json": [],
            "html_lang": "en",
        }

    targets = ["https://e.test/gone", "https://e.test/noindex", "https://e.test/chain"]
    sources = [
        page(f"https://e.test/source-{i}", canonicals=[{"href": target, "source": "html_head"}])
        for i, target in enumerate(targets)
    ]
    rows = canonical_hreflang_report(
        [
            *sources,
            page(targets[0], status=404, indexable=None),
            page(targets[1], indexable=False),
            page(targets[2], canonicals=[{"href": "https://e.test/final", "source": "html_head"}]),
        ]
    )
    target_states = {
        row["canonical_url"]: row["canonical_target_state"]
        for row in rows
        if row.get("candidate_type") == "non_self_canonical_candidate"
    }
    assert target_states[targets[0]] == "status_404"
    assert target_states[targets[1]] == "noindex_or_unknown"
    assert target_states[targets[2]] == "canonicalized_elsewhere"


def test_hreflang_valid_reciprocal_cluster_passes_and_noindex_source_only_gets_guidance():
    def page(url, locale, links, indexable=True):
        return {
            "url": url,
            "kind": "html",
            "final_status_code": 200,
            "content_extracted": True,
            "overall_indexable": indexable,
            "canonical_evidence_json": [{"href": url, "source": "html_head", "well_formed_http_url": True}],
            "canonical_urls_json": [],
            "hreflang_json": links,
            "html_lang": locale,
        }

    en = "https://e.test/en/page"
    fr = "https://e.test/fr/page"
    result = canonical_hreflang_report(
        [
            page(
                en,
                "en",
                [
                    {"href": en, "hreflang": "en", "source": "html_head"},
                    {"href": fr, "hreflang": "fr", "source": "html_head"},
                ],
            ),
            page(
                fr,
                "fr",
                [
                    {"href": fr, "hreflang": "fr", "source": "html_head"},
                    {"href": en, "hreflang": "en", "source": "html_head"},
                ],
            ),
            page(
                "https://e.test/noindex",
                "en",
                [{"href": "https://e.test/noindex", "hreflang": "bad!", "source": "html_head"}],
                False,
            ),
        ]
    )
    issues = result[1:]
    assert not any(row.get("candidate_type", "").startswith("hreflang_") for row in issues)
    assert [row["candidate_type"] for row in issues] == ["noindex_source_hreflang_guidance"]


def test_audit_is_stable_and_never_calls_candidate_checks_healthy():
    reports = {
        "indexability": [
            {
                "url": "https://example.test/a",
                "html_meta_allows": True,
                "http_header_allows": False,
                "content_extracted": True,
                "directive_evidence": [
                    {"channel": "html_meta", "user_agent": "*", "raw_value": "index", "directives": ["index"]},
                    {
                        "channel": "http_header",
                        "user_agent": "*",
                        "raw_value": "noindex",
                        "directives": ["noindex"],
                    },
                ],
            },
            {
                "url": "https://example.test/b",
                "html_meta_allows": True,
                "http_header_allows": True,
                "content_extracted": True,
                "directive_evidence": [],
            },
        ],
        "tracking-parameter-links": [
            {
                "source_url": "https://example.test/",
                "target_url": "https://example.test/a?utm_source=nav",
                "tracking_parameters": "utm_source",
            }
        ],
        "schema-compatibility": [
            {
                "url": "https://example.test/a",
                "is_valid": False,
                "diagnostic_code": "bad-json",
                "evidence": "{",
                "remediation": "Fix JSON.",
            }
        ],
        "near-duplicates": [],
        "similarity-coverage": [
            {
                "eligible_population": 0,
                "sampled_population": 0,
                "truncated": False,
                "findings_truncated": False,
                "missing_primary_hashes": 0,
            }
        ],
        "authority-coverage": [{"graph_complete": True, "canonical_indexable_population": 0}],
    }
    context = {
        "completion_state": "complete",
        "parsed_html_count": 2,
        "hashed_count": 0,
        "schema_capabilities": {"indexability_evidence_json": True},
    }
    first = build_technical_audit(crawl_run_id="run-1", reports=reports, run_context=context)
    second = build_technical_audit(crawl_run_id="run-1", reports=reports, run_context=context)

    assert first == second
    statuses = {check["id"]: check["status"] for check in first["checks"]}
    assert statuses["indexability-directive-conflicts"] == "finding"
    assert statuses["tracking-parameter-links"] == "finding"
    assert statuses["near-duplicate-content"] == "no_observations"
    assert first["check_registry"]
    assert "canonical-targets" in {item["id"] for item in first["check_registry"]}
    assert len(first["audit_log"]) == 3
    assert first["audit_log"][0]["Evidence Reference"] == "indexability-directive-conflicts"


def test_sheet_tables_only_include_detail_tabs_with_evidence():
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={"tracking-parameter-links": [{"target_url": "https://e.test/?gclid=x"}]},
    )
    tables = audit_sheet_tables(audit)

    assert set(tables) == {"Overview"}
    assert ["Client publication ready", False] in tables["Overview"]


def test_missing_run_context_and_missing_source_are_not_reported_as_passes():
    audit = build_technical_audit(crawl_run_id="run-1", reports={"indexability": []})
    checks = {check["id"]: check for check in audit["checks"]}
    assert checks["indexability-directive-conflicts"]["status"] == "unavailable"
    assert checks["near-duplicate-content"]["status"] == "unavailable"
    assert checks["indexability-directive-conflicts"]["denominator"] is None


def test_similarity_sample_and_authority_graph_gaps_are_partial_not_pass():
    reports = {
        "near-duplicates": [],
        "similarity-coverage": [
            {
                "eligible_population": 6000,
                "sampled_population": 5000,
                "truncated": True,
                "findings_truncated": False,
                "missing_primary_hashes": 0,
            }
        ],
        "internal-authority": [],
        "authority-coverage": [{"graph_complete": False, "canonical_indexable_population": 200}],
    }
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports=reports,
        run_context={"completion_state": "complete", "parsed_html_count": 6000},
    )
    checks = {check["id"]: check for check in audit["checks"]}
    assert checks["near-duplicate-content"]["status"] == "partial"
    assert checks["internal-authority-inventory"]["status"] == "partial"


def test_source_provenance_is_deterministic_and_distinguishes_missing_from_empty():
    reports = {"indexability": []}
    first = build_technical_audit(crawl_run_id="run-1", reports=reports)
    second = build_technical_audit(crawl_run_id="run-1", reports=reports)

    first_coverage = first["source_coverage"]
    second_coverage = second["source_coverage"]
    assert first_coverage == second_coverage
    assert first_coverage["indexability"]["available"] is True
    assert first_coverage["indexability"]["row_count"] == 0
    assert first_coverage["indexability"]["source_digest_sha256"]
    assert first_coverage["image-issues"]["available"] is False
    assert first_coverage["image-issues"]["source_digest_sha256"] is None
    assert first["parser"]
    assert first["structured_data_parser_mode"]


def test_legacy_rows_without_explicit_directive_evidence_are_unavailable():
    audit = build_technical_audit(
        crawl_run_id="run-1",
        reports={
            "indexability": [
                {
                    "url": "https://e.test/",
                    "content_extracted": True,
                    "html_meta_allows": False,
                    "http_header_allows": True,
                }
            ]
        },
        run_context={
            "completion_state": "complete",
            "parsed_html_count": 1,
            "schema_capabilities": {"indexability_evidence_json": True},
        },
    )
    check = next(check for check in audit["checks"] if check["id"] == "indexability-directive-conflicts")
    assert check["status"] == "unavailable"
    assert check["evidence"] == []
