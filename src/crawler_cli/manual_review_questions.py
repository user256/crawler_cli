"""The complete deterministic answer register for ``MANUAL-REVIEW.md``.

The register is intentionally separate from individual detector controls.
One manual-review question can require several controls and, in a few cases,
new evidence that the saved crawl does not yet collect.  In that case the
answer is ``unavailable`` rather than an inferred healthy result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final, TypedDict


class ManualReviewQuestion(TypedDict):
    id: str
    question: str
    controls: tuple[str, ...]
    additional_evidence: str | None


MANUAL_REVIEW_QUESTIONS: Final[tuple[ManualReviewQuestion, ...]] = (
    {"id": "Q1", "question": "Important robots paths and first-party resources", "controls": ("robots-controls", "critical-resource-impact"), "additional_evidence": "per-host rendered resource requests evaluated against each host's current robots.txt"},
    {"id": "Q2", "question": "HTTP, HTTPS, www and apex redirect matrix", "controls": ("url-host-and-variants",), "additional_evidence": None},
    {"id": "Q3", "question": "Sitemap validity, indexability, canonicals and lastmod", "controls": ("sitemap-integrity",), "additional_evidence": None},
    {"id": "Q4", "question": "Indexable self-canonical URLs absent from sitemaps", "controls": ("sitemap-integrity", "canonical-target-validation"), "additional_evidence": "run-scoped sitemap membership for every canonical indexable URL"},
    {"id": "Q5", "question": "Mixed-content and non-SSL asset references", "controls": ("critical-resource-impact",), "additional_evidence": "raw and rendered asset scheme inventory"},
    {"id": "Q6", "question": "Synthetic route responses and soft 404s", "controls": ("soft404-error-routes",), "additional_evidence": None},
    {"id": "Q7", "question": "Case, camel-case and locale-path variants", "controls": ("url-host-and-variants", "locale-redirects"), "additional_evidence": None},
    {"id": "Q8", "question": "HTML lang and hreflang agreement", "controls": ("locale-html-lang", "hreflang-html-http"), "additional_evidence": None},
    {"id": "Q9", "question": "Hreflang reciprocity, target state and noindex conflicts", "controls": ("hreflang-html-http", "hreflang-noindex", "hreflang-sitemap"), "additional_evidence": None},
    {"id": "Q10", "question": "Duplicate HTML head declarations and HTTP Link canonical agreement", "controls": ("canonical-declarations", "metadata-basics"), "additional_evidence": "HTML5-parsed per-page head declaration counts and HTTP Link canonical comparison"},
    {"id": "Q11", "question": "Duplicate title, H1 and meta descriptions within canonical locale scope", "controls": ("metadata-duplicates-aliases",), "additional_evidence": None},
    {"id": "Q12", "question": "Core head declarations parsed in the document body", "controls": ("canonical-declarations",), "additional_evidence": "HTML5 parser placement for title, meta, canonical, hreflang, charset and base"},
    {"id": "Q13", "question": "Sitemap orphan candidates by browser and bot link graph", "controls": ("orphan-candidates", "rendered-indexing-parity"), "additional_evidence": "separately labelled browser and verified-bot link graphs"},
    {"id": "Q14", "question": "Internal link volume and sitewide-link concentration", "controls": ("internal-authority", "crawl-waste-url-families"), "additional_evidence": "per-page inlink/outlink distributions and navigation-link concentration"},
    {"id": "Q15", "question": "Heading order, absent or repeated H1 and skipped levels", "controls": ("metadata-basics",), "additional_evidence": "ordered raw-HTML heading outlines"},
    {"id": "Q16", "question": "Structured-data vocabulary and consistency, IDs, URLs and breadcrumbs", "controls": ("schema-parser-diagnostics", "structured-data-feature-rules"), "additional_evidence": "per-page JSON-LD node identity, URL/canonical and breadcrumb-target consistency"},
    {"id": "Q17", "question": "Open Graph and Twitter metadata and social-image delivery", "controls": ("metadata-basics", "image-resource-delivery"), "additional_evidence": "raw and rendered Open Graph/Twitter inventory with image fetch evidence"},
    {"id": "Q31", "question": "Browser and verified-search-bot parity / cloaking", "controls": ("rendered-indexing-parity", "validated-bot-log-analysis"), "additional_evidence": "paired browser and Google-InspectionTool or verified-Googlebot raw/render evidence"},
)


def manual_review_answer_register(
    controls: Sequence[Mapping[str, object]],
    *,
    collected_evidence: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    """Return a row for every manual-review question without inferred passes."""

    by_id = {str(row.get("id")): row for row in controls}
    supplied = collected_evidence if isinstance(collected_evidence, Mapping) else {}
    answers: list[dict[str, object]] = []
    for definition in MANUAL_REVIEW_QUESTIONS:
        sources = [by_id[identifier] for identifier in definition["controls"] if identifier in by_id]
        missing_controls = [identifier for identifier in definition["controls"] if identifier not in by_id]
        extra_key = definition["additional_evidence"]
        extra_available = extra_key is None or supplied.get(extra_key) is True
        statuses = [str(row.get("status") or "unavailable") for row in sources]
        if missing_controls or not extra_available or "unavailable" in statuses:
            status = "unavailable"
        elif "finding" in statuses:
            status = "finding"
        elif "partial" in statuses or "not_applicable" in statuses:
            status = "partial"
        elif statuses and all(value == "pass" for value in statuses):
            status = "pass"
        else:
            status = "unavailable"
        answers.append(
            {
                "id": definition["id"],
                "question": definition["question"],
                "status": status,
                "control_ids": list(definition["controls"]),
                "additional_evidence_required": extra_key,
                "additional_evidence_available": extra_available,
                "missing_control_ids": missing_controls,
                "evidence": [
                    {
                        "control_id": row.get("id"),
                        "status": row.get("status"),
                        "detail_sheet": row.get("detail_sheet"),
                        "affected_count": row.get("affected_count"),
                        "tested_count": row.get("tested_count"),
                        "qualification": row.get("qualification"),
                    }
                    for row in sources
                ],
            }
        )
    return answers
