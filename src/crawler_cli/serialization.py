from __future__ import annotations

from typing import Any

from .models import BrowserRuntime, CrawlJobResult, CrawlResult, ExtractedContent, FetchResponse

CRAWL_ARTIFACT_SCHEMA_VERSION = "crawler-cli/crawl-artifact/5"
"""Schema identifier stamped on saved crawl artifacts (ticket 3344).

Downstream consumers (e.g. the portal migration worker) pin on this string;
v2 added explicit partial-body and run-budget terminal data; v3 added static
JavaScript URL candidate evidence; v4 added CSS candidates, confidence/base
metadata, rejection counts, and speculative admission totals; v5 adds the
``authorization_scope`` record (ticket 148). Loaders keep accepting legacy
artifacts and missing fields.

There is deliberately no separate identifier for a manifest-backed artifact.
One run of the writer produces one version, so the stamp describes the build
that wrote the file rather than which optional records happened to be
populated. ``authorization_scope`` is present and ``null`` on a manifest-free
crawl, which keeps the field's absence and its emptiness from meaning two
different things."""

KNOWN_CRAWL_ARTIFACT_SCHEMA_VERSIONS = frozenset(
    {
        "crawler-cli/crawl-artifact/1",
        "crawler-cli/crawl-artifact/2",
        "crawler-cli/crawl-artifact/3",
        "crawler-cli/crawl-artifact/4",
        "crawler-cli/crawl-artifact/5",
    }
)
"""Every artifact version this build can read.

Each bump has been additive, so an older artifact still loads: absent fields
fall back to their documented defaults. Validating against the current version
alone would make a build unable to read the artifacts it wrote before the last
bump, which is why the accepted set is explicit. An unrecognised version is
still rejected, because a newer writer may carry fields this build would
silently drop."""


def serialize_browser_runtime(runtime: BrowserRuntime) -> dict[str, object]:
    return {
        "provider": runtime.provider,
        "cdp_endpoint": runtime.cdp_endpoint,
        "managed": runtime.managed,
        "stealth": runtime.stealth,
        "persistent": runtime.persistent,
        "channel": runtime.channel,
        "executable_path": runtime.executable_path,
        "user_data_dir": runtime.user_data_dir,
        "profile_directory": runtime.profile_directory,
        "headless": runtime.headless,
    }


def serialize_fetch_response(response: FetchResponse, *, include_text: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {
        "url": response.url,
        "requested_url": response.requested_url,
        "status": response.status,
        "headers": response.headers,
        "body_length": len(response.body),
        "body_truncated": response.body_truncated,
        "wire_bytes": response.wire_bytes,
        "decoded_bytes": response.decoded_bytes,
        "accounted_bytes": response.accounted_bytes,
        "body_truncation_reason": response.body_truncation_reason,
        "observed_requests": [
            {
                "url": item.url,
                "method": item.method,
                "resource_type": item.resource_type,
                "outcome": item.outcome,
                "status": item.status,
                "failure": item.failure,
                "occurrence_count": item.occurrence_count,
            }
            for item in response.observed_requests
        ],
        "render_settled": response.render_settled,
    }
    if include_text:
        payload["text"] = response.text
    return payload


def serialize_extracted_content(extracted: ExtractedContent) -> dict[str, object]:
    return {
        "title": extracted.title,
        "meta_description": extracted.meta_description,
        "meta_robots": extracted.meta_robots.raw,
        "x_robots_tag": extracted.x_robots_tag.raw,
        "canonical": extracted.canonical,
        "x_canonical": extracted.x_canonical,
        "hreflang_links": [
            {"hreflang": link.hreflang, "href": link.href, "source": link.source} for link in extracted.hreflang_links
        ],
        "html_lang": extracted.html_lang,
        "headings": extracted.headings,
        "text": extracted.text,
        "word_count": extracted.word_count,
        "metadata": extracted.metadata,
        "schema_data": extracted.schema_data,
    }


def serialize_crawl_result(result: CrawlResult) -> dict[str, object]:
    payload: dict[str, Any] = {
        "requested_url": result.requested_url,
        "final_url": result.final_url,
        "status": result.status,
        "headers": result.headers,
        "content_type": result.content_type,
        "fetch_backend": result.fetch_backend,
        "raw_html": result.raw_html,
        "body_truncated": result.body_truncated,
        "wire_bytes": result.wire_bytes,
        "decoded_bytes": result.decoded_bytes,
        "accounted_bytes": result.accounted_bytes,
        "body_truncation_reason": result.body_truncation_reason,
        "content_hash_sha256": result.content_hash_sha256,
        "content_hash_simhash": result.content_hash_simhash,
        "discovered_links": [
            {
                "href": link.href,
                "anchor_text": link.anchor_text,
                "xpath": link.xpath,
                "is_image": link.is_image,
                "fragment": link.fragment,
                "url_parameters": link.url_parameters,
                "original_href": link.original_href,
            }
            for link in result.discovered_links
        ],
        "javascript_url_candidates": [
            {
                "url": candidate.url,
                "source_kind": candidate.source_kind,
                "script_source": candidate.script_source,
                "script_index": candidate.script_index,
                "literal_kind": candidate.literal_kind,
                "classification": candidate.classification,
                "follow_eligible": candidate.follow_eligible,
                "occurrence_count": candidate.occurrence_count,
                "confidence": candidate.confidence,
                "confidence_weight": candidate.confidence_weight,
                "resolution_base": candidate.resolution_base,
            }
            for candidate in result.javascript_url_candidates
        ],
        "css_url_candidates": [
            {
                "url": candidate.url,
                "source_kind": candidate.source_kind,
                "stylesheet_source": candidate.stylesheet_source,
                "style_index": candidate.style_index,
                "token_kind": candidate.token_kind,
                "classification": candidate.classification,
                "follow_eligible": candidate.follow_eligible,
                "occurrence_count": candidate.occurrence_count,
                "confidence": candidate.confidence,
                "confidence_weight": candidate.confidence_weight,
                "resolution_base": candidate.resolution_base,
            }
            for candidate in result.css_url_candidates
        ],
        "speculative_rejection_counts": result.speculative_rejection_counts,
        "render_url_candidates": [
            {
                "url": candidate.url,
                "source_kind": candidate.source_kind,
                "classification": candidate.classification,
                "follow_eligible": candidate.follow_eligible,
                "resource_type": candidate.resource_type,
                "method": candidate.method,
                "outcome": candidate.outcome,
                "status": candidate.status,
                "occurrence_count": candidate.occurrence_count,
                "confidence": candidate.confidence,
            }
            for candidate in result.render_url_candidates
        ],
        "render_discovery_attempted": result.render_discovery_attempted,
        "render_discovery_complete": result.render_discovery_complete,
        "render_discovery_skip_reason": result.render_discovery_skip_reason,
        "allowed_by_robots": result.allowed_by_robots,
        "skip_reason": result.skip_reason,
        "persist_error": result.persist_error,
        "challenge": result.challenge,
        "ttfb_seconds": result.ttfb_seconds,
        "total_duration_seconds": result.total_duration_seconds,
        "lcp_ms": result.lcp_ms,
        "cls": result.cls,
        "inp_ms": result.inp_ms,
        "redirect_chain": result.redirect_chain,
        "custom_data": result.custom_data,
        "detected_cms": None
        if result.detected_cms is None
        else {
            "cms_name": result.detected_cms.cms_name,
            "confidence": result.detected_cms.confidence,
            "indicators": result.detected_cms.indicators,
        },
        "detected_analytics": None
        if result.detected_analytics is None
        else [
            {
                "vendor": hit.vendor,
                "category": hit.category,
                "identifier": hit.identifier,
                "evidence_type": hit.evidence_type,
                "evidence_snippet": hit.evidence_snippet,
                "confidence": hit.confidence,
            }
            for hit in result.detected_analytics.hits
        ],
        "extracted": None if result.extracted is None else serialize_extracted_content(result.extracted),
    }
    if result.browser_runtime is not None:
        payload["browser_runtime"] = serialize_browser_runtime(result.browser_runtime)
    return payload


def serialize_job_summary_metadata(job: CrawlJobResult, *, saved_to: str | None = None) -> dict[str, object]:
    """Aggregate fields for JSONL summary lines and crawl metadata (tickets 092, 115).

    ``authorization_scope`` is added only when the run had a scope manifest, so
    ordinary crawl summaries keep exactly the key set they had before ticket 148.
    """
    payload: dict[str, object] = {
        "crawled_count": job.crawled_count,
        "blocked_count": job.blocked_count,
        "persist_error_count": job.persist_error_count,
        "persist_failed_urls": job.persist_failed_urls,
        "durability": job.durability,
        "frontier_mark_done_error_count": job.frontier_mark_done_error_count,
        "frontier_mark_done_failed_urls": job.frontier_mark_done_failed_urls,
        "crawl_run_status": job.crawl_run_status,
        "retry_attempts": job.retry_attempts,
        "interrupted": job.interrupted,
        "saved_to": job.saved_to if saved_to is None else saved_to,
        "refresh_skipped_count": job.refresh_skipped_count,
        "challenge_blocked_count": job.challenge_blocked_count,
        "budget_requests_started": job.budget_requests_started,
        "budget_wire_bytes": job.budget_wire_bytes,
        "budget_decoded_bytes": job.budget_decoded_bytes,
        "budget_accounted_bytes": job.budget_accounted_bytes,
        "budget_stop_reason": job.budget_stop_reason,
        "javascript_url_candidate_count": job.javascript_url_candidate_count,
        "javascript_url_enqueued_count": job.javascript_url_enqueued_count,
        "css_url_candidate_count": job.css_url_candidate_count,
        "css_url_enqueued_count": job.css_url_enqueued_count,
        "speculative_capped_count": job.speculative_capped_count,
        "render_url_candidate_count": job.render_url_candidate_count,
        "render_dom_enqueued_count": job.render_dom_enqueued_count,
        "render_discovery_attempt_count": job.render_discovery_attempt_count,
    }
    if job.authorization_scope is not None:
        payload["authorization_scope"] = job.authorization_scope
    return payload


def serialize_crawl_job(job: CrawlJobResult, *, saved_to: str | None = None) -> dict[str, object]:
    resolved_saved_to = job.saved_to if saved_to is None else saved_to
    payload: dict[str, object] = {
        "schema_version": CRAWL_ARTIFACT_SCHEMA_VERSION,
        "mode": job.mode,
        "run_id": job.run_id,
        "seed_urls": job.seed_urls,
        "saved_to": resolved_saved_to,
        "crawled_count": job.crawled_count,
        "blocked_count": job.blocked_count,
        "challenge_blocked_count": job.challenge_blocked_count,
        "persist_error_count": job.persist_error_count,
        "persist_failed_urls": job.persist_failed_urls,
        "durability": job.durability,
        "frontier_mark_done_error_count": job.frontier_mark_done_error_count,
        "frontier_mark_done_failed_urls": job.frontier_mark_done_failed_urls,
        "crawl_run_status": job.crawl_run_status,
        "retry_attempts": job.retry_attempts,
        "interrupted": job.interrupted,
        "refresh_skipped_count": job.refresh_skipped_count,
        "budget_requests_started": job.budget_requests_started,
        "budget_wire_bytes": job.budget_wire_bytes,
        "budget_decoded_bytes": job.budget_decoded_bytes,
        "budget_accounted_bytes": job.budget_accounted_bytes,
        "budget_stop_reason": job.budget_stop_reason,
        "javascript_url_candidate_count": job.javascript_url_candidate_count,
        "javascript_url_enqueued_count": job.javascript_url_enqueued_count,
        "css_url_candidate_count": job.css_url_candidate_count,
        "css_url_enqueued_count": job.css_url_enqueued_count,
        "speculative_capped_count": job.speculative_capped_count,
        "render_url_candidate_count": job.render_url_candidate_count,
        "render_dom_enqueued_count": job.render_dom_enqueued_count,
        "render_discovery_attempt_count": job.render_discovery_attempt_count,
        "results": [serialize_crawl_result(result) for result in job.results],
    }
    if job.max_urls is not None:
        payload["max_urls"] = job.max_urls
    # Always present, and null when the run had no scope manifest (ticket 148).
    # Emitting the key unconditionally keeps "no manifest was used" distinct
    # from "this artifact predates the field".
    payload["authorization_scope"] = job.authorization_scope
    return payload
