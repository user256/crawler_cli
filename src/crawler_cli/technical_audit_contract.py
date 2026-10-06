"""Versioned runtime contract for deterministic technical audits."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final, TypedDict


class TechnicalAuditCheck(TypedDict):
    id: str
    title: str
    detail_sheet: str
    required_evidence: str
    owner_ticket: int


# Keep this as the single product-side contract. The skill documents the same
# five fields and tests compare the two tables exactly.
TECHNICAL_AUDIT_CHECK_CONTRACT: Final[tuple[TechnicalAuditCheck, ...]] = (
    {
        "id": "audit-run-integrity",
        "title": "Audit run integrity",
        "detail_sheet": "Run integrity",
        "required_evidence": "crawl/job metadata, run ID, timestamps, scope and counts",
        "owner_ticket": 183,
    },
    {
        "id": "audit-collection-safeguards",
        "title": "Collection safeguards",
        "detail_sheet": "Collection safeguards",
        "required_evidence": "collection configuration and event evidence",
        "owner_ticket": 224,
    },
    {
        "id": "discovery-source-provenance",
        "title": "Discovery-source provenance",
        "detail_sheet": "Discovery sources",
        "required_evidence": "run-scoped discovery-source evidence",
        "owner_ticket": 228,
    },
    {
        "id": "response-status-and-redirect-history",
        "title": "Response status and redirects",
        "detail_sheet": "Response and redirects",
        "required_evidence": "response and redirect evidence",
        "owner_ticket": 218,
    },
    {
        "id": "internal-link-targets",
        "title": "Internal link targets",
        "detail_sheet": "Internal link failures",
        "required_evidence": "run-scoped link graph and destination evidence",
        "owner_ticket": 186,
    },
    {
        "id": "external-link-integrity",
        "title": "External link integrity",
        "detail_sheet": "External link rechecks",
        "required_evidence": "explicit external-link recheck evidence",
        "owner_ticket": 211,
    },
    {
        "id": "orphan-candidates",
        "title": "Orphan-page candidates",
        "detail_sheet": "Orphan candidates",
        "required_evidence": "run-scoped link and discovery evidence",
        "owner_ticket": 222,
    },
    {
        "id": "crawl-depth-distribution",
        "title": "Crawl-depth distribution",
        "detail_sheet": "Crawl depth",
        "required_evidence": "root set and run-scoped graph",
        "owner_ticket": 228,
    },
    {
        "id": "internal-authority",
        "title": "Internal authority",
        "detail_sheet": "Internal authority",
        "required_evidence": "run-scoped internal graph and declared calculation",
        "owner_ticket": 187,
    },
    {
        "id": "image-markup",
        "title": "Image markup",
        "detail_sheet": "Image issues",
        "required_evidence": "raw or rendered image markup",
        "owner_ticket": 210,
    },
    {
        "id": "image-resource-delivery",
        "title": "Image resource delivery",
        "detail_sheet": "Image resources",
        "required_evidence": "resource and performance evidence",
        "owner_ticket": 210,
    },
    {
        "id": "url-host-and-variants",
        "title": "URL host and variants",
        "detail_sheet": "URL variants",
        "required_evidence": "crawl URLs, redirects, canonicals and link targets",
        "owner_ticket": 236,
    },
    {
        "id": "nonproduction-https",
        "title": "Non-production and HTTPS",
        "detail_sheet": "Host and HTTPS",
        "required_evidence": "host, response, robots and indexability evidence",
        "owner_ticket": 202,
    },
    {
        "id": "robots-controls",
        "title": "Robots controls",
        "detail_sheet": "Robots",
        "required_evidence": "current robots fetch and crawl evidence",
        "owner_ticket": 234,
    },
    {
        "id": "sitemap-integrity",
        "title": "Sitemap integrity",
        "detail_sheet": "Sitemaps",
        "required_evidence": "current sitemap fetches and crawl evidence",
        "owner_ticket": 234,
    },
    {
        "id": "rendered-robots-links",
        "title": "Rendered robots links",
        "detail_sheet": "Rendered robots links",
        "required_evidence": "raw/rendered links and robots evaluation",
        "owner_ticket": 205,
    },
    {
        "id": "indexability-segmentation",
        "title": "Indexability segmentation",
        "detail_sheet": "Index conflicts",
        "required_evidence": "stored page directives and responses",
        "owner_ticket": 184,
    },
    {
        "id": "crawl-waste-url-families",
        "title": "Crawl-waste URL families",
        "detail_sheet": "URL families",
        "required_evidence": "URL-family analysis with denominators",
        "owner_ticket": 220,
    },
    {
        "id": "parameter-and-faceted-controls",
        "title": "Parameter and faceted controls",
        "detail_sheet": "Tracking parameters",
        "required_evidence": "link, canonical, indexability and URL-family evidence",
        "owner_ticket": 236,
    },
    {
        "id": "soft404-error-routes",
        "title": "Soft 404 and error routes",
        "detail_sheet": "Soft 404s",
        "required_evidence": "response, title/body and template evidence",
        "owner_ticket": 236,
    },
    {
        "id": "metadata-basics",
        "title": "Metadata basics",
        "detail_sheet": "Metadata",
        "required_evidence": "metadata inventory",
        "owner_ticket": 190,
    },
    {
        "id": "metadata-duplicates-aliases",
        "title": "Metadata duplicates and aliases",
        "detail_sheet": "Duplicate metadata",
        "required_evidence": "metadata, canonical and alias evidence",
        "owner_ticket": 229,
    },
    {
        "id": "content-quality",
        "title": "Content quality",
        "detail_sheet": "Content quality",
        "required_evidence": "extracted-content evidence and declared thresholds",
        "owner_ticket": 190,
    },
    {
        "id": "locale-html-lang",
        "title": "Locale HTML language",
        "detail_sheet": "Locale language",
        "required_evidence": "HTML attributes and declared locale rules",
        "owner_ticket": 221,
    },
    {
        "id": "near-duplicate-content",
        "title": "Near-duplicate content",
        "detail_sheet": "Near duplicates",
        "required_evidence": "content hashes, similarity evidence and comparison population",
        "owner_ticket": 229,
    },
    {
        "id": "canonical-declarations",
        "title": "Canonical declarations",
        "detail_sheet": "Canonicals",
        "required_evidence": "raw HTML canonical inventory",
        "owner_ticket": 191,
    },
    {
        "id": "canonical-target-validation",
        "title": "Canonical target validation",
        "detail_sheet": "Canonical targets",
        "required_evidence": "canonical target and response/indexability evidence",
        "owner_ticket": 231,
    },
    {
        "id": "hreflang-html-http",
        "title": "HTML and HTTP hreflang",
        "detail_sheet": "Hreflang",
        "required_evidence": "hreflang inventory and target evidence",
        "owner_ticket": 231,
    },
    {
        "id": "hreflang-sitemap",
        "title": "Sitemap hreflang",
        "detail_sheet": "Sitemap hreflang",
        "required_evidence": "sitemap extension inventory and target evidence",
        "owner_ticket": 164,
    },
    {
        "id": "hreflang-noindex",
        "title": "Hreflang noindex conflicts",
        "detail_sheet": "Hreflang noindex",
        "required_evidence": "hreflang, canonical and indexability evidence",
        "owner_ticket": 206,
    },
    {
        "id": "locale-redirects",
        "title": "Locale redirects",
        "detail_sheet": "Locale redirects",
        "required_evidence": "authorised geo/locale probe evidence",
        "owner_ticket": 194,
    },
    {
        "id": "schema-parser-diagnostics",
        "title": "Schema parser diagnostics",
        "detail_sheet": "Schema diagnostics",
        "required_evidence": "structured-data parser evidence",
        "owner_ticket": 214,
    },
    {
        "id": "structured-data-feature-rules",
        "title": "Structured-data feature rules",
        "detail_sheet": "Structured data",
        "required_evidence": "typed structured-data evidence and documented rule set",
        "owner_ticket": 232,
    },
    {
        "id": "rendered-indexing-parity",
        "title": "Rendered indexing parity",
        "detail_sheet": "Rendered parity",
        "required_evidence": "paired raw/rendered evidence",
        "owner_ticket": 233,
    },
    {
        "id": "mobile-rendering-parity",
        "title": "Mobile rendering parity",
        "detail_sheet": "Mobile rendering",
        "required_evidence": "explicit mobile render evidence",
        "owner_ticket": 233,
    },
    {
        "id": "critical-resource-impact",
        "title": "Critical resource impact",
        "detail_sheet": "Critical resources",
        "required_evidence": "render trace and resource evidence",
        "owner_ticket": 233,
    },
    {
        "id": "nonhtml-search-assets",
        "title": "Non-HTML search assets",
        "detail_sheet": "Non-HTML assets",
        "required_evidence": "supplied or collected asset inventory",
        "owner_ticket": 194,
    },
    {
        "id": "performance-distribution",
        "title": "Performance distribution",
        "detail_sheet": "Performance",
        "required_evidence": "performance samples, percentiles and denominators",
        "owner_ticket": 196,
    },
    {
        "id": "conditional-cache-behaviour",
        "title": "Conditional cache behaviour",
        "detail_sheet": "Conditional requests",
        "required_evidence": "ETag/Last-Modified and conditional-request evidence",
        "owner_ticket": 235,
    },
    {
        "id": "validated-bot-log-analysis",
        "title": "Validated bot-log analysis",
        "detail_sheet": "Bot logs",
        "required_evidence": "supplied logs with verified bot identity",
        "owner_ticket": 196,
    },
    {
        "id": "supplied-search-evidence",
        "title": "Supplied search evidence",
        "detail_sheet": "Supplied search evidence",
        "required_evidence": "supplied Search Console, URL Inspection, CDN, origin or analytics evidence",
        "owner_ticket": 204,
    },
    {
        "id": "recipient-action-eligibility",
        "title": "Recipient action eligibility",
        "detail_sheet": "Recipient actions",
        "required_evidence": "audit finding records and supplied context",
        "owner_ticket": 227,
    },
    {
        "id": "healthy-overview",
        "title": "Healthy overview",
        "detail_sheet": "Healthy controls",
        "required_evidence": "qualified pass or not-applicable rows",
        "owner_ticket": 227,
    },
    {
        "id": "artifact-validation",
        "title": "Artifact validation",
        "detail_sheet": "Artifact validation",
        "required_evidence": "artifact validation evidence",
        "owner_ticket": 198,
    },
)


# All currently emitted v2 detector IDs have an explicit v3 destination. Two
# parameter detectors intentionally merge because they examine complementary
# evidence for one contract control.
LEGACY_CHECK_ID_ALIASES: Final[dict[str, str]] = {
    "indexability-directive-conflicts": "indexability-segmentation",
    "internal-link-failures": "internal-link-targets",
    "tracking-parameter-links": "parameter-and-faceted-controls",
    "parameterized-canonical-links": "parameter-and-faceted-controls",
    "orphan-candidates": "orphan-candidates",
    "redirect-chains": "response-status-and-redirect-history",
    "near-duplicate-content": "near-duplicate-content",
    "schema-parser-defects": "schema-parser-diagnostics",
    "feature-specific-structured-data": "structured-data-feature-rules",
    "performance-and-conditional-requests": "conditional-cache-behaviour",
    "image-markup-candidates": "image-markup",
    "internal-authority-inventory": "internal-authority",
    "metadata-and-locale": "metadata-basics",
    "canonical-consistency": "canonical-declarations",
    "hreflang-consistency": "hreflang-html-http",
    "current-robots-and-sitemaps": "robots-controls",
    "url-variants-and-soft-404": "url-host-and-variants",
    "rendered-mobile-and-resource-evidence": "rendered-indexing-parity",
}


# The v2 audit exposes detector-oriented rows.  The client workbook, the skill,
# and the remediation language use the broader v3 controls above.  This map is
# deliberately data, rather than a second hand-maintained result list: every
# v3 row names the detector evidence that can support it.  Empty entries are
# explicit evidence requirements, never implied passes.
CONTROL_DETECTORS: Final[dict[str, tuple[str, ...]]] = {
    "response-status-and-redirect-history": ("redirect-chains",),
    "internal-link-targets": ("internal-link-failures",),
    "external-link-integrity": ("external-link-rechecks",),
    "orphan-candidates": ("orphan-candidates",),
    "crawl-depth-distribution": ("internal-authority-inventory",),
    "internal-authority": ("internal-authority-inventory",),
    "image-markup": ("image-markup-candidates",),
    "image-resource-delivery": ("rendered-mobile-and-resource-evidence",),
    "url-host-and-variants": ("url-variants-and-soft-404",),
    "robots-controls": ("current-robots-and-sitemaps",),
    "sitemap-integrity": ("current-robots-and-sitemaps",),
    "rendered-robots-links": ("rendered-mobile-and-resource-evidence", "current-robots-and-sitemaps"),
    "indexability-segmentation": ("indexability-directive-conflicts",),
    "crawl-waste-url-families": ("tracking-parameter-links", "parameterized-canonical-links"),
    "parameter-and-faceted-controls": ("tracking-parameter-links", "parameterized-canonical-links"),
    "soft404-error-routes": ("url-variants-and-soft-404",),
    "metadata-basics": ("metadata-and-locale",),
    "metadata-duplicates-aliases": ("metadata-and-locale",),
    "content-quality": ("metadata-and-locale",),
    "locale-html-lang": ("metadata-and-locale",),
    "near-duplicate-content": ("near-duplicate-content",),
    "canonical-declarations": ("canonical-consistency",),
    "canonical-target-validation": ("canonical-consistency",),
    "hreflang-html-http": ("hreflang-consistency",),
    "hreflang-sitemap": ("hreflang-consistency", "current-robots-and-sitemaps"),
    "hreflang-noindex": ("hreflang-consistency", "indexability-directive-conflicts"),
    "locale-redirects": ("url-variants-and-soft-404",),
    "schema-parser-diagnostics": ("schema-parser-defects",),
    "structured-data-feature-rules": ("feature-specific-structured-data",),
    "rendered-indexing-parity": ("rendered-mobile-and-resource-evidence",),
    "mobile-rendering-parity": ("rendered-mobile-and-resource-evidence",),
    "critical-resource-impact": ("rendered-mobile-and-resource-evidence",),
    "performance-distribution": ("performance-and-conditional-requests",),
    "conditional-cache-behaviour": ("performance-and-conditional-requests",),
}


# ---------------------------------------------------------------------------
# Evidence scoping (ticket 241)
#
# A detector row may support a v3 control only with the evidence that belongs
# to that control.  Several detectors feed more than one control, so the
# projection scopes each detector's evidence rows by their row type
# (``candidate_type``, falling back to ``issue``) before merging:
#
# * ``None`` means the detector's rows belong wholly to the control (the
#   detector examines exactly this control's population).
# * A frozenset lists the row types the control accepts from that detector.
#   An empty frozenset means the detector is required supporting evidence (it
#   must be present and passing for a pass) but contributes no rows.
#
# A detector row whose type is not declared for any control fed by that
# detector (and not listed in ``DETECTOR_ROWS_OUTSIDE_V3``) is unscoped: every
# control fed by the detector gets the blocking ``unscoped_detector_evidence``
# qualification and cannot pass.  A ``finding`` detector with no rows scoped to
# a control makes that control ``partial`` (``detector_finding_outside_control_scope``),
# never ``finding`` and never ``pass``: the detector's pass/fail state for the
# control's own subset was not recorded separately.
# ---------------------------------------------------------------------------

_Scope = frozenset[str] | None

CONTROL_EVIDENCE_SCOPES: Final[dict[str, dict[str, _Scope]]] = {
    "response-status-and-redirect-history": {"redirect-chains": None},
    "internal-link-targets": {"internal-link-failures": None},
    "external-link-integrity": {"external-link-rechecks": None},
    "orphan-candidates": {"orphan-candidates": None},
    "internal-authority": {"internal-authority-inventory": None},
    "image-markup": {"image-markup-candidates": None},
    "url-host-and-variants": {
        "url-variants-and-soft-404": frozenset({"url_variant_observation", "url_variant_probe_not_admitted"}),
    },
    "soft404-error-routes": {"url-variants-and-soft-404": frozenset({"soft_404_risk_review"})},
    "robots-controls": {
        "current-robots-and-sitemaps": frozenset({"robots_controls_incomplete", "malformed_bare_sitemap_declaration"}),
    },
    "sitemap-integrity": {
        "current-robots-and-sitemaps": frozenset(
            {
                "duplicate_sitemap_url",
                "sitemap_protocol_mismatch_review",
                "sitemap_host_mismatch_review",
                "sitemap_lastmod_review",
            }
        ),
    },
    "indexability-segmentation": {"indexability-directive-conflicts": None},
    "parameter-and-faceted-controls": {"tracking-parameter-links": None, "parameterized-canonical-links": None},
    "metadata-basics": {
        "metadata-and-locale": frozenset({"missing_title", "missing_description", "missing_h1", "multiple_h1_markup"}),
    },
    "metadata-duplicates-aliases": {
        "metadata-and-locale": frozenset({"duplicate_title_same_locale", "duplicate_description_same_locale"}),
    },
    "locale-html-lang": {"metadata-and-locale": frozenset({"missing_html_lang"})},
    "near-duplicate-content": {"near-duplicate-content": None},
    "canonical-declarations": {
        "canonical-consistency": frozenset(
            {
                "missing_canonical",
                "multiple_canonicals",
                "malformed_canonical",
                "non_https_canonical",
                "cross_host_canonical_review",
                "parameterized_canonical_review",
                "canonical_channel_disagreement",
            }
        ),
    },
    "canonical-target-validation": {"canonical-consistency": frozenset({"non_self_canonical_candidate"})},
    "hreflang-html-http": {
        "hreflang-consistency": frozenset(
            {
                "invalid_hreflang_syntax",
                "duplicate_hreflang_language",
                "malformed_hreflang_target",
                "non_https_hreflang_target",
                "hreflang_target_unknown_not_crawled",
                "hreflang_reciprocity_candidate",
                "multiple_x_default",
                "missing_hreflang_self_reference",
                "hreflang_channel_disagreement",
            }
        ),
    },
    "hreflang-sitemap": {
        "hreflang-consistency": frozenset(),
        "current-robots-and-sitemaps": frozenset(
            {
                "duplicate_sitemap_hreflang_language",
                "invalid_sitemap_hreflang_syntax",
                "sitemap_hreflang_path_locale_review",
            }
        ),
    },
    "hreflang-noindex": {
        "hreflang-consistency": frozenset(
            {
                "hreflang_target_not_indexable_200",
                "hreflang_target_canonicalized_elsewhere",
                "noindex_source_hreflang_guidance",
            }
        ),
        "indexability-directive-conflicts": frozenset(),
    },
    "schema-parser-diagnostics": {"schema-parser-defects": None},
    "structured-data-feature-rules": {"feature-specific-structured-data": None},
    "rendered-indexing-parity": {
        "rendered-mobile-and-resource-evidence": frozenset({"render_divergence_review"}),
    },
    "conditional-cache-behaviour": {"performance-and-conditional-requests": None},
}

# Row types a shared detector emits that belong to no v3 control it feeds.
# They are known (so they do not block sibling controls) but never projected.
DETECTOR_ROWS_OUTSIDE_V3: Final[dict[str, frozenset[str]]] = {
    # Rendered missing-alt candidates are image markup evidence; the v3
    # image-markup control is fed by the image-markup-candidates detector.
    "rendered-mobile-and-resource-evidence": frozenset({"image_missing_alt_attribute_review"}),
}

# Controls whose contract evidence no mapped detector collects.  They are
# never ``pass`` (or ``finding``) from the nearby detector: the projection
# reports them ``unavailable`` with ``contract_evidence_not_collected`` until
# a collector for the contract evidence exists.
CONTROL_EVIDENCE_GAPS: Final[dict[str, str]] = {
    "crawl-depth-distribution": "authority inventory records no root set or shortest-path depth per page",
    "image-resource-delivery": "rendered candidates carry no image resource status, size or format evidence",
    "rendered-robots-links": "no detector evaluates rendered links against the fetched robots rules",
    "crawl-waste-url-families": "parameter detectors do not produce URL-family growth analysis with denominators",
    "content-quality": "metadata inventory has no extracted-content word counts or declared thresholds",
    "locale-redirects": "URL-variant probes are not authorised geo/locale probes",
    "mobile-rendering-parity": "rendered detector evidence does not prove a paired mobile render",
    "critical-resource-impact": "rendered candidates carry no render-trace resource impact evidence",
    "performance-distribution": "detector evidence is conditional-request candidates, not timing percentiles",
}

# Merge rule for ``tested_count`` and ``denominator``: detectors merged
# into one control examine the same (or an overlapping) population, so the
# control reports the largest contributing value, never the sum.

_NOT_PASSING = frozenset({"partial", "unavailable", "error", "no_observations"})


def project_v3_controls(
    detector_checks: Sequence[Mapping[str, object]],
    *,
    run_context: Mapping[str, object],
) -> list[dict[str, object]]:
    """Project detector rows into the ordered client/skill v3 control contract.

    A control is only ``pass`` when every detector required for it is present
    and passed, and only ``finding`` when rows scoped to that control exist.
    Controls without contract evidence (``CONTROL_EVIDENCE_GAPS``) and
    controls whose detectors are all missing are ``unavailable``.  Detector
    rows stay in the audit as ``detector_checks`` for diagnostic detail and
    backwards-compatible sheets.
    """

    by_id = {str(row.get("id")): row for row in detector_checks}
    contract_by_id = {row["id"]: row for row in TECHNICAL_AUDIT_CHECK_CONTRACT}
    result: list[dict[str, object]] = []
    for contract in TECHNICAL_AUDIT_CHECK_CONTRACT:
        identifier = contract["id"]
        detector_ids = CONTROL_DETECTORS.get(identifier, ())
        if identifier == "audit-run-integrity":
            result.append(_context_control(contract, run_context, "completion_state", "complete"))
            continue
        if identifier == "artifact-validation":
            result.append(_context_control(contract, run_context, "snapshot_consistency", "stable"))
            continue
        if identifier == "healthy-overview":
            # This is calculated after the substantive controls below.
            continue
        if identifier == "recipient-action-eligibility":
            result.append(_unavailable_control(contract, "recipient action requires evidenced control results"))
            continue
        if identifier in CONTROL_EVIDENCE_GAPS:
            row = _unavailable_control(contract, "contract_evidence_not_collected")
            row["detector_ids"] = list(detector_ids)
            row["evidence_gap"] = CONTROL_EVIDENCE_GAPS[identifier]
            result.append(row)
            continue
        if not any(source in by_id for source in detector_ids):
            result.append(_unavailable_control(contract))
            continue
        result.append(_merge_detector_controls(contract, by_id, detector_ids))

    substantive = [row for row in result if row["id"] not in {"healthy-overview"}]
    healthy = contract_by_id["healthy-overview"]
    incomplete = [row for row in substantive if row["status"] in {"partial", "unavailable", "finding"}]
    result.append(
        {
            "id": healthy["id"],
            "title": healthy["title"],
            "detail_sheet": healthy["detail_sheet"],
            "required_evidence": healthy["required_evidence"],
            "owner_ticket": healthy["owner_ticket"],
            "status": "pass" if not incomplete else "partial",
            "affected_count": len(incomplete),
            "tested_count": len(substantive),
            "denominator": len(substantive),
            "qualification": None if not incomplete else "controls_incomplete_or_finding",
            "evidence": [{"control_id": row["id"], "status": row["status"]} for row in incomplete],
        }
    )
    # The contract order is product API order.  Do not let the special healthy
    # row move to the end when new controls are added above it.
    by_result_id = {str(row["id"]): row for row in result}
    return [by_result_id[row["id"]] for row in TECHNICAL_AUDIT_CHECK_CONTRACT]


def _context_control(
    contract: TechnicalAuditCheck,
    context: Mapping[str, object],
    key: str,
    expected: str,
) -> dict[str, object]:
    actual = str(context.get(key) or "unavailable")
    passed = actual == expected
    return {
        **contract,
        "status": "pass" if passed else "partial",
        "affected_count": 0 if passed else 1,
        "tested_count": 1,
        "denominator": 1,
        "qualification": None if passed else f"{key}:{actual}",
        "evidence": [{"field": key, "observed": actual, "expected": expected}],
    }


def _unavailable_control(contract: TechnicalAuditCheck, qualification: str | None = None) -> dict[str, object]:
    return {
        **contract,
        "status": "unavailable",
        "affected_count": 0,
        "tested_count": None,
        "denominator": None,
        "qualification": qualification or "collector_not_available_for_this_run",
        "evidence": [],
    }


def _row_type(row: Mapping[str, object]) -> str | None:
    for field in ("candidate_type", "issue"):
        value = row.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def _detector_known_types(detector_id: str) -> frozenset[str] | None:
    """Every row type some v3 control (or the outside list) claims; ``None`` = all rows claimed."""

    known: set[str] = set(DETECTOR_ROWS_OUTSIDE_V3.get(detector_id, frozenset()))
    for scopes in CONTROL_EVIDENCE_SCOPES.values():
        if detector_id not in scopes:
            continue
        scope = scopes[detector_id]
        if scope is None:
            return None
        known.update(scope)
    return frozenset(known)


def _evidence_rows(source: Mapping[str, object]) -> list[Mapping[str, object]]:
    rows = source.get("evidence")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def _merge_detector_controls(
    contract: TechnicalAuditCheck,
    by_id: Mapping[str, Mapping[str, object]],
    detector_ids: Sequence[str],
) -> dict[str, object]:
    identifier = contract["id"]
    scopes = CONTROL_EVIDENCE_SCOPES.get(identifier, {})
    statuses: list[str] = []
    evidence: list[dict[str, object]] = []
    qualifications: list[str] = []
    tested: list[int] = []
    denominators: list[int] = []
    missing: list[str] = []
    contributing: list[str] = []
    for detector_id in detector_ids:
        source = by_id.get(detector_id)
        if source is None:
            # A missing required detector is unavailable evidence, not a
            # detector that can be skipped.
            missing.append(detector_id)
            statuses.append("unavailable")
            continue
        detector_status = str(source.get("status") or "unavailable")
        # Unknown controls (no declared scope) fall back to the whole detector.
        scope = scopes.get(detector_id) if detector_id in scopes else None
        rows = _evidence_rows(source)
        known = _detector_known_types(detector_id)
        unscoped = [row for row in rows if known is not None and _row_type(row) not in known]
        scoped = [row for row in rows if scope is None or _row_type(row) in scope]
        if source.get("qualification"):
            qualifications.append(str(source["qualification"]))
        if unscoped:
            qualifications.append("unscoped_detector_evidence")
        if detector_status == "finding":
            if scoped:
                statuses.append("finding")
            else:
                statuses.append("partial")
                qualifications.append("detector_finding_outside_control_scope")
        else:
            statuses.append(detector_status)
        if scoped:
            contributing.append(detector_id)
        evidence.extend({"detector_id": detector_id, **dict(row)} for row in scoped)
        for key, bucket in (("tested_count", tested), ("denominator", denominators)):
            value = source.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                bucket.append(value)

    if "finding" in statuses:
        status = "finding"
    elif any(value in _NOT_PASSING for value in statuses):
        status = "partial" if any(value != "unavailable" for value in statuses) else "unavailable"
    elif statuses and all(value == "pass" for value in statuses):
        status = "pass"
    else:
        status = "partial"
    if missing:
        qualifications.append("required_detector_missing:" + ",".join(missing))
    if len(contributing) > 1:
        qualifications.append("combined_v2_detectors")
    return {
        **contract,
        "status": status,
        "affected_count": len(evidence),
        "tested_count": max(tested) if tested else None,
        "denominator": max(denominators) if denominators else None,
        "qualification": "; ".join(dict.fromkeys(qualifications)) or None,
        "evidence": evidence,
        "detector_ids": list(detector_ids),
    }
