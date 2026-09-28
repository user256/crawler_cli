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
import re
from urllib.parse import parse_qsl, urlsplit

from .schema import JSON_LD_PARSER_MODE, _PARSER
from .indexability import directive_conflicts
from .models import RobotsDirectiveEvidence
from .redaction import redact_url_without_digest


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
    "link-graph-metrics",
    "tracking-parameter-links",
    "near-duplicates",
    "similarity-coverage",
    "internal-authority",
    "authority-coverage",
    "metadata-locale-inventory",
)

# Registry is intentionally wider than the currently implemented report set.
# A fixed count of SQL reports must never be presented as coverage of the full
# analyst skill. Implemented reports stay candidates until their prerequisites
# and population denominator are known.
TECHNICAL_AUDIT_CHECK_REGISTRY = (
    {"id": "crawl-integrity", "state": "partial", "source": "crawl run and snapshots"},
    {"id": "indexability-directive-conflicts", "state": "implemented", "source": "indexability report"},
    {"id": "internal-link-quality", "state": "implemented", "source": "link graph report"},
    {
        "id": "live-link-rechecks",
        "state": "implemented_conditional",
        "source": "guarded crawler and authorization manifest",
    },
    {"id": "tracking-parameter-links", "state": "implemented", "source": "link graph report"},
    {"id": "orphan-candidates", "state": "implemented_candidate", "source": "orphan report"},
    {"id": "redirect-observations", "state": "implemented_candidate", "source": "redirect report"},
    {
        "id": "near-duplicate-content",
        "state": "implemented_candidate",
        "source": "primary-content signatures and bounded similarity coverage",
    },
    {"id": "schema-parser-diagnostics", "state": "implemented_candidate", "source": "schema report"},
    {"id": "image-markup", "state": "implemented_candidate", "source": "image report"},
    {
        "id": "internal-authority",
        "state": "implemented_candidate",
        "source": "canonical indexable HTML and run-scoped link graph",
    },
    {
        "id": "metadata-and-locale",
        "state": "implemented_candidate",
        "source": "run-scoped parsed HTML snapshots; sitemap membership unavailable",
    },
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


def metadata_locale_report(source_rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Classify saved metadata facts without converting incomplete evidence into defects."""
    eligible: list[dict[str, object]] = []
    excluded: dict[str, int] = {}
    all_segments: dict[str, int] = {}
    indexable_segments: dict[str, int] = {}
    required = ("url", "kind", "final_status_code", "content_extracted", "overall_indexable")
    for source in source_rows:
        row = dict(source)
        reason = None
        if any(key not in row for key in required):
            reason = "required_field_unavailable"
        elif row.get("kind") != "html":
            reason = "non_html"
        elif row.get("challenge"):
            reason = "challenged"
        elif row.get("final_status_code") != 200:
            reason = "status_not_200"
        elif row.get("content_extracted") is not True:
            reason = "content_not_extracted_or_unknown"
        elif row.get("overall_indexable") not in (True, False):
            reason = "indexability_unknown"
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            if reason == "indexability_unknown":
                url = str(row.get("url") or "")
                unknown_context: dict[str, object] = {
                    "locale": _clean_metadata(row.get("html_lang")) or "missing_locale",
                    "template": _clean_metadata(row.get("template")) or "not_stored",
                    "query_parameter_names": sorted(
                        {key for key, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True)}
                    ),
                    "canonical_state": _canonical_state(row.get("canonical_urls_json"), url),
                    "indexability": "unknown",
                }
                segment = _segment_key(unknown_context)
                all_segments[segment] = all_segments.get(segment, 0) + 1
            continue
        url = str(row.get("url") or "")
        locale = _clean_metadata(row.get("html_lang"))
        query_names = sorted({key for key, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True)})
        page_context: dict[str, object] = {
            "url": _metadata_url(url),
            "url_digest_sha256": hashlib.sha256(url.encode()).hexdigest(),
            "locale": locale,
            "indexable": row.get("overall_indexable"),
            "template": _clean_metadata(row.get("template")) or "not_stored",
            "variant_kind": _clean_metadata(row.get("variant_kind")) or "unknown",
            "query_parameter_names": query_names,
            "pagination_parameter_candidates": [
                key for key in query_names if key.lower() in {"page", "paged", "p", "offset", "cursor"}
            ],
            "alias_url": _metadata_url(str(row["final_url"]))
            if row.get("final_url") and row.get("final_url") != url
            else None,
            "canonical_state": _canonical_state(row.get("canonical_urls_json"), url),
            "sitemap_inclusion": "unavailable_not_run_scoped",
            "title_length": len(_clean_metadata(row.get("title")) or ""),
            "description_length": len(_clean_metadata(row.get("meta_description")) or ""),
            "h1_count": len([value for value in str(row.get("h1_tags") or "").splitlines() if value.strip()]),
        }
        eligible.append({**row, "_context": page_context})
        segment = _segment_key(page_context)
        all_segments[segment] = all_segments.get(segment, 0) + 1
        if row.get("overall_indexable") is True:
            segment = _segment_key(page_context)
            indexable_segments[segment] = indexable_segments.get(segment, 0) + 1

    candidates: list[dict[str, object]] = []
    duplicate_groups: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for row in eligible:
        raw_context = row["_context"]
        assert isinstance(raw_context, dict)
        context: dict[str, object] = raw_context
        if row.get("overall_indexable") is not True:
            continue
        title = _clean_metadata(row.get("title"))
        description = _clean_metadata(row.get("meta_description"))
        h1s = [value.strip() for value in str(row.get("h1_tags") or "").splitlines() if value.strip()]
        for field, value in (
            ("title", title),
            ("description", description),
            ("h1", "\n".join(h1s)),
            ("html_lang", context["locale"]),
        ):
            if not value:
                candidates.append(
                    {
                        "record_type": "candidate",
                        "candidate_type": f"missing_{field}",
                        **context,
                        "visible_content_state": "unknown_without_rendered_confirmation" if field == "h1" else None,
                    }
                )
        if len(h1s) > 1:
            candidates.append({"record_type": "candidate", "candidate_type": "multiple_h1_markup", **context})
        for field, value in (("title", title), ("description", description)):
            if value and context["locale"]:
                normalized = re.sub(r"\s+", " ", value).strip().casefold()
                duplicate_groups.setdefault((field, str(context["locale"]).casefold(), normalized), []).append(
                    {
                        **context,
                        "metadata_value": value,
                    }
                )
    for (field, locale, normalized), members in sorted(duplicate_groups.items()):
        if len(members) < 2:
            continue
        group_id = hashlib.sha256(f"{field}\0{locale}\0{normalized}".encode()).hexdigest()
        for member in members:
            candidates.append(
                {
                    "record_type": "candidate",
                    "candidate_type": f"duplicate_{field}_same_locale",
                    "duplicate_group_id": group_id,
                    "affected_count": len(members),
                    **member,
                }
            )
    indexable_count = sum(row.get("overall_indexable") is True for row in eligible)
    coverage = {
        "record_type": "coverage",
        "inventory_complete": not excluded.get("required_field_unavailable"),
        "source_row_count": len(source_rows),
        "eligible_count": len(eligible),
        "eligible_indexable_count": indexable_count,
        "eligible_noindex_count": len(eligible) - indexable_count,
        "excluded_count": sum(excluded.values()),
        "excluded_by_reason": excluded,
        "segments": all_segments,
        "indexable_segments": indexable_segments,
        "sitemap_inclusion": "unavailable_not_run_scoped",
        "locale_missing_count": sum(not _clean_metadata(row.get("html_lang")) for row in eligible),
        "threshold_scoring": "not_configured; lengths are contextual only",
        "thin_text_scoring": "unavailable_no_saved_primary_content_extraction_or_template_thresholds",
        "eligible_length_ranges": _length_ranges(eligible),
    }
    return [coverage, *candidates]


def _clean_metadata(value: object) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", str(value)).strip()
    return normalized or None


def _metadata_url(url: str) -> str:
    """Keep query names for segmentation while never exporting query values."""
    parts = urlsplit(url)
    query_names = sorted({key for key, _ in parse_qsl(parts.query, keep_blank_values=True)})
    return redact_url_without_digest(parts._replace(query="&".join(query_names)).geturl())


def _segment_key(context: Mapping[str, object]) -> str:
    query_state = "query" if context.get("query_parameter_names") else "clean"
    return "|".join(
        (
            str(context.get("indexable", "noindex" if context.get("indexable") is False else "unknown")),
            str(context.get("locale") or "missing_locale"),
            str(context.get("template")),
            query_state,
            str(context.get("canonical_state")),
            "sitemap_unavailable",
        )
    )


def _length_ranges(rows: Sequence[Mapping[str, object]]) -> dict[str, dict[str, int | None]]:
    values: dict[str, list[int]] = {"title": [], "description": [], "h1": []}
    for row in rows:
        context = row.get("_context")
        if not isinstance(context, Mapping):
            continue
        for field in values:
            number = context.get(f"{field}_length" if field != "h1" else "h1_count")
            if isinstance(number, int):
                values[field].append(number)
    return {
        field: {"min": min(numbers) if numbers else None, "max": max(numbers) if numbers else None}
        for field, numbers in values.items()
    }


def _canonical_state(value: object, url: str) -> str:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            value = [value] if value else []
    if not isinstance(value, list) or not value:
        return "implicit_or_unavailable"
    canonicals = [str(item) for item in value if item]
    if not canonicals:
        return "implicit_or_unavailable"
    return "declared_self" if canonicals[0].split("#", 1)[0] == url.split("#", 1)[0] else "declared_nonself"


def build_technical_audit(
    *,
    crawl_run_id: str,
    reports: Mapping[str, Sequence[Mapping[str, object]]],
    run_context: Mapping[str, object] | None = None,
    live_rechecks: Mapping[str, Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """Build a stable audit payload from run-scoped report rows.

    The caller owns collection.  Keeping classification pure makes an audit
    reproducible from a saved report fixture and makes it safe to test without
    a database or network connection.
    """

    rows = {name: [dict(row) for row in reports.get(name, ())] for name in TECHNICAL_AUDIT_REPORTS}
    for row in rows["orphans"]:
        url = str(row.get("url", ""))
        recheck = _lookup_recheck(live_rechecks, url)
        if isinstance(recheck, Mapping):
            row["live_validation_state"] = str(recheck.get("state", "incomplete"))
            row["live_validation"] = dict(recheck)
        elif live_rechecks is not None and row.get("source_labels"):
            row["live_validation_state"] = "not_selected_by_recheck_limit"
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
    completion_state = str(context.get("completion_state", "unavailable"))
    graph_complete = bool(rows["link-graph-metrics"] and rows["link-graph-metrics"][0].get("graph_complete") is True)
    known_url_inventory = [row for row in rows["orphans"] if row.get("source_labels")]
    orphan_candidates = [
        row
        for row in rows["orphans"]
        if row.get("candidate_type")
        in {
            "crawled_html_zero_observed_inlinks",
            "source_known_zero_observed_inlinks",
        }
    ]

    capabilities = context.get("schema_capabilities", {})
    if not isinstance(capabilities, Mapping):
        capabilities = {}
    has_directive_evidence = capabilities.get("indexability_evidence_json") is True
    indexability_rows = [row for row in rows["indexability"] if row.get("content_extracted") is True]
    directive_data_complete = has_directive_evidence and all(
        row.get("directive_evidence") is not None for row in indexability_rows
    )
    indexability_conflicts = []
    if has_directive_evidence:
        for row in indexability_rows:
            declarations = _parse_directive_evidence(row.get("directive_evidence"))
            conflicts = directive_conflicts(declarations)
            if conflicts:
                indexability_conflicts.append({**row, "conflicts": conflicts})
    schema_defects = [row for row in rows["schema-compatibility"] if row.get("is_valid") is False]
    similarity = rows["similarity-coverage"][0] if rows["similarity-coverage"] else {}
    similarity_complete = (
        source_coverage["similarity-coverage"]["available"] is True
        and similarity.get("truncated") is False
        and similarity.get("findings_truncated") is False
        and similarity.get("missing_primary_hashes") == 0
    )
    authority = rows["authority-coverage"][0] if rows["authority-coverage"] else {}
    authority_complete = (
        source_coverage["authority-coverage"]["available"] is True and authority.get("graph_complete") is True
    )
    saved_link_failures = [row for row in rows["internal-link-quality"] if row.get("issue") == "error_target"]
    confirmed_link_failures = []
    analyst_link_failures = []
    for row in saved_link_failures:
        target_url = str(row.get("target_url", ""))
        recheck = _lookup_recheck(live_rechecks, target_url)
        if isinstance(recheck, Mapping) and recheck.get("state") in {
            "persistent_http_failure",
            "persistent_server_error",
        }:
            confirmed_link_failures.append({**row, "live_recheck": dict(recheck)})
        else:
            analyst_link_failures.append(
                {
                    **row,
                    "recheck_state": recheck.get("state") if isinstance(recheck, Mapping) else "not_checked",
                    **({"live_recheck": dict(recheck)} if isinstance(recheck, Mapping) else {}),
                }
            )
    all_saved_failures_rechecked = (
        all(_lookup_recheck(live_rechecks, str(row.get("target_url", ""))) is not None for row in saved_link_failures)
        if live_rechecks is not None
        else not saved_link_failures
    )

    metadata_rows = rows["metadata-locale-inventory"]
    metadata_coverage = metadata_rows[0] if metadata_rows and metadata_rows[0].get("record_type") == "coverage" else {}
    metadata_evidence = [row for row in metadata_rows if row.get("record_type") == "candidate"]

    checks = (
        _check(
            "indexability-directive-conflicts",
            "Indexability directive conflicts",
            "Index conflicts",
            indexability_conflicts,
            "finding",
            "HTML and HTTP indexing directives disagree on the same saved response.",
            available=source_coverage["indexability"]["available"] is True and directive_data_complete,
            denominator=parsed_html_count,
            completion_state=completion_state,
        ),
        _check(
            "internal-link-failures",
            "Internal links to failed targets",
            "Internal link failures",
            confirmed_link_failures,
            "finding",
            "Saved-crawl failures must be rechecked live before client reporting.",
            available=source_coverage["internal-link-quality"]["available"] is True and all_saved_failures_rechecked,
            denominator=parsed_html_count,
            completion_state=completion_state,
            qualification=(
                "live_confirmed" if confirmed_link_failures else ("recheck_required" if saved_link_failures else None)
            ),
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
            orphan_candidates if graph_complete else [],
            "finding",
            "Zero observed parent does not prove an orphan without graph-coverage evidence.",
            available=(
                source_coverage["orphans"]["available"] is True
                and source_coverage["link-graph-metrics"]["available"] is True
                and graph_complete
            ),
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
            available=source_coverage["similarity-coverage"]["available"] is True,
            denominator=_optional_int(similarity.get("eligible_population")),
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
            available=source_coverage["authority-coverage"]["available"] is True,
            denominator=_optional_int(authority.get("canonical_indexable_population")),
            completion_state=completion_state,
        ),
        _check(
            "metadata-and-locale",
            "Metadata and locale inventory",
            "Metadata & locale",
            metadata_evidence,
            "finding",
            "Saved parsed-HTML metadata candidates; rendered visibility and business impact are not inferred.",
            available=(
                source_coverage["metadata-locale-inventory"]["available"] is True
                and metadata_coverage.get("inventory_complete") is True
            ),
            denominator=_optional_int(metadata_coverage.get("eligible_indexable_count")),
            completion_state=completion_state,
            qualification="analyst_only",
        ),
    )
    for check in checks:
        if check["id"] == "near-duplicate-content" and not similarity_complete:
            check["status"] = "partial" if source_coverage["similarity-coverage"]["available"] else "unavailable"
            check["tested_count"] = _optional_int(similarity.get("sampled_population"))
            check["qualification"] = "bounded_or_incomplete_coverage"
        if check["id"] == "internal-authority-inventory" and not authority_complete:
            check["status"] = "partial" if source_coverage["authority-coverage"]["available"] else "unavailable"
            check["qualification"] = "incomplete_graph"
        if check["id"] == "metadata-and-locale" and metadata_coverage.get("inventory_complete") is not True:
            check["status"] = "partial" if source_coverage["metadata-locale-inventory"]["available"] else "unavailable"
            check["qualification"] = "incomplete_or_unknown_population"

    audit_log = [
        *_indexability_actions(indexability_conflicts),
        *_tracking_actions(rows["tracking-parameter-links"]),
        *_schema_actions(schema_defects),
    ]
    client_actions = _link_actions(confirmed_link_failures)
    unresolved_link_failures = [row for row in analyst_link_failures if row.get("recheck_state") not in {"recovered"}]
    checks_complete = all(check["status"] not in {"partial", "unavailable", "error"} for check in checks)
    publication_ready = (
        completion_state == "complete"
        and live_rechecks is not None
        and checks_complete
        and not unresolved_link_failures
        and not audit_log
    )
    publishable_actions = client_actions if publication_ready else []
    analyst_evidence = [
        *[{"check_id": "internal-link-failures", **row} for row in analyst_link_failures],
        *[{"check_id": "saved-run-candidate", **row} for row in audit_log],
    ]
    publication_reasons = []
    if completion_state != "complete":
        publication_reasons.append("crawl run is incomplete")
    if live_rechecks is None:
        publication_reasons.append("live rechecks were not requested")
    if not checks_complete:
        publication_reasons.append("one or more deterministic checks have incomplete coverage")
    if unresolved_link_failures:
        publication_reasons.append("some saved link failures are unverified or not publishable")
    if audit_log:
        publication_reasons.append("saved action candidates require field-specific current validation")
    return {
        "schema_version": TECHNICAL_AUDIT_SCHEMA_VERSION,
        "ruleset_version": TECHNICAL_AUDIT_RULESET_VERSION,
        "parser": _PARSER,
        "parser_versions": parser_versions,
        "structured_data_parser_mode": JSON_LD_PARSER_MODE,
        "crawl_run_id": crawl_run_id,
        "run_context": context,
        "source_coverage": source_coverage,
        "known_url_inventory": known_url_inventory,
        "metadata_locale_coverage": dict(metadata_coverage),
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
        "analyst_evidence": analyst_evidence,
        "live_rechecks": [
            {
                "target_url": redact_url_without_digest(url),
                "url_digest_sha256": hashlib.sha256(url.encode()).hexdigest(),
                **dict(recheck),
            }
            for url, recheck in sorted((live_rechecks or {}).items())
        ],
        "live_rechecks_by_digest": {
            "sha256:" + hashlib.sha256(url.encode()).hexdigest(): dict(recheck)
            for url, recheck in sorted((live_rechecks or {}).items())
        },
        "client_publication_gate": {
            "ready": publication_ready,
            "eligible_action_count": len(publishable_actions),
            "candidate_count": len(analyst_evidence),
            "blocked_reasons": publication_reasons,
            "client_actions": publishable_actions,
        },
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
    raw_gate = audit.get("client_publication_gate", {})
    gate = raw_gate if isinstance(raw_gate, Mapping) else {}
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
        [
            "Client publication ready",
            gate.get("ready", False),
        ],
    ]
    for check in checks:
        assert isinstance(check, Mapping)
        overview.append([str(check["title"]), str(check["status"])])

    tables: dict[str, list[list[object]]] = {"Overview": overview}
    raw_metadata_coverage = audit.get("metadata_locale_coverage", {})
    if isinstance(raw_metadata_coverage, Mapping) and raw_metadata_coverage:
        tables["Metadata Coverage"] = [
            ["Metric", "Value"],
            *[
                [str(key), json.dumps(value, sort_keys=True) if isinstance(value, (Mapping, list)) else value]
                for key, value in sorted(raw_metadata_coverage.items())
                if key != "record_type"
            ],
        ]
    client_actions = gate.get("client_actions", [])
    if gate.get("ready") is True and isinstance(client_actions, list) and client_actions:
        tables["Audit Log"] = _table(
            client_actions,
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
        )
    for check in checks:
        assert isinstance(check, Mapping)
        evidence = check["evidence"]
        assert isinstance(evidence, list)
        if evidence and str(check.get("qualification") or "") == "analyst_only":
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


def _lookup_recheck(
    live_rechecks: Mapping[str, Mapping[str, object]] | None,
    url: str,
) -> Mapping[str, object] | None:
    if live_rechecks is None:
        return None
    direct = live_rechecks.get(url)
    if direct is not None:
        return direct
    digest_key = "sha256:" + hashlib.sha256(url.encode()).hexdigest()
    return live_rechecks.get(digest_key)


def _parse_directive_evidence(value: object) -> list[RobotsDirectiveEvidence]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        channel, agent, raw = item.get("channel"), item.get("user_agent"), item.get("raw_value")
        directives = item.get("directives")
        if channel not in {"html_meta", "http_header"} or not isinstance(agent, str) or not isinstance(raw, str):
            continue
        if not isinstance(directives, list) or not all(isinstance(token, str) for token in directives):
            continue
        result.append(RobotsDirectiveEvidence(channel, agent, raw, list(directives)))
    return result


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
            explanation=f"Explicit HTML and HTTP directives contradict: {row.get('conflicts', [])}.",
            fix="Choose one intended indexability state and make header and HTML directives agree.",
            impact="Conflicting signals can lead to unintended indexation handling.",
            evidence="indexability-directive-conflicts",
        )
        for row in rows
    ]


def _link_actions(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        _action(
            problem="Internal link targets a repeatedly failing URL",
            url=row.get("target_url", ""),
            explanation=(
                f"Saved status {row.get('target_status')}; bounded live rechecks repeatedly failed. "
                f"Source: {row.get('source_url', '')}; anchor: {row.get('anchor_text', '')}."
            ),
            fix="Restore the destination or update the internal link to its intended working URL.",
            impact="Repeatedly failing internal destinations interrupt navigation and waste crawl paths.",
            evidence="internal-link-failures with live_recheck evidence",
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
