from __future__ import annotations

from typing import Any

from .models import BrowserRuntime, CrawlJobResult, CrawlResult, ExtractedContent, FetchResponse


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
        "allowed_by_robots": result.allowed_by_robots,
        "skip_reason": result.skip_reason,
        "persist_error": result.persist_error,
        "challenge": result.challenge,
        "ttfb_seconds": result.ttfb_seconds,
        "total_duration_seconds": result.total_duration_seconds,
        "lcp_ms": result.lcp_ms,
        "cls": result.cls,
        "inp_ms": result.inp_ms,
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
    """Aggregate fields for JSONL summary lines and crawl metadata (ticket 092)."""
    return {
        "crawled_count": job.crawled_count,
        "blocked_count": job.blocked_count,
        "persist_error_count": job.persist_error_count,
        "persist_failed_urls": job.persist_failed_urls,
        "durability": job.durability,
        "retry_attempts": job.retry_attempts,
        "interrupted": job.interrupted,
        "saved_to": job.saved_to if saved_to is None else saved_to,
        "refresh_skipped_count": job.refresh_skipped_count,
        "challenge_blocked_count": job.challenge_blocked_count,
    }


def serialize_crawl_job(job: CrawlJobResult, *, saved_to: str | None = None) -> dict[str, object]:
    resolved_saved_to = job.saved_to if saved_to is None else saved_to
    payload: dict[str, object] = {
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
        "retry_attempts": job.retry_attempts,
        "interrupted": job.interrupted,
        "refresh_skipped_count": job.refresh_skipped_count,
        "results": [serialize_crawl_result(result) for result in job.results],
    }
    if job.max_urls is not None:
        payload["max_urls"] = job.max_urls
    return payload
