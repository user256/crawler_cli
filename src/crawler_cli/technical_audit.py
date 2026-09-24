"""Deterministic technical-audit projection over a stored crawl run.

This module deliberately separates facts that can be derived from one saved
``crawler_cli`` run from live checks and SEO judgement.  A no-row result is
therefore reported as ``no_observations`` rather than as a claim that a check
is healthy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json

from .schema import JSON_LD_PARSER_MODE, _PARSER


TECHNICAL_AUDIT_SCHEMA_VERSION = "crawler-cli/technical-audit/1"
TECHNICAL_AUDIT_RULESET_VERSION = "technical-audit-rules/1"

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
)

# Registry is intentionally wider than the currently implemented report set.
# A fixed count of SQL reports must never be presented as coverage of the full
# analyst skill. Implemented reports stay candidates until their prerequisites
# and population denominator are known.
TECHNICAL_AUDIT_CHECK_REGISTRY = (
    {"id": "crawl-integrity", "state": "partial", "source": "crawl run and snapshots"},
    {"id": "indexability-directive-conflicts", "state": "implemented", "source": "indexability report"},
    {"id": "internal-link-quality", "state": "implemented", "source": "link graph report"},
    {"id": "tracking-parameter-links", "state": "implemented", "source": "link graph report"},
    {"id": "orphan-candidates", "state": "implemented_candidate", "source": "orphan report"},
    {"id": "redirect-observations", "state": "implemented_candidate", "source": "redirect report"},
    {"id": "near-duplicate-content", "state": "implemented_candidate", "source": "content hash report"},
    {"id": "schema-parser-diagnostics", "state": "implemented_candidate", "source": "schema report"},
    {"id": "image-markup", "state": "implemented_candidate", "source": "image report"},
    {"id": "internal-authority", "state": "implemented_candidate", "source": "internal graph report"},
    {"id": "metadata-and-locale", "state": "not_implemented", "source": "stored page snapshots"},
    {"id": "canonical-targets", "state": "not_implemented", "source": "canonical and live response evidence"},
    {"id": "hreflang-clusters", "state": "not_implemented", "source": "HTML, header and sitemap annotations"},
    {"id": "current-robots-and-sitemaps", "state": "not_implemented", "source": "live HTTP collection"},
    {"id": "url-variants-and-soft-404", "state": "not_implemented", "source": "controlled live probes"},
    {
        "id": "rendered-mobile-and-resource-evidence",
        "state": "not_implemented",
        "source": "browser collection and resource fetches",
    },
    {
        "id": "feature-specific-structured-data",
        "state": "not_implemented",
        "source": "versioned feature rules and live markup",
    },
    {
        "id": "performance-and-conditional-requests",
        "state": "not_implemented",
        "source": "timings and conditional GET observations",
    },
    {"id": "verified-search-bot-logs", "state": "conditional", "source": "validated operator-supplied access logs"},
    {"id": "geo-dependent-behaviour", "state": "conditional", "source": "configured regional proxy observations"},
    {
        "id": "severity-content-intent-and-priority",
        "state": "analyst_judgement",
        "source": "site purpose and business evidence",
    },
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
    link_failures = [row for row in rows["internal-link-quality"] if row.get("issue") == "error_target"]

    checks = (
        _check(
            "indexability-directive-conflicts",
            "Indexability directive conflicts",
            "Index conflicts",
            indexability_conflicts,
            "finding",
            "HTML and HTTP indexing directives disagree on the same saved response.",
            available=source_coverage["indexability"]["available"] is True,
            denominator=parsed_html_count,
            completion_state=completion_state,
        ),
        _check(
            "internal-link-failures",
            "Internal links to failed targets",
            "Internal link failures",
            link_failures,
            "finding",
            "Saved-crawl failures must be rechecked live before client reporting.",
            available=source_coverage["internal-link-quality"]["available"] is True,
            denominator=parsed_html_count,
            completion_state=completion_state,
            qualification="recheck_required",
        ),
        _check(
            "tracking-parameter-links",
            "Internal tracking-parameter links",
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
            "redirect-chains",
            "Redirect observations",
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
            "schema-parser-defects",
            "Structured-data parser defects",
            "Schema diagnostics",
            schema_defects,
            "finding",
            "Stored structured data failed deterministic parser validation.",
            available=source_coverage["schema-compatibility"]["available"] is True,
            denominator=parsed_html_count,
            completion_state=completion_state,
        ),
        _check(
            "image-markup-candidates",
            "Image markup candidates",
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
            "internal-authority-inventory",
            "Internal authority inventory",
            "Internal authority",
            rows["internal-authority"],
            "inventory",
            "Relative scores require template and business-priority comparison.",
            available=source_coverage["internal-authority"]["available"] is True,
            denominator=parsed_html_count,
            completion_state=completion_state,
        ),
    )

    audit_log = [
        *_indexability_actions(indexability_conflicts),
        *_tracking_actions(rows["tracking-parameter-links"]),
        *_schema_actions(schema_defects),
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
        "status_vocabulary": [
            "tested",
            "pass",
            "finding",
            "partial",
            "unavailable",
            "not_applicable",
            "error",
            "no_observations",
        ],
        "check_registry": [dict(item) for item in TECHNICAL_AUDIT_CHECK_REGISTRY],
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
    for check in checks:
        assert isinstance(check, Mapping)
        evidence = check["evidence"]
        assert isinstance(evidence, list)
        if evidence:
            tables[str(check["detail_sheet"])] = _table(evidence)
    return tables


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
) -> dict[str, object]:
    if evidence:
        status = positive_status
    elif not available or denominator is None or completion_state != "complete":
        status = "partial" if available else "unavailable"
    elif denominator == 0:
        status = "no_observations"
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
    }


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
            evidence="indexability-directive-conflicts",
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
            evidence="tracking-parameter-links",
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
            evidence="schema-parser-defects",
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
            "id": "live-rechecks",
            "reason": "Current status, redirect paths, and intermittent failures change after a crawl.",
        },
        {
            "id": "robots-and-sitemaps",
            "reason": "Fetch current robots.txt and every current XML sitemap independently.",
        },
        {"id": "rendered-parity", "reason": "Raw and rendered DOM signals require representative browser evidence."},
        {
            "id": "geo-and-language",
            "reason": "Locale redirects require the relevant proxy regions and request headers.",
        },
        {
            "id": "rich-result-eligibility",
            "reason": "Google feature requirements and site intent need current, contextual validation.",
        },
        {
            "id": "severity-and-priority",
            "reason": "Business value, template purpose, and recipient-value filtering remain analyst decisions.",
        },
    ]
