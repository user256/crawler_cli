"""Deterministic technical-audit projection over a stored crawl run.

This module deliberately separates facts that can be derived from one saved
``crawler_cli`` run from live checks and SEO judgement. A control without its
required evidence is therefore reported as ``unavailable`` rather than as a
claim that a check is healthy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json

from .schema import JSON_LD_PARSER_MODE, _PARSER


TECHNICAL_AUDIT_SCHEMA_VERSION = "crawler-cli/technical-audit/3"
TECHNICAL_AUDIT_RULESET_VERSION = "technical-audit-rules/2"

# The report names are run-scoped and have no dependency on a changing live
# endpoint.  Keep this list explicit so additions are intentional and appear
# in the audit coverage matrix.
TECHNICAL_AUDIT_REPORTS = (
    "orphans",
    "indexability",
    "redirect-chains",
    "schema-compatibility",
    "image-issues",
    "internal-link-quality",
    "tracking-parameter-links",
    "near-duplicates",
    "internal-authority",
    "locale-content-alignment",
    "render-url-candidates",
    "render-attempts",
    "stored-html",
    "metadata-duplicates",
    "nonhtml-search-assets",
    "hreflang-validation",
    "semantic-html",
    "profile-indexability-pages",
    "soft404-error-routes",
    "discovery-source-provenance",
    "inventory-interactions",
    "supplied-search-evidence",
)

# This is the code representation of the table in
# skills/technical-seo-audit/SKILL.md. Every invocation emits these IDs in this
# order. Static support metadata is deliberately separate from the per-run
# result: an unimplemented collector still produces an explicit unavailable
# row instead of vanishing from checks[].
TECHNICAL_AUDIT_CHECK_CONTRACT = (
    {
        "id": "audit-run-integrity",
        "title": "Audit run integrity",
        "detail_sheet": "Run integrity",
        "required_evidence": "crawl/job metadata, run ID, timestamps, scope and counts",
        "owner_ticket": "183",
    },
    {
        "id": "audit-collection-safeguards",
        "title": "Collection safeguards",
        "detail_sheet": "Collection safeguards",
        "required_evidence": "collection configuration and event evidence",
        "owner_ticket": "224",
    },
    {
        "id": "discovery-source-provenance",
        "title": "Discovery-source provenance",
        "detail_sheet": "Discovery sources",
        "required_evidence": "run-scoped discovery-source evidence",
        "owner_ticket": "228",
    },
    {
        "id": "response-status-and-redirect-history",
        "title": "Response status and redirects",
        "detail_sheet": "Response and redirects",
        "required_evidence": "response and redirect evidence",
        "owner_ticket": "218",
    },
    {
        "id": "internal-link-targets",
        "title": "Internal link targets",
        "detail_sheet": "Internal link failures",
        "required_evidence": "run-scoped link graph and destination evidence",
        "owner_ticket": "186",
    },
    {
        "id": "external-link-integrity",
        "title": "External link integrity",
        "detail_sheet": "External link rechecks",
        "required_evidence": "explicit external-link recheck evidence",
        "owner_ticket": "211",
    },
    {
        "id": "orphan-candidates",
        "title": "Orphan-page candidates",
        "detail_sheet": "Orphan candidates",
        "required_evidence": "run-scoped link and discovery evidence",
        "owner_ticket": "222",
    },
    {
        "id": "crawl-depth-distribution",
        "title": "Crawl-depth distribution",
        "detail_sheet": "Crawl depth",
        "required_evidence": "root set and run-scoped graph",
        "owner_ticket": "228",
    },
    {
        "id": "internal-authority",
        "title": "Internal authority",
        "detail_sheet": "Internal authority",
        "required_evidence": "run-scoped internal graph and declared calculation",
        "owner_ticket": "187",
    },
    {
        "id": "image-markup",
        "title": "Image markup",
        "detail_sheet": "Image issues",
        "required_evidence": "raw or rendered image markup",
        "owner_ticket": "210",
    },
    {
        "id": "image-resource-delivery",
        "title": "Image resource delivery",
        "detail_sheet": "Image resources",
        "required_evidence": "resource and performance evidence",
        "owner_ticket": "210",
    },
    {
        "id": "url-host-and-variants",
        "title": "URL host and variants",
        "detail_sheet": "URL variants",
        "required_evidence": "crawl URLs, redirects, canonicals and link targets",
        "owner_ticket": "193",
    },
    {
        "id": "nonproduction-https",
        "title": "Non-production and HTTPS",
        "detail_sheet": "Host and HTTPS",
        "required_evidence": "host, response, robots and indexability evidence",
        "owner_ticket": "202",
    },
    {
        "id": "robots-controls",
        "title": "Robots controls",
        "detail_sheet": "Robots",
        "required_evidence": "current robots fetch and crawl evidence",
        "owner_ticket": "192",
    },
    {
        "id": "sitemap-integrity",
        "title": "Sitemap integrity",
        "detail_sheet": "Sitemaps",
        "required_evidence": "current sitemap fetches and crawl evidence",
        "owner_ticket": "192",
    },
    {
        "id": "rendered-robots-links",
        "title": "Rendered robots links",
        "detail_sheet": "Rendered robots links",
        "required_evidence": "initial raw/rendered links plus an explicit pre/post-interaction inventory capture",
        "owner_ticket": "205",
    },
    {
        "id": "indexability-segmentation",
        "title": "Indexability segmentation",
        "detail_sheet": "Index conflicts",
        "required_evidence": "stored page directives and responses",
        "owner_ticket": "184",
    },
    {
        "id": "crawl-waste-url-families",
        "title": "Crawl-waste URL families",
        "detail_sheet": "URL families",
        "required_evidence": "URL-family analysis with denominators",
        "owner_ticket": "220",
    },
    {
        "id": "parameter-and-faceted-controls",
        "title": "Parameter and faceted controls",
        "detail_sheet": "Tracking parameters",
        "required_evidence": "link, canonical, indexability and URL-family evidence",
        "owner_ticket": "193",
    },
    {
        "id": "soft404-error-routes",
        "title": "Soft 404 and error routes",
        "detail_sheet": "Soft 404s",
        "required_evidence": "response, title/body and template evidence",
        "owner_ticket": "193",
    },
    {
        "id": "metadata-basics",
        "title": "Metadata basics",
        "detail_sheet": "Metadata",
        "required_evidence": "metadata inventory",
        "owner_ticket": "190",
    },
    {
        "id": "metadata-duplicates-aliases",
        "title": "Metadata duplicates and aliases",
        "detail_sheet": "Duplicate metadata",
        "required_evidence": "metadata, canonical and alias evidence",
        "owner_ticket": "229",
    },
    {
        "id": "content-quality",
        "title": "Content quality",
        "detail_sheet": "Content quality",
        "required_evidence": "extracted-content evidence and declared thresholds",
        "owner_ticket": "190",
    },
    {
        "id": "locale-html-lang",
        "title": "Locale HTML language",
        "detail_sheet": "Locale language",
        "required_evidence": "HTML lang, hreflang context and run-scoped primary-content signatures",
        "owner_ticket": "221",
    },
    {
        "id": "near-duplicate-content",
        "title": "Near-duplicate content",
        "detail_sheet": "Near duplicates",
        "required_evidence": "content hashes, similarity evidence and comparison population",
        "owner_ticket": "229",
    },
    {
        "id": "canonical-declarations",
        "title": "Canonical declarations",
        "detail_sheet": "Canonicals",
        "required_evidence": "raw HTML canonical inventory",
        "owner_ticket": "191",
    },
    {
        "id": "canonical-target-validation",
        "title": "Canonical target validation",
        "detail_sheet": "Canonical targets",
        "required_evidence": "canonical target and response/indexability evidence",
        "owner_ticket": "231",
    },
    {
        "id": "hreflang-html-http",
        "title": "HTML and HTTP hreflang",
        "detail_sheet": "Hreflang",
        "required_evidence": "hreflang inventory and target evidence",
        "owner_ticket": "191",
    },
    {
        "id": "hreflang-sitemap",
        "title": "Sitemap hreflang",
        "detail_sheet": "Sitemap hreflang",
        "required_evidence": "sitemap extension inventory and target evidence",
        "owner_ticket": "164",
    },
    {
        "id": "hreflang-noindex",
        "title": "Hreflang noindex conflicts",
        "detail_sheet": "Hreflang noindex",
        "required_evidence": "hreflang, canonical and indexability evidence",
        "owner_ticket": "206",
    },
    {
        "id": "locale-redirects",
        "title": "Locale redirects",
        "detail_sheet": "Locale redirects",
        "required_evidence": "authorised geo/locale probe evidence",
        "owner_ticket": "194",
    },
    {
        "id": "schema-parser-diagnostics",
        "title": "Schema parser diagnostics",
        "detail_sheet": "Schema diagnostics",
        "required_evidence": "structured-data parser evidence",
        "owner_ticket": "214",
    },
    {
        "id": "structured-data-feature-rules",
        "title": "Structured-data feature rules",
        "detail_sheet": "Structured data",
        "required_evidence": "typed structured-data evidence and documented rule set",
        "owner_ticket": "232",
    },
    {
        "id": "rendered-indexing-parity",
        "title": "Rendered indexing parity",
        "detail_sheet": "Rendered parity",
        "required_evidence": "paired raw/rendered evidence",
        "owner_ticket": "194",
    },
    {
        "id": "mobile-rendering-parity",
        "title": "Mobile rendering parity",
        "detail_sheet": "Mobile rendering",
        "required_evidence": "explicit mobile render evidence",
        "owner_ticket": "233",
    },
    {
        "id": "critical-resource-impact",
        "title": "Critical resource impact",
        "detail_sheet": "Critical resources",
        "required_evidence": "render trace and resource evidence",
        "owner_ticket": "233",
    },
    {
        "id": "nonhtml-search-assets",
        "title": "Non-HTML search assets",
        "detail_sheet": "Non-HTML assets",
        "required_evidence": "supplied or collected asset inventory",
        "owner_ticket": "194",
    },
    {
        "id": "performance-distribution",
        "title": "Performance distribution",
        "detail_sheet": "Performance",
        "required_evidence": "performance samples, percentiles and denominators",
        "owner_ticket": "196",
    },
    {
        "id": "conditional-cache-behaviour",
        "title": "Conditional cache behaviour",
        "detail_sheet": "Conditional requests",
        "required_evidence": "ETag/Last-Modified and conditional-request evidence",
        "owner_ticket": "235",
    },
    {
        "id": "validated-bot-log-analysis",
        "title": "Validated bot-log analysis",
        "detail_sheet": "Bot logs",
        "required_evidence": "supplied logs with verified bot identity",
        "owner_ticket": "196",
    },
    {
        "id": "supplied-search-evidence",
        "title": "Supplied search evidence",
        "detail_sheet": "Supplied search evidence",
        "required_evidence": "dated Search Console performance/indexing and URL Inspection records",
        "owner_ticket": "204",
    },
    {
        "id": "recipient-action-eligibility",
        "title": "Recipient action eligibility",
        "detail_sheet": "Recipient actions",
        "required_evidence": "audit finding records and supplied context",
        "owner_ticket": "227",
    },
    {
        "id": "healthy-overview",
        "title": "Healthy overview",
        "detail_sheet": "Healthy controls",
        "required_evidence": "qualified pass or not-applicable rows",
        "owner_ticket": "227",
    },
    {
        "id": "artifact-validation",
        "title": "Artifact validation",
        "detail_sheet": "Artifact validation",
        "required_evidence": "artifact validation evidence",
        "owner_ticket": "198",
    },
)

_IMPLEMENTED_CHECK_REPORTS = {
    "indexability-segmentation": ("indexability", "stored-html"),
    "internal-link-targets": ("internal-link-quality",),
    "orphan-candidates": ("orphans",),
    "response-status-and-redirect-history": ("redirect-chains",),
    "parameter-and-faceted-controls": ("tracking-parameter-links",),
    "near-duplicate-content": ("near-duplicates",),
    "schema-parser-diagnostics": ("schema-compatibility",),
    "image-markup": ("image-issues",),
    "internal-authority": ("internal-authority",),
    "metadata-basics": ("stored-html",),
    "metadata-duplicates-aliases": ("metadata-duplicates",),
    "locale-html-lang": ("locale-content-alignment",),
    "canonical-declarations": ("stored-html",),
    "canonical-target-validation": ("stored-html",),
    "soft404-error-routes": ("soft404-error-routes",),
    "discovery-source-provenance": ("discovery-source-provenance",),
    "hreflang-html-http": ("hreflang-validation",),
    "hreflang-noindex": ("hreflang-validation",),
    "nonhtml-search-assets": ("nonhtml-search-assets",),
    "rendered-robots-links": ("render-url-candidates", "render-attempts", "inventory-interactions"),
    "supplied-search-evidence": ("supplied-search-evidence",),
}

TECHNICAL_AUDIT_LEGACY_CHECK_ID_ALIASES = {
    "indexability-directive-conflicts": "indexability-segmentation",
    "internal-link-failures": "internal-link-targets",
    "tracking-parameter-links": "parameter-and-faceted-controls",
    "redirect-chains": "response-status-and-redirect-history",
    "schema-parser-defects": "schema-parser-diagnostics",
    "image-markup-candidates": "image-markup",
    "internal-authority-inventory": "internal-authority",
    "parameterized-canonical-links": "parameter-and-faceted-controls",
    "feature-specific-structured-data": "structured-data-feature-rules",
    "performance-and-conditional-requests": "conditional-cache-behaviour",
    "metadata-and-locale": "locale-html-lang",
    "canonical-consistency": "canonical-target-validation",
    "hreflang-consistency": "hreflang-html-http",
    "current-robots-and-sitemaps": "sitemap-integrity",
    "url-variants-and-soft-404": "url-host-and-variants",
    "rendered-mobile-and-resource-evidence": "rendered-indexing-parity",
}

TECHNICAL_AUDIT_CHECK_REGISTRY = tuple(
    {
        **item,
        "support_state": "implemented" if item["id"] in _IMPLEMENTED_CHECK_REPORTS else "not_implemented",
        "source": item["required_evidence"],
    }
    for item in TECHNICAL_AUDIT_CHECK_CONTRACT
)


def build_technical_audit(
    *,
    crawl_run_id: str,
    reports: Mapping[str, Sequence[Mapping[str, object]]],
    run_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build a stable audit payload from run-scoped report rows.

    The caller owns collection.  Keeping classification pure makes an audit
    reproducible from a saved report fixture and makes it safe to test without
    a database or network connection.
    """

    rows = {name: [dict(row) for row in reports.get(name, ())] for name in TECHNICAL_AUDIT_REPORTS}
    source_coverage = {}
    for name in TECHNICAL_AUDIT_REPORTS:
        source_rows = rows[name]
        encoded = json.dumps(source_rows, sort_keys=True, separators=(",", ":"), default=str).encode()
        source_coverage[name] = {
            "available": name in reports,
            "row_count": len(source_rows),
            "source_digest_sha256": hashlib.sha256(encoded).hexdigest() if name in reports else None,
        }
    context = dict(run_context or {})
    parser_versions = {"beautifulsoup4": _package_version("beautifulsoup4")}
    if _PARSER == "lxml":
        parser_versions["lxml"] = _package_version("lxml")
    parsed_html_count = _optional_int(context.get("parsed_html_count"))
    hashed_count = _optional_int(context.get("hashed_count"))
    completion_state = str(context.get("completion_state", "unavailable"))

    indexability_rows = [row for row in rows["indexability"] if row.get("content_extracted") is True]
    indexability_conflicts = [
        row
        for row in indexability_rows
        if row.get("html_meta_allows") is not None
        and row.get("http_header_allows") is not None
        and row.get("html_meta_allows") != row.get("http_header_allows")
    ]
    schema_defects = [row for row in rows["schema-compatibility"] if row.get("is_valid") is False]
    link_failures = _link_target_failures(rows["internal-link-quality"])
    locale_signature_count = _optional_int(context.get("locale_signature_count"))
    locale_alignment = rows["locale-content-alignment"]
    interaction_rows = rows["inventory-interactions"]
    inventory_issues = [
        row
        for row in interaction_rows
        if row.get("requires_interaction") is True
        or (_optional_int(row.get("post_interaction_document_url_count")) or 0)
        > (_optional_int(row.get("initial_document_url_count")) or 0)
    ]
    search_records = rows["supplied-search-evidence"]
    search_issues = [row for row in search_records if row.get("is_issue") is True]
    stored_html = rows["stored-html"]
    stored_html_denominator = _optional_int(context.get("stored_html_count"))
    nonhtml_document_count = _optional_int(context.get("nonhtml_document_count"))
    metadata_rows = [
        row
        for row in stored_html
        if row.get("kind")
        in {
            "duplicate-title",
            "duplicate-meta-description",
            "duplicate-meta-robots",
            "head-only-element-in-body",
            "missing-h1",
            "multiple-h1",
            "heading-level-skip",
            "missing-html-lang",
            "invalid-html-lang",
            "html-lang-self-hreflang-mismatch",
        }
    ]
    canonical_rows = [
        row
        for row in stored_html
        if row.get("kind")
        in {"missing-canonical", "duplicate-canonical", "relative-canonical", "html-header-canonical-mismatch"}
    ]
    canonical_target_rows = [row for row in stored_html if row.get("kind") == "canonical-to-homepage"]
    hreflang_rows = rows["hreflang-validation"]
    hreflang_noindex_rows = [row for row in hreflang_rows if row.get("kind") == "hreflang-target-noindex"]
    hreflang_html_rows = [row for row in hreflang_rows if row.get("kind") != "hreflang-target-noindex"]
    # Q82 compares sitemap and link discovery; a run that recorded no sitemap
    # sources cannot show a sitemap-only population.
    sitemap_sources_recorded = (_optional_int(context.get("run_sitemap_source_count")) or 0) > 0

    detector_checks = (
        _check(
            "metadata-basics",
            "Metadata basics",
            "Metadata",
            metadata_rows,
            "finding",
            "Saved raw HTML contains duplicate metadata, invalid html lang markup or an invalid heading outline.",
            available=source_coverage["stored-html"]["available"] is True,
            denominator=stored_html_denominator,
            completion_state=completion_state,
        ),
        _check(
            "canonical-declarations",
            "Canonical declarations",
            "Canonicals",
            canonical_rows,
            "finding",
            "Saved raw HTML has a missing, duplicate or relative canonical declaration.",
            available=source_coverage["stored-html"]["available"] is True,
            denominator=stored_html_denominator,
            completion_state=completion_state,
        ),
        _check(
            "metadata-duplicates-aliases",
            "Metadata duplicates and aliases",
            "Duplicate metadata",
            rows["metadata-duplicates"],
            "finding",
            "Two or more indexable self-canonical pages share a saved title or H1.",
            available=source_coverage["metadata-duplicates"]["available"] is True,
            denominator=parsed_html_count,
            completion_state=completion_state,
        ),
        _check(
            "canonical-target-validation",
            "Canonical target validation",
            "Canonical targets",
            canonical_target_rows,
            "finding",
            "A non-homepage saved URL declares the homepage as its canonical target.",
            available=source_coverage["stored-html"]["available"] is True,
            denominator=stored_html_denominator,
            completion_state=completion_state,
        ),
        _check(
            "soft404-error-routes",
            "Soft 404 and error routes",
            "Soft 404s",
            rows["soft404-error-routes"],
            "finding",
            "A saved 200 response has an error-page title or H1; confirm the route and intended content live.",
            available=source_coverage["soft404-error-routes"]["available"] is True,
            denominator=stored_html_denominator,
            completion_state=completion_state,
            qualification="review_required",
        ),
        _check(
            "discovery-source-provenance",
            "Discovery-source provenance",
            "Discovery sources",
            rows["discovery-source-provenance"] if sitemap_sources_recorded else [],
            "finding",
            "Saved sitemap and internal-link discovery sources disagree; confirm whether the population is intentionally excluded from one source.",
            available=source_coverage["discovery-source-provenance"]["available"] is True and sitemap_sources_recorded,
            denominator=parsed_html_count,
            completion_state=completion_state,
            qualification="review_required",
        ),
        _check(
            "hreflang-html-http",
            "HTML and HTTP hreflang",
            "Hreflang",
            hreflang_html_rows,
            "finding",
            "A saved HTML or HTTP hreflang edge is non-reciprocal, targets an invalid canonical/status, or exceeds the HTML alternates bound.",
            available=source_coverage["hreflang-validation"]["available"] is True,
            denominator=parsed_html_count,
            completion_state=completion_state,
        ),
        _check(
            "hreflang-noindex",
            "Hreflang noindex conflicts",
            "Hreflang noindex",
            hreflang_noindex_rows,
            "finding",
            "A saved hreflang edge targets a known noindex page.",
            available=source_coverage["hreflang-validation"]["available"] is True,
            denominator=parsed_html_count,
            completion_state=completion_state,
        ),
        _check(
            "nonhtml-search-assets",
            "Non-HTML search assets",
            "Non-HTML assets",
            rows["nonhtml-search-assets"],
            "finding",
            "A saved 200 document response has neither an X-Robots-Tag nor a Link canonical header.",
            available=source_coverage["nonhtml-search-assets"]["available"] is True,
            denominator=nonhtml_document_count,
            completion_state=completion_state,
        ),
        _check(
            "indexability-segmentation",
            "Indexability segmentation",
            "Index conflicts",
            indexability_conflicts,
            "finding",
            "HTML and HTTP indexing directives disagree on the same saved response.",
            available=source_coverage["indexability"]["available"] is True,
            denominator=parsed_html_count,
            completion_state=completion_state,
        ),
        _check(
            "internal-link-targets",
            "Internal links to failed targets",
            "Internal link failures",
            link_failures,
            "finding",
            "Saved internal links point to an error, redirect, noindex or non-canonical target; recheck material paths live before client reporting.",
            available=source_coverage["internal-link-quality"]["available"] is True,
            denominator=parsed_html_count,
            completion_state=completion_state,
            qualification="recheck_required",
        ),
        _check(
            "parameter-and-faceted-controls",
            "Parameter and faceted controls",
            "Tracking parameters",
            rows["tracking-parameter-links"],
            "finding",
            "Known tracking parameters occur in internal crawlable links.",
            available=source_coverage["tracking-parameter-links"]["available"] is True,
            denominator=parsed_html_count,
            completion_state=completion_state,
        ),
        _check(
            "orphan-candidates",
            "Orphan-page candidates",
            "Orphan candidates",
            rows["orphans"],
            "finding",
            "Zero observed parent does not prove an orphan without graph-coverage evidence.",
            available=source_coverage["orphans"]["available"] is True,
            denominator=parsed_html_count,
            completion_state=completion_state,
            qualification="coverage_required",
        ),
        _check(
            "response-status-and-redirect-history",
            "Response status and redirects",
            "Redirect chains",
            rows["redirect-chains"],
            "finding",
            "A redirect is not a defect by itself; validate material paths live.",
            available=source_coverage["redirect-chains"]["available"] is True,
            denominator=parsed_html_count,
            completion_state=completion_state,
            qualification="recheck_required",
        ),
        _check(
            "near-duplicate-content",
            "Near-duplicate content candidates",
            "Near duplicates",
            rows["near-duplicates"],
            "finding",
            "Similarity is evidence for review, not proof of a duplicate-content defect.",
            available=source_coverage["near-duplicates"]["available"] is True,
            denominator=hashed_count,
            completion_state=completion_state,
            qualification="review_required",
        ),
        _check(
            "schema-parser-diagnostics",
            "Schema parser diagnostics",
            "Schema diagnostics",
            schema_defects,
            "finding",
            "Stored structured data failed deterministic parser validation.",
            available=source_coverage["schema-compatibility"]["available"] is True,
            denominator=parsed_html_count,
            completion_state=completion_state,
        ),
        _check(
            "image-markup",
            "Image markup",
            "Image issues",
            rows["image-issues"],
            "finding",
            "Decorative-image intent and delivered-layout impact require page-context review.",
            available=source_coverage["image-issues"]["available"] is True,
            denominator=parsed_html_count,
            completion_state=completion_state,
            qualification="review_required",
        ),
        _check(
            "internal-authority",
            "Internal authority",
            "Internal authority",
            rows["internal-authority"],
            "partial",
            "Relative scores require template and business-priority comparison.",
            available=source_coverage["internal-authority"]["available"] is True,
            denominator=parsed_html_count,
            completion_state=completion_state,
        ),
        _check(
            "locale-html-lang",
            "Locale language and substantive content",
            "Locale language",
            locale_alignment,
            "finding",
            "The same primary-content signature occurs on pages that declare different languages; confirm the page purpose before treating this as untranslated locale content.",
            available=source_coverage["locale-content-alignment"]["available"] is True
            and locale_signature_count is not None
            and locale_signature_count > 0,
            denominator=locale_signature_count,
            completion_state=completion_state,
            qualification="review_required",
        ),
        _check(
            "rendered-robots-links",
            "Inventory discovery without interaction",
            "Rendered robots links",
            inventory_issues,
            "finding",
            "A documented interaction exposes additional document URLs that were absent from the initial rendered DOM.",
            available=source_coverage["inventory-interactions"]["available"] is True,
            denominator=len(interaction_rows)
            if source_coverage["inventory-interactions"]["available"] is True
            else None,
            completion_state=completion_state,
            verified_evidence=interaction_rows,
        ),
        _check(
            "supplied-search-evidence",
            "Google indexing, canonical and performance evidence",
            "Supplied search evidence",
            search_issues,
            "finding",
            "Supplied Search Console or URL Inspection records show an indexing, canonical-selection or priority-URL impression issue.",
            available=source_coverage["supplied-search-evidence"]["available"] is True,
            denominator=len(search_records)
            if source_coverage["supplied-search-evidence"]["available"] is True
            else None,
            completion_state=completion_state,
            verified_evidence=search_records,
        ),
    )

    checks = _complete_contract_checks(detector_checks, source_coverage)

    audit_log = [
        *_indexability_actions(indexability_conflicts),
        *_tracking_actions(rows["tracking-parameter-links"]),
        *_schema_actions(schema_defects),
        *_locale_actions(locale_alignment),
        *_inventory_actions(inventory_issues),
        *_search_evidence_actions(search_issues),
    ]
    return {
        "schema_version": TECHNICAL_AUDIT_SCHEMA_VERSION,
        "ruleset_version": TECHNICAL_AUDIT_RULESET_VERSION,
        "parser": _PARSER,
        "parser_versions": parser_versions,
        "structured_data_parser_mode": JSON_LD_PARSER_MODE,
        "crawl_run_id": crawl_run_id,
        "run_context": context,
        "source_coverage": source_coverage,
        "question_inputs": {
            "semantic-html": rows["semantic-html"],
            "profile-indexability-pages": rows["profile-indexability-pages"],
        },
        "status_vocabulary": [
            "pass",
            "finding",
            "partial",
            "unavailable",
            "not_applicable",
        ],
        "check_contract": [dict(item) for item in TECHNICAL_AUDIT_CHECK_CONTRACT],
        "check_registry": [dict(item) for item in TECHNICAL_AUDIT_CHECK_REGISTRY],
        "check_id_aliases": dict(TECHNICAL_AUDIT_LEGACY_CHECK_ID_ALIASES),
        "checks": list(checks),
        "audit_log": audit_log,
        "manual_checks": _manual_checks(),
    }


def audit_sheet_tables(audit: Mapping[str, object]) -> dict[str, list[list[object]]]:
    """Return only the tabs which have deterministic content to publish.

    Existing template formatting is retained by the publisher.  Detail tabs
    are created only when that test produced rows.
    """

    checks = audit.get("checks", [])
    assert isinstance(checks, list)
    raw_context = audit.get("run_context", {})
    context = raw_context if isinstance(raw_context, Mapping) else {}
    raw_coverage = audit.get("source_coverage", {})
    source_coverage = raw_coverage if isinstance(raw_coverage, Mapping) else {}
    registry = audit.get("check_registry", [])
    audit_log = audit.get("audit_log", [])
    ticket_register = audit.get("ticket_register", [])
    overview = [
        ["Metric", "Value"],
        ["Audit schema", str(audit["schema_version"])],
        ["Ruleset version", str(audit.get("ruleset_version", "unknown"))],
        ["Crawl run", str(audit["crawl_run_id"])],
        ["Run status", str(context.get("run_status", "unknown"))],
        ["Completion state", str(context.get("completion_state", "unavailable"))],
        ["Parsed HTML denominator", context.get("parsed_html_count", "unknown")],
        [
            "Source reports available",
            sum(bool(item["available"]) for item in source_coverage.values() if isinstance(item, Mapping)),
        ],
        ["Registry checks", len(registry) if isinstance(registry, list) else 0],
        ["Candidate/action rows", len(audit_log) if isinstance(audit_log, list) else 0],
    ]
    for check in checks:
        assert isinstance(check, Mapping)
        overview.append([str(check["title"]), str(check["status"])])

    tables: dict[str, list[list[object]]] = {
        "Overview": overview,
        "Audit Log": _table(
            audit.get("audit_log", []),
            (
                "Problem",
                "URL",
                "Explanation",
                "Fix",
                "SEO Impact",
                "Action Needed",
                "Responsible Team",
                "Owner",
                "Acceptance Criteria",
                "Retest Status",
                "Evidence Reference",
                "Resolved",
            ),
        ),
    }
    if "ticket_register" in audit and isinstance(ticket_register, list):
        from .technical_audit_tickets import ticket_sheet_table

        tables["Tickets"] = ticket_sheet_table([row for row in ticket_register if isinstance(row, Mapping)])
    for check in checks:
        assert isinstance(check, Mapping)
        evidence = check["evidence"]
        assert isinstance(evidence, list)
        verified_evidence = check.get("verified_evidence", [])
        assert isinstance(verified_evidence, list)
        if evidence or verified_evidence:
            tables[str(check["detail_sheet"])] = _table(evidence or verified_evidence)
    return tables


_LINK_FAILURE_PRIORITY = ("error_target", "redirect_target", "noncanonical_target", "non_indexable_target")


def _link_target_failures(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """One row per link (source, target, position) with its most serious target state first."""

    edges: dict[tuple[object, object, object], dict[str, object]] = {}
    for row in rows:
        issue = row.get("issue")
        if issue not in _LINK_FAILURE_PRIORITY:
            continue
        key = (row.get("source_url"), row.get("target_url"), row.get("xpath"))
        edge = edges.setdefault(key, {**row, "issues": []})
        issues = edge["issues"]
        assert isinstance(issues, list)
        issues.append(issue)
    for edge in edges.values():
        issues = edge["issues"]
        assert isinstance(issues, list)
        issues.sort(key=_LINK_FAILURE_PRIORITY.index)
        edge["issue"] = issues[0]
    return list(edges.values())


def _check(
    identifier: str,
    title: str,
    detail_sheet: str,
    evidence: list[dict[str, object]],
    positive_status: str,
    interpretation: str,
    *,
    available: bool,
    denominator: int | None,
    completion_state: str,
    qualification: str | None = None,
    verified_evidence: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if evidence:
        status = positive_status
    elif not available or denominator is None or completion_state != "complete":
        status = "partial" if available else "unavailable"
    elif denominator == 0:
        # A zero collection population is not proof that this control does
        # not apply.  It commonly means that hashing, rendering or another
        # collector never produced a usable population.
        status = "unavailable"
    else:
        status = "pass"
    return {
        "id": identifier,
        "title": title,
        "mode": "deterministic",
        "status": status,
        "coverage_state": completion_state,
        "row_count": len(evidence),
        "affected_count": len(evidence),
        "eligible_count": denominator,
        "tested_count": denominator if available and denominator is not None else None,
        "excluded_count": None,
        "denominator": denominator,
        "detail_sheet": detail_sheet,
        "interpretation": interpretation,
        "qualification": qualification,
        "evidence": evidence,
        "verified_evidence": verified_evidence or [],
    }


def _complete_contract_checks(
    detector_checks: Sequence[Mapping[str, object]],
    source_coverage: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    """Return exactly one result per contract control in contract order."""

    by_id = {str(check["id"]): dict(check) for check in detector_checks}
    unexpected_ids = set(by_id).difference(item["id"] for item in TECHNICAL_AUDIT_CHECK_CONTRACT)
    if unexpected_ids:
        raise ValueError(f"detector checks outside contract: {sorted(unexpected_ids)}")
    if len(by_id) != len(detector_checks):
        raise ValueError("duplicate detector check IDs")

    aliases_by_contract_id: dict[str, list[str]] = {}
    for legacy_id, contract_id in TECHNICAL_AUDIT_LEGACY_CHECK_ID_ALIASES.items():
        aliases_by_contract_id.setdefault(contract_id, []).append(legacy_id)

    completed: list[dict[str, object]] = []
    for contract in TECHNICAL_AUDIT_CHECK_CONTRACT:
        identifier = contract["id"]
        check = by_id.get(identifier)
        if check is None:
            check = _unavailable_contract_check(contract)
        check["title"] = contract["title"]
        check["detail_sheet"] = contract["detail_sheet"]
        check["required_evidence"] = contract["required_evidence"]
        check["owner_ticket"] = contract["owner_ticket"]
        check["input_provenance"] = _input_provenance(identifier, source_coverage)
        legacy_ids = aliases_by_contract_id.get(identifier)
        if legacy_ids:
            check["legacy_check_ids"] = legacy_ids
        completed.append(check)
    return completed


def _unavailable_contract_check(contract: Mapping[str, str]) -> dict[str, object]:
    """Describe absent collection without replacing it with an empty pass."""

    return _check(
        contract["id"],
        contract["title"],
        contract["detail_sheet"],
        [],
        "finding",
        "The deterministic collector for this control did not run.",
        available=False,
        denominator=None,
        completion_state="unavailable",
        qualification=f"missing_required_evidence: {contract['required_evidence']}",
    )


def _input_provenance(
    identifier: str,
    source_coverage: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    report_names = _IMPLEMENTED_CHECK_REPORTS.get(identifier, ())
    if not report_names:
        return []
    return [
        {
            "kind": "saved_run_report",
            "report": report_name,
            "available": source_coverage[report_name]["available"],
            "source_digest_sha256": source_coverage[report_name]["source_digest_sha256"],
        }
        for report_name in report_names
    ]


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if isinstance(value, (int, float, str)) else None
    except (TypeError, ValueError):
        return None


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unavailable"


def _action(*, problem: str, url: object, explanation: str, fix: str, impact: str, evidence: str) -> dict[str, object]:
    return {
        "Problem": problem,
        "URL": url,
        "Explanation": explanation,
        "Fix": fix,
        "SEO Impact": impact,
        "Action Needed": "Yes",
        "Responsible Team": "Engineering",
        "Owner": "Unassigned",
        "Acceptance Criteria": "Deploy the change and recheck the exact URL live.",
        "Retest Status": "Not retested",
        "Evidence Reference": evidence,
        "Resolved": "No",
    }


def _indexability_actions(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        _action(
            problem="Conflicting indexability directives",
            url=row.get("url", ""),
            explanation="The saved HTML meta and HTTP header directives disagree.",
            fix="Choose one intended indexability state and make header and HTML directives agree.",
            impact="Conflicting signals can lead to unintended indexation handling.",
            evidence="indexability-segmentation",
        )
        for row in rows
    ]


def _tracking_actions(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        _action(
            problem="Internal link publishes tracking parameters",
            url=row.get("target_url", ""),
            explanation=f"Source: {row.get('source_url', '')}; parameters: {row.get('tracking_parameters', '')}.",
            fix="Change the internal link to the clean canonical URL.",
            impact="Crawlable tracking variants waste crawl paths and can overwrite attribution.",
            evidence="parameter-and-faceted-controls",
        )
        for row in rows
    ]


def _schema_actions(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        _action(
            problem="Structured-data parser defect",
            url=row.get("url", ""),
            explanation=f"{row.get('diagnostic_code', 'Unknown parser diagnostic')}: {row.get('evidence', '')}",
            fix=str(row.get("remediation", "Correct the structured-data markup and validate it again.")),
            impact="Invalid markup can prevent eligible structured-data features from being understood.",
            evidence="schema-parser-diagnostics",
        )
        for row in rows
    ]


def _locale_actions(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        _action(
            problem="Locale pages reuse the same primary-content signature",
            url=row.get("url", ""),
            explanation=(
                f"Declared language: {row.get('html_lang', '')}; the same signature appears in "
                f"{row.get('languages', '')}. Confirm whether this page is intentionally shared before assignment."
            ),
            fix="Translate and localise the page's primary content, or remove the locale URL from indexation and hreflang.",
            impact="Untranslated locale pages can compete with the intended language version and give users an irrelevant result.",
            evidence="locale-html-lang",
        )
        for row in rows
    ]


def _inventory_actions(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        _action(
            problem="Inventory URLs require a user interaction to appear",
            url=row.get("source_url", row.get("url", "")),
            explanation=(
                f"Action {row.get('action', 'interaction')} increased document URLs from "
                f"{row.get('initial_document_url_count', '')} to {row.get('post_interaction_document_url_count', '')}."
            ),
            fix="Publish crawlable pagination or ordinary links for the additional inventory URLs in the initial response or initial rendered DOM.",
            impact="URLs exposed only after interaction can remain undiscovered or receive weak internal discovery signals.",
            evidence="rendered-robots-links",
        )
        for row in rows
    ]


def _search_evidence_actions(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        _action(
            problem="Google evidence conflicts with the intended technical state",
            url=row.get("url", ""),
            explanation=str(row.get("issue_reason", "The supplied search record requires review.")),
            fix="Resolve the recorded indexing, canonical or performance cause, then validate the URL through URL Inspection and the next Search Console export.",
            impact="Google may exclude the URL, select another canonical, or show no demand for a declared priority page.",
            evidence="supplied-search-evidence",
        )
        for row in rows
    ]


def _table(rows: object, columns: tuple[str, ...] | None = None) -> list[list[object]]:
    materialised = [dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []
    if columns is None:
        columns = tuple(dict.fromkeys(key for row in materialised for key in row))
    return [list(columns), *[[row.get(column, "") for column in columns] for row in materialised]]


def _manual_checks() -> list[dict[str, str]]:
    return [
        {
            "id": "internal-link-targets",
            "reason": "Current status, redirect paths, and intermittent failures change after a crawl.",
        },
        {
            "id": "robots-controls",
            "reason": "Fetch current robots.txt independently from the saved crawl.",
        },
        {
            "id": "sitemap-integrity",
            "reason": "Fetch every current XML sitemap independently from the saved crawl.",
        },
        {
            "id": "rendered-indexing-parity",
            "reason": "Raw and rendered DOM signals require representative browser evidence.",
        },
        {
            "id": "locale-redirects",
            "reason": "Locale redirects require the relevant proxy regions and request headers.",
        },
        {
            "id": "structured-data-feature-rules",
            "reason": "Google feature requirements and site intent need current, contextual validation.",
        },
        {
            "id": "recipient-action-eligibility",
            "reason": "Business value, template purpose, and recipient-value filtering remain analyst decisions.",
        },
    ]
