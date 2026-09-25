"""Bounded current URL-variant and synthetic soft-404 evidence collection."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urljoin, urlsplit

from .hashing import simhash64
from .probes import soft_404_fingerprint
from .redaction import redact_url_without_digest
from .variants import generate_variants


_ERROR_COPY = re.compile(r"\b(page not found|not found|404|does not exist|no longer available)\b", re.I)


async def collect_url_variant_evidence(
    engine: Any,
    page_rows: Sequence[Mapping[str, object]],
    *,
    max_control_pages: int = 10,
    max_variant_probes: int = 50,
    max_soft404_hosts: int = 10,
) -> dict[str, object]:
    """Probe a bounded, representative set of saved canonical pages.

    All outcomes are analyst candidates. Synthetic path probes alone do not
    establish demand, crawl waste, or an indexing defect. The underlying
    engine applies robots, host, authorization, and destination guards.
    """
    if max_control_pages < 1 or max_variant_probes < 1 or max_soft404_hosts < 1:
        raise ValueError("URL-variant audit budgets must be positive")
    selected = _select_controls(page_rows, max_control_pages)
    eligible_population_count = len(_select_controls(page_rows, len(page_rows) or 1))
    variants: list[dict[str, object]] = []
    controls: list[dict[str, object]] = []
    control_results: dict[str, Any] = {}
    probe_count = 0

    for row in selected:
        canonical_url = str(row["url"])
        control = await engine.crawl(canonical_url)
        control_results[canonical_url] = control
        control_observed = datetime.now(timezone.utc).isoformat(timespec="seconds")
        controls.append(
            {
                "url": _safe_url(canonical_url),
                "observed_at": control_observed,
                "http_status": control.status,
                "final_url": _safe_url(control.final_url),
                "content_type": control.content_type,
                "indexable_by_saved_directives": _is_indexable(control),
                "canonical": _safe_url(control.extracted.canonical)
                if control.extracted and control.extracted.canonical
                else None,
                "state": "fetched" if control.status else (control.skip_reason or "unavailable"),
            }
        )
        if control.status != 200:
            continue
        for candidate in generate_variants(canonical_url):
            if probe_count >= max_variant_probes:
                break
            reason = engine.config.url_admission_reason(candidate.url, purpose="probe")
            if reason:
                variants.append(
                    {
                        "record_type": "candidate",
                        "candidate_type": "url_variant_probe_not_admitted",
                        "control_url": _safe_url(canonical_url),
                        "variant_url": _safe_url(candidate.url),
                        "variant_kind": candidate.kind,
                        "admission_reason": reason,
                        "demand_state": "probe_only_not_observed",
                    }
                )
                continue
            original_follow = engine.config.follow_redirects
            engine.config.follow_redirects = False
            try:
                result = await engine.crawl(candidate.url)
            finally:
                engine.config.follow_redirects = original_follow
            probe_count += 1
            observed = datetime.now(timezone.utc).isoformat(timespec="seconds")
            location = result.headers.get("Location") or result.headers.get("location")
            resolved_location = urljoin(candidate.url, location) if location else None
            canonical = result.extracted.canonical if result.extracted else None
            canonical_state = _canonical_relation(canonical, canonical_url)
            demand = _observed_demand(page_rows, candidate.url)
            variants.append(
                {
                    "record_type": "candidate",
                    "candidate_type": "url_variant_observation",
                    "control_url": _safe_url(canonical_url),
                    "variant_url": _safe_url(candidate.url),
                    "variant_kind": candidate.kind,
                    "observed_at": observed,
                    "http_status": result.status,
                    "final_url": _safe_url(result.final_url),
                    "redirect_location": _safe_url(resolved_location) if resolved_location else None,
                    "redirect_chain": [
                        {"url": _safe_url(str(hop.get("url") or "")), "status": hop.get("status")}
                        for hop in result.redirect_chain
                        if isinstance(hop, Mapping)
                    ],
                    "response_headers": _safe_headers(result.headers),
                    "elapsed_seconds": result.total_duration_seconds,
                    "canonical": _safe_url(canonical) if canonical else None,
                    "canonical_relation_to_control": canonical_state,
                    "indexable_by_saved_directives": _is_indexable(result),
                    "demand_state": "observed_in_selected_run" if demand else "probe_only_not_observed",
                    "qualification": "synthetic_probe_candidate_requires_demand_and_intent_review",
                }
            )
        if probe_count >= max_variant_probes:
            break

    host_population = sorted(
        {
            f"{urlsplit(str(row['url'])).scheme}://{urlsplit(str(row['url'])).netloc}"
            for row in selected
            if row.get("url")
        }
    )
    hosts = host_population[:max_soft404_hosts]
    soft404: list[dict[str, object]] = []
    for origin in hosts:
        fingerprint = await soft_404_fingerprint(engine, origin)
        observed = datetime.now(timezone.utc).isoformat(timespec="seconds")
        control_row = next(
            (row for row in selected if urlsplit(str(row["url"])).netloc == urlsplit(origin).netloc),
            None,
        )
        control_page = control_results.get(str(control_row["url"])) if control_row else None
        error_title = bool(fingerprint.title and _ERROR_COPY.search(fingerprint.title))
        error_copy = error_title or fingerprint.error_phrase_in_body
        same_as_control = bool(
            fingerprint.simhash is not None
            and control_page is not None
            and control_page.raw_html
            and _simhash_distance(fingerprint.simhash, simhash64(control_page.raw_html)) <= 3
        )
        has_risk_signal = (
            fingerprint.status == 200
            and (error_copy or same_as_control)
            and fingerprint.noindex_by_saved_directives is not True
        )
        soft404.append(
            {
                "record_type": "candidate" if has_risk_signal else "observation",
                "candidate_type": "soft_404_risk_review" if has_risk_signal else "synthetic_404_control",
                "tested_url": _safe_url(fingerprint.tested_url),
                "observed_at": observed,
                "http_status": fingerprint.status,
                "final_url": _safe_url(fingerprint.final_url),
                "body_length": fingerprint.body_len,
                "title": fingerprint.title,
                "response_headers": _safe_headers(fingerprint.headers),
                "redirect_chain": [
                    {"url": _safe_url(str(hop.get("url") or "")), "status": hop.get("status")}
                    for hop in fingerprint.redirect_chain
                    if isinstance(hop, Mapping)
                ],
                "canonical": _safe_url(fingerprint.canonical),
                "noindex_by_saved_directives": fingerprint.noindex_by_saved_directives,
                "elapsed_seconds": fingerprint.elapsed_seconds,
                "error_phrase_in_title": error_title,
                "error_phrase_in_body": fingerprint.error_phrase_in_body,
                "simhash_matches_live_control": same_as_control,
                "control_url": _safe_url(str(control_row["url"])) if control_row else None,
                "effective_rendered_noindex": "not_tested",
                "qualification": "synthetic_probe_risk_only_requires_rendered_and_template_confirmation",
            }
        )

    return {
        "record_type": "coverage",
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "complete": len(selected) == eligible_population_count
        and len(hosts) == len(host_population)
        and probe_count < max_variant_probes,
        "control_page_count": len(selected),
        "variant_probe_count": probe_count,
        "soft404_host_count": len(soft404),
        "control_pages": controls,
        "variant_candidates": variants,
        "soft404_candidates": soft404,
        "rendered_controls": "unavailable_not_tested",
        "sampling": "deterministic locale/template/path-depth round-robin from saved self-canonical indexable HTML",
    }


def _select_controls(page_rows: Sequence[Mapping[str, object]], limit: int) -> list[Mapping[str, object]]:
    strata: dict[tuple[str, str, int], list[Mapping[str, object]]] = defaultdict(list)
    for row in page_rows:
        url = str(row.get("url") or "")
        parts = urlsplit(url)
        if (
            not url
            or parts.scheme not in {"http", "https"}
            or row.get("kind") != "html"
            or row.get("final_status_code") != 200
            or row.get("overall_indexable") is not True
        ):
            continue
        canonicals = row.get("canonical_urls_json")
        if isinstance(canonicals, str):
            import json

            try:
                canonicals = json.loads(canonicals)
            except ValueError:
                canonicals = []
        if not isinstance(canonicals, list) or not any(str(value) == url for value in canonicals):
            continue
        segments = [segment for segment in parts.path.split("/") if segment]
        locale = str(row.get("html_lang") or "missing")
        template = str(row.get("template") or (segments[0] if segments else "root"))
        depth_band = min(len(segments), 3)
        strata[(locale, template, depth_band)].append(row)
    groups = {key: sorted(values, key=lambda item: str(item.get("url"))) for key, values in strata.items()}
    selected: list[Mapping[str, object]] = []
    keys = sorted(groups)
    while keys and len(selected) < limit:
        remaining = []
        for key in keys:
            group = groups[key]
            if group:
                selected.append(group.pop(0))
                if len(selected) == limit:
                    break
            if group:
                remaining.append(key)
        keys = remaining
    return selected


def _canonical_relation(canonical: str | None, control_url: str) -> str:
    if not canonical:
        return "missing_or_unavailable"
    return "same_as_control" if _normalized_url(canonical) == _normalized_url(control_url) else "points_elsewhere"


def _normalized_url(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path or '/'}?{parsed.query}"


def _observed_demand(page_rows: Sequence[Mapping[str, object]], url: str) -> bool:
    target = _normalized_url(url)
    for row in page_rows:
        if _normalized_url(str(row.get("url") or "")) == target:
            return True
        links = row.get("links_json")
        if isinstance(links, str):
            import json

            try:
                links = json.loads(links)
            except ValueError:
                continue
        if isinstance(links, list) and any(
            isinstance(link, Mapping) and _normalized_url(str(link.get("href") or "")) == target for link in links
        ):
            return True
    return False


def _is_indexable(result) -> bool | None:
    if result.extracted is None:
        return None
    return not result.extracted.meta_robots.noindex and not result.extracted.x_robots_tag.noindex


def _simhash_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _safe_url(url: str | None) -> str | None:
    return redact_url_without_digest(url) if url else None


def _safe_headers(headers: Mapping[str, str]) -> dict[str, str]:
    excluded = {"set-cookie", "www-authenticate", "proxy-authenticate"}
    safe: dict[str, str] = {}
    for name, value in headers.items():
        key = str(name).lower()
        if key not in excluded:
            safe[key] = _safe_url(str(value)) or "" if key == "location" else str(value)
    return safe
