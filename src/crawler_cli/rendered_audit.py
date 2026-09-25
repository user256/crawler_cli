"""Projection helpers for bounded same-navigation technical-audit renders."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
from urllib.parse import parse_qsl, urlsplit

from .compare_renders import RenderParityComparison
from .redaction import redact_headers, redact_url_without_digest, scrub_text


def render_audit_records(
    comparisons: Sequence[RenderParityComparison],
    *,
    device: str,
    viewport: tuple[int, int],
    page_context: Mapping[str, Mapping[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Return stable coverage, analyst candidates, and raw observations.

    A settle timeout or incomplete same-navigation capture cannot produce
    render-divergence candidates. Network/image records are observations only;
    impact needs analyst confirmation against affected primary content.
    """
    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    observations: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    link_capture_summaries: list[Mapping[str, object]] = []
    complete = True
    incomplete_count = 0
    for comparison in comparisons:
        page_url = comparison.url
        digest = hashlib.sha256(page_url.encode()).hexdigest()
        result = comparison.crawl_result
        context = _safe_value(dict((page_context or {}).get(page_url, {})))
        context_fields = context if isinstance(context, dict) else {}
        result_link_capture = getattr(result, "render_link_capture", None) if result is not None else None
        if isinstance(result_link_capture, Mapping):
            link_capture_summaries.append(result_link_capture)
        state = comparison.state
        state_reason = comparison.state_reason
        rendered_text = comparison.rendered_main_text or ""
        rendered_content = comparison.rendered
        has_primary_content = bool(
            rendered_text.strip()
            or (rendered_content and any(value.strip() for value in rendered_content.headings.get("h1", [])))
            or comparison.rendered_internal_links
        )
        if state == "complete" and not has_primary_content:
            state = "inconclusive"
            state_reason = "empty_rendered_primary_content"
        if state != "complete":
            complete = False
            incomplete_count += 1
        summary = comparison.as_dict()
        safe_signals = _safe_value(summary["signals"])
        observations.append(
            {
                "record_type": "observation",
                "record_kind": "render_comparison",
                "url": _safe_url(page_url),
                "url_digest_sha256": digest,
                **context_fields,
                "device": device,
                "viewport_width": viewport[0],
                "viewport_height": viewport[1],
                "observed_at": observed_at,
                "state": state,
                "state_reason": state_reason,
                "http_status": comparison.status,
                "final_url": _safe_url(comparison.final_url),
                "response_headers": redact_headers(getattr(result, "headers", {})) if result is not None else {},
                "ttfb_seconds": getattr(result, "ttfb_seconds", None) if result is not None else None,
                "elapsed_seconds": getattr(result, "total_duration_seconds", None) if result is not None else None,
                "primary_summary": comparison.primary_summary if state == "complete" else "inconclusive",
                "signals": safe_signals,
                "raw_rendered_links_basis": "same_navigation_pre_hydration_and_pre_interaction_dom",
            }
        )
        if state == "complete":
            for finding in comparison.findings:
                if finding.completeness != "complete":
                    continue
                candidates.append(
                    {
                        "record_type": "candidate",
                        "candidate_type": "render_divergence_review",
                        "url": _safe_url(page_url),
                        "url_digest_sha256": digest,
                        "device": device,
                        "code": finding.code,
                        "severity_hint": finding.severity,
                        "field": finding.field,
                        "explanation": finding.explanation,
                        "raw_value": _safe_value(finding.raw_value),
                        "rendered_value": _safe_value(finding.rendered_value),
                        "qualification": "same_navigation_candidate_requires_template_and_search_impact_review",
                    }
                )
        if result is None:
            continue
        source_host = (urlsplit(comparison.final_url).hostname or "").casefold()
        for link in getattr(result, "render_link_observations", []) or []:
            if not isinstance(link, Mapping):
                continue
            target_url = str(link.get("href") or "")
            target_host = (urlsplit(target_url).hostname or "").casefold()
            observations.append(
                {
                    "record_type": "observation",
                    "record_kind": "rendered_link",
                    "source_url": _safe_url(page_url),
                    "url_digest_sha256": digest,
                    **context_fields,
                    "device": device,
                    "observed_at": observed_at,
                    "target_url": _safe_url(target_url),
                    "capture_phase": link.get("capture_phase"),
                    "reveal_state": link.get("reveal_state"),
                    "anchor_text": scrub_text(str(link.get("anchor_text") or "")),
                    "dom_path": scrub_text(str(link.get("dom_path") or "")),
                    "rendered_visible": link.get("rendered_visible"),
                    "in_initial_viewport": link.get("in_viewport"),
                    "same_host": bool(source_host and source_host == target_host),
                    "qualification": "scroll_only_capture; controls_not_activated; interpret_with_link_and_robots_checks",
                }
            )
        missing_alt_images: dict[tuple[str, str, str], list[str]] = {}
        for image_state, extracted in (("raw", comparison.raw), ("rendered", comparison.rendered)):
            if extracted is None:
                continue
            for item in extracted.schema_data:
                raw_data = str(item.get("raw_data") or "")
                observations.append(
                    {
                        "record_type": "observation",
                        "record_kind": "structured_data_item",
                        "url": _safe_url(page_url),
                        "url_digest_sha256": digest,
                        **context_fields,
                        "source_channel": "raw_html" if image_state == "raw" else "rendered_dom",
                        "format": item.get("format"),
                        "extraction_state": image_state,
                        "schema_type": item.get("type"),
                        "position": item.get("position"),
                        "is_valid": item.get("is_valid"),
                        "validation_errors": _safe_value(item.get("validation_errors", [])),
                        "compatibility_diagnostics": _safe_value(item.get("compatibility_diagnostics", [])),
                        "parser_mode": item.get("parser_mode"),
                        "raw_data": raw_data,
                        "parsed_data": item.get("parsed_data"),
                        "device": device,
                        "state": state,
                    }
                )
            for image in extracted.image_references:
                observations.append(
                    {
                        "record_type": "observation",
                        "record_kind": "image_reference",
                        "source_url": _safe_url(page_url),
                        "url_digest_sha256": digest,
                        **context_fields,
                        "device": device,
                        "extraction_state": image_state,
                        "image_url": _safe_url(image.url),
                        "source_kind": image.source,
                        "xpath": image.xpath,
                        "alt_present": image.alt_present,
                        "alt": scrub_text(image.alt) if image.alt is not None else None,
                        "intentional_empty_alt": image.alt_present and image.alt == "",
                        "width_attribute": image.width,
                        "height_attribute": image.height,
                        "state": state,
                        "qualification": "dimensions_are_markup_attributes_not_measured_display_layout",
                    }
                )
                if state == "complete" and not image.alt_present:
                    image_key = (image.url, image.source, image.xpath)
                    missing_alt_images.setdefault(image_key, []).append(image_state)
        for (image_url, source_kind, xpath), image_states in missing_alt_images.items():
            candidates.append(
                {
                    "record_type": "candidate",
                    "candidate_type": "image_missing_alt_attribute_review",
                    "url": _safe_url(page_url),
                    "url_digest_sha256": digest,
                    **context_fields,
                    "device": device,
                    "image_url": _safe_url(image_url),
                    "source_kind": source_kind,
                    "xpath": xpath,
                    "observed_in": sorted(image_states),
                    "qualification": "missing_attribute_not_equivalent_to_decorative_empty_alt",
                }
            )
        request_rows = result.observed_requests
        for request in request_rows:
            target = urlsplit(request.url)
            source = urlsplit(comparison.final_url)
            is_mixed = source.scheme.lower() == "https" and target.scheme.lower() == "http"
            observations.append(
                {
                    "record_type": "observation",
                    "record_kind": "browser_request",
                    "source_url": _safe_url(page_url),
                    "url_digest_sha256": digest,
                    **context_fields,
                    "device": device,
                    "target_url": _safe_url(request.url),
                    "method": request.method,
                    "resource_type": request.resource_type,
                    "outcome": request.outcome,
                    "http_status": request.status,
                    "content_type": request.content_type,
                    "failure_observed": request.failure is not None,
                    "occurrence_count": request.occurrence_count,
                    "mixed_content_candidate": is_mixed,
                    "state": state,
                    "qualification": "resource_failure_does_not_prove_primary_content_impact",
                }
            )
    return [
        {
            "record_type": "coverage",
            "observed_at": observed_at,
            "device": device,
            "viewport_width": viewport[0],
            "viewport_height": viewport[1],
            "sample_size": len(comparisons),
            "complete": complete,
            "incomplete_count": incomplete_count,
            "rendered_only_link_count": sum(len(item.only_in_rendered) for item in comparisons),
            "raw_only_link_count": sum(len(item.only_in_raw) for item in comparisons),
            "image_reference_observation_count": sum(item["record_kind"] == "image_reference" for item in observations),
            "browser_request_observation_count": sum(item["record_kind"] == "browser_request" for item in observations),
            "scroll_link_state_capture": (
                "not_tested"
                if not link_capture_summaries
                else "complete"
                if len(link_capture_summaries) == len(comparisons)
                and all(item.get("state") == "complete" for item in link_capture_summaries)
                else "partial"
            ),
            "interaction_state": "bounded_scroll_only" if link_capture_summaries else "not_tested",
            "controls_activated": "not_tested",
            "rendered_link_observation_count": sum(item.get("record_kind") == "rendered_link" for item in observations),
            "scroll_revealed_link_count": sum(
                count
                for item in link_capture_summaries
                for count in [item.get("scroll_revealed_link_count")]
                if isinstance(count, int) and not isinstance(count, bool)
            ),
            "external_link_rechecks": "not_tested",
            "measured_image_layout_impact": "not_tested",
            "geo_evidence": {
                "state": "unavailable",
                "reason": "no regional proxy was selected; local requests are not a substitute",
            },
            "non_html_search_assets": "not_tested",
        },
        *candidates,
        *observations,
    ]


def _safe_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlsplit(url)
    query_names = [key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)]
    stripped = parsed._replace(query="&".join(query_names)).geturl()
    return redact_url_without_digest(stripped)


def _safe_value(value: object) -> object:
    if isinstance(value, str):
        parsed = urlsplit(value)
        if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
            return _safe_url(value)
        return scrub_text(value)
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {scrub_text(str(key)): _safe_value(item) for key, item in value.items()}
    return value
